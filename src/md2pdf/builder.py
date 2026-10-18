"""Markdown トークン → ReportLab Flowable ストーリーへの変換（本体）。

markdown-it-py の SyntaxTreeNode を歩き、JParagraph やコードブロック等の Flowable を
生成する。脚注の収集、改ページ記法、見出しのしおり、ルビ・数式・Mermaid もここで扱う。
"""

from __future__ import annotations

import html
import os
import re
from typing import Optional

from markdown_it.tree import SyntaxTreeNode
from reportlab.lib import colors
from reportlab.platypus import (
    Flowable, PageBreak, Spacer, Table, TableStyle,
)

from . import config
from .layout import Layout
from .parser import make_parser
from .render import flowables as F
from .render import highlight
from .render.inline import (
    ALIGN_CENTER, ALIGN_LEFT, JParagraph, Run,
)
from .render.math_render import render_math
from .render.mermaid import render_mermaid
from .render.styles import Styles

_RUBY_RE = re.compile(r"\{([^|{}]+)\|([^|{}]+)\}")
# 下線タグ。markdown-it は <u> と </u> を別々の html_inline トークンとして出す
_U_OPEN_RE = re.compile(r"^<u(\s[^>]*)?>$", re.IGNORECASE)
_U_CLOSE_RE = re.compile(r"^</u\s*>$", re.IGNORECASE)
_TASK_RE = re.compile(r"^\[([ xX])\]\s+")
_ALERT_RE = re.compile(r"^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*$", re.IGNORECASE)
_FONT_MAP = {
    "serif": (config.FONT_SERIF, config.FONT_SERIF_BOLD),
    "sans": (config.FONT_SANS, config.FONT_SANS_BOLD),
    "mono": (config.FONT_MONO, config.FONT_MONO_BOLD),
}


class _Ctx:
    """インラインのスタイル文脈。"""

    def __init__(self, base="serif", size=12.0, color=config.COLOR_TEXT,
                 bold=False, link=None, code=False):
        self.base = base
        self.size = size
        self.color = color
        self.bold = bold
        self.link = link
        self.code = code

    def copy(self, **kw) -> "_Ctx":
        c = _Ctx(self.base, self.size, self.color, self.bold, self.link, self.code)
        for k, v in kw.items():
            setattr(c, k, v)
        return c

    @property
    def font(self) -> str:
        normal, bold = _FONT_MAP[self.base]
        return bold if self.bold else normal


