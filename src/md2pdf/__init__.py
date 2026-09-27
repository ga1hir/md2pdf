"""md2pdf — 純Python・外部ツール非依存の Markdown→PDF 変換ツール。

書籍原稿の「仕上がりページ数」を最終版面で確認すること、および編集者・組版担当へ
渡せる品質の PDF を出力することを目的とする。pandoc / weasyprint / Node 等の
ネイティブ外部ツールに依存せず、pip で入る純 Python パッケージのみで動作する。
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
