"""Markdown パーサの構築（markdown-it-py + プラグイン）。

テーブル・脚注・定義リスト・数式（dollarmath）を有効化する。タスクリストと
ルビ（{漢字|かんじ}）は builder 側で検出するため、ここではプラグインを使わない。
"""

from __future__ import annotations

from markdown_it import MarkdownIt
from mdit_py_plugins.deflist import deflist_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin


def make_parser() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": True, "breaks": False})
    md.enable(["table"])
    md.use(footnote_plugin)
    md.use(deflist_plugin)
    # digit/space に隣接する $ は通貨表記（$5.00 など）と衝突するため許可しない。
    # 既定値のままだと2箇所の通貨表記に挟まれた地の文が丸ごと数式扱いされる。
    md.use(dollarmath_plugin, allow_digits=False, allow_space=False)
    return md
