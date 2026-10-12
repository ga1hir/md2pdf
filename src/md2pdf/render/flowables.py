"""独自 Flowable 群。

見出し下線・コードブロック（背景＋枠＋ページ跨ぎ分割）・引用・リスト項目・水平線・
画像（ラスタ/SVG）を実装する。テーブルは builder 側で ReportLab Table を用いる。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from reportlab.lib.colors import Color
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import Flowable, Image

from .. import config
from .inline import JParagraph, Run

_CODE_PAD = 8.0  # コードブロック内側余白
_QUOTE_INDENT = 14.0


def _run_width(run: Run) -> float:
    return pdfmetrics.stringWidth(run.text, run.font, run.size)


def _wrap_code_line(runs: list[Run], maxw: float) -> list[list[Run]]:
    """コード 1 論理行を、等幅で maxw に収まる視覚行へ折り返す（pre-wrap 相当）。"""
    visual: list[list[Run]] = [[]]
    x = 0.0
    for run in runs:
        # 行末マーカー（↵）は折り返しに含めず常に末尾へ
        text = run.text
        if not text:
            continue
        for ch in text:
            w = pdfmetrics.stringWidth(ch, run.font, run.size)
            if x + w > maxw + 0.2 and visual[-1]:
                visual.append([])
                x = 0.0
            cur = visual[-1]
            if cur and cur[-1].font == run.font and cur[-1].color == run.color:
                cur[-1] = Run(cur[-1].text + ch, run.font, run.size, run.color)
            else:
                cur.append(Run(ch, run.font, run.size, run.color))
            x += w
    return visual


class CodeBlock(Flowable):
    """背景・枠付きのコードブロック。ページ跨ぎ分割に対応。"""

    def __init__(self, lines: list[list[Run]], size: float, leading: float,
                 first: bool = True, last: bool = True) -> None:
        super().__init__()
        self.lines = lines          # 論理行（list[Run]）
        self.size = size
        self.leading = leading
        self.first = first          # 連続ブロックの先頭か（上余白/角丸）
        self.last = last            # 末尾か
        self._visual: list[list[Run]] = []
        self._width = 0.0

    def wrap(self, availWidth: float, availHeight: float):
        self._width = availWidth
        inner = availWidth - 2 * _CODE_PAD
        self._visual = []
        for line in self.lines:
            self._visual.extend(_wrap_code_line(line, inner))
        pad_top = _CODE_PAD if self.first else 0.0
        pad_bot = _CODE_PAD if self.last else 0.0
        height = len(self._visual) * self.leading + pad_top + pad_bot
        return availWidth, height

    def split(self, availWidth: float, availHeight: float):
        if not self._visual:
            self.wrap(availWidth, availHeight)
        pad_top = _CODE_PAD if self.first else 0.0
        avail_lines = int((availHeight - pad_top) // self.leading)
        total = len(self._visual)
        if avail_lines >= total:
            return [self]
        if avail_lines < 1:
            return []
        head = CodeBlock([], self.size, self.leading, first=self.first, last=False)
        head._visual = self._visual[:avail_lines]
        head._width = availWidth
        tail = CodeBlock([], self.size, self.leading, first=False, last=self.last)
        tail._visual = self._visual[avail_lines:]
        tail._width = availWidth
        return [head, tail]

    def draw(self) -> None:
        c = self.canv
        pad_top = _CODE_PAD if self.first else 0.0
        pad_bot = _CODE_PAD if self.last else 0.0
        height = len(self._visual) * self.leading + pad_top + pad_bot
        # 背景＋枠
        c.setFillColor(config.COLOR_CODE_BG)
        c.setStrokeColor(config.COLOR_CODE_BORDER)
        c.setLineWidth(0.75)
        c.roundRect(0, 0, self._width, height, 4 if (self.first and self.last) else 0,
                    stroke=1, fill=1)
        # 各視覚行
        ascent = self.size * 0.82
        top = height - pad_top
        for i, line in enumerate(self._visual):
            baseline = top - i * self.leading - ascent
            x = _CODE_PAD
            for run in line:
                if not run.text:
                    continue
                c.setFont(run.font, run.size)
                c.setFillColor(run.color)
                c.drawString(x, baseline, run.text)
                x += _run_width(run)


class Rule(Flowable):
    """水平線（hr）および見出し下線。"""

    def __init__(self, width_ratio: float = 1.0, thickness: float = 1.0,
                 color: Color = config.COLOR_RULE, space_before: float = 0.0,
                 space_after: float = 0.0) -> None:
        super().__init__()
        self.width_ratio = width_ratio
        self.thickness = thickness
        self.color = color
        self.spaceBefore = space_before
        self.spaceAfter = space_after
        self._width = 0.0

    def wrap(self, availWidth: float, availHeight: float):
        self._width = availWidth * self.width_ratio
        return availWidth, self.thickness

    def draw(self) -> None:
        c = self.canv
        c.setStrokeColor(self.color)
        c.setLineWidth(self.thickness)
        c.line(0, self.thickness / 2, self._width, self.thickness / 2)


class Heading(Flowable):
    """見出し（テキスト＋ h1/h2 の下線）。次要素と分離しない。"""

    def __init__(self, para: JParagraph, level: int) -> None:
        super().__init__()
        self.para = para
        self.level = level
        self.keepWithNext = 1
        self.spaceBefore = para.spaceBefore
        self.spaceAfter = para.spaceAfter
        para.spaceBefore = 0.0
        para.spaceAfter = 0.0
        self._rule = level <= 2
        self._rule_gap = para.base_size * 0.3
        self._rule_thickness = 2.0 if level == 1 else 1.0
        self._rule_color = (config.COLOR_HEADING_RULE_H1 if level == 1
                            else config.COLOR_HEADING_RULE_H2)
        self._pw = 0.0
        self._ph = 0.0

    def wrap(self, availWidth: float, availHeight: float):
        self._pw, self._ph = self.para.wrap(availWidth, availHeight)
        extra = (self._rule_gap + self._rule_thickness) if self._rule else 0.0
        return availWidth, self._ph + extra

    def draw(self) -> None:
        c = self.canv
        extra = (self._rule_gap + self._rule_thickness) if self._rule else 0.0
        self.para.canv = c
        self.para.drawOn(c, 0, extra)
        if self._rule:
            c.setStrokeColor(self._rule_color)
            c.setLineWidth(self._rule_thickness)
            y = self._rule_thickness / 2
            c.line(0, y, self._pw, y)


class _Container(Flowable):
    """子 Flowable を縦に積み、装飾（引用の左罫＋背景）を描く汎用コンテナ。"""

    def __init__(self, children: list[Flowable], indent: float = 0.0,
                 bar: Optional[Color] = None, bg: Optional[Color] = None,
                 pad: float = 4.0, space_before: float = 0.0,
                 space_after: float = 0.0, keep_head: int = 0) -> None:
        super().__init__()
        self.children = children
        self.indent = indent
        self.bar = bar
        self.bg = bg
        self.pad = pad
        self.keep_head = keep_head  # 先頭 N 子だけでの分割を禁止（アラートのタイトル孤立防止）
        self.spaceBefore = space_before
        self.spaceAfter = space_after
        self._width = 0.0
        self._sizes: list[tuple[float, float]] = []

    def wrap(self, availWidth: float, availHeight: float):
        self._width = availWidth
        inner = availWidth - self.indent - self.pad
        self._sizes = []
        h = self.pad * 2
        for ch in self.children:
            w, ch_h = ch.wrap(inner, availHeight)
            self._sizes.append((w, ch_h))
            h += ch_h
        return availWidth, h

    def split(self, availWidth: float, availHeight: float):
        # 子境界で分割し、先頭の子が単独で入らない場合はその子自身を分割する。
        if not self._sizes:
            self.wrap(availWidth, availHeight)
        inner = availWidth - self.indent - self.pad
        avail = availHeight - self.pad * 2
        head_children: list[Flowable] = []
        rest_children: list[Flowable] = []
        y = 0.0
        for i, (ch, (_, ch_h)) in enumerate(zip(self.children, self._sizes)):
            if y + ch_h <= avail:
                head_children.append(ch)
                y += ch_h
                continue
            parts = ch.split(inner, avail - y)
            if len(parts) == 2:
                head_children.append(parts[0])
                rest_children = [parts[1]] + self.children[i + 1:]
            elif head_children:
                rest_children = self.children[i:]
            else:
                return []  # この子が単独で入らず分割も不可 → 丸ごと次ページへ
            break
        else:
            return [self]
        if len(head_children) <= self.keep_head:
            return []  # 空、またはタイトルだけがページ末に残る → 丸ごと次ページへ
        head = _Container(head_children, self.indent, self.bar, self.bg,
                          self.pad, self.spaceBefore, 0.0, self.keep_head)
        tail = _Container(rest_children, self.indent, self.bar, self.bg,
                          self.pad, 0.0, self.spaceAfter)
        return [head, tail]

    def draw(self) -> None:
        c = self.canv
        _, total_h = self.wrap(self._width, 1e9)
        if self.bg is not None:
            c.setFillColor(self.bg)
            c.rect(self.indent, 0, self._width - self.indent, total_h, stroke=0, fill=1)
        if self.bar is not None:
            c.setFillColor(self.bar)
            c.rect(self.indent, 0, 3.0, total_h, stroke=0, fill=1)
        y = total_h - self.pad
        for ch, (_, ch_h) in zip(self.children, self._sizes):
            y -= ch_h
            ch.canv = c
            ch.drawOn(c, self.indent + self.pad, y)


def blockquote(children: list[Flowable], space: float) -> _Container:
    return _Container(children, indent=0.0, bar=config.COLOR_QUOTE_BAR,
                      bg=config.COLOR_QUOTE_BG, pad=5.0,
                      space_before=space * 0.3, space_after=space * 0.3)


def _draw_alert_icon(c, kind: str, x: float, y: float, s: float, color: Color) -> None:
    """GFM アラートの octicon 風アイコンを (x, y) を左下とする s×s の枠に線画で描く。

    フォントの cmap に依存しないよう、記号グリフではなく canvas の図形で描画する。
    """
    lw = s * 0.09
    c.saveState()
    c.setStrokeColor(color)
    c.setFillColor(color)
    c.setLineWidth(lw)
    c.setLineCap(1)
    c.setLineJoin(1)

    def P(px: float, py: float) -> tuple[float, float]:
        return x + px * s, y + py * s

    def polygon(pts) -> None:
        p = c.beginPath()
        p.moveTo(*P(*pts[0]))
        for pt in pts[1:]:
            p.lineTo(*P(*pt))
        p.close()
        c.drawPath(p, stroke=1, fill=0)

    def line(x0: float, y0: float, x1: float, y1: float) -> None:
        c.line(*P(x0, y0), *P(x1, y1))

    def bang(top: float, bottom: float, dot: float) -> None:
        line(0.5, top, 0.5, bottom)
        c.circle(*P(0.5, dot), lw * 0.75, stroke=0, fill=1)

    if kind == "note":  # 丸に i
        c.circle(*P(0.5, 0.5), s * 0.44, stroke=1, fill=0)
        line(0.5, 0.25, 0.5, 0.50)
        c.circle(*P(0.5, 0.70), lw * 0.75, stroke=0, fill=1)
    elif kind == "tip":  # 電球
        c.circle(*P(0.5, 0.62), s * 0.32, stroke=1, fill=0)
        line(0.38, 0.30, 0.38, 0.20)
        line(0.62, 0.30, 0.62, 0.20)
        line(0.36, 0.18, 0.64, 0.18)
        line(0.42, 0.04, 0.58, 0.04)
    elif kind == "important":  # 吹き出しに !
        polygon([(0.06, 0.95), (0.94, 0.95), (0.94, 0.28), (0.45, 0.28),
                 (0.22, 0.06), (0.22, 0.28), (0.06, 0.28)])
        bang(0.82, 0.58, 0.42)
    elif kind == "warning":  # 三角に !
        polygon([(0.5, 0.95), (0.96, 0.08), (0.04, 0.08)])
        bang(0.66, 0.40, 0.24)
    else:  # caution: 八角形に !
        a, b = 0.06, 0.32
        polygon([(b, 0.94), (1 - b, 0.94), (1 - a, 1 - b), (1 - a, b),
                 (1 - b, 0.06), (b, 0.06), (a, b), (a, 1 - b)])
        bang(0.74, 0.44, 0.27)
    c.restoreState()


class AlertTitle(Flowable):
    """GFM アラートのタイトル行（アイコン＋種類色の太字ラベル）。高さはちょうど 1 行送り。"""

    def __init__(self, kind: str, size: float, leading: float) -> None:
        super().__init__()
        self.kind = kind
        self.label, self.color = config.ALERT_TYPES[kind]
        self.size = size
        self.leading = leading
        self.keepWithNext = 1
        self._gutter = size * 1.4

    def wrap(self, availWidth: float, availHeight: float):
        return availWidth, self.leading

    def draw(self) -> None:
        c = self.canv
        baseline = self.leading - self.size * 0.86  # JParagraph の 1 行目と同じ基準
        icon = self.size * 0.95
        _draw_alert_icon(c, self.kind, 0, baseline - self.size * 0.1, icon, self.color)
        c.setFont(config.FONT_SANS_BOLD, self.size)
        c.setFillColor(self.color)
        c.drawString(self._gutter, baseline, self.label)


def alert(children: list[Flowable], kind: str, space: float) -> _Container:
    """GFM アラート（> [!NOTE] 等）。children の先頭は AlertTitle を想定。"""
    box = _Container(children, indent=0.0, bar=config.ALERT_TYPES[kind][1], bg=None,
                     pad=5.0, space_before=space * 0.3, space_after=space * 0.3,
                     keep_head=1)
    box.kind = kind
    return box


class ListItem(Flowable):
    """箇条書き/番号付き/タスクリストの 1 項目（マーカー＋本文）。"""

    def __init__(self, para: JParagraph, marker: str, indent: float,
                 checkbox: Optional[bool] = None) -> None:
        super().__init__()
        self.para = para
        self.marker = marker
        self.indent = indent
        self.checkbox = checkbox  # None=通常, True/False=チェック状態
        self.spaceBefore = 0.0
        self.spaceAfter = 0.0
        self._h = 0.0
        self._gutter = para.base_size * 1.6

    def wrap(self, availWidth: float, availHeight: float):
        _, self._h = self.para.wrap(availWidth - self.indent - self._gutter, availHeight)
        return availWidth, self._h

    def split(self, availWidth: float, availHeight: float):
        parts = self.para.split(availWidth - self.indent - self._gutter, availHeight)
        if len(parts) <= 1:
            return parts and [self] or []
        first = ListItem(parts[0], self.marker, self.indent, self.checkbox)
        rest = ListItem(parts[1], "", self.indent, None)  # 継続行はマーカー無し
        return [first, rest]

    def draw(self) -> None:
        c = self.canv
        size = self.para.base_size
        top = self._h
        baseline = top - size * 0.86
        mx = self.indent
        if self.checkbox is not None:
            box = size * 0.85
            by = baseline - box * 0.05
            c.setStrokeColor(config.COLOR_TEXT)
            c.setLineWidth(0.7)
            if self.checkbox:
                c.setFillColor(config.HexColor("#333333"))
                c.roundRect(mx, by, box, box, 1.5, stroke=1, fill=1)
                c.setFillColor(config.HexColor("#ffffff"))
                c.setFont(config.FONT_SANS, box * 0.85)
                c.drawString(mx + box * 0.12, by + box * 0.16, "✓")
            else:
                c.setFillColor(config.HexColor("#ffffff"))
                c.roundRect(mx, by, box, box, 1.5, stroke=1, fill=1)
        elif self.marker:
            c.setFont(self.para.runs[0].font if self.para.runs else config.FONT_SERIF, size)
            c.setFillColor(config.COLOR_TEXT)
            c.drawString(mx, baseline, self.marker)
        self.para.canv = c
        self.para.drawOn(c, self.indent + self._gutter, 0)


_SVG_NS = "http://www.w3.org/2000/svg"
_NUM_RE = None  # lazy


def _floats(s: str) -> "list[float]":
    import re as _re
    global _NUM_RE
    if _NUM_RE is None:
        _NUM_RE = _re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
    return [float(x) for x in _NUM_RE.findall(s or "")]


def _vertices(tag: str, el) -> "list[tuple[float, float]]":
    """要素の頂点列を返す（marker の配置・向き算出用）。"""
    if tag == "line":
        return [(float(el.get("x1", 0)), float(el.get("y1", 0))),
                (float(el.get("x2", 0)), float(el.get("y2", 0)))]
    if tag in ("polyline", "polygon"):
        nums = _floats(el.get("points", ""))
        pts = list(zip(nums[0::2], nums[1::2]))
        if tag == "polygon" and len(pts) >= 2:
            pts = pts + [pts[0]]
        return pts
    if tag == "path":
        nums = _floats(el.get("d", ""))
        return list(zip(nums[0::2], nums[1::2]))   # 近似（H/V/A は厳密でない）
    return []


def _stroke_width(el) -> float:
    sw = el.get("stroke-width")
    if sw is None:
        style = el.get("style", "")
        import re as _re
        m = _re.search(r"stroke-width\s*:\s*([0-9.]+)", style)
        sw = m.group(1) if m else None
    try:
        return float(sw) if sw is not None else 1.0
    except ValueError:
        return 1.0


def _preprocess_svg(data: bytes) -> "Optional[bytes]":
    """svglib が描けない SVG 機能を前処理で実体化する。

    (1) <image href="data:image/svg+xml;…">（ネスト SVG）を中身の <g> に展開、
    (2) <marker>/marker-start|mid|end を実体図形（矢じり等）の <g> に展開。
    どちらも対象が無ければ何もしない。変更が無ければ None（元ファイルをそのまま使う）。
    """
    import base64
    import copy
    import math
    import re as _re
    import urllib.parse
    import xml.etree.ElementTree as ET

    text = data.decode("utf-8", "replace")
    if "data:image/svg+xml" not in text and "marker" not in text:
        return None
    try:
        ET.register_namespace("", _SVG_NS)
        ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
        root = ET.fromstring(text)
    except Exception:
        return None

    changed = False
    href_attrs = ("href", "{http://www.w3.org/1999/xlink}href")

    # --- (1) ネスト SVG 画像の実体化 ---------------------------------------------
    def decode_svg(uri: str) -> Optional[str]:
        m = _re.match(r"data:image/svg\+xml(;[^,]*)?,(.*)$", uri, _re.DOTALL)
        if not m:
            return None
        meta, payload = m.group(1) or "", m.group(2)
        try:
            if "base64" in meta:
                return base64.b64decode(payload).decode("utf-8", "replace")
            return urllib.parse.unquote(payload)
        except Exception:
            return None

    def inline_images(parent: ET.Element) -> None:
        nonlocal changed
        for idx, child in enumerate(list(parent)):
            tag = child.tag.split("}")[-1]
            if tag == "image":
                uri = next((child.get(a) for a in href_attrs if child.get(a)), None)
                inner = decode_svg(uri) if uri else None
                if inner:
                    try:
                        inner_root = ET.fromstring(inner)
                    except Exception:
                        continue
                    x = float(child.get("x", 0)); y = float(child.get("y", 0))
                    w = float(child.get("width", 0)); h = float(child.get("height", 0))
                    vb = inner_root.get("viewBox")
                    if vb:
                        _, _, vbw, vbh = _floats(vb)
                    else:
                        vbw = float(inner_root.get("width", w) or w or 1)
                        vbh = float(inner_root.get("height", h) or h or 1)
                    sx = (w / vbw) if (w and vbw) else 1.0
                    sy = (h / vbh) if (h and vbh) else 1.0
                    g = ET.Element(f"{{{_SVG_NS}}}g")
                    g.set("transform", f"translate({x},{y}) scale({sx},{sy})")
                    for sub in list(inner_root):
                        g.append(sub)
                    parent.remove(child)
                    parent.insert(idx, g)
                    changed = True
            else:
                inline_images(child)

    inline_images(root)

    # --- (2) marker の実体化 -----------------------------------------------------
    markers: dict = {}
    for el in root.iter():
        if el.tag.split("}")[-1] == "marker" and el.get("id"):
            markers[el.get("id")] = el

    def marker_id(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        m = _re.search(r"url\(\s*#([^)\s]+)\s*\)", value)
        return m.group(1) if m else None

    def make_marker_group(mk, vx, vy, seg_angle, position, sw):
        mw = float(mk.get("markerWidth", 3)); mh = float(mk.get("markerHeight", 3))
        refx = float(mk.get("refX", 0)); refy = float(mk.get("refY", 0))
        units = mk.get("markerUnits", "strokeWidth")
        vb = mk.get("viewBox")
        csx = csy = 1.0
        if vb:
            f = _floats(vb)
            if len(f) == 4 and f[2] and f[3]:
                csx, csy = mw / f[2], mh / f[3]
        unit = sw if units != "userSpaceOnUse" else 1.0
        sx, sy = unit * csx, unit * csy
        orient = (mk.get("orient") or "0").strip()
        if orient == "auto":
            deg = math.degrees(seg_angle)
        elif orient == "auto-start-reverse":
            deg = math.degrees(seg_angle) + (180.0 if position == "start" else 0.0)
        else:
            try:
                deg = float(orient.replace("deg", ""))
            except ValueError:
                deg = 0.0
        g = ET.Element(f"{{{_SVG_NS}}}g")
        g.set("transform",
              f"translate({vx},{vy}) rotate({deg}) scale({sx},{sy}) "
              f"translate({-refx},{-refy})")
        for sub in list(mk):
            g.append(copy.deepcopy(sub))
        return g

    def angle(p, q):
        return math.atan2(q[1] - p[1], q[0] - p[0])

    marker_groups: list = []
    for el in list(root.iter()):
        tag = el.tag.split("}")[-1]
        shorthand = el.get("marker")
        refs = {
            "start": marker_id(el.get("marker-start") or shorthand),
            "mid": marker_id(el.get("marker-mid") or shorthand),
            "end": marker_id(el.get("marker-end") or shorthand),
        }
        if not any(refs.values()):
            continue
        verts = _vertices(tag, el)
        if len(verts) >= 2:
            sw = _stroke_width(el)
            specs = []
            if refs["start"]:
                specs.append((refs["start"], verts[0], angle(verts[0], verts[1]), "start"))
            if refs["end"]:
                specs.append((refs["end"], verts[-1], angle(verts[-2], verts[-1]), "end"))
            if refs["mid"]:
                for i in range(1, len(verts) - 1):
                    specs.append((refs["mid"], verts[i], angle(verts[i - 1], verts[i + 1]), "mid"))
            for mid, (vx, vy), ang, pos in specs:
                mk = markers.get(mid)
                if mk is not None:
                    marker_groups.append(make_marker_group(mk, vx, vy, ang, pos, sw))
                    changed = True
        for a in ("marker", "marker-start", "marker-mid", "marker-end"):
            if a in el.attrib:
                del el.attrib[a]

    for g in marker_groups:
        root.append(g)   # 軸の上に矢じりを重ねる

    if not changed:
        return None
    return ET.tostring(root, encoding="utf-8")


def _svg_intrinsic_size(data: bytes) -> "tuple[float, float]":
    """SVG の固有サイズ(pt 相当)を width/height か viewBox から推定する。"""
    import re as _re
    head = data[:2048].decode("utf-8", "replace")
    m = _re.search(r"<svg\b[^>]*>", head, _re.DOTALL)
    tag = m.group(0) if m else head

    def dim(name: str) -> float:
        mm = _re.search(rf'{name}\s*=\s*"([0-9.]+)', tag)
        return float(mm.group(1)) if mm else 0.0

    w, h = dim("width"), dim("height")
    if not (w and h):
        vb = _re.search(r'viewBox\s*=\s*"([^"]+)"', tag)
        if vb:
            f = _floats(vb.group(1))
            if len(f) == 4:
                w, h = w or f[2], h or f[3]
    return w, h


def _svg_via_resvg(data: bytes, max_width: float, max_height: float) -> Optional[Flowable]:
    """resvg で SVG を高解像度ラスタライズして埋め込む（marker/ネスト画像/各種効果に対応）。

    同梱 Noto のみを使い（skip_system_fonts）機種非依存の確定描画にする。失敗時は None。
    """
    try:
        import hashlib

        import resvg_py
        from .. import fontreg
        from ..cache import cache_path
    except Exception:
        return None
    try:
        iw, ih = _svg_intrinsic_size(data)
        if not iw or not ih:
            iw, ih = 600.0, 400.0
        ss = 2  # スーパーサンプリング（印刷で滲まない解像度）
        key = "svg-resvg-%d-%s" % (ss, hashlib.sha1(data).hexdigest()[:20])
        png_path = cache_path(key, ".png")
        if not os.path.exists(png_path):
            png = resvg_py.svg_to_bytes(
                svg_string=data.decode("utf-8", "replace"),
                skip_system_fonts=True,
                font_dirs=[str(fontreg.fonts_dir())],
                sans_serif_family="Noto Sans JP",
                serif_family="Noto Serif JP",
                monospace_family="Noto Sans Mono CJK JP",
                width=int(iw * ss), height=int(ih * ss),
            )
            with open(png_path, "wb") as f:
                f.write(bytes(png))
        scale = min(max_width / iw, max_height / ih, 1.0)
        img = Image(png_path)
        img.drawWidth = iw * scale
        img.drawHeight = ih * scale
        return img
    except Exception:
        return None


def _svg_via_svglib(data: bytes, max_width: float, max_height: float) -> Optional[Flowable]:
    """svglib によるベクタ描画（保険）。marker/ネスト画像は _preprocess_svg で補う。"""
    try:
        import io

        from svglib.svglib import svg2rlg
        prepared = _preprocess_svg(data)
        drawing = svg2rlg(io.BytesIO(prepared if prepared is not None else data))
        if drawing is None:
            return None
        scale = min(max_width / drawing.width, max_height / drawing.height, 1.0)
        if scale < 1.0:
            drawing.scale(scale, scale)
            drawing.width *= scale
            drawing.height *= scale
        return drawing
    except Exception:
        return None


def make_image(path: str, max_width: float, max_height: float) -> Optional[Flowable]:
    """ラスタ/SVG 画像 Flowable を生成。失敗時は None。

    SVG は resvg（高忠実・確定描画）を優先し、未導入や失敗時は svglib にフォールバック。
    """
    p = Path(path)
    if not p.exists():
        return None
    if p.suffix.lower() == ".svg":
        data = p.read_bytes()
        return _svg_via_resvg(data, max_width, max_height) \
            or _svg_via_svglib(data, max_width, max_height)
    try:
        img = Image(str(p))
        iw, ih = img.imageWidth, img.imageHeight
        scale = min(max_width / iw, max_height / ih, 1.0)
        img.drawWidth = iw * scale
        img.drawHeight = ih * scale
        return img
    except Exception:
        return None
