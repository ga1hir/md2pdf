"""Noto CJK フォントを上流から取得し、ReportLab 用の TrueType に変換して fonts/ に置く。

  python -m md2pdf.fetch_fonts           未配置・不一致のものだけ生成
  python -m md2pdf.fetch_fonts --force   すべて生成し直す

ReportLab は CFF/OTF を埋め込めないため、可変 TTF は fontTools の instancer で
Regular(400)/Bold(700) に固定し、等幅 CJK の OTF は otf2ttf で TrueType(glyf) に変換する。
ページ数の再現性のため、上流はコミット固定で取得し、入力・出力とも SHA-256 で照合する。
出力の head.modified は SOURCE_DATE_EPOCH で固定するので、生成物はバイト単位で一致する。

変換には追加の依存が要る:  pip install -e '.[fonts]'（リポジトリのディレクトリで）
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import NamedTuple, Optional

from .fontreg import fonts_dir


class Source(NamedTuple):
    url: str
    sha256: str


class Target(NamedTuple):
    filename: str
    source: str  # SOURCES のキー
    convert: tuple[str, ...]  # 変換コマンド（{src} {dst} を置換）
    epoch: int  # SOURCE_DATE_EPOCH（head.modified）
    sha256: str


_GH = "https://raw.githubusercontent.com"

SOURCES: dict[str, Source] = {
    # google/fonts: Noto Sans JP 可変フォント（Version 2.004-H2）
    "sans_vf": Source(
        f"{_GH}/google/fonts/295d98a7a0c17c68f1341eaeea354e7960ea70d3/"
        "ofl/notosansjp/NotoSansJP%5Bwght%5D.ttf",
        "c2f3b4d463500a2ddcd3849cded1fceeb9fd6d1c32e6cbecd568453ba50fc68f",
    ),
    # google/fonts: Noto Serif JP 可変フォント（Version 2.003-H1）
    "serif_vf": Source(
        f"{_GH}/google/fonts/8a7c74854f766ae441c7584925cc0ec626fc5aa6/"
        "ofl/notoserifjp/NotoSerifJP%5Bwght%5D.ttf",
        "2fd527ba12b6a44ec30d796d633360da0aeba6c5d4af1304ce12bb4dc15a7dfc",
    ),
    # notofonts/noto-cjk: Noto Sans Mono CJK JP（Version 2.004, CFF）
    "mono_otf": Source(
        f"{_GH}/notofonts/noto-cjk/165c01b46ea533872e002e0785ff17e44f6d97d8/"
        "Sans/Mono/NotoSansMonoCJKjp-Regular.otf",
        "4d01725be822d144cf9a56ade981e6fb920cd7a610b8fc24cc601a920beea5b9",
    ),
}

_INSTANCER = (sys.executable, "-m", "fontTools.varLib.instancer", "-q")
_OTF2TTF = (sys.executable, "-c", "import sys; from otf2ttf.cli import main; sys.exit(main())")

TARGETS: tuple[Target, ...] = (
    Target("NotoSansJP-Regular.ttf", "sans_vf",
           _INSTANCER + ("{src}", "wght=400", "-o", "{dst}"), 1782220335,
           "311df73b2fe46080586b1e1f36652b535b9866349389231e62416f9074e55f3e"),
    Target("NotoSansJP-Bold.ttf", "sans_vf",
           _INSTANCER + ("{src}", "wght=700", "-o", "{dst}"), 1782220342,
           "b8353d67468b216dccb168f3c630178aa762c1b2310b74e227bd2bc4dea80b6a"),
    Target("NotoSerifJP-Regular.ttf", "serif_vf",
           _INSTANCER + ("{src}", "wght=400", "-o", "{dst}"), 1782220350,
           "b1632aa1f1f0bffe4729e9a949361f548fdce2b864c5185e23b8a532443d40ff"),
    Target("NotoSerifJP-Bold.ttf", "serif_vf",
           _INSTANCER + ("{src}", "wght=700", "-o", "{dst}"), 1782220359,
           "283b3fdb5c003e7399f1ad66e09f53cab94b428b7dddec15968a0b8b64948482"),
    Target("NotoSansMonoCJKjp-Regular.ttf", "mono_otf",
           _OTF2TTF + ("{src}", "-o", "{dst}"), 1782221198,
           "641d554aff2411892cc25f771c9ce3dd1bbc534aae43781b44df5a4b180aeb5f"),
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_deps() -> None:
    missing = []
    for mod in ("fontTools.varLib.instancer", "otf2ttf.cli"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod.split(".")[0])
    if missing:
        raise SystemExit(
            f"フォント変換に必要なパッケージがありません: {', '.join(missing)}\n"
            "  pip install -e '.[fonts]'   （リポジトリのディレクトリで）"
        )


def _download(src: Source, dst: Path) -> None:
    print(f"取得中: {src.url}")
    with urllib.request.urlopen(src.url) as r, open(dst, "wb") as f:
        shutil.copyfileobj(r, f)
    got = _sha256(dst)
    if got != src.sha256:
        raise SystemExit(f"取得したファイルのハッシュが一致しません: {src.url}\n"
                         f"  期待: {src.sha256}\n  実際: {got}")


def fetch(force: bool = False, out_dir: Optional[Path] = None) -> int:
    """フォントを生成して out_dir（既定はパッケージの fonts/）に置く。生成した数を返す。"""
    out = Path(out_dir) if out_dir else fonts_dir()
    out.mkdir(parents=True, exist_ok=True)
    todo = [t for t in TARGETS
            if force or not (out / t.filename).exists()
            or _sha256(out / t.filename) != t.sha256]
    if not todo:
        print(f"フォントはすべて配置済みです: {out}")
        return 0

    _check_deps()
    with tempfile.TemporaryDirectory(prefix="md2pdf-fonts-") as tmp:
        tmpd = Path(tmp)
        fetched: dict[str, Path] = {}
        for t in todo:
            if t.source not in fetched:
                src_path = tmpd / Path(SOURCES[t.source].url).name.replace("%5B", "[").replace("%5D", "]")
                _download(SOURCES[t.source], src_path)
                fetched[t.source] = src_path
            dst = tmpd / t.filename
            cmd = [a.format(src=fetched[t.source], dst=dst) for a in t.convert]
            env = dict(os.environ, SOURCE_DATE_EPOCH=str(t.epoch))
            print(f"変換中: {t.filename}")
            subprocess.run(cmd, check=True, env=env, stdout=subprocess.DEVNULL)
            got = _sha256(dst)
            if got != t.sha256:
                raise SystemExit(
                    f"変換結果のハッシュが一致しません: {t.filename}\n"
                    f"  期待: {t.sha256}\n  実際: {got}\n"
                    "fonttools / otf2ttf / cu2qu の版が想定（pyproject の [fonts]）と異なる可能性があります。"
                )
            shutil.move(str(dst), out / t.filename)
    print(f"完了: {len(todo)} 個のフォントを配置しました → {out}")
    return len(todo)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m md2pdf.fetch_fonts",
        description="Noto CJK フォントを上流から取得・変換して配置します。",
    )
    p.add_argument("--force", action="store_true", help="配置済みでも生成し直す")
    p.add_argument("--out-dir", type=Path, help="出力先（既定: パッケージの fonts/）")
    args = p.parse_args(argv)
    fetch(force=args.force, out_dir=args.out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
