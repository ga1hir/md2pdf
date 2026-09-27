"""インライン組版エンジン（本ツールの中核）。

ReportLab の素朴な CJK 折り返しではなく、自前で行分割することで
(1) 字詰め×行数の厳密な版面、(2) 禁則処理、(3) ルビ、(4) インラインコード背景・
リンク を同時に満たす。本文の行数が安定するためページ数が実書籍と一致する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from reportlab.lib.colors import Color
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import Flowable
from reportlab.rl_config import _FUZZ as _RL_FIT_EPS

from .. import config
from . import kinsoku

ALIGN_LEFT = "left"
ALIGN_CENTER = "center"
ALIGN_RIGHT = "right"
ALIGN_JUSTIFY = "justify"


@dataclass
class Run:
    """インラインの一区切り（同一スタイルの連続テキスト）。"""

    text: str
    font: str = config.FONT_SERIF
    size: float = 12.0
    color: Color = config.COLOR_TEXT
    bg: Optional[Color] = None          # インラインコード背景
    border: Optional[Color] = None      # インラインコード枠
    underline: bool = False             # リンク
    link: Optional[str] = None          # リンク先 URL
    ruby: Optional[str] = None          # このラン全体に振るルビ
    sup: bool = False                   # 上付き（脚注参照番号）
    image: Optional[tuple] = None       # インライン画像 (path, w_pt, h_pt) 例: インライン数式
    fn_id: Optional[int] = None         # 脚注参照の id（どの断片に参照があるかの判定に使う）


@dataclass
class _Atom:
    text: str
    run: Run
    width: float
    kind: str   # 'cjk' | 'word' | 'space' | 'br' | 'ruby'


def _stringwidth(text: str, run: Run) -> float:
    size = run.size * (0.7 if run.sup else 1.0)
    return pdfmetrics.stringWidth(text, run.font, size)


def _atomize(runs: list[Run]) -> list[_Atom]:
    atoms: list[_Atom] = []
    for run in runs:
        if run.image:
            atoms.append(_Atom("", run, run.image[1], "image"))
            continue
        if run.ruby:
            # ルビ付きランは分割不可の 1 アトムとして扱う
            atoms.append(_Atom(run.text, run, _stringwidth(run.text, run), "ruby"))
            continue
        buf = ""
        for ch in run.text:
            if ch == "\n":
                if buf:
                    atoms.append(_Atom(buf, run, _stringwidth(buf, run), "word"))
                    buf = ""
                atoms.append(_Atom("", run, 0.0, "br"))
            elif ch == " ":
                if buf:
                    atoms.append(_Atom(buf, run, _stringwidth(buf, run), "word"))
                    buf = ""
                atoms.append(_Atom(" ", run, _stringwidth(" ", run), "space"))
            elif kinsoku.is_cjk(ch):
                if buf:
                    atoms.append(_Atom(buf, run, _stringwidth(buf, run), "word"))
                    buf = ""
                atoms.append(_Atom(ch, run, _stringwidth(ch, run), "cjk"))
            else:
                buf += ch
        if buf:
            atoms.append(_Atom(buf, run, _stringwidth(buf, run), "word"))
    return atoms


@dataclass
class _Line:
    atoms: list[_Atom] = field(default_factory=list)
    width: float = 0.0
    ragged: bool = True  # True なら均等割り付けしない（最終行・強制改行行）


def _trim_trailing_spaces(atoms: list[_Atom]) -> tuple[list[_Atom], float]:
    out = list(atoms)
    w = sum(a.width for a in out)
    while out and out[-1].kind == "space":
        w -= out.pop().width
    return out, w


# 行幅判定の許容誤差（pt）。全角字幅の丸めで N 字目が 1e-10 はみ出すのを吸収する。
# 半角 1 文字よりは十分小さいので余分な文字が入ることはない。
_FIT_EPS = 0.2


# 行幅を超える単語（URL 等）の分割候補。この文字の直後で折り返す（ハイフンは足さない）。
_WORD_BREAK_AFTER = "/.-_?&="


def _split_word(atom: _Atom, maxw: float) -> list[_Atom]:
    """行幅を超える 1 語を、区切り文字の直後 → それでも超える片は文字単位で分割する。"""
    pieces: list[str] = []
    buf = ""
    for ch in atom.text:
        buf += ch
        if ch in _WORD_BREAK_AFTER:
            pieces.append(buf)
            buf = ""
    if buf:
        pieces.append(buf)
    out: list[_Atom] = []
    for piece in pieces:
        w = _stringwidth(piece, atom.run)
        if w <= maxw + _FIT_EPS:
            out.append(_Atom(piece, atom.run, w, "word"))
            continue
        buf = ""
        for ch in piece:
            if buf and _stringwidth(buf + ch, atom.run) > maxw + _FIT_EPS:
                out.append(_Atom(buf, atom.run, _stringwidth(buf, atom.run), "word"))
                buf = ""
            buf += ch
        if buf:
            out.append(_Atom(buf, atom.run, _stringwidth(buf, atom.run), "word"))
    return out


def _split_long_words(atoms: list[_Atom], maxw: float) -> list[_Atom]:
    if not any(a.kind == "word" and a.width > maxw + _FIT_EPS for a in atoms):
        return atoms
    out: list[_Atom] = []
    for a in atoms:
        if a.kind == "word" and a.width > maxw + _FIT_EPS:
            out.extend(_split_word(a, maxw))
        else:
            out.append(a)
    return out


def _frag_atoms(lines: list[_Line]) -> list[_Atom]:
    """分割断片用に、行群のアトムを平坦化する（強制改行は br として戻す）。"""
    run = next((a.run for line in lines for a in line.atoms), None)
    if run is None:
        return []
    out: list[_Atom] = []
    for i, line in enumerate(lines):
        if i and lines[i - 1].ragged:
            out.append(_Atom("", run, 0.0, "br"))
        elif i and out and line.atoms and out[-1].kind == "word" \
                and line.atoms[0].kind == "word":
            # 空白で折り返した英単語境界。空白を戻して再折り返しでも語が連結しないようにする
            out.append(_Atom(" ", out[-1].run, _stringwidth(" ", out[-1].run), "space"))
        out.extend(line.atoms)
    return out


def _break_lines(atoms: list[_Atom], maxw: float) -> list[_Line]:
    atoms = _split_long_words(atoms, maxw)
    lines: list[_Line] = []
    cur: list[_Atom] = []
    curw = 0.0

    def flush(ragged: bool) -> None:
        nonlocal cur, curw
        trimmed, w = _trim_trailing_spaces(cur)
        lines.append(_Line(trimmed, w, ragged))
        cur = []
        curw = 0.0

    for atom in atoms:
        if atom.kind == "br":
            flush(ragged=True)
            continue
        if atom.kind == "space":
            if not cur:
                continue  # 行頭の空白は捨てる
            if curw + atom.width <= maxw + _FIT_EPS:
                cur.append(atom)
                curw += atom.width
            else:
                flush(ragged=False)  # 空白位置での折り返し → 均等割り付け対象
            continue

        w = atom.width
        if curw + w <= maxw + _FIT_EPS or not cur:
            cur.append(atom)
            curw += w
            continue

        # 折り返しが必要
        if atom.kind == "cjk" and kinsoku.cannot_start_line(atom.text):
            # 行頭禁則 → 追い込み（多少のはみ出しを許して現在行に残す）
            cur.append(atom)
            curw += w
            continue

        # 行末禁則 → 末尾の開き括弧等を次行へ送る
        moved: list[_Atom] = []
        while cur and cur[-1].kind == "cjk" and kinsoku.cannot_end_line(cur[-1].text):
            moved.insert(0, cur.pop())
        flush(ragged=False)
        cur = moved + [atom]
        curw = sum(a.width for a in cur)

    if cur:
        flush(ragged=True)
    if not lines:
        lines.append(_Line([], 0.0, True))
    # 段落の最終行は均等割り付けしない
    lines[-1].ragged = True
    return lines


class JParagraph(Flowable):
    """禁則・ルビ対応の日本語段落 Flowable。"""

    def __init__(
        self,
        runs: list[Run],
        leading: float,
        align: str = ALIGN_JUSTIFY,
        space_before: float = 0.0,
        space_after: float = 0.0,
        base_size: float = 12.0,
        bookmark: Optional[tuple[str, str, int]] = None,
    ) -> None:
        super().__init__()
        self.runs = runs
        self.leading = leading
        self.align = align
        self.spaceBefore = space_before  # ReportLab が前後の空きとして解釈する
        self.spaceAfter = space_after
        self.base_size = base_size
        self.bookmark = bookmark  # (key, title, level) 見出し用しおり
        self._atoms = _atomize(runs)
        self._lines: list[_Line] = []
        self._width = 0.0
        self._continues = False  # split() の前半断片: 最終行もページをまたいで続く

    @property
    def footnote_ids(self) -> list[int]:
        """この段落（断片ならその断片）に含まれる脚注参照 id（出現順・重複なし）。"""
        ids: list[int] = []
        for a in self._atoms:
            fid = a.run.fn_id
            if fid is not None and fid not in ids:
                ids.append(fid)
        return ids

    # --- レイアウト ------------------------------------------------------------------
    def wrap(self, availWidth: float, availHeight: float) -> tuple[float, float]:
        # ReportLab は split() が返した断片にも wrap() を呼び直す。同じ幅なら組み直さない
        # （断片の行はここで確定済み。組み直すと寡婦・孤児制御の結果が崩れうる）。
        if self._lines and availWidth == self._width:
            return availWidth, len(self._lines) * self.leading
        self._width = availWidth
        self._lines = _break_lines(self._atoms, availWidth)
        if self._continues:
            self._lines[-1].ragged = False  # 次ページへ続く最終行は均等割り付けを保つ
        return availWidth, len(self._lines) * self.leading

    def _fragment(self, lines: list[_Line], width: float, space_before: float,
                  space_after: float, bookmark, continues: bool) -> "JParagraph":
        frag = JParagraph([], self.leading, self.align, space_before, space_after,
                          self.base_size, bookmark)
        frag._atoms = _frag_atoms(lines)   # 幅が変わって組み直されても本文を失わない
        frag._lines = lines
        frag._width = width
        frag._continues = continues and not lines[-1].ragged
        return frag

    def split(self, availWidth: float, availHeight: float):
        self.wrap(availWidth, availHeight)  # 同じ幅なら組み直さない
        total = len(self._lines)
        # ReportLab の Frame._add() は wrap() の高さが availHeight+_FUZZ(1e-6) を超えたら
        # 「収まらない」と判定して split() を呼ぶ。ここで横幅用の _FIT_EPS(0.2) を使うと
        # 両者の基準がずれ、availHeight が total*leading 直下 0.2pt の窓に入ったとき
        # split() が [self]（未分割）を返して Splitting error(n==1) を誘発する。
        # 必ず ReportLab 側と同じ基準（_RL_FIT_EPS）で判定すること。
        n_fit = int((availHeight + _RL_FIT_EPS) // self.leading)
        if n_fit >= total:
            # 本来 ReportLab は「収まる」なら split() を呼ばないはずだが、
            # 万一この前提が崩れても [self] を返すと無限ループになるため、
            # 必ず 1 行以上は分割するようクランプする（フェイルセーフ）。
            n_fit = total - 1
        # 寡婦・孤児防止: 片側に 1 行だけ残さない
        if n_fit < 2:
            return []  # まるごと次ページへ
        if total - n_fit < 2:
            n_fit = total - 2
        if n_fit < 1:
            return []

        # 断片は行と元アトムの該当範囲を持つ（runs=[] だけだと wrap() で本文が消える）。
        # 脚注 id も断片ごとのアトムから求まるので、後半の参照は後半のページに付く。
        width = self._width
        first = self._fragment(self._lines[:n_fit], width, self.spaceBefore, 0.0,
                               self.bookmark, continues=True)
        rest = self._fragment(self._lines[n_fit:], width, 0.0, self.spaceAfter, None,
                              continues=self._continues)
        return [first, rest]

    # --- 描画 ------------------------------------------------------------------------
    def draw(self) -> None:
        c = self.canv
        if self.bookmark:
            key, title, level = self.bookmark
            c.bookmarkPage(key)
            c.addOutlineEntry(title, key, level=level, closed=False)

        height = len(self._lines) * self.leading
        ascent = self.base_size * 0.86
        for i, line in enumerate(self._lines):
            baseline = height - i * self.leading - ascent
            self._draw_line(line, baseline)

    def _draw_line(self, line: _Line, baseline: float) -> None:
        c = self.canv
        maxw = self._width
        atoms = line.atoms
        n = len(atoms)
        # 均等割り付け（両端揃え）の余白を算出
        extra = 0.0
        if self.align == ALIGN_JUSTIFY and not line.ragged and n > 1:
            extra = max(0.0, maxw - line.width) / (n - 1)

        if self.align == ALIGN_CENTER:
            x = (maxw - line.width) / 2.0
        elif self.align == ALIGN_RIGHT:
            x = maxw - line.width
        else:
            x = 0.0

        for idx, atom in enumerate(atoms):
            run = atom.run
            size = run.size * (0.7 if run.sup else 1.0)
            y = baseline + (run.size * 0.34 if run.sup else 0.0)

            # インラインコード背景・枠
            if run.bg is not None and atom.kind != "space":
                pad = size * 0.12
                c.setFillColor(run.bg)
                if run.border is not None:
                    c.setStrokeColor(run.border)
                    c.setLineWidth(0.5)
                    c.roundRect(x - pad, baseline - size * 0.22, atom.width + 2 * pad,
                                size * 1.18, 2, stroke=1, fill=1)
                else:
                    c.roundRect(x - pad, baseline - size * 0.22, atom.width + 2 * pad,
                                size * 1.18, 2, stroke=0, fill=1)

            if atom.kind == "image" and run.image:
                path, iw, ih = run.image
                try:
                    c.drawImage(path, x, baseline - ih * 0.18, width=iw, height=ih,
                                mask="auto")
                except Exception:
                    pass
            elif atom.text:
                c.setFont(run.font, size)
                c.setFillColor(run.color)
                c.drawString(x, y, atom.text)

            # ルビ
            if atom.kind == "ruby" and run.ruby:
                rsize = run.size * 0.5
                rwidth = pdfmetrics.stringWidth(run.ruby, run.font, rsize)
                rx = x + (atom.width - rwidth) / 2.0
                ry = baseline + run.size * 0.92
                c.setFont(run.font, rsize)
                c.setFillColor(run.color)
                c.drawString(rx, ry, run.ruby)

            # リンク下線＋注釈
            if run.underline and atom.text:
                c.setStrokeColor(run.color)
                c.setLineWidth(0.5)
                c.line(x, baseline - 1.2, x + atom.width, baseline - 1.2)
            if run.link and atom.text:
                c.linkURL(run.link, (x, baseline - 2, x + atom.width, baseline + size),
                          relative=0, thickness=0)

            x += atom.width
            if idx < n - 1:
                x += extra
