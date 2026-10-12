"""見た目に関する定数群（参考ツールの style.css 相当を一元管理）。

色・空白可視化マーカー・禁則文字集合・フォント論理名など、レンダリング全体で
共有する設定をここに集約する。レイアウト（判型・字詰め・行数）は layout.py を参照。
"""

from __future__ import annotations

from reportlab.lib.colors import HexColor

# --- フォント論理名（fonts/ に置いた実ファイルを fontreg.py で登録する） -------------
# 明朝（本文）/ ゴシック（見出し）/ 等幅（コード）。CJK と Latin を兼ねる。
FONT_SERIF = "NotoSerifJP"          # 本文
FONT_SERIF_BOLD = "NotoSerifJP-Bold"
FONT_SANS = "NotoSansJP"            # 見出し
FONT_SANS_BOLD = "NotoSansJP-Bold"
FONT_MONO = "NotoSansMonoCJK"       # コード（等幅、CJK フォールバック付き）
FONT_MONO_BOLD = "NotoSansMonoCJK-Bold"

# --- 基本色（style.css 由来） ---------------------------------------------------------
COLOR_TEXT = HexColor("#333333")
COLOR_LINK = HexColor("#0066cc")
COLOR_RULE = HexColor("#cccccc")          # 水平線
COLOR_HEADING_RULE_H1 = HexColor("#333333")
COLOR_HEADING_RULE_H2 = HexColor("#666666")

# コードブロック
COLOR_CODE_BG = HexColor("#f5f5f5")
COLOR_CODE_BORDER = HexColor("#dddddd")
COLOR_INLINE_CODE_BG = HexColor("#f0f0f0")
COLOR_INLINE_CODE_BORDER = HexColor("#e0e0e0")

# 引用
COLOR_QUOTE_BAR = HexColor("#cccccc")
COLOR_QUOTE_BG = HexColor("#fafafa")
COLOR_QUOTE_TEXT = HexColor("#555555")

# GFM アラート（> [!NOTE] 等）: 種類 → (表示ラベル, 色)。色は GitHub ライトテーマ準拠。
ALERT_TYPES = {
    "note": ("補足", HexColor("#0969da")),
    "tip": ("ヒント", HexColor("#1a7f37")),
    "important": ("重要", HexColor("#8250df")),
    "warning": ("警告", HexColor("#9a6700")),
    "caution": ("注意", HexColor("#d1242f")),
}

# テーブル
COLOR_TABLE_BORDER = HexColor("#999999")
COLOR_TABLE_HEADER_BG = HexColor("#f0f0f0")
COLOR_TABLE_STRIPE_BG = HexColor("#fafafa")

# 空白可視化（灰）
COLOR_WHITESPACE = HexColor("#aaaaaa")

# ノンブル・脚注
COLOR_PAGE_NUMBER = HexColor("#666666")
COLOR_FOOTNOTE_RULE = HexColor("#cccccc")

# --- 空白可視化マーカー（codeblock.lua 由来） ----------------------------------------
WS_SPACE = "·"        # 半角スペース → 中点
WS_IDEOGRAPHIC = "□"  # 全角スペース → 白四角
WS_TAB = "→"          # タブ → 右矢印
WS_NEWLINE = "⏎"      # 行末 → 改行マーク（U+23CE。等幅 CJK フォントに収録あり）
TAB_WIDTH = 4              # タブの表示幅（半角換算）

# --- Pygments トークン → 色（tango 風。style.css の .sourceCode .* を踏襲） ----------
# キーは Pygments の標準トークン短縮名（Token.Keyword 等）に対応付ける。
# 実際のマッピングは highlight.py が Pygments Token を辿って解決する。
TANGO_COLORS = {
    "Keyword": HexColor("#204a87"),            # .kw 太字
    "Keyword.Type": HexColor("#204a87"),       # .dt
    "Name.Builtin": HexColor("#204a87"),
    "Literal.Number": HexColor("#0000cf"),     # .dv .bn .fl
    "Literal.String": HexColor("#4e9a06"),     # .st .vs .ss
    "Literal.String.Char": HexColor("#4e9a06"),
    "Comment": HexColor("#8f5902"),            # .co 斜体
    "Comment.Preproc": HexColor("#8f5902"),
    "Name.Function": HexColor("#000000"),      # .fu
    "Name.Attribute": HexColor("#c4a000"),     # .at
    "Generic.Error": HexColor("#a40000"),      # .er 太字
    "Generic.Deleted": HexColor("#cc0000"),    # diff 削除行
    "Generic.Inserted": HexColor("#00aa00"),   # diff 追加行
    "Operator": HexColor("#ce5c00"),           # .op 太字
    "Keyword.Constant": HexColor("#000000"),
    "Name": COLOR_TEXT,
    "Text": COLOR_TEXT,
}
COLOR_CODE_DEFAULT = COLOR_TEXT

# --- 禁則処理 -------------------------------------------------------------------------
# 行頭にあってはならない文字（前の行末へぶら下げる/追い込む）。
KINSOKU_NOT_LINE_START = set(
    "、。，．・：；！？）］｝」』】〕〉》〙〗»"
    "ヽヾゝゞ々ー"
    "ぁぃぅぇぉっゃゅょゎ"
    "ァィゥェォッャュョヮ"
    "゛゜?!)]}､｡｣"
    "‐”’＝"
    "…‥"
)
# 行末にあってはならない文字（次の行頭へ送る）。
KINSOKU_NOT_LINE_END = set(
    "（［｛「『【〔〈《〘〖«"
    "([{“‘"
)

# --- 数式・画像 -----------------------------------------------------------------------
MATH_DPI = 300                     # 数式ラスタライズ DPI
IMAGE_MAX_WIDTH_RATIO = 1.0        # 本文幅に対する画像最大幅
