"""スモークテスト＋版面の回帰テスト。

PDF が例外なく生成されること、版面（字詰め×行数）が厳密に保たれること、
プリセット切替・結合・脚注・ルビ・数式などが壊れていないことを検証する。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfReader

from md2pdf import layout
from md2pdf.builder import Builder
from md2pdf.document import render_passes
from md2pdf.render.inline import JParagraph, Run

ASSETS = Path(__file__).parent / "assets"


def _pages(path: Path) -> int:
    return len(PdfReader(str(path)).pages)


def _convert(src: str, preset: str, out: Path, **kw) -> int:
    lay = layout.resolve(preset)

    def make():
        b = Builder(lay)
        return b.build(src), b

    return render_passes(str(out), make, lay, **kw)


def test_38x35_grid_exact():
    """本文ブロックが厳密に 38 字 × 35 行で組まれる。"""
    src = (ASSETS / "test_38x35.md").read_text(encoding="utf-8")
    i = src.find("<div>\n<span>")
    j = src.find("</div>", i) + len("</div>")
    lay = layout.resolve("a4-38x35")
    para = next(f for f in Builder(lay).build(src[i:j]) if isinstance(f, JParagraph))
    para.wrap(lay.body_width, 1e9)
    counts = [len(line.atoms) for line in para._lines]
    assert len(para._lines) == 35
    assert min(counts) == 38 and max(counts) == 38


def test_b5_grid_exact():
    """B5変形では 40 字 × 40 行になる。"""
    lay = layout.resolve("b5h-40x40")
    assert lay.chars_per_line == 40 and lay.lines_per_page == 40
    para = JParagraph(
        [__import__("md2pdf.render.inline", fromlist=["Run"]).Run("あ" * 200,
                                                                   size=lay.font_size)],
        lay.leading, base_size=lay.font_size)
    para.wrap(lay.body_width, 1e9)
    assert all(len(l.atoms) == 40 for l in para._lines[:-1])


def test_split_boundary_never_returns_unsplit_self():
    """availHeight が total*leading のごく直下（旧 _FIT_EPS=0.2pt の窓）でも、
    split() は必ず分割し、未分割の自分自身 [self] を返してはならない
    （Splitting error(n==1) の回帰防止。--merge でページ途中からの残り高さが
    たまたまこの窓に落ちると再現していたバグ）。"""
    lay = layout.resolve("b5h-40x40")
    para = JParagraph([Run("あ" * 400, size=lay.font_size)], lay.leading,
                       base_size=lay.font_size)
    para.wrap(lay.body_width, 1e9)
    total = len(para._lines)
    assert total >= 5

    # 修正前の _FIT_EPS(0.2) だとここで n_fit>=total と誤判定され [self] が返っていた。
    avail = total * lay.leading - 0.1
    result = para.split(lay.body_width, avail)
    assert result != [para]
    assert len(result) == 2
    assert sum(len(p._lines) for p in result) == total


def test_split_boundary_no_layout_error_via_reportlab_frame():
    """ReportLab が実際に踏む Frame.add() → Frame.split() → Frame.add(trySplit=0) の
    手順（doctemplate.handle_flowable と同じ）を境界の availHeight で再現し、
    LayoutError('Splitting error') が起きないことを確認する。"""
    import io

    from reportlab.pdfgen.canvas import Canvas
    from reportlab.platypus import Frame

    lay = layout.resolve("b5h-40x40")
    para = JParagraph([Run("あ" * 400, size=lay.font_size)], lay.leading,
                       base_size=lay.font_size)
    para.wrap(lay.body_width, 1e9)
    total = len(para._lines)
    avail = total * lay.leading - 0.1

    canv = Canvas(io.BytesIO(), pagesize=(lay.body_width, avail))
    frame = Frame(0, 0, lay.body_width, avail, leftPadding=0, rightPadding=0,
                  topPadding=0, bottomPadding=0)
    assert frame.add(para, canv) == 0  # 前提: このぎりぎりの高さでは一括では収まらない
    S = frame.split(para, canv)
    assert len(S) >= 1
    assert frame.add(S[0], canv, trySplit=0) == 1


@pytest.mark.parametrize("preset", ["a4-38x35", "b5h-40x40"])
def test_convert_produces_pdf(tmp_path, preset):
    src = (ASSETS / "test_38x35.md").read_text(encoding="utf-8")
    out = tmp_path / f"out_{preset}.pdf"
    pages = _convert(src, preset, out)
    assert out.exists() and out.stat().st_size > 1000
    assert pages >= 1
    assert _pages(out) == pages


def test_features_build(tmp_path):
    """ルビ・脚注・数式・タスクリスト・テーブルが例外なく組める。"""
    src = (
        "# 見出し\n\n本文[^1]に{漢字|かんじ}とルビ。\n\n"
        "インライン $x^2$ とブロック:\n\n$$a^2+b^2=c^2$$\n\n"
        "- [x] 済\n- [ ] 未\n\n"
        "| A | B |\n| - | - |\n| 1 | 2 |\n\n"
        "```python\ndef f():\n    return 1\n```\n\n"
        "[^1]: 脚注本文。\n"
    )
    out = tmp_path / "features.pdf"
    pages = _convert(src, "a4-38x35", out, title="t", author="a")
    assert pages >= 1 and out.stat().st_size > 1000


def test_currency_dollar_stays_literal():
    """通貨表記の$が複数あっても dollarmath に誤認識されず地の文が保持される。"""
    lay = layout.resolve("a4-38x35")
    text = ("固定部分は、作成したWeb ACL1つあたり月額$5.00と、"
            "Web ACLに追加したルール1つあたり月額$1.00です。")
    para = next(f for f in Builder(lay).build(text + "\n") if isinstance(f, JParagraph))
    assert not any(r.image for r in para.runs)
    assert "".join(r.text for r in para.runs) == text


def test_metadata(tmp_path):
    out = tmp_path / "meta.pdf"
    _convert("# T\n\n本文。\n", "a4-38x35", out, title="マイ書籍", author="著者名")
    info = PdfReader(str(out)).metadata
    assert info.title == "マイ書籍"
    assert info.author == "著者名"


def test_merge(tmp_path):
    from reportlab.platypus import PageBreak
    lay = layout.resolve("a4-38x35")
    texts = ["# 章1\n\n本文1[^x]。\n\n[^x]: 注1。\n",
             "# 章2\n\n本文2[^y]。\n\n[^y]: 注2。\n"]

    def make():
        b = Builder(lay)
        story = []
        for i, text in enumerate(texts):
            if i:
                story.append(PageBreak())
            story.extend(b.build(text))
            b.next_file()
        return story, b

    out = tmp_path / "book.pdf"
    pages = render_passes(str(out), make, lay)
    assert pages >= 2
    # 脚注 id が衝突せず両方登録されている
    _, b = make()
    assert len(b.footnotes) == 2


def test_cli_missing_file(tmp_path, capsys):
    from md2pdf.cli import main
    rc = main([str(tmp_path / "nope.md")])
    assert rc == 1


def test_footnote_overflow_examples(tmp_path):
    """多数の長い脚注があっても例外なく変換でき、本文ブロック下部に配置される。"""
    refs = "".join(f"参照{i}[^{i}]。" for i in range(1, 11))
    defs = "\n".join(
        f"[^{i}]: 脚注{i}の本文。少し長めの説明をここに書いて二行以上にします。さらに説明。"
        for i in range(1, 11)
    )
    out = tmp_path / "fn.pdf"
    pages = _convert(f"# 見出し\n\n{refs}\n\n{defs}\n", "a4-38x35", out)
    assert pages >= 1 and out.stat().st_size > 1000


def test_svg_marker_expansion():
    """<marker>/marker-end が実体図形に展開される（svglib は marker 非対応のため）。"""
    from md2pdf.render.flowables import _preprocess_svg
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50" '
        'viewBox="0 0 100 50">'
        '<defs><marker id="a" markerWidth="10" markerHeight="7" refX="9" refY="3.5" '
        'orient="auto"><polygon points="0 0, 10 3.5, 0 7" fill="#333"/></marker></defs>'
        '<line x1="10" y1="25" x2="90" y2="25" stroke="#333" stroke-width="2" '
        'marker-end="url(#a)"/></svg>'
    ).encode("utf-8")
    out = _preprocess_svg(svg)
    assert out is not None
    text = out.decode("utf-8")
    assert "rotate(" in text          # 矢じりの配置 <g> が生成された
    assert "marker-end" not in text   # 元の marker 参照は除去された


def test_svg_with_marker_renders(tmp_path):
    """marker 付き SVG を含む Markdown が例外なく PDF 化できる。"""
    svg = tmp_path / "arrow.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="40" '
        'viewBox="0 0 120 40">'
        '<defs><marker id="a" markerWidth="10" markerHeight="7" refX="9" refY="3.5" '
        'orient="auto"><path d="M0,0 L10,3.5 L0,7 z" fill="#333"/></marker></defs>'
        '<line x1="10" y1="20" x2="110" y2="20" stroke="#333" stroke-width="2" '
        'marker-end="url(#a)"/></svg>',
        encoding="utf-8",
    )
    md = tmp_path / "doc.md"
    md.write_text(f"# 図\n\n![矢印](arrow.svg)\n", encoding="utf-8")
    lay = layout.resolve("a4-38x35")

    def make():
        b = Builder(lay, base_dir=str(tmp_path))
        return b.build(md.read_text(encoding="utf-8")), b

    out = tmp_path / "doc.pdf"
    pages = render_passes(str(out), make, lay)
    assert pages >= 1 and out.stat().st_size > 1000


def test_leading_zenkaku_indent():
    """段落先頭の全角スペースが字下げ（1行目先頭の全角アトム）として復元される。"""
    lay = layout.resolve("a4-38x35")
    b = Builder(lay)
    story = b.build("　字下げ段落。\n\n地付き段落。")
    paras = [f for f in story if isinstance(f, JParagraph)]
    paras[0].wrap(lay.body_width, 1e9)
    paras[1].wrap(lay.body_width, 1e9)
    assert paras[0]._lines[0].atoms[0].text == "　"   # 字下げが入る
    assert paras[1]._lines[0].atoms[0].text != "　"   # 地付きは入らない


def test_pagebreak_directive(tmp_path):
    src = "# A\n\n前\n\n<!-- pagebreak -->\n\n後\n"
    out = tmp_path / "pb.pdf"
    pages = _convert(src, "a4-38x35", out)
    assert pages == 2


# --- 実原稿で見つかった不具合の回帰テスト ----------------------------------------------

def _pdf_text(path: Path) -> str:
    """PDF 全体のテキスト（空白・改行とノンブル等の数字を除去）。"""
    import re
    text = "".join(p.extract_text() or "" for p in PdfReader(str(path)).pages)
    return re.sub(r"[\s\d]", "", text)


def _kana(n: int) -> str:
    return "".join("いろはにほへとちりぬるをわかよたれそつねならむ"[i % 23] for i in range(n))


@pytest.mark.parametrize("preset", ["a4-38x35", "b5h-40x40"])
def test_page_spanning_paragraph_not_lost(tmp_path, preset):
    """短い段落 14 個の後でページをまたぐ長い段落の全文が PDF に出る（#1）。

    旧版は split() の断片が runs=[] で、ReportLab が断片に wrap() を呼び直すと
    行が作り直されて本文が丸ごと消えていた。"""
    body = "始" + _kana(1500) + "終"
    src = "\n\n".join([f"短い段落です。{_kana(5)}。" for _ in range(14)] + [body]) + "\n"
    out = tmp_path / "span.pdf"
    pages = _convert(src, preset, out)
    assert pages >= 2
    assert body in _pdf_text(out)


def test_split_fragments_survive_rewrap():
    """split() の断片は wrap() を呼び直しても（幅が変わっても）本文を失わない（#1）。"""
    lay = layout.resolve("b5h-40x40")
    text = _kana(400)
    para = JParagraph([Run(text, size=lay.font_size)], lay.leading, base_size=lay.font_size)
    para.wrap(lay.body_width, 1e9)
    first, rest = para.split(lay.body_width, lay.leading * 4)

    def joined(p):
        return "".join(a.text for line in p._lines for a in line.atoms)

    for w in (lay.body_width, lay.body_width * 0.7):
        first.wrap(w, 1e9)
        rest.wrap(w, 1e9)
        assert joined(first) + joined(rest) == text
    first.wrap(lay.body_width, 1e9)
    assert len(first._lines) == 4 and not first._lines[-1].ragged  # 続く行は両端揃え


