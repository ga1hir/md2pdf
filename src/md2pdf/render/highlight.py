"""コードのシンタックスハイライト＋空白可視化。

Pygments でトークン化し、tango 風配色（config.TANGO_COLORS）を当てつつ、
半角スペース→·、全角スペース→□、タブ→→、行末→↵ を灰色マーカーとして埋め込んだ
「行ごとの Run リスト」を返す。コードブロック Flowable がこれを等幅で描画する。
"""

from __future__ import annotations

from typing import Optional

from pygments import lex
from pygments.lexers import get_lexer_by_name
from pygments.lexers.special import TextLexer
from pygments.token import Token
from pygments.util import ClassNotFound

from .. import config
from .inline import Run


def _color_for(tokentype) -> "config.HexColor":
    for t in reversed(tokentype.split()):
        name = str(t)
        if name.startswith("Token."):
            name = name[len("Token."):]
        if name in config.TANGO_COLORS:
            return config.TANGO_COLORS[name]
    return config.COLOR_CODE_DEFAULT


def _get_lexer(lang: Optional[str]):
    if lang:
        try:
            return get_lexer_by_name(lang, stripnl=False, stripall=False)
        except ClassNotFound:
            pass
    return TextLexer(stripnl=False, stripall=False)


def _visualize_segment(text: str, color, size: float, col: list[int]) -> list[Run]:
    """色付きセグメントを、空白可視化マーカーを切り出した Run 列に変換する。"""
    runs: list[Run] = []
    buf = ""

    def flush_buf() -> None:
        nonlocal buf
        if buf:
            runs.append(Run(buf, config.FONT_MONO, size, color))
            col[0] += len(buf) * 2  # 概算（半角=2 単位）
            buf = ""

    for ch in text:
        if ch == " ":
            flush_buf()
            runs.append(Run(config.WS_SPACE, config.FONT_MONO, size, config.COLOR_WHITESPACE))
            col[0] += 2
        elif ch == "　":  # 全角スペース
            flush_buf()
            runs.append(Run(config.WS_IDEOGRAPHIC, config.FONT_MONO, size, config.COLOR_WHITESPACE))
            col[0] += 4
        elif ch == "\t":
            flush_buf()
            # 次のタブストップ（TAB_WIDTH 半角単位）までを矢印＋余白で埋める
            stop = config.TAB_WIDTH * 2
            advance = stop - (col[0] % stop)
            pad = max(0, (advance - 2) // 2)  # 矢印は全角 1 文字 = 2 半角分
            runs.append(Run(config.WS_TAB + " " * pad, config.FONT_MONO, size,
                            config.COLOR_WHITESPACE))
            col[0] += advance
        else:
            buf += ch
    flush_buf()
    return runs


def highlight_code(code: str, lang: Optional[str], size: float) -> list[list[Run]]:
    """コード文字列を「行ごとの Run リスト」に変換する。行末に ↵ を付す。"""
    lexer = _get_lexer(lang)
    lines: list[list[Run]] = [[]]
    col = [0]
    for tokentype, value in lex(code, lexer):
        color = _color_for(tokentype)
        parts = value.split("\n")
        for i, part in enumerate(parts):
            if i > 0:
                # 行末マーカー＋改行
                lines[-1].append(
                    Run(config.WS_NEWLINE, config.FONT_MONO, size, config.COLOR_WHITESPACE)
                )
                lines.append([])
                col[0] = 0
            if part:
                lines[-1].extend(_visualize_segment(part, color, size, col))
    # Pygments は末尾に余分な空行を作ることがある（行末改行）。最後が空なら落とす。
    if len(lines) > 1 and not lines[-1]:
        lines.pop()
    return lines
