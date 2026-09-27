"""コマンドラインインターフェース。

  md2pdf input.md [...]            個別変換（入力ごとに .pdf を出力）
  md2pdf --preset b5h-40x40 *.md   版面プリセット指定
  md2pdf --merge -o book.pdf *.md  複数入力を 1 つの PDF に結合
  md2pdf --watch *.md              保存時に自動再生成

変換後に各ファイルおよび合計のページ数を表示する。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Optional

from . import layout as layoutmod
from .builder import Builder
from .document import render_passes
from .layout import PRESETS


def _parse_trim(value: str) -> tuple[float, float]:
    m = value.lower().replace("mm", "").split("x")
    if len(m) != 2:
        raise argparse.ArgumentTypeError("--trim は 例: 182x230 の形式で指定してください")
    return float(m[0]), float(m[1])


def build_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="md2pdf",
        description="Markdown を最終版面の PDF に変換し、ページ数を表示します。",
    )
    p.add_argument("inputs", nargs="*", help="入力 Markdown ファイル")
    p.add_argument("--preset", default=layoutmod.DEFAULT_PRESET,
                   choices=list(PRESETS), help="版面プリセット")
    p.add_argument("--trim", type=_parse_trim, help="判型 幅x高 (mm) 例: 182x230")
    p.add_argument("--chars", type=int, help="字詰め（全角字数）")
    p.add_argument("--lines", type=int, help="1 ページの行数")
    p.add_argument("--font-size", type=float, help="本文フォントサイズ (pt)")
    p.add_argument("--line-height", type=float, help="行送り倍率")
    p.add_argument("--margin", type=float, dest="side_margin",
                   help="左右余白 (mm)。未指定なら水平センタリング")
    p.add_argument("--merge", action="store_true", help="複数入力を 1 つの PDF に結合")
    p.add_argument("-o", "--output", help="出力ファイル名（--merge 時に使用）")
    p.add_argument("--watch", action="store_true", help="保存時に自動再生成")
    p.add_argument("--no-page-number", action="store_true", help="ノンブルを付けない")
    p.add_argument("--title", default="", help="PDF タイトル（メタデータ）")
    p.add_argument("--author", default="", help="PDF 著者（メタデータ）")
    p.add_argument("--list-presets", action="store_true", help="プリセット一覧を表示")
    return p.parse_args(argv)


def _resolve_layout(args: argparse.Namespace):
    return layoutmod.resolve(
        args.preset, trim=args.trim, chars=args.chars, lines=args.lines,
        font_size=args.font_size, line_height=args.line_height,
        side_margin_mm=args.side_margin,
    )


def _convert_one(path: Path, lay, args) -> Optional[int]:
    if not path.is_file():
        print(f"エラー: ファイルが見つかりません: {path}", file=sys.stderr)
        return None
    out = path.with_suffix(".pdf")
    print(f"変換中: {path.name} → {out.name}")
    try:
        text = path.read_text(encoding="utf-8")

        def make():
            b = Builder(lay, base_dir=str(path.resolve().parent))
            return b.build(text), b

        pages = render_passes(str(out), make, lay,
                              show_page_number=not args.no_page_number,
                              title=args.title or path.stem, author=args.author)
    except Exception as e:  # noqa: BLE001
        print(f"エラー: 変換に失敗しました: {path.name}: {e}", file=sys.stderr)
        return None
    print(f"  完了: {out.name}（{pages}ページ）")
    return pages


def _convert_merged(paths: list[Path], lay, args) -> Optional[int]:
    out = Path(args.output) if args.output else Path("merged.pdf")
    from reportlab.platypus import PageBreak
    existing = [p for p in paths if p.is_file()]
    for p in paths:
        if not p.is_file():
            print(f"エラー: ファイルが見つかりません: {p}", file=sys.stderr)
    if not existing:
        return None
    for p in existing:
        print(f"結合: {p.name}")

    def make():
        b = Builder(lay)
        story: list = []
        for i, path in enumerate(existing):
            if i > 0:
                story.append(PageBreak())
            b.base_dir = str(path.resolve().parent)  # 相対画像はファイル基準で解決
            new_flowables = b.build(path.read_text(encoding="utf-8"))
            for fl in new_flowables:
                fl._src_file = path.name  # エラー時にどのファイル由来か特定するため
            story.extend(new_flowables)
            b.next_file()
        return story, b

    try:
        pages = render_passes(str(out), make, lay,
                              show_page_number=not args.no_page_number,
                              title=args.title or out.stem, author=args.author)
    except Exception as e:  # noqa: BLE001
        print(f"エラー: 結合 PDF の生成に失敗しました: {e}", file=sys.stderr)
        return None
    print(f"  完了: {out.name}（合計 {pages}ページ）")
    return pages


def _run_once(args) -> int:
    lay = _resolve_layout(args)
    print(f"版面: {lay.describe()}")
    paths = [Path(p) for p in args.inputs]
    if args.merge:
        _convert_merged(paths, lay, args)
        return 0
    total = 0
    ok = 0
    fail = 0
    for path in paths:
        pages = _convert_one(path, lay, args)
        if pages is None:
            fail += 1
        else:
            ok += 1
            total += pages
    print("\n===== 結果 =====")
    print(f"成功: {ok}件  失敗: {fail}件  合計: {total}ページ")
    return 0 if fail == 0 else 1


def _watch(args) -> int:
    paths = [Path(p) for p in args.inputs if Path(p).is_file()]
    if not paths:
        print("エラー: 監視対象の入力がありません", file=sys.stderr)
        return 1
    print("監視中（Ctrl-C で終了）:", ", ".join(p.name for p in paths))
    _run_once(args)
    mtimes = {p: p.stat().st_mtime for p in paths}
    try:
        while True:
            time.sleep(0.7)
            changed = False
            for p in paths:
                try:
                    mt = p.stat().st_mtime
                except OSError:
                    continue
                if mt != mtimes.get(p):
                    mtimes[p] = mt
                    changed = True
            if changed:
                print("\n変更を検出。再生成します…")
                _run_once(args)
    except KeyboardInterrupt:
        print("\n監視を終了しました。")
        return 0


def main(argv: Optional[list[str]] = None) -> int:
    args = build_args(argv)
    if args.list_presets:
        for name, lay in PRESETS.items():
            print(f"{name}: {lay.describe()}")
        return 0
    if not args.inputs:
        print("使い方: md2pdf input.md [...]  /  md2pdf --merge -o book.pdf *.md",
              file=sys.stderr)
        return 1
    if args.watch:
        return _watch(args)
    return _run_once(args)


if __name__ == "__main__":
    sys.exit(main())