def test_split_fragment_footnote_ids():
    """分割後の後半にある脚注参照は後半の断片に属する（#8）。"""
    lay = layout.resolve("b5h-40x40")
    src = f"{_kana(100)}[^a]{_kana(300)}[^b]\n\n[^a]: 前半の注。\n[^b]: 後半の注。\n"
    b = Builder(lay)
    para = next(f for f in b.build(src) if isinstance(f, JParagraph))
    assert para.footnote_ids == [0, 1]
    para.wrap(lay.body_width, 1e9)
    first, rest = para.split(lay.body_width, lay.leading * 4)
    assert first.footnote_ids == [0]
    assert rest.footnote_ids == [1]


def _heavy_footnote_src(n_paras: int = 24) -> str:
    paras, defs = [], []
    k = 0
    for i in range(n_paras):
        refs = []
        for _ in range(1 + i % 3):
            k += 1
            refs.append(f"[^{k}]")
            defs.append(f"[^{k}]: 脚注{k}。" + _kana(40 + (k * 37) % 160))
        cut = 60 + (i * 53) % 200
        body = _kana(320 + (i * 71) % 300)
        paras.append(body[:cut] + refs[0] + body[cut:] + "".join(refs[1:]) + "。")
    return "# 見出し\n\n" + "\n\n".join(paras) + "\n\n" + "\n".join(defs) + "\n"


