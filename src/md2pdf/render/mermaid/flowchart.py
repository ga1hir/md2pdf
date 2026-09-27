"""Mermaid flowchart / graph のサブセット描画。

対応: 方向 TD/TB/LR/RL、ノード形状 [..]（矩形）/ (..)（角丸）/ {..}（菱形）、
エッジ --> / --- / -.-> / ==> と |ラベル|。簡易な層別レイアウトで配置する。
"""

from __future__ import annotations

import re
from typing import Optional

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import Flowable

_NODE_RE = re.compile(r"^([A-Za-z0-9_]+)\s*(\[(.+?)\]|\((.+?)\)|\{(.+?)\})?$")
_ARROW_RE = re.compile(r"(-\.->|-->|---|==>)")
_LABEL_RE = re.compile(r"^\|(.+?)\|\s*")

_BOX_BG = HexColor("#eef3fb")
_BOX_BORDER = HexColor("#204a87")
_LINE = HexColor("#555555")
_TEXT = HexColor("#222222")


class _Node:
    def __init__(self, nid: str, label: str, shape: str) -> None:
        self.id = nid
        self.label = label
        self.shape = shape
        self.layer = 0
        self.x = 0.0
        self.y = 0.0
        self.w = 0.0
        self.h = 0.0


def _parse_node(text: str, nodes: dict, order: list, font: str, size: float) -> Optional[str]:
    text = text.strip()
    m = _NODE_RE.match(text)
    if not m:
        return None
    nid = m.group(1)
    label = m.group(3) or m.group(4) or m.group(5)
    shape = "rect"
    if m.group(2):
        if m.group(2).startswith("("):
            shape = "round"
        elif m.group(2).startswith("{"):
            shape = "diamond"
    if nid not in nodes:
        node = _Node(nid, label or nid, shape)
        nodes[nid] = node
        order.append(nid)
    elif label:
        nodes[nid].label = label
        nodes[nid].shape = shape
    return nid


def render(code: str, max_width: float, font: str, size: float) -> Optional[Flowable]:
    lines = code.strip().splitlines()
    header = lines[0].strip().split()
    direction = "TD"
    if len(header) > 1:
        direction = header[1].upper()
    horizontal = direction in ("LR", "RL")

    nodes: dict[str, _Node] = {}
    order: list[str] = []
    edges: list[tuple[str, str, str]] = []

    for raw in lines[1:]:
        line = raw.strip().rstrip(";")
        if not line or line.startswith("%%"):
            continue
        am = _ARROW_RE.search(line)
        if not am:
            _parse_node(line, nodes, order, font, size)
            continue
        left = line[: am.start()].strip()
        right = line[am.end():].strip()
        elabel = ""
        lm = _LABEL_RE.match(right)
        if lm:
            elabel = lm.group(1)
            right = right[lm.end():].strip()
        src = _parse_node(left, nodes, order, font, size)
        dst = _parse_node(right, nodes, order, font, size)
        if src and dst:
            edges.append((src, dst, elabel))

    if not nodes:
        return None

    # 層別（longest-path）
    incoming = {n: 0 for n in nodes}
    for s, d, _ in edges:
        incoming[d] += 1
    for _ in range(len(nodes)):
        for s, d, _ in edges:
            if nodes[d].layer < nodes[s].layer + 1:
                nodes[d].layer = nodes[s].layer + 1

    # ノードサイズ
    pad_x, pad_y = size * 0.9, size * 0.7
    for n in nodes.values():
        tw = pdfmetrics.stringWidth(n.label, font, size)
        n.w = max(tw + 2 * pad_x, size * 4)
        n.h = size + 2 * pad_y
        if n.shape == "diamond":
            n.w *= 1.25
            n.h *= 1.4

    # 層ごとにグループ化
    layers: dict[int, list[_Node]] = {}
    for nid in order:
        n = nodes[nid]
        layers.setdefault(n.layer, []).append(n)

    gap_main = size * 2.4   # 層間
    gap_cross = size * 1.6  # 層内
    # 配置
    if horizontal:
        x = 0.0
        max_h = 0.0
        layer_keys = sorted(layers)
        col_x = {}
        for lk in layer_keys:
            col_w = max(n.w for n in layers[lk])
            col_x[lk] = x + col_w / 2
            x += col_w + gap_main
        for lk in layer_keys:
            col = layers[lk]
            total = sum(n.h for n in col) + gap_cross * (len(col) - 1)
            max_h = max(max_h, total)
        for lk in layer_keys:
            col = layers[lk]
            total = sum(n.h for n in col) + gap_cross * (len(col) - 1)
            y = total / 2
            for n in col:
                n.x = col_x[lk]
                n.y = y - n.h / 2
                y -= n.h + gap_cross
        total_w = x - gap_main
        total_h = max_h
        # y を正領域へ
        for n in nodes.values():
            n.y += total_h / 2
    else:
        y = 0.0
        layer_keys = sorted(layers)
        row_y = {}
        for lk in layer_keys:
            row_h = max(n.h for n in layers[lk])
            row_y[lk] = y + row_h / 2
            y += row_h + gap_main
        total_h = y - gap_main
        max_w = 0.0
        for lk in layer_keys:
            row = layers[lk]
            total = sum(n.w for n in row) + gap_cross * (len(row) - 1)
            max_w = max(max_w, total)
        for lk in layer_keys:
            row = layers[lk]
            total = sum(n.w for n in row) + gap_cross * (len(row) - 1)
            x = -total / 2
            for n in row:
                n.x = x + n.w / 2
                n.y = total_h - row_y[lk]
                x += n.w + gap_cross
        total_w = max_w
        for n in nodes.values():
            n.x += total_w / 2

    margin = size
    dw = total_w + 2 * margin
    dh = total_h + 2 * margin
    d = Drawing(dw, dh)
    for n in nodes.values():
        n.x += margin
        n.y += margin

    # エッジ
    for s, dst, elabel in edges:
        a, b = nodes[s], nodes[dst]
        x1, y1, x2, y2 = _edge_points(a, b)
        d.add(Line(x1, y1, x2, y2, strokeColor=_LINE, strokeWidth=0.8))
        _add_arrowhead(d, x1, y1, x2, y2, size)
        if elabel:
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            lw = pdfmetrics.stringWidth(elabel, font, size * 0.8)
            d.add(Rect(mx - lw / 2 - 1, my - size * 0.4, lw + 2, size * 0.9,
                       fillColor=HexColor("#ffffff"), strokeColor=None))
            d.add(String(mx - lw / 2, my - size * 0.28, elabel, fontName=font,
                         fontSize=size * 0.8, fillColor=_TEXT))

    # ノード
    for n in nodes.values():
        _draw_node(d, n, font, size)

    return _scale_to_width(d, max_width)


