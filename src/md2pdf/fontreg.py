"""同梱 Noto CJK フォントの登録。

ReportLab は CFF/OTF を埋め込めないため、同梱フォントはすべて TrueType(glyf)。
本文=明朝(NotoSerifJP)、見出し=ゴシック(NotoSansJP)、コード=等幅(NotoSansMonoCJKjp)。
それぞれ Regular/Bold を登録し、Paragraph の <b> が効くよう FontFamily も登録する。
等幅 Bold は容量節約のため Regular を流用する。
"""

from __future__ import annotations

from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from . import config

# (論理名, ファイル名) の対応。Bold が無いものは Regular を再利用する。
_FONT_FILES: dict[str, str] = {
    config.FONT_SERIF: "NotoSerifJP-Regular.ttf",
    config.FONT_SERIF_BOLD: "NotoSerifJP-Bold.ttf",
    config.FONT_SANS: "NotoSansJP-Regular.ttf",
    config.FONT_SANS_BOLD: "NotoSansJP-Bold.ttf",
    config.FONT_MONO: "NotoSansMonoCJKjp-Regular.ttf",
    config.FONT_MONO_BOLD: "NotoSansMonoCJKjp-Regular.ttf",  # Bold は Regular 流用
}

_registered = False


def fonts_dir() -> Path:
    return Path(__file__).resolve().parent / "fonts"


def register_fonts() -> None:
    """同梱フォントを ReportLab に登録する（多重呼び出しは無視）。"""
    global _registered
    if _registered:
        return

    d = fonts_dir()
    for logical, filename in _FONT_FILES.items():
        path = d / filename
        if not path.exists():
            raise FileNotFoundError(
                f"同梱フォントが見つかりません: {path}\n"
                "fonts/ ディレクトリに Noto CJK の TTF が必要です。"
            )
        pdfmetrics.registerFont(TTFont(logical, str(path)))

    # <b> などのインラインマークアップで太字へ切り替えられるよう family を登録
    pdfmetrics.registerFontFamily(
        config.FONT_SERIF,
        normal=config.FONT_SERIF,
        bold=config.FONT_SERIF_BOLD,
        italic=config.FONT_SERIF,
        boldItalic=config.FONT_SERIF_BOLD,
    )
    pdfmetrics.registerFontFamily(
        config.FONT_SANS,
        normal=config.FONT_SANS,
        bold=config.FONT_SANS_BOLD,
        italic=config.FONT_SANS,
        boldItalic=config.FONT_SANS_BOLD,
    )
    pdfmetrics.registerFontFamily(
        config.FONT_MONO,
        normal=config.FONT_MONO,
        bold=config.FONT_MONO_BOLD,
        italic=config.FONT_MONO,
        boldItalic=config.FONT_MONO_BOLD,
    )

    # SVG 内の font-family 名を同梱フォントへ別名登録する。svglib は ReportLab の
    # フォント名で解決するため、これが無いと SVG 中の日本語が豆腐になる。
    sans = str(d / _FONT_FILES[config.FONT_SANS])
    serif = str(d / _FONT_FILES[config.FONT_SERIF])
    sans_aliases = ["Hiragino Sans", "Hiragino Kaku Gothic ProN", "Hiragino Kaku Gothic Pro",
                    "Yu Gothic", "YuGothic", "Meiryo", "MS Gothic", "sans-serif",
                    "Helvetica", "Arial", "Noto Sans JP", "Noto Sans CJK JP"]
    serif_aliases = ["Hiragino Mincho ProN", "Yu Mincho", "YuMincho", "MS Mincho",
                     "serif", "Times New Roman", "Noto Serif JP", "Noto Serif CJK JP"]
    for alias in sans_aliases:
        pdfmetrics.registerFont(TTFont(alias, sans))
    for alias in serif_aliases:
        pdfmetrics.registerFont(TTFont(alias, serif))

    _registered = True
