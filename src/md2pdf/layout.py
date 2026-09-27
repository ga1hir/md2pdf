"""版面（判型・字詰め・行数）モデル — 本ツールの中核。

書籍のページ数を正確に出すため、本文の組版域を「字詰め × 全角字幅」「行数 × 行送り」で
厳密に定義する。これにより 1 ページ = N 字 × M 行となり、本文流し込みのページ数が
実書籍の見積りと一致する。判型はプリセット選択＋個別指定の両対応。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

from reportlab.lib.units import mm


@dataclass(frozen=True)
class Layout:
    """1 つの版面設定。寸法は mm / pt を明示。座標計算は pt で行う。"""

    name: str
    trim_w_mm: float          # 仕上がり判型 幅
    trim_h_mm: float          # 仕上がり判型 高さ
    chars_per_line: int       # 字詰め（全角字数）
    lines_per_page: int       # 1 ページの行数
    font_size: float          # 本文フォントサイズ（pt）
    line_height: float        # 行送り倍率（leading = font_size * line_height）
    side_margin_mm: Optional[float] = None  # 左右余白。None なら水平センタリング
    top_margin_mm: Optional[float] = None   # 上余白。None なら垂直センタリング
    description: str = ""

    # --- 基本量（pt） ----------------------------------------------------------------
    @property
    def page_size(self) -> tuple[float, float]:
        return (self.trim_w_mm * mm, self.trim_h_mm * mm)

    @property
    def em(self) -> float:
        """全角 1 文字の送り幅（= フォントサイズ）。"""
        return self.font_size

    @property
    def leading(self) -> float:
        return self.font_size * self.line_height

    @property
    def body_width(self) -> float:
        return self.chars_per_line * self.em

    @property
    def body_height(self) -> float:
        return self.lines_per_page * self.leading

    # --- フレーム配置（ReportLab 座標: 原点は左下） ----------------------------------
    @property
    def left_margin(self) -> float:
        page_w, _ = self.page_size
        if self.side_margin_mm is not None:
            return self.side_margin_mm * mm
        return (page_w - self.body_width) / 2.0

    @property
    def top_margin(self) -> float:
        _, page_h = self.page_size
        if self.top_margin_mm is not None:
            return self.top_margin_mm * mm
        return (page_h - self.body_height) / 2.0

    @property
    def frame(self) -> tuple[float, float, float, float]:
        """本文フレーム (x, y_bottom, width, height) を pt で返す。"""
        _, page_h = self.page_size
        x = self.left_margin
        y_bottom = page_h - self.top_margin - self.body_height
        return (x, y_bottom, self.body_width, self.body_height)

    @property
    def bottom_margin(self) -> float:
        """本文フレーム下端から用紙下端までの余白（ノンブル・脚注領域）。"""
        x, y_bottom, w, h = self.frame
        return y_bottom

    def describe(self) -> str:
        return (
            f"{self.name}: {self.trim_w_mm:g}×{self.trim_h_mm:g}mm / "
            f"{self.chars_per_line}字×{self.lines_per_page}行 / "
            f"本文{self.font_size:g}pt 行送り{self.line_height:g}"
        )


# --- プリセット ----------------------------------------------------------------------
# a4-38x35: 参考ツールを踏襲（A4・38字×35行・12.68pt・行送り1.64）。
#   38 * 12.68pt = 481.84pt ≒ 170mm。A4 幅 210mm に対し左右 20mm で一致する。
# b5h-40x40: B5変形（182×230mm）・40字×40行。40 字×40 行が収まるよう本文 10pt /
#   行送り 1.4 を既定とし、左右・天地ともバランスの取れた余白に自動センタリングする。
PRESETS: dict[str, Layout] = {
    "a4-38x35": Layout(
        name="a4-38x35",
        trim_w_mm=210.0,
        trim_h_mm=297.0,
        chars_per_line=38,
        lines_per_page=35,
        font_size=12.68,
        line_height=1.64,
        description="A4 / 38字×35行（参考ツール踏襲）",
    ),
    "b5h-40x40": Layout(
        name="b5h-40x40",
        trim_w_mm=182.0,
        trim_h_mm=230.0,
        chars_per_line=40,
        lines_per_page=40,
        font_size=10.0,
        line_height=1.4,
        description="B5変形 182×230mm / 40字×40行",
    ),
}

DEFAULT_PRESET = "a4-38x35"


def resolve(
    preset: str = DEFAULT_PRESET,
    *,
    trim: Optional[tuple[float, float]] = None,
    chars: Optional[int] = None,
    lines: Optional[int] = None,
    font_size: Optional[float] = None,
    line_height: Optional[float] = None,
    side_margin_mm: Optional[float] = None,
    top_margin_mm: Optional[float] = None,
) -> Layout:
    """プリセットを基底に、指定された項目だけを上書きした Layout を返す。"""
    if preset not in PRESETS:
        raise ValueError(
            f"未知のプリセット: {preset!r}（利用可能: {', '.join(PRESETS)}）"
        )
    base = PRESETS[preset]
    changes: dict = {}
    if trim is not None:
        changes["trim_w_mm"], changes["trim_h_mm"] = trim
    if chars is not None:
        changes["chars_per_line"] = chars
    if lines is not None:
        changes["lines_per_page"] = lines
    if font_size is not None:
        changes["font_size"] = font_size
    if line_height is not None:
        changes["line_height"] = line_height
    if side_margin_mm is not None:
        changes["side_margin_mm"] = side_margin_mm
    if top_margin_mm is not None:
        changes["top_margin_mm"] = top_margin_mm
    if changes and preset == base.name:
        changes.setdefault("name", base.name + "*")  # 上書きを示す
    return replace(base, **changes)