class Builder:
    def __init__(self, layout: Layout, base_dir: Optional[str] = None) -> None:
        from . import fontreg
        fontreg.register_fonts()  # 幅計測のため構築前に登録が必要
        self.base_dir = base_dir  # 相対画像パスの基準（Markdown ファイルのあるディレクトリ）
        self.layout = layout
        self.styles = Styles(layout)
        self.md = make_parser()
        self.footnotes: dict[int, tuple[int, list[Run]]] = {}
        self.fn_offset = 0  # 結合出力で脚注 id を全体一意にするためのオフセット
        self._bm = 0
        self._outline_stack: list[int] = []  # しおりの階層正規化用
        self._src_lines: list[str] = []      # build() で設定（字下げ復元用）
        self._u_depth = 0                    # <u> の入れ子深さ（インライン塊ごとにリセット）

    def next_file(self) -> None:
        """結合出力で次ファイルへ進む前に脚注オフセットを更新する。"""
        if self.footnotes:
            self.fn_offset = max(self.footnotes) + 1

    # --- エントリ --------------------------------------------------------------------
    def build(self, src: str) -> list[Flowable]:
        self._src_lines = src.split("\n")  # 段落先頭の全角字下げ復元用（.map で参照）
        tokens = self.md.parse(src)
        tree = SyntaxTreeNode(tokens)
        story: list[Flowable] = []
        for node in tree.children:
            self._block(node, story, indent=0.0)
        return story

    # --- ブロック --------------------------------------------------------------------
    def _block(self, node: SyntaxTreeNode, story: list[Flowable], indent: float) -> None:
        t = node.type
        if t == "heading":
            self._heading(node, story)
        elif t == "paragraph":
            self._paragraph(node, story, indent)
        elif t == "fence" or t == "code_block":
            self._code(node, story)
        elif t == "blockquote":
            self._blockquote(node, story)
        elif t in ("bullet_list", "ordered_list"):
            self._list(node, story, indent, ordered=(t == "ordered_list"))
        elif t == "table":
            self._table(node, story)
        elif t == "hr":
            story.append(F.Rule(space_before=self.layout.leading,
                                space_after=self.layout.leading))
        elif t == "math_block":
            self._math_block(node, story)
        elif t == "html_block":
            self._html(node.content, story)
        elif t == "footnote_block":
            self._footnote_defs(node)
        elif t == "dl":
            self._deflist(node, story, indent)
        else:
            # 未対応ブロックは子を辿る
            for ch in node.children:
                self._block(ch, story, indent)

    def _heading(self, node: SyntaxTreeNode, story: list[Flowable]) -> None:
        level = int(node.tag[1])
        st = self.styles.heading(level)
        ctx = _Ctx(base="sans", size=st.size, bold=(level <= 4))
        runs, blocks = self._inline(node.children[0], ctx)
        title = self._plain_text(node.children[0])
        self._bm += 1
        key = f"bm{self._bm}"
        outline_level = self._outline_level(level)
        para = JParagraph(runs, st.leading, align=ALIGN_LEFT,
                          space_before=st.space_before, space_after=st.space_after,
                          base_size=st.size, bookmark=(key, title, outline_level))
        story.append(F.Heading(para, level))
        story.extend(blocks)

    def _outline_level(self, level: int) -> int:
        """見出しの Markdown レベル(1-6)を、飛びの無い PDF しおり階層へ正規化する。"""
        while self._outline_stack and self._outline_stack[-1] >= level:
            self._outline_stack.pop()
        depth = len(self._outline_stack)
        self._outline_stack.append(level)
        return depth

    def _leading_zenkaku(self, node: SyntaxTreeNode) -> int:
        """段落の元ソース行頭にある全角スペース(U+3000)の個数を返す（字下げ復元用）。"""
        m = getattr(node, "map", None)
        if not m:
            return 0
        start = m[0]
        if start is None or start >= len(self._src_lines):
            return 0
        line = self._src_lines[start]
        return len(line) - len(line.lstrip("　"))

    def _paragraph(self, node: SyntaxTreeNode, story: list[Flowable], indent: float) -> None:
        inline = node.children[0] if node.children else None
        if inline is None:
            return
        ctx = _Ctx(size=self.layout.font_size)
        runs, blocks = self._inline(inline, ctx)
        # 段落先頭の全角スペース（字下げ）を復元する。markdown-it が空白として除去するため、
        # 元ソース行から個数を数えて Run として先頭へ戻す（1字=1em の CJK アトムとして組まれる）。
        n = self._leading_zenkaku(node)
        if n and runs:
            runs.insert(0, Run("　" * n, ctx.font, ctx.size, ctx.color))
        if any(r.text or r.image for r in runs):
            para = JParagraph(runs, self.layout.leading, base_size=self.layout.font_size,
                              space_after=self.styles.body.space_after)
            if indent:
                para = _indented(para, indent)
            story.append(para)
        story.extend(blocks)

    def _code(self, node: SyntaxTreeNode, story: list[Flowable]) -> None:
        info = (node.info or "").strip().split()
        lang = info[0] if info else None
        content = node.content.rstrip("\n")
        if lang == "mermaid":
            g = render_mermaid(content, self.layout.body_width, config.FONT_SANS,
                               self.styles.code_size)
            if g is not None:
                g.hAlign = "CENTER"
                story.append(Spacer(1, self.layout.leading * 0.3))
                story.append(g)
                story.append(Spacer(1, self.layout.leading * 0.3))
                return
        lines = highlight.highlight_code(content, lang, self.styles.code_size)
        cb = F.CodeBlock(lines, self.styles.code_size, self.styles.code_leading)
        cb.spaceBefore = self.layout.leading * 0.3
        cb.spaceAfter = self.layout.leading * 0.3
        story.append(cb)

    def _blockquote(self, node: SyntaxTreeNode, story: list[Flowable]) -> None:
        kind = self._alert_kind(node)
        if kind:
            self._alert(node, kind, story)
            return
        inner: list[Flowable] = []
        for ch in node.children:
            self._block(ch, inner, indent=0.0)
        story.append(F.blockquote(inner, self.layout.leading))

    def _alert_kind(self, node: SyntaxTreeNode) -> Optional[str]:
        """引用が GFM アラート（先頭行が [!NOTE] 等のみ）なら種類名（小文字）を返す。

        GitHub に合わせ、マーカーと同じ行に本文が続く場合・未知の種類・本文が空の場合は
        通常の引用とする。
        """
        children = node.children
        if not children or children[0].type != "paragraph" or not children[0].children:
            return None
        items = children[0].children[0].children
        if not items or items[0].type != "text":
            return None
        m = _ALERT_RE.match(items[0].content)
        if not m:
            return None
        if len(items) > 1 and items[1].type not in ("softbreak", "hardbreak"):
            return None
        if len(items) <= 2 and len(children) == 1:
            return None
        return m.group(1).lower()

    def _alert(self, node: SyntaxTreeNode, kind: str, story: list[Flowable]) -> None:
        inner: list[Flowable] = [F.AlertTitle(kind, self.layout.font_size, self.layout.leading)]
        # マーカーと直後の改行を除く。次行頭の全角字下げは text に残るのでそのまま組まれる。
        inline = node.children[0].children[0]
        inline.children = inline.children[2:]
        for ch in node.children:
            if ch.type == "paragraph" and not ch.children[0].children:
                continue  # マーカーだけの段落
            self._block(ch, inner, indent=0.0)
        story.append(F.alert(inner, kind, self.layout.leading))

    def _list(self, node: SyntaxTreeNode, story: list[Flowable], indent: float,
              ordered: bool) -> None:
        start = 1
        if ordered and node.attrs.get("start"):
            try:
                start = int(node.attrs["start"])
            except (ValueError, TypeError):
                start = 1
        num = start
        step = self.layout.font_size * 1.6
        for item in node.children:
            if item.type != "list_item":
                continue
            marker = f"{num}." if ordered else "•"
            self._list_item(item, story, indent + step, marker)
            num += 1

    def _list_item(self, item: SyntaxTreeNode, story: list[Flowable], indent: float,
                   marker: str) -> None:
        children = list(item.children)
        first_done = False
        for ch in children:
            if ch.type == "paragraph" and not first_done:
                inline = ch.children[0] if ch.children else None
                ctx = _Ctx(size=self.layout.font_size)
                runs, blocks = self._inline(inline, ctx) if inline else ([], [])
                checkbox = None
                # タスクリスト検出（先頭の [ ] / [x]）
                if runs and runs[0].text:
                    m = _TASK_RE.match(runs[0].text)
                    if m:
                        checkbox = m.group(1).lower() == "x"
                        runs[0] = Run(runs[0].text[m.end():], runs[0].font,
                                      runs[0].size, runs[0].color)
                        marker_use = ""
                    else:
                        marker_use = marker
                else:
                    marker_use = marker
                para = JParagraph(runs, self.layout.leading,
                                  base_size=self.layout.font_size)
                li = F.ListItem(para, marker_use, indent, checkbox)
                story.append(li)
                story.extend(blocks)
                first_done = True
            elif ch.type in ("bullet_list", "ordered_list"):
                self._list(ch, story, indent, ordered=(ch.type == "ordered_list"))
            else:
                self._block(ch, story, indent)

    def _table(self, node: SyntaxTreeNode, story: list[Flowable]) -> None:
        rows: list[list[JParagraph]] = []
        header_rows = 0
        for section in node.children:  # thead / tbody
            is_head = section.type == "thead"
            for tr in section.children:
                cells = []
                for cell in tr.children:  # th / td
                    inline = cell.children[0] if cell.children else None
                    ctx = _Ctx(base="sans" if is_head else "serif",
                               size=self.styles.table_size,
                               bold=is_head)
                    runs, _ = self._inline(inline, ctx) if inline else ([], [])
                    align = {"center": ALIGN_CENTER, "right": "right"}.get(
                        _cell_align(cell), ALIGN_LEFT)
                    cells.append(JParagraph(runs, self.styles.table_leading,
                                            align=align,
                                            base_size=self.styles.table_size))
                rows.append(cells)
                if is_head:
                    header_rows += 1
        if not rows:
            return
        ncols = max(len(r) for r in rows)
        for r in rows:
            while len(r) < ncols:
                r.append(JParagraph([], self.styles.table_leading,
                                    base_size=self.styles.table_size))
        col_w = self.layout.body_width / ncols
        tbl = Table(rows, colWidths=[col_w] * ncols, repeatRows=header_rows)
        ts = [
            ("GRID", (0, 0), (-1, -1), 0.5, config.COLOR_TABLE_BORDER),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        if header_rows:
            ts.append(("BACKGROUND", (0, 0), (-1, header_rows - 1),
                       config.COLOR_TABLE_HEADER_BG))
        for i in range(header_rows, len(rows)):
            if (i - header_rows) % 2 == 1:
                ts.append(("BACKGROUND", (0, i), (-1, i), config.COLOR_TABLE_STRIPE_BG))
        tbl.setStyle(TableStyle(ts))
        tbl.spaceBefore = self.layout.leading * 0.4
        tbl.spaceAfter = self.layout.leading * 0.4
        tbl.hAlign = "LEFT"
        story.append(tbl)

    def _math_block(self, node: SyntaxTreeNode, story: list[Flowable]) -> None:
        expr = node.content.strip()
        r = render_math(expr, self.layout.font_size * 1.1, display=True)
        if r is None:
            self._code_fallback(expr, story)
            return
        path, w, h = r
        from reportlab.platypus import Image as RLImage
        img = RLImage(path, width=w, height=h)
        img.hAlign = "CENTER"
        story.append(Spacer(1, self.layout.leading * 0.3))
        story.append(img)
        story.append(Spacer(1, self.layout.leading * 0.3))

    def _deflist(self, node: SyntaxTreeNode, story: list[Flowable], indent: float) -> None:
        for ch in node.children:
            if ch.type == "dt":
                ctx = _Ctx(base="sans", size=self.layout.font_size, bold=True)
                inline = ch.children[0] if ch.children else None
                runs, _ = self._inline(inline, ctx) if inline else ([], [])
                story.append(JParagraph(runs, self.layout.leading,
                                        base_size=self.layout.font_size))
            elif ch.type == "dd":
                for c in ch.children:
                    self._block(c, story, indent + self.layout.font_size * 1.6)

    def _code_fallback(self, text: str, story: list[Flowable]) -> None:
        lines = highlight.highlight_code(text, None, self.styles.code_size)
        story.append(F.CodeBlock(lines, self.styles.code_size, self.styles.code_leading))

    # --- HTML ------------------------------------------------------------------------
    def _html(self, content: str, story: list[Flowable]) -> None:
        low = content.lower()
        if "pagebreak" in low or "page-break" in low:
            story.append(PageBreak())
            # ページ区切り div 等に本文が無ければここで終わり
            text = _html_to_text(content)
            if not _strip_u_sentinels(text).strip():
                return
        if low.strip().startswith("<!--"):
            return  # コメントは無視
        text = _html_to_text(content)
        self._u_depth = 0
        for para in text.split("\n\n"):
            para = para.strip("\n")
            if not _strip_u_sentinels(para).strip():
                continue
            # <u>/</u> の番兵で区切り、下線の有無を切り替えながら Run 化する
            runs: list[Run] = []
            ctx = _Ctx(size=self.layout.font_size)
            for part in re.split(f"([{_U_OPEN}{_U_CLOSE}])", para):
                if part == _U_OPEN:
                    self._u_depth += 1
                elif part == _U_CLOSE:
                    self._u_depth = max(0, self._u_depth - 1)
                elif part:
                    runs.extend(self._text_runs(part, ctx))
            story.append(JParagraph(runs, self.layout.leading,
                                    base_size=self.layout.font_size,
                                    space_after=self.styles.body.space_after))

    # --- インライン ------------------------------------------------------------------
    def _inline(self, inline: SyntaxTreeNode, ctx: _Ctx):
        runs: list[Run] = []
        blocks: list[Flowable] = []
        self._u_depth = 0  # 閉じ忘れの <u> を前の段落から持ち越さない
        self._walk_inline(inline, ctx, runs, blocks)
        return runs, blocks

    def _walk_inline(self, node: SyntaxTreeNode, ctx: _Ctx,
                     runs: list[Run], blocks: list[Flowable]) -> None:
        for ch in node.children:
            t = ch.type
            if t == "text":
                runs.extend(self._text_runs(ch.content, ctx))
            elif t == "strong":
                self._walk_inline(ch, ctx.copy(bold=True), runs, blocks)
            elif t == "em":
                self._walk_inline(ch, ctx, runs, blocks)  # CJK にイタリック無し
            elif t == "s":
                self._walk_inline(ch, ctx, runs, blocks)
            elif t == "code_inline":
                runs.append(Run(ch.content, config.FONT_MONO,
                                self.styles.code_size, config.COLOR_CODE_DEFAULT,
                                bg=config.COLOR_INLINE_CODE_BG,
                                border=config.COLOR_INLINE_CODE_BORDER,
                                underline=self._u_depth > 0))
            elif t == "link":
                href = ch.attrs.get("href", "")
                self._walk_inline(ch, ctx.copy(color=config.COLOR_LINK, link=href),
                                  runs, blocks)
            elif t == "image":
                self._inline_image(ch, blocks)
            elif t == "softbreak":
                pass  # CJK: 行内のソフト改行は無視
            elif t == "hardbreak":
                runs.append(Run("\n", ctx.font, ctx.size, ctx.color))
            elif t == "math_inline":
                self._inline_math(ch.content, ctx, runs)
            elif t == "footnote_ref":
                rid = int(ch.meta.get("id", 0))
                num = rid + 1
                key = rid + self.fn_offset
                prev = runs[-1] if runs else None
                if prev is not None and prev.fn_id is not None:
                    # 連続する参照は区切る（[^1][^2] が「12」と読めないよう「1,2」にする）。
                    # 前の番号側に付けて、カンマが行頭に来ないようにする
                    prev.text += ","
                runs.append(Run(str(num), ctx.font, ctx.size, config.COLOR_LINK, sup=True,
                                fn_id=key))
            elif t == "html_inline":
                tag = ch.content.strip()
                if _U_OPEN_RE.match(tag):
                    self._u_depth += 1
                elif _U_CLOSE_RE.match(tag):
                    self._u_depth = max(0, self._u_depth - 1)  # 余分な </u> は無視
                elif "<br" in tag.lower():
                    runs.append(Run("\n", ctx.font, ctx.size, ctx.color))
            else:
                self._walk_inline(ch, ctx, runs, blocks)

    def _text_runs(self, text: str, ctx: _Ctx) -> list[Run]:
        """テキストをルビ記法で分割しつつ Run 列へ。"""
        out: list[Run] = []
        pos = 0
        ul = bool(ctx.link) or self._u_depth > 0
        for m in _RUBY_RE.finditer(text):
            if m.start() > pos:
                out.append(Run(text[pos:m.start()], ctx.font, ctx.size, ctx.color,
                               underline=ul, link=ctx.link))
            out.append(Run(m.group(1), ctx.font, ctx.size, ctx.color, ruby=m.group(2),
                           underline=ul, link=ctx.link))
            pos = m.end()
        if pos < len(text):
            out.append(Run(text[pos:], ctx.font, ctx.size, ctx.color,
                           underline=ul, link=ctx.link))
        return out

    def _inline_image(self, node: SyntaxTreeNode, blocks: list[Flowable]) -> None:
        src = node.attrs.get("src", "")
        path = src
        if self.base_dir and not os.path.isabs(src) and "://" not in src:
            path = os.path.normpath(os.path.join(self.base_dir, src))
        img = F.make_image(path, self.layout.body_width,
                           self.layout.page_size[1] * 0.8)
        if img is not None:
            img.hAlign = "CENTER"
            img._src_image = path  # エラー時にどの画像由来か特定するため
            blocks.append(img)

    def _inline_math(self, expr: str, ctx: _Ctx, runs: list[Run]) -> None:
        r = render_math(expr, ctx.size)
        if r is None:
            runs.append(Run(expr, config.FONT_MONO, self.styles.code_size, ctx.color))
            return
        path, w, h = r
        runs.append(Run("", ctx.font, ctx.size, ctx.color, image=(path, w, h)))

    # --- 脚注 ------------------------------------------------------------------------
    def _footnote_defs(self, node: SyntaxTreeNode) -> None:
        for fn in node.children:
            if fn.type != "footnote":
                continue
            rid = int(fn.meta.get("id", 0))
            key = rid + self.fn_offset
            ctx = _Ctx(size=self.styles.footnote.size)
            runs: list[Run] = []
            for ch in fn.children:
                if ch.type == "paragraph" and ch.children:
                    r, _ = self._inline(ch.children[0], ctx)
                    runs.extend(r)
            self.footnotes[key] = (rid + 1, runs)

    # --- ユーティリティ --------------------------------------------------------------
    def _plain_text(self, inline: SyntaxTreeNode) -> str:
        parts: list[str] = []

        def rec(n: SyntaxTreeNode) -> None:
            for ch in n.children:
                if ch.type == "text" or ch.type == "code_inline":
                    parts.append(ch.content)
                else:
                    rec(ch)

        rec(inline)
        text = "".join(parts)
        return _RUBY_RE.sub(lambda m: m.group(1), text)


def _indented(para: JParagraph, indent: float) -> Flowable:
    return F.ListItem(para, "", indent, None)


def _cell_align(cell: SyntaxTreeNode) -> str:
    style = cell.attrs.get("style", "")
    if "center" in style:
        return "center"
    if "right" in style:
        return "right"
    return "left"


_BR_SENTINEL = "\x00"
_U_OPEN = "\x01"   # html_block 内の <u>（_html で下線開始に戻す）
_U_CLOSE = "\x02"  # 同 </u>


def _strip_u_sentinels(text: str) -> str:
    return text.replace(_U_OPEN, "").replace(_U_CLOSE, "")


def _strip_line(ln: str) -> str:
    """行頭・行末の空白を除く。<u> の番兵の外側にある空白（`<u>\\n本文` 由来）も除く。"""
    lead = re.match(r"[\s\x01\x02]*", ln).group()
    ln = re.sub(r"\s", "", lead) + ln[len(lead):]
    trail = re.search(r"[\s\x01\x02]*$", ln).group()
    return ln[:len(ln) - len(trail)] + re.sub(r"\s", "", trail)


def _html_to_text(content: str) -> str:
    """生 HTML を本文テキストへ。<br> とブロック要素終端のみ改行とし、
    HTML ソース中の改行（タグ整形のための空白）は空白に畳む。"""
    s = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
    s = re.sub(r"<br\s*/?>", _BR_SENTINEL, s, flags=re.IGNORECASE)
    s = re.sub(r"</(p|div|li|tr|h[1-6])>", _BR_SENTINEL, s, flags=re.IGNORECASE)
    s = re.sub(r"<u(\s[^>]*)?>", _U_OPEN, s, flags=re.IGNORECASE)
    s = re.sub(r"</u\s*>", _U_CLOSE, s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)            # 残りのタグを除去
    s = re.sub(r"\s+", " ", s)               # ソース改行・連続空白を 1 空白へ畳む
    s = s.replace(_BR_SENTINEL, "\n")
    s = html.unescape(s)
    lines = [_strip_line(ln) for ln in s.split("\n")]
    # 末尾の空行を除去
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)