@pytest.mark.parametrize("preset", ["a4-38x35", "b5h-40x40"])
def test_footnotes_single_pass_no_overlap_no_overreserve(tmp_path, preset):
    """脚注の多い文書で、各ページの予約＝必要高、脚注と本文が重ならない、警告なし（#2 #3）。"""
    lay = layout.resolve(preset)
    src = _heavy_footnote_src()
    stats: dict = {}

    def make():
        b = Builder(lay)
        return b.build(src), b

    out = tmp_path / "fn.pdf"
    pages = render_passes(str(out), make, lay, stats=stats)
    assert pages >= 3
    assert stats["passes"] == 1
    assert stats["warnings"] == []
    fn_pages = 0
    for page, s in stats["pages"].items():
        assert not s["overlap"], page
        assert abs(s["reserve"] - s["required"]) <= lay.leading, page
        if s["fn_top"] is not None:
            fn_pages += 1
            assert s["body_bottom"] >= s["fn_top"], page
    assert fn_pages >= 3
    n_fn = src.count("\n[^")
    assert _pdf_text(out).count("脚注。") == n_fn  # 全脚注が 1 回ずつ出力されている


def test_footnotes_in_list_and_blockquote_are_drawn(tmp_path):
    """箇条書き・引用の中の脚注参照も脚注として配置される。"""
    src = ("- 項目[^a]です。\n\n> 引用[^b]です。\n\n"
           "[^a]: りすとのちゅう。\n[^b]: いんようのちゅう。\n")
    out = tmp_path / "nested.pdf"
    _convert(src, "a4-38x35", out)
    text = _pdf_text(out)
    assert "りすとのちゅう。" in text
    assert "いんようのちゅう。" in text


