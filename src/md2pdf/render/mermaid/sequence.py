"""Mermaid sequenceDiagram のサブセット描画。

対応: participant/actor 宣言（as ラベル可）、メッセージ A->>B: text（実線/破線、
矢尻有無）。参加者をカラム化し、ライフラインとメッセージ矢印を描く。
Note/alt/loop 等の制御構文は対象外（無視）。
"""

from __future__ import annotations

import re
from typing import Optional

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import Flowable

_PARTICIPANT_RE = re.compile(r"^(participant|actor)\s+([^\s]+)(?:\s+as\s+(.+))?$")
_MSG_RE = re.compile(r"^([^\s:>-]+)\s*(--?>>?|-->>?)\s*([^\s:>-]+)\s*:\s*(.*)$")

_BOX_BG = HexColor("#eef3fb")
_BOX_BORDER = HexColor("#204a87")
_LINE = HexColor("#555555")
_TEXT = HexColor("#222222")


def render(code: str, max_width: float, font: str, size: float) -> Optional[Flowable]:
    lines = code.strip().splitlines()[1:]
    labels: dict[str, str] = {}
    order: list[str] = []
    messages: list[tuple[str, str, str, bool, bool]] = []  # src,dst,text,dashed,arrow

    def ensure(pid: str) -> None:
        if pid not in labels:
            labels[pid] = pid
            order.append(pid)

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("%%"):
            continue
        pm = _PARTICIPANT_RE.match(line)
        if pm:
            pid = pm.group(2)
            labels[pid] = pm.group(3) or pid
            if pid not in order:
                order.append(pid)
            continue
        mm = _MSG_RE.match(line)
        if mm:
            src, arrow, dst, text = mm.group(1), mm.group(2), mm.group(3), mm.group(4)
            ensure(src)
            ensure(dst)
            dashed = "--" in arrow
            has_arrow = ">" in arrow
            messages.append((src, dst, text.strip(), dashed, has_arrow))

    if not order or not messages:
        return None

    # カラム配置
    box_h = size + size * 1.2
    col_w = {}
    for pid in order:
        tw = pdfmetrics.stringWidth(labels[pid], font, size)
        col_w[pid] = max(tw + size * 1.6, size * 5)
    gap = size * 2.2
    margin = size
    x = margin
    cx: dict[str, float] = {}
    for pid in order:
        cx[pid] = x + col_w[pid] / 2
        x += col_w[pid] + gap
    total_w = x - gap + margin

    row_h = size * 2.4
    top_box_y = 0.0  # 後で計算
    n_rows = len(messages)
    diagram_h = box_h + size + n_rows * row_h + box_h + margin * 2
    d = Drawing(total_w, diagram_h)

    top = diagram_h - margin
    # 参加者ボックス（上）
    for pid in order:
        _participant_box(d, cx[pid], top - box_h, col_w[pid], box_h, labels[pid], font, size)
    # ライフライン
    life_top = top - box_h
    life_bottom = margin + box_h
    for pid in order:
        d.add(Line(cx[pid], life_top, cx[pid], life_bottom,
                   strokeColor=HexColor("#bbbbbb"), strokeWidth=0.6,
                   strokeDashArray=[2, 2]))
    # メッセージ
    y = life_top - size * 1.4
    for src, dst, text, dashed, has_arrow in messages:
        _message(d, cx[src], cx[dst], y, text, dashed, has_arrow, font, size)
        y -= row_h
    # 参加者ボックス（下）
    for pid in order:
        _participant_box(d, cx[pid], margin, col_w[pid], box_h, labels[pid], font, size)

    return _scale_to_width(d, max_width)


def _participant_box(d, cx, y, w, h, label, font, size):
    d.add(Rect(cx - w / 2, y, w, h, rx=2, ry=2, fillColor=_BOX_BG,
               strokeColor=_BOX_BORDER, strokeWidth=1))
    tw = pdfmetrics.stringWidth(label, font, size)
    d.add(String(cx - tw / 2, y + h / 2 - size * 0.33, label, fontName=font,
                 fontSize=size, fillColor=_TEXT))


def _message(d, x1, x2, y, text, dashed, has_arrow, font, size):
    dash = [3, 2] if dashed else None
    if abs(x1 - x2) < 1:  # 自己メッセージ（ループ）
        loop = size * 2.0
        d.add(Line(x1, y, x1 + loop, y, strokeColor=_LINE, strokeWidth=0.8, strokeDashArray=dash))
        d.add(Line(x1 + loop, y, x1 + loop, y - size, strokeColor=_LINE, strokeWidth=0.8, strokeDashArray=dash))
        d.add(Line(x1 + loop, y - size, x1, y - size, strokeColor=_LINE, strokeWidth=0.8, strokeDashArray=dash))
        if has_arrow:
            _arrowhead(d, x1 + loop, y - size, x1, y - size, size)
        if text:
            d.add(String(x1 + loop + 2, y - size * 0.4, text, fontName=font,
                         fontSize=size * 0.85, fillColor=_TEXT))
        return
    d.add(Line(x1, y, x2, y, strokeColor=_LINE, strokeWidth=0.8, strokeDashArray=dash))
    if has_arrow:
        _arrowhead(d, x1, y, x2, y, size)
    if text:
        tw = pdfmetrics.stringWidth(text, font, size * 0.85)
        mx = (x1 + x2) / 2
        d.add(String(mx - tw / 2, y + size * 0.2, text, fontName=font,
                     fontSize=size * 0.85, fillColor=_TEXT))


def _arrowhead(d, x1, y1, x2, y2, size):
    import math
    ang = math.atan2(y2 - y1, x2 - x1)
    L, w = size * 0.7, size * 0.3
    bx, by = x2 - L * math.cos(ang), y2 - L * math.sin(ang)
    px, py = -math.sin(ang) * w, math.cos(ang) * w
    d.add(Polygon([x2, y2, bx + px, by + py, bx - px, by - py],
                  fillColor=_LINE, strokeColor=_LINE))


def _scale_to_width(d: Drawing, max_width: float):
    if d.width > max_width:
        s = max_width / d.width
        d.scale(s, s)
        d.width *= s
        d.height *= s
    return d
