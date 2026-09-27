"""数式の純 Python 描画。

matplotlib の mathtext で LaTeX 風数式を画像化し、PDF に埋め込む。インライン数式は
本文フォントサイズに合わせた小画像（inline 画像アトム）として、ブロック数式は中央寄せ
画像として配置する。描画結果はキャッシュする。
"""

from __future__ import annotations

import os
from typing import Optional

import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure  # noqa: E402

from .. import config
from ..cache import cache_path


def render_math(expr: str, fontsize: float, display: bool = False) -> Optional[tuple[str, float, float]]:
    """数式を PNG に描画し (path, width_pt, height_pt) を返す。失敗時 None。"""
    key = f"math-{'D' if display else 'I'}-{fontsize:.2f}-{expr}"
    path = cache_path(key, ".png")
    dpi = config.MATH_DPI
    if not os.path.exists(path):
        try:
            fig = Figure()
            fig.text(0.0, 0.0, f"${expr}$", fontsize=fontsize, color="#333333")
            fig.savefig(path, dpi=dpi, bbox_inches="tight", pad_inches=0.01,
                        transparent=True)
        except Exception:
            return None
    try:
        from PIL import Image as PILImage
        with PILImage.open(path) as im:
            px_w, px_h = im.size
    except Exception:
        return None
    # 画素 → pt（dpi に基づく）。matplotlib の fontsize=pt なので物理サイズが一致する。
    w_pt = px_w * 72.0 / dpi
    h_pt = px_h * 72.0 / dpi
    return path, w_pt, h_pt
