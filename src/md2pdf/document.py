"""PDF ドキュメント生成（ノンブル・脚注・しおり・メタデータ）。

脚注は LaTeX 同様、参照のあるページの**本文ブロック下部**に別枠で配置し、その分だけ
本文の行数をそのページで減らす（版面の外＝下マージンにはノンブルのみ）。本文フレームに
Flowable を置く時点で、その Flowable が持ち込む脚注の高さを差し引いて入るかを判定する
（`_FootnoteFrame`）。予約はそのページに実際に置かれた脚注だけから決まるため 1 パスで確定し、
反復計算の振動や古い予約の残存は起こらない。
フォントは同梱 Noto を埋め込むため、受け手環境に依存しない。
"""

from __future__ import annotations

import sys
from copy import deepcopy
from typing import Callable, Optional

from reportlab.platypus import BaseDocTemplate, Flowable, Frame, PageTemplate
from reportlab.platypus.doctemplate import ActionFlowable

from . import config, fontreg
from .builder import Builder
from .layout import Layout
from .render.inline import ALIGN_LEFT, JParagraph, Run

_SLACK = 2.0          # N 行ぴったりがフロート誤差で溢れて split 無限ループするのを防ぐ
_MAX_RESERVE_RATIO = 0.5   # 脚注が本文ブロックを占有してよい最大割合
_MAX_SINGLE_RATIO = 0.85   # 単独で上限を超える脚注 1 件に許す最大割合（超えると重なる）
_SPLIT_TRIES = 8           # 分割前半の脚注に合わせて予約を増やしながら分割し直す上限


def _footnote_ids(f) -> list[int]:
    """Flowable（入れ子を含む）に含まれる脚注参照 id を出現順・重複なしで返す。

    JParagraph は断片ごとに自分のアトムから id を求める。ListItem/Heading（.para）、
    引用（.children）、KeepTogether（._content）、表（._cellvalues）は中身を辿る。
    """
    ids: list[int] = []

    def add(src) -> None:
        for i in src:
            if i not in ids:
                ids.append(i)

    own = getattr(f, "footnote_ids", None)
    if own:
        add(own)
    para = getattr(f, "para", None)
    if para is not None:
        add(_footnote_ids(para))
    for attr in ("children", "_content"):
        for ch in getattr(f, attr, None) or []:
            if isinstance(ch, Flowable):
                add(_footnote_ids(ch))
    for row in getattr(f, "_cellvalues", None) or []:
        for cell in row:
            for c in (cell if isinstance(cell, (list, tuple)) else [cell]):
                if isinstance(c, Flowable):
                    add(_footnote_ids(c))
    return ids


class _FootnoteFrame(Frame):
    """脚注の高さを差し引いて本文を置く本文フレーム（LaTeX 型）。

    フレーム下端（= 脚注帯の上端）を `set_reserve()` で動かす。上端 `_y2` は不変なので、
    すでに置いた本文の位置は変わらない。
    """

    def __init__(self, doc: "MdDocTemplate", x: float, y: float, w: float, h: float):
        Frame.__init__(self, x, y, w, h, id="body", leftPadding=0, rightPadding=0,
                       topPadding=0, bottomPadding=0)
        self._doc = doc
        self.reserve = 0.0

    def __deepcopy__(self, memo):
        # ReportLab の _listWrapOn（KeepTogether 等）は現フレームを deepcopy する。
        # 文書テンプレートは複製できない（モジュール参照を持つ）ので共有させる。
        memo[id(self._doc)] = self._doc
        new = self.__class__.__new__(self.__class__)
        memo[id(self)] = new
        for k, v in self.__dict__.items():
            new.__dict__[k] = deepcopy(v, memo)
        return new

    def set_reserve(self, r: float) -> None:
        d = self._doc
        self.reserve = r
        self.__dict__["_y1"] = d._base_y + r
        self.__dict__["_height"] = d._base_h - r
        self._geom()   # _y2 は不変、_y1p と利用可能高 _aH を再計算

    def _new_ids(self, flowable) -> list[int]:
        pending = self._doc._pending_ids()
        fns = self._doc.builder.footnotes
        return [i for i in _footnote_ids(flowable)
                if i not in pending and fns.get(i) is not None]

    def add(self, flowable, canv, trySplit=0):
        new = self._new_ids(flowable)
        old = self.reserve
        if new:
            self.set_reserve(max(old, self._doc._reserve_for(new)))
        ok = Frame.add(self, flowable, canv, trySplit)
        if ok:
            self._doc._body_bottom = self._y + flowable.getSpaceAfter()
        elif new:
            self.set_reserve(old)
        return ok

    def split(self, flowable, canv):
        new = self._new_ids(flowable)
        if not new:
            return Frame.split(self, flowable, canv)
        # 前半の断片が持ち込む脚注の分だけ予約を増やして分割し直す。予約は単調増加かつ
        # 上限付きなので必ず止まる。続く add(S[0]) が同じ予約を張り直すので、ここでは戻す。
        old = r = self.reserve
        try:
            for _ in range(_SPLIT_TRIES):
                self.set_reserve(r)
                S = Frame.split(self, flowable, canv)
                if not S:
                    return S
                head = [i for i in _footnote_ids(S[0]) if i in new]
                need = max(old, self._doc._reserve_for(head)) if head else old
                if need <= r + 1e-6:
                    return S
                r = need
            return []
        finally:
            self.set_reserve(old)


