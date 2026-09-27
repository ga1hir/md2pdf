"""版面（Layout）から各要素のスタイル（フォント・級数・行送り・前後空き）を導出する。

JParagraph は ReportLab の ParagraphStyle を使わないため、ここで要素別のスタイルを
一元的に決める。色は config を参照する。
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import config
from ..layout import Layout


@dataclass
class ParaStyle:
    font: str
    size: float
    leading: float
    align: str = "justify"
    space_before: float = 0.0
    space_after: float = 0.0
    color = config.COLOR_TEXT


class Styles:
    """1 つの Layout に対する要素別スタイル集合。"""

    def __init__(self, layout: Layout) -> None:
        self.layout = layout
        fs = layout.font_size
        lead = layout.leading

        self.body = ParaStyle(config.FONT_SERIF, fs, lead, "justify",
                              space_before=0.0, space_after=lead * 0.3)

        # 見出し（ゴシック）。h1/h2 は下線（flowables 側で描画）。
        self._heading_scale = {1: 1.8, 2: 1.4, 3: 1.2, 4: 1.1, 5: 1.0, 6: 0.95}

        self.code_size = fs * 0.9
        self.code_leading = self.code_size * 1.5

        self.quote = ParaStyle(config.FONT_MONO, fs * 0.95, lead, "left")
        self.table_size = fs * 0.9
        self.table_leading = self.table_size * 1.4

        self.footnote = ParaStyle(config.FONT_SERIF, fs * 0.8, fs * 0.8 * 1.35, "left")
        self.caption = ParaStyle(config.FONT_SANS, fs * 0.85, lead * 0.9, "left",
                                 space_before=lead * 0.2, space_after=lead * 0.1)

    def heading(self, level: int) -> ParaStyle:
        scale = self._heading_scale.get(level, 1.0)
        size = self.layout.font_size * scale
        bold = level <= 4
        return ParaStyle(
            config.FONT_SANS_BOLD if bold else config.FONT_SANS,
            size,
            size * 1.3,
            "left",
            space_before=self.layout.leading * (1.2 if level <= 2 else 0.8),
            space_after=self.layout.leading * 0.3,
        )

    def heading_font(self, level: int) -> str:
        return config.FONT_SANS_BOLD if level <= 4 else config.FONT_SANS
