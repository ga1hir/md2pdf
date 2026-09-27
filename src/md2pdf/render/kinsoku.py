"""禁則処理のための文字判定ヘルパー。

実際の行分割は inline.py の JParagraph が行う。ここでは「行頭に来てはならない」
「行末に来てはならない」文字の判定と、CJK 文字（1 文字単位で折り返してよい文字）の
判定だけを提供する。
"""

from __future__ import annotations

from .. import config


def cannot_start_line(ch: str) -> bool:
    """行頭禁則: 句読点・閉じ括弧など、行の先頭に来てはならない文字。"""
    return ch in config.KINSOKU_NOT_LINE_START


def cannot_end_line(ch: str) -> bool:
    """行末禁則: 開き括弧など、行の末尾に来てはならない文字。"""
    return ch in config.KINSOKU_NOT_LINE_END


def is_cjk(ch: str) -> bool:
    """CJK（漢字・かな・全角約物等）か。1 文字単位で折り返せる文字を True とする。"""
    code = ord(ch)
    return (
        0x3000 <= code <= 0x30FF      # CJK 記号・ひらがな・カタカナ
        or 0x3400 <= code <= 0x4DBF   # CJK 拡張 A
        or 0x4E00 <= code <= 0x9FFF   # CJK 統合漢字
        or 0xF900 <= code <= 0xFAFF   # CJK 互換漢字
        or 0xFF00 <= code <= 0xFFEF   # 全角・半角形
    )
