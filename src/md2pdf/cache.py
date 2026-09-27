"""描画キャッシュ（数式・Mermaid 画像など）。

入力内容のハッシュをキーに、一時ディレクトリへ生成物を保存する。同じ入力なら再描画を
省き、--watch での編集ループを高速化する。内容ベースなので明示的な無効化は不要。
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

_CACHE_DIR = Path(tempfile.gettempdir()) / "md2pdf-cache"


def cache_dir() -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR


def cache_path(key: str, ext: str) -> str:
    """key の内容ハッシュから安定したキャッシュファイルパスを返す。"""
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
    return str(cache_dir() / f"{digest}{ext}")