def _edge_points(a: _Node, b: _Node) -> tuple[float, float, float, float]:
    # 中心同士を結び、各ボックスの境界で交差する点に丸める（簡易: 上下左右で判定）
    ax, ay, bx, by = a.x, a.y, b.x, b.y
    dx, dy = bx - ax, by - ay
    x1, y1 = _box_exit(a, dx, dy)
    x2, y2 = _box_exit(b, -dx, -dy)
    return x1, y1, x2, y2


def _box_exit(n: _Node, dx: float, dy: float) -> tuple[float, float]:
    if dx == 0 and dy == 0:
        return n.x, n.y
    hw, hh = n.w / 2, n.h / 2
    if abs(dx) * hh >= abs(dy) * hw:
        sx = hw if dx > 0 else -hw
        sy = dy * (hw / abs(dx)) if dx != 0 else 0
        sy = max(-hh, min(hh, sy))
        return n.x + sx, n.y + sy
    sy = hh if dy > 0 else -hh
    sx = dx * (hh / abs(dy)) if dy != 0 else 0
    sx = max(-hw, min(hw, sx))
    return n.x + sx, n.y + sy


def _add_arrowhead(d: Drawing, x1: float, y1: float, x2: float, y2: float, size: float) -> None:
    import math
    ang = math.atan2(y2 - y1, x2 - x1)
    L = size * 0.7
    w = size * 0.32
    bx, by = x2 - L * math.cos(ang), y2 - L * math.sin(ang)
    px, py = -math.sin(ang) * w, math.cos(ang) * w
    d.add(Polygon([x2, y2, bx + px, by + py, bx - px, by - py],
                  fillColor=_LINE, strokeColor=_LINE))


def _draw_node(d: Drawing, n: _Node, font: str, size: float) -> None:
    if n.shape == "diamond":
        cx, cy = n.x, n.y
        hw, hh = n.w / 2, n.h / 2
        d.add(Polygon([cx, cy + hh, cx + hw, cy, cx, cy - hh, cx - hw, cy],
                      fillColor=_BOX_BG, strokeColor=_BOX_BORDER, strokeWidth=1))
    else:
        rad = n.h / 2 if n.shape == "round" else 2
        d.add(Rect(n.x - n.w / 2, n.y - n.h / 2, n.w, n.h, rx=rad, ry=rad,
                   fillColor=_BOX_BG, strokeColor=_BOX_BORDER, strokeWidth=1))
    tw = pdfmetrics.stringWidth(n.label, font, size)
    d.add(String(n.x - tw / 2, n.y - size * 0.33, n.label, fontName=font,
                 fontSize=size, fillColor=_TEXT))


def _scale_to_width(d: Drawing, max_width: float):
    if d.width > max_width:
        s = max_width / d.width
        d.scale(s, s)
        d.width *= s
        d.height *= s
    return d