class MdDocTemplate(BaseDocTemplate):
    def __init__(self, filename: str, layout: Layout, builder: Builder,
                 show_page_number: bool = True, title: str = "",
                 author: str = "") -> None:
        x, y, w, h = layout.frame
        page_w, page_h = layout.page_size
        self.layout = layout
        self.builder = builder
        self.show_page_number = show_page_number
        self._page_fn_ids: list[int] = []      # このページで参照された脚注 id
        self._carry_fn: list[int] = []         # 前ページから繰り越した脚注 id
        self._fn_cache: dict[int, tuple[JParagraph, float]] = {}
        self._fn_oversize: list[int] = []      # 単独で上限を超えた脚注の表示番号
        self._body_bottom: Optional[float] = None
        self.page_stats: dict[int, dict] = {}  # 検証用: ページごとの予約・必要高・重なり
        self._base_y = y - _SLACK
        self._base_h = h + _SLACK
        self._last_src_file: Optional[str] = None   # 直近まで処理できた入力ファイル（診断用）
        self._last_flowable_desc: str = ""

        BaseDocTemplate.__init__(
            self, filename, pagesize=layout.page_size,
            leftMargin=x, rightMargin=page_w - x - w,
            topMargin=page_h - (y + h), bottomMargin=y,
            title=title or None, author=author or None,
        )
        self._frame = _FootnoteFrame(self, x, self._base_y, w, self._base_h)
        self.addPageTemplates([
            PageTemplate(id="main", frames=[self._frame],
                         onPage=self._page_begin, onPageEnd=self._page_end)
        ])

    # --- 脚注帯の寸法（予約と描画で同じ計算を使う） ------------------------------------
    def _footnote_para(self, fid: int) -> tuple[JParagraph, float]:
        hit = self._fn_cache.get(fid)
        if hit is not None:
            return hit
        fn = self.builder.styles.footnote
        num, runs = self.builder.footnotes[fid]
        para_runs = [Run(f"{num} ", fn.font, fn.size, config.COLOR_QUOTE_TEXT)]
        para_runs.extend(runs or [Run("", fn.font, fn.size, config.COLOR_TEXT)])
        para = JParagraph(para_runs, fn.leading, align=ALIGN_LEFT, base_size=fn.size)
        para.wrap(self.layout.frame[2], 1e9)
        hit = (para, len(para._lines) * fn.leading)
        self._fn_cache[fid] = hit
        return hit

    def _band(self, ids: list[int]):
        """脚注 ids を帯に並べたときの (載せる [(para, ph)], 繰り越す ids, 帯の高さ)。

        帯の高さ = 区切り罫と上下の余白 + 各脚注の高さ + 脚注間の空き。上限
        （本文ブロックの _MAX_RESERVE_RATIO）を超える分は次ページへ繰り越す。先頭の 1 件が
        単独で上限を超える場合だけは、_MAX_SINGLE_RATIO まで載せる。
        """
        fn = self.builder.styles.footnote
        gap = fn.size * 0.25
        cap = self._base_h * _MAX_RESERVE_RATIO
        taken: list[tuple[JParagraph, float]] = []
        height = fn.size * 0.9
        for idx, fid in enumerate(ids):
            para, ph = self._footnote_para(fid)
            add = ph + (gap if taken else 0.0)
            if height + add > cap and taken:
                return taken, ids[idx:], height
            taken.append((para, ph))
            height += add
        if not taken:
            return [], [], 0.0
        return taken, [], min(height, self._base_h * _MAX_SINGLE_RATIO)

    def _reserve_for(self, new_ids: list[int]) -> float:
        """このページの既存の脚注に new_ids を加えたときに必要な予約高。"""
        return self._band(self._pending_ids() + new_ids)[2]

    def _pending_ids(self) -> list[int]:
        ids = list(self._carry_fn)
        for fid in self._page_fn_ids:
            if fid not in ids:
                ids.append(fid)
        return [i for i in ids if self.builder.footnotes.get(i) is not None]

    # --- ページ開始: 繰越し脚注の分を最初から予約する ----------------------------------
    def _page_begin(self, canvas, doc) -> None:
        self._page_fn_ids = []
        self._body_bottom = None
        self._frame.set_reserve(self._band(self._pending_ids())[2])

    def afterFlowable(self, flowable) -> None:
        src = getattr(flowable, "_src_file", None)
        if src is not None:
            self._last_src_file = src
        image_path = getattr(flowable, "_src_image", None)
        self._last_flowable_desc = (
            f"画像 {image_path}" if image_path else type(flowable).__name__
        )
        for fid in _footnote_ids(flowable):
            if fid not in self._page_fn_ids:
                self._page_fn_ids.append(fid)

    # --- ページ終了時に脚注とノンブルを描画 ------------------------------------------
    def _page_end(self, canvas, doc) -> None:
        page = canvas.getPageNumber()
        taken, leftover, height = self._band(self._pending_ids())
        reserve = self._frame.reserve
        fn_top = self._draw_footnotes(canvas, taken) if taken else None
        body = self._body_bottom
        self.page_stats[page] = {
            "reserve": reserve,
            "required": height,
            "body_bottom": body,
            "fn_top": fn_top,
            "overlap": bool(fn_top is not None and body is not None
                            and body < fn_top - 0.01),
            "carried": len(leftover),
        }
        self._carry_fn = leftover
        self._page_fn_ids = []
        self._draw_page_number(canvas)

    def _has_overflow_pending(self) -> bool:
        return bool(self._band(self._pending_ids())[1])

    def _nombre_baseline(self) -> float:
        return max(14.0, self.layout.frame[1] * 0.45)

    def _draw_page_number(self, canvas) -> None:
        if not self.show_page_number:
            return
        page_w, _ = self.layout.page_size
        size = self.layout.font_size * 0.8
        canvas.setFont(config.FONT_SANS, size)
        canvas.setFillColor(config.COLOR_PAGE_NUMBER)
        canvas.drawCentredString(page_w / 2.0, self._nombre_baseline(),
                                 str(canvas.getPageNumber()))

    def _draw_footnotes(self, canvas, taken: list[tuple[JParagraph, float]]) -> float:
        """脚注を帯（本文ブロック下部〜ノンブル直上）に下詰めで描き、区切り罫の y を返す。"""
        x, _, w, _ = self.layout.frame
        fn = self.builder.styles.footnote
        gap = fn.size * 0.25
        floor = self._base_y + fn.size * 0.2          # ノンブルは更に下
        block_h = sum(ph for _, ph in taken) + gap * (len(taken) - 1)
        if fn.size * 0.9 + block_h > self._base_h * _MAX_RESERVE_RATIO:
            num = self.builder.footnotes[self._pending_ids()[0]][0]
            if num not in self._fn_oversize:
                self._fn_oversize.append(num)
        top = floor + block_h
        rule_y = top + fn.size * 0.35
        canvas.setStrokeColor(config.COLOR_FOOTNOTE_RULE)
        canvas.setLineWidth(0.5)
        canvas.line(x, rule_y, x + w * 0.35, rule_y)
        y = top
        for para, ph in taken:
            para.canv = canvas
            para.drawOn(canvas, x, y - ph)
            y -= ph + gap
        return rule_y


