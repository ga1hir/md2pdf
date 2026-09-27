"""Mermaid のローカル（純 Python）レンダリング。

純 Python の Mermaid レンダラは存在しないため、よく使う図種別のサブセットを自前で
ReportLab Drawing に描画する。対応するのは flowchart/graph と sequenceDiagram。
未対応の種別・構文エラーは None を返し、builder 側でコードブロックにフォールバックする。
"""

from __future__ import annotations

from typing import Optional

from reportlab.platypus import Flowable

from . import flowchart, sequence


def render_mermaid(code: str, max_width: float, font: str, size: float) -> Optional[Flowable]:
    head = ""
    for line in code.strip().splitlines():
        s = line.strip()
        if s:
            head = s
            break
    kind = head.split()[0].lower() if head else ""
    try:
        if kind in ("flowchart", "graph"):
            return flowchart.render(code, max_width, font, size)
        if kind == "sequencediagram":
            return sequence.render(code, max_width, font, size)
    except Exception:
        return None
    return None
