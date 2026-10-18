# md2pdf

Markdown を **最終版面の PDF** に変換し、書籍原稿が「仕上がりで何ページになるか」を
確認しながら執筆するためのツールです。生成 PDF は編集者・組版担当へ渡せる品質
（フォント埋め込み・テキスト選択可・ノンブル・PDF しおり）を備えます。

**pandoc / WeasyPrint / Node / ブラウザに依存しません。** `pip` で入る純 Python
パッケージのみで動作し、日本語フォントをパッケージ内に置いて使うため、オフラインでも全環境で同じ見た目になります。

## 特徴

- **版面を厳密に再現** — 指定した字詰め×行数（例: A4・38字×35行、B5変形・40字×40行）で
  本文を組むため、ページ数が実書籍の見積りと一致します。
- **日本語組版** — 明朝（本文）/ ゴシック（見出し）、禁則処理、均等割り付け、ルビ（`{漢字|かんじ}`）。
- **コードブロック** — シンタックスハイライト（tango 配色）＋空白可視化（半角スペース→`·`、
  全角→`□`、タブ→`→`、行末→`⏎`）、背景・枠、ページ跨ぎ対応。
- **表・引用・GFM アラート・リスト・タスクリスト・脚注**（ページ内別枠）・**数式**（純 Python 描画）・
  **Mermaid**（flowchart / sequence をローカル描画）・**画像**（ラスタ / SVG）。
- **複数ファイルの結合出力**、**ノンブル**、**PDF しおり**、**`--watch`** 自動再生成。

## インストール

```bash
git clone https://github.com/ga1hir/md2pdf.git
cd md2pdf
python3 -m venv .venv && source .venv/bin/activate
pip install -U pip              # macOS 標準 Python 3.9 の pip 21 は editable install 非対応
pip install -e '.[fonts]'
python -m md2pdf.fetch_fonts   # 日本語フォントを取得・生成（初回のみ・要ネット接続）
```

Python 3.9 以上。依存（`markdown-it-py` / `Pygments` / `reportlab` / `matplotlib` /
`resvg-py` / `svglib` / `watchdog`）は自動で入ります。

日本語フォント（Noto Serif JP / Noto Sans JP / Noto Sans Mono CJK JP, SIL OFL）はリポジトリに含めず、
`fetch_fonts` が上流（google/fonts, notofonts/noto-cjk）からコミット固定で取得し、ReportLab が埋め込める
TrueType に変換して `src/md2pdf/fonts/` に置きます。入力・出力とも SHA-256 で照合するので、
どの環境でも同一のフォントになり、ページ数が変わりません。生成後はオフラインで動作します。
SVG は resvg（このフォントで機種非依存に描画）を優先し、未導入環境では svglib にフォールバックします。

## 使い方

```bash
# 個別変換（入力ごとに .pdf を出力）
md2pdf input.md
md2pdf *.md

# 版面プリセット
md2pdf --preset b5h-40x40 input.md
md2pdf --list-presets

# 個別に上書き（プリセットを基底に）
md2pdf --trim 182x230 --chars 40 --lines 40 --font-size 10 input.md

# 出力先の指定（--merge なしなら入力 1 件のときだけ）
md2pdf -o /tmp/out.pdf input.md

# 複数ファイルを 1 つの PDF に結合（章をまとめて 1 冊化）
# 入力が 1 件でも見つからなければ結合せず終了コード 1
md2pdf --merge -o book.pdf 01_*.md 02_*.md

# 保存時に自動再生成（執筆しながらページ数確認）
md2pdf --watch input.md

# メタデータ／ノンブル
md2pdf --title "私の本" --author "著者名" input.md
md2pdf --no-page-number input.md
```

変換後、各ファイルおよび合計のページ数を表示します。

```
変換中: input.md → input.pdf
  完了: input.pdf（12ページ）

===== 結果 =====
成功: 1件  失敗: 0件  合計: 12ページ
```

### プリセット

| プリセット | 判型 | 字詰め×行数 | 本文 |
| ---------- | ---- | ----------- | ---- |
| `a4-38x35`（既定） | A4 (210×297mm) | 38字×35行 | 12.68pt |
| `b5h-40x40` | B5変形 (182×230mm) | 40字×40行 | 10pt |

`python -m md2pdf ...` でも実行できます。

## 対応する Markdown

見出し、段落、強調、リスト（番号付き／なし／タスクリスト）、コードブロック、
インラインコード、表、引用、GFM アラート（`> [!NOTE]` / `[!TIP]` / `[!IMPORTANT]` /
`[!WARNING]` / `[!CAUTION]`）、水平線、リンク、画像（PNG/JPEG/SVG）、脚注、定義リスト、
数式（`$...$` / `$$...$$`）、Mermaid（` ```mermaid `）、ルビ（`{漢字|かんじ}`）、下線（HTML の `<u>…</u>`）、
手動改ページ（`<!-- pagebreak -->`）。

## 制限事項

- 縦書き・段組は非対応（横書きのみ）。
- Mermaid はよく使うサブセット（flowchart / sequenceDiagram）のみ。未対応の図種別・
  構文はスタイル付きコードブロックにフォールバックします。
- SVG 画像内に埋め込まれた CJK テキストはフォント解決の都合で字形が出ない場合があります
  （図形は問題ありません）。

## ライセンス

MIT License（[LICENSE](LICENSE)）。日本語フォントは SIL Open Font License
（[src/md2pdf/fonts/](src/md2pdf/fonts/) の各 LICENSE を参照）。