class _CondPageBreak(ActionFlowable):
    """脚注が予約帯に収まらず繰り越しが残る場合だけ改ページする番兵（末尾掃き出し用）。"""

    def __init__(self, doc: "MdDocTemplate") -> None:
        ActionFlowable.__init__(self)
        self._doc = doc

    def apply(self, doc) -> None:
        if self._doc._has_overflow_pending():
            doc.handle_pageBreak()


def render_passes(filename: str, make_story: Callable[[], "tuple[list, Builder]"],
                  layout: Layout, show_page_number: bool = True, title: str = "",
                  author: str = "", stats: Optional[dict] = None) -> int:
    """PDF 化して総ページ数を返す。

    脚注は本文を置く時点で予約するため 1 パスで確定する（make_story() は 1 回だけ呼ぶ。
    名前と引数は従来の反復版との互換のため）。stats を渡すとページごとの予約・必要高・
    重なりと警告を格納する（検証用）。
    """
    fontreg.register_fonts()
    story, builder = make_story()
    doc = MdDocTemplate(filename, layout, builder, show_page_number, title, author)
    flowables = list(story)
    if builder.footnotes:
        flowables += [_CondPageBreak(doc) for _ in range(len(builder.footnotes) + 1)]
    try:
        doc.build(flowables)
    except Exception as e:  # noqa: BLE001
        where = []
        if doc._last_src_file:
            where.append(f"入力ファイル: {doc._last_src_file}")
        where.append(f"到達ページ: {doc.page}付近")
        if doc._last_flowable_desc:
            where.append(f"直前の要素: {doc._last_flowable_desc}")
        raise RuntimeError(f"{e}（{', '.join(where)}）") from e

    warnings: list[str] = []
    overlap = [p for p, s in doc.page_stats.items() if s["overlap"]]
    if overlap:
        warnings.append(f"脚注が本文に重なっているページがあります: {overlap}")
    if doc._fn_oversize:
        warnings.append(f"単独で脚注領域を超える脚注があります（脚注 {doc._fn_oversize}）")
    if doc._carry_fn:
        warnings.append(f"出力されなかった脚注があります: {len(doc._carry_fn)}件")
    for w in warnings:
        print(f"  警告: {w}: {filename}", file=sys.stderr)
    if stats is not None:
        stats["pages"] = doc.page_stats
        stats["passes"] = 1
        stats["warnings"] = warnings
    return doc.page


def render_to_pdf(filename: str, story: list, layout: Layout, builder: Builder,
                  show_page_number: bool = True, title: str = "",
                  author: str = "") -> int:
    """単一の (story, builder) を用いる薄いラッパ。"""
    return render_passes(filename, lambda: (story, builder), layout,
                         show_page_number, title, author)