def test_long_url_wraps_within_line():
    """行幅を超える URL は区切り文字の後で折り返し、ハイフンを足さない（#5）。"""
    lay = layout.resolve("b5h-40x40")
    url = ("https://docs.example.com/product/latest/developerguide/"
           "managed-rule-groups-use-case-and-something-very-very-long.html")
    b = Builder(lay)
    b.build(f"本文[^1]。\n\n[^1]: 脚注A {url}\n")
    fn = b.styles.footnote
    para = JParagraph(b.footnotes[0][1], fn.leading, base_size=fn.size)
    para.wrap(lay.body_width, 1e9)
    assert len(para._lines) >= 2
    assert all(line.width <= lay.body_width + 0.2 for line in para._lines)
    joined = "".join(a.text for line in para._lines for a in line.atoms)
    assert joined == f"脚注A {url}"


def test_long_word_without_break_chars_split_per_char():
    lay = layout.resolve("b5h-40x40")
    word = "x" * 300
    para = JParagraph([Run(word, size=lay.font_size)], lay.leading, base_size=lay.font_size)
    para.wrap(lay.body_width, 1e9)
    assert all(line.width <= lay.body_width + 0.2 for line in para._lines)
    assert "".join(a.text for line in para._lines for a in line.atoms) == word


def test_consecutive_footnote_refs_are_separated():
    """[^1][^2] は上付きの「1,2」になり「12」と読めない（#6）。"""
    lay = layout.resolve("a4-38x35")
    para = next(f for f in Builder(lay).build("本文です[^1][^2]。\n\n[^1]: A\n[^2]: B\n")
                if isinstance(f, JParagraph))
    sup = "".join(r.text for r in para.runs if r.sup)
    assert sup == "1,2"


def test_cli_merge_missing_input_fails(tmp_path):
    """--merge で入力が見つからなければ変換せず終了コード 1（#4）。"""
    from md2pdf.cli import main
    ok = tmp_path / "ok.md"
    ok.write_text("# A\n\n本文。\n", encoding="utf-8")
    out = tmp_path / "x.pdf"
    assert main(["--merge", "-o", str(out), str(tmp_path / "nope.md")]) == 1
    assert main(["--merge", "-o", str(out), str(tmp_path / "nope.md"), str(ok)]) == 1
    assert not out.exists()
    assert main(["--merge", "-o", str(out), str(ok)]) == 0
    assert out.exists()


def test_cli_output_without_merge(tmp_path):
    """--merge なしの -o: 入力 1 件ならそこへ出力、複数ならエラー（#7）。"""
    from md2pdf.cli import main
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    for p in (a, b):
        p.write_text("本文。\n", encoding="utf-8")
    out = tmp_path / "sub.pdf"
    assert main(["-o", str(out), str(a)]) == 0
    assert out.exists() and not a.with_suffix(".pdf").exists()
    with pytest.raises(SystemExit) as e:
        main(["-o", str(out), str(a), str(b)])
    assert e.value.code == 2
