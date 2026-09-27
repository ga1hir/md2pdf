"""PDF ドキュメント生成（ノンブル・脚注・しおり・メタデータ）。

脚注は LaTeX 同様、参照のあるページの**本文ブロック下部**に別枠で配置し、その分だけ
本文の行数をそのページで減らす（版面の外＝下マージンにはノンブルのみ）。脚注量に応じて
本文フレーム高が変わりページ割りも変わるため、ページごとの脚注高を反復計算で収束させる。
フォントは同梱 Noto を埋め込むため、受け手環境に依存しない。
"""

from __future__ import annotations

import sys
from typing import Callable, Optional

from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate
from reportlab.platypus.doctemplate import ActionFlowable

from . import config, fontreg
from .builder import Builder
from .layout import Layout
from .render.inline import ALIGN_LEFT, JParagraph, Run

_SLACK = 2.0          # N 行ぴったりがフロート誤差で溢れて split 無限ループするのを防ぐ
_MAX_RESERVE_RATIO = 0.5   # 脚注が本文ブロックを占有してよい最大割合


class MdDocTemplate(BaseDocTemplate):
    def __init__(self, filename: str, layout: Layout, builder: Builder,
                 show_page_number: bool = True, title: str = "", author: str = "",
                 reserve: Optional[dict[int, float]] = None) -> None:
        x, y, w, h = layout.frame
        page_w, page_h = layout.page_size
        self.layout = layout
        self.builder = builder
        self.show_page_number = show_page_number
        self._reserve = reserve or {}          # 前パスで決めた各ページの脚注高
        self._fn_pages: dict[int, list[int]] = {}  # このパスでの「ページ→脚注 id」
        self._page_fn_ids: list[int] = []
        self._carry_fn: list[int] = []
        self._fn_overflow = False
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
        self._frame = Frame(x, self._base_y, w, self._base_h, id="body",
                            leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates([
            PageTemplate(id="main", frames=[self._frame],
                         onPage=self._page_begin, onPageEnd=self._page_end)
        ])

    # --- フレームの脚注予約（ページ開始時に本文フレーム高を縮める） ------------------
    def _page_begin(self, canvas, doc) -> None:
        r = self._reserve.get(canvas.getPageNumber(), 0.0)
        fr = self._frame
        fr._y1 = self._base_y + r
        fr._height = self._base_h - r
        fr._geom()    # _y2 と利用可能高 _aH を再計算（_reset だけでは反映されない）
        fr._reset()

    def afterFlowable(self, flowable) -> None:
        src = getattr(flowable, "_src_file", None)
        if src is not None:
            self._last_src_file = src
        image_path = getattr(flowable, "_src_image", None)
        self._last_flowable_desc = (
            f"画像 {image_path}" if image_path else type(flowable).__name__
        )
        ids = getattr(flowable, "footnote_ids", None)
        if ids:
            self._page_fn_ids.extend(ids)
            page = self.canv.getPageNumber()
            self._fn_pages.setdefault(page, []).extend(ids)

    # --- ページ終了時に脚注とノンブルを描画 ------------------------------------------
    def _page_end(self, canvas, doc) -> None:
        page = canvas.getPageNumber()
        r = self._reserve.get(page, 0.0)
        self._carry_fn = self._draw_footnotes(canvas, self._pending_ids(), r, draw=True)
        self._draw_page_number(canvas)
        self._page_fn_ids = []

    def _has_overflow_pending(self) -> bool:
        page = self.canv.getPageNumber()
        r = self._reserve.get(page, 0.0)
        return bool(self._draw_footnotes(None, self._pending_ids(), r, draw=False))

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

    def _pending_ids(self) -> list[int]:
        ids = list(self._carry_fn)
        for fid in self._page_fn_ids:
            if fid not in ids:
                ids.append(fid)
        return [i for i in ids if self.builder.footnotes.get(i) is not None]

    def _footnote_para(self, fid: int, width: float) -> JParagraph:
        fn = self.builder.styles.footnote
        num, runs = self.builder.footnotes[fid]
        para_runs = [Run(f"{num} ", fn.font, fn.size, config.COLOR_QUOTE_TEXT)]
        para_runs.extend(runs or [Run("", fn.font, fn.size, config.COLOR_TEXT)])
        para = JParagraph(para_runs, fn.leading, align=ALIGN_LEFT, base_size=fn.size)
        para.wrap(width, 1e9)
        return para

    def _draw_footnotes(self, canvas, ids: list[int], reserve: float,
                        draw: bool = True) -> list[int]:
        """脚注を予約帯（本文ブロック下部〜ノンブル直上）へ下詰めで配置し、溢れた id を返す。

        予約に余りがある（過予約の）場合は下詰めにすることで、上に自然な余白が出るだけで
        クリップしない。帯に収まらない分は次ページへ繰り越す。
        """
        if not ids:
            return []
        x, _, w, _ = self.layout.frame
        fn = self.builder.styles.footnote
        band_top = self._base_y + reserve
        floor = self._base_y + fn.size * 0.2          # ノンブルは更に下
        gap = fn.size * 0.25
        avail = band_top - floor
        if avail <= 0:
            # reserve が未確定（収束前の初回パス、または前パスに存在しなかった繰越し
            # 専用ページ）だと avail が 0 以下になり、1 ページ 1 件しか捌けなくなる。
            # 脚注が多い文書（特に複数ファイル結合）では繰越しが 10 ページ超に及び、
            # ReportLab の「10 ページ連続で内容なし」ガードに引っかかって全体が失敗
            # する。上限（_MAX_RESERVE_RATIO）までは受け入れて複数件ずつ捌けるように
            # する。実際にどこまで表示するかは次パスの required_reserve() が決める。
            avail = self._base_h * _MAX_RESERVE_RATIO - fn.size * 0.2

        taken: list = []          # (para, ph)
        total = 0.0
        leftover: list[int] = []
        for idx, fid in enumerate(ids):
            para = self._footnote_para(fid, w)
            ph = len(para._lines) * fn.leading
            add = ph + (gap if taken else 0.0)
            if total + add > avail:
                if taken:
                    leftover = ids[idx:]              # 次ページへ繰り越し
                    break
                self._fn_overflow = True              # 単独で帯を超える（収束で通常は解消）
            taken.append((para, ph))
            total += add

        if draw and taken:
            block_h = sum(ph for _, ph in taken) + gap * (len(taken) - 1)
            top = floor + min(block_h, avail)          # 下詰め（ブロック下端＝floor）
            canvas.setStrokeColor(config.COLOR_FOOTNOTE_RULE)
            canvas.setLineWidth(0.5)
            canvas.line(x, top + fn.size * 0.35, x + w * 0.35, top + fn.size * 0.35)
            y = top
            for para, ph in taken:
                para.canv = canvas
                para.drawOn(canvas, x, y - ph)
                y -= ph + gap
        return leftover

    # --- 反復計算用: このパスで判明した「ページ→必要脚注高」 -------------------------
    def required_reserve(self) -> dict[int, float]:
        fn = self.builder.styles.footnote
        x, _, w, _ = self.layout.frame
        cap = self._base_h * _MAX_RESERVE_RATIO
        res: dict[int, float] = {}
        for page, ids in self._fn_pages.items():
            seen: list[int] = []
            for i in ids:
                if i not in seen and self.builder.footnotes.get(i) is not None:
                    seen.append(i)
            if not seen:
                continue
            total = fn.size * 0.9                  # 区切り罫＋上下の余白
            for fid in seen:
                para = self._footnote_para(fid, w)
                total += len(para._lines) * fn.leading + fn.size * 0.25
            res[page] = min(total, cap)
        return res


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
                  author: str = "") -> int:
    """脚注の予約高を反復計算で収束させながら PDF 化し、総ページ数を返す。

    make_story() は毎パス新しい (story, builder) を返すこと（Flowable の使い回しは不可）。
    脚注が無ければ 1 パスで終わる。
    """
    fontreg.register_fonts()
    reserve: dict[int, float] = {}
    doc = None
    for _ in range(8):
        story, builder = make_story()
        doc = MdDocTemplate(filename, layout, builder, show_page_number, title,
                            author, reserve=reserve)
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
        req = doc.required_reserve()
        # 既存の予約で全ページの脚注が収まっていれば収束（クリップしない）
        if all(v <= reserve.get(p, 0.0) + 1.0 for p, v in req.items()):
            break
        # 単調マージ（脚注のあるページのみ・予約は減らさない）→ 振動を止めて収束させる
        reserve = {p: max(reserve.get(p, 0.0), v) for p, v in req.items()}
    if doc is not None and doc._fn_overflow:
        print(f"  警告: 単独で脚注領域を超える脚注があります: {filename}",
              file=sys.stderr)
    return doc.page if doc else 0


def render_to_pdf(filename: str, story: list, layout: Layout, builder: Builder,
                  show_page_number: bool = True, title: str = "",
                  author: str = "") -> int:
    """単一の (story, builder) を用いる薄いラッパ。

    脚注の反復収束には Flowable の作り直しが必要なため、内部では同じ story/builder を
    返すファクトリを使う（脚注が無い場合や 1 パスで収束する場合に適切）。脚注を含み
    厳密な収束が必要な場合は render_passes を直接使うこと。
    """
    return render_passes(filename, lambda: (story, builder), layout,
                         show_page_number, title, author)
