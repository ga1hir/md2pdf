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


@pytest.mark.parametrize("preset", ["a4-38x35", "b5h-40x40"])
def test_page_spanning_code_block_not_lost(tmp_path, preset):
    """ページ下部から始まり、ページをまたぐコードブロックの全行が PDF に出る（GitHub #1）。

    旧版は CodeBlock.split() の断片が lines=[] で、wrap() の呼び直しで中身が消えていた。"""
    import re
    lay = layout.resolve(preset)
    body = "\n\n".join("　" + _kana(lay.chars_per_line * 2) for _ in range(lay.lines_per_page // 2 - 4))
    code = "\n".join(f"codeline{chr(65 + i % 26)}{chr(97 + i // 26)}" for i in range(lay.lines_per_page))
    src = f"{body}\n\n```text\n{code}\n```\n\n　後続の段落。\n"
    out = tmp_path / "code.pdf"
    pages = _convert(src, preset, out)
    assert pages >= 2
    text = re.sub(r"[·⏎]", "", _pdf_text(out))
    for i in range(lay.lines_per_page):
        assert f"codeline{chr(65 + i % 26)}{chr(97 + i // 26)}" in text
    assert "後続の段落" in text


def test_code_block_split_fragments_survive_rewrap():
    """CodeBlock.split() の断片は wrap() を呼び直しても（幅が変わっても）行を失わない（GitHub #1）。"""
    from md2pdf import config, fontreg
    from md2pdf.render.flowables import CodeBlock
    fontreg.register_fonts()
    lay = layout.resolve("b5h-40x40")
    lines = [[Run(f"line {i:02d}: sample output text", config.FONT_MONO, lay.font_size)]
             for i in range(1, 26)]
    cb = CodeBlock(lines, lay.font_size, lay.leading)
    cb.wrap(lay.body_width, 1e9)
    head, tail = cb.split(lay.body_width, lay.leading * 10)

    def joined(b):
        return "".join(r.text for line in b._visual for r in line)

    expected = "".join(r.text for line in lines for r in line)
    for w in (lay.body_width, lay.body_width * 0.4):
        head.wrap(w, 1e9)
        tail.wrap(w, 1e9)
        assert joined(head) + joined(tail) == expected
    head.wrap(lay.body_width, 1e9)
    tail.wrap(lay.body_width, 1e9)
    assert (len(head._visual), len(tail._visual)) == (9, 16)


def test_code_block_split_keeps_outer_spacing():
    """分割した前半は元の spaceBefore、後半は元の spaceAfter を持つ（GitHub #2）。"""
    from md2pdf import config, fontreg
    from md2pdf.render.flowables import CodeBlock
    fontreg.register_fonts()
    lay = layout.resolve("b5h-40x40")
    lines = [[Run(f"line {i:02d}", config.FONT_MONO, lay.font_size)] for i in range(25)]
    cb = CodeBlock(lines, lay.font_size, lay.leading)
    cb.spaceBefore = cb.spaceAfter = lay.leading * 0.3
    cb.wrap(lay.body_width, 1e9)
    head, tail = cb.split(lay.body_width, lay.leading * 10)
    assert (head.spaceBefore, head.spaceAfter) == (cb.spaceBefore, 0)
    assert (tail.spaceBefore, tail.spaceAfter) == (0, cb.spaceAfter)


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


def _alert_box(src: str):
    from md2pdf.render.flowables import _Container
    story = Builder(layout.resolve("a4-38x35")).build(src)
    assert story and isinstance(story[0], _Container)
    return story[0]


@pytest.mark.parametrize("marker,label", [
    ("NOTE", "補足"), ("TIP", "ヒント"), ("IMPORTANT", "重要"),
    ("WARNING", "警告"), ("CAUTION", "注意"), ("tip", "ヒント"),
])
def test_gfm_alert_types(tmp_path, marker, label):
    """GFM アラートは種類ラベル付きで組まれ、[!…] マーカーは本文に残らない。"""
    src = f"> [!{marker}]\n> アラート本文です。\n"
    box = _alert_box(src)
    assert box.kind == marker.lower()
    out = tmp_path / "alert.pdf"
    _convert(src, "a4-38x35", out)
    text = _pdf_text(out)
    assert label in text and "アラート本文です。" in text
    assert "[!" not in text


def test_gfm_alert_blank_line_after_marker():
    """マーカー行の後に空行を挟んだ段落・後続ブロックもアラート本文になる。"""
    box = _alert_box("> [!NOTE]\n>\n> 段落です。\n>\n> - 項目\n")
    assert box.kind == "note"
    assert len(box.children) == 3  # タイトル・段落・リスト項目


@pytest.mark.parametrize("src", [
    "> [!WARNING] 同じ行の本文\n",
    "> [!FOO]\n> 未知の種類\n",
    "> [!NOTE]\n",
])
def test_gfm_alert_not_matched(tmp_path, src):
    """同一行本文・未知の種類・本文なしは通常の引用で、マーカーが文字として残る。"""
    box = _alert_box(src)
    assert not hasattr(box, "kind")
    out = tmp_path / "quote.pdf"
    _convert(src, "a4-38x35", out)
    assert "[!" in _pdf_text(out)


def test_gfm_alert_zenkaku_indent():
    """マーカー次行の全角スペース字下げが保持される。"""
    box = _alert_box("> [!NOTE]\n> 　字下げした本文。\n")
    para = box.children[1]
    assert isinstance(para, JParagraph)
    text = "".join(r.text for r in para.runs)
    assert text.startswith("　字") and not text.startswith("　　")


def test_gfm_alert_title_not_orphaned():
    """ページ末にタイトル行しか入らない場合は分割せず丸ごと次ページへ送る。"""
    lay = layout.resolve("a4-38x35")
    box = _alert_box("> [!NOTE]\n> " + _kana(38 * 5) + "\n")
    w = lay.body_width
    box.wrap(w, lay.body_height)
    title_only = box.pad * 2 + lay.leading + 1.0
    assert box.split(w, title_only) == []
    parts = box.split(w, title_only + lay.leading * 2)
    assert len(parts) == 2 and len(parts[0].children) == 2
    assert parts[0].keep_head == 1 and parts[1].keep_head == 0


def test_gfm_alert_page_spanning_and_footnote(tmp_path):
    """複数ページに跨るアラートの本文が欠落せず、中の脚注も描画される。"""
    body = _kana(38 * 50)
    src = f"> [!WARNING]\n> {body}[^w]\n\n[^w]: あらーとのちゅう。\n"
    out = tmp_path / "long.pdf"
    pages = _convert(src, "a4-38x35", out)
    assert pages >= 2
    text = _pdf_text(out)
    assert body in text
    assert "あらーとのちゅう。" in text


def _para_runs(src: str, preset: str = "a4-38x35") -> list[list[Run]]:
    lay = layout.resolve(preset)
    return [f.runs for f in Builder(lay).build(src) if isinstance(f, JParagraph)]


def test_u_tag_underlines_runs():
    """<u>…</u> の間だけ下線が付き、タグ文字は本文に漏れない。"""
    (runs,) = _para_runs("前<u>下線</u>後\n")
    assert "".join(r.text for r in runs) == "前下線後"
    assert [(r.text, r.underline) for r in runs] == [
        ("前", False), ("下線", True), ("後", False)]


def test_u_tag_with_bold_ruby_code_link():
    (runs,) = _para_runs("<u>**太字**と{漢字|かんじ}と`code`と[リンク](https://e.x)</u>外\n")
    by_text = {r.text: r for r in runs}
    assert by_text["太字"].underline and by_text["太字"].font != by_text["と"].font
    assert by_text["漢字"].underline and by_text["漢字"].ruby == "かんじ"
    assert by_text["code"].underline and by_text["code"].bg is not None
    assert by_text["リンク"].underline and by_text["リンク"].link == "https://e.x"
    assert not by_text["外"].underline


@pytest.mark.parametrize("src", ['<U>大</U>\n', '<u class="x">大</u>\n', '<u >大</u >\n'])
def test_u_tag_case_and_attrs(src):
    (runs,) = _para_runs(src)
    assert [(r.text, r.underline) for r in runs] == [("大", True)]


def test_u_tag_unclosed_does_not_leak():
    """閉じ忘れの <u> は段落末で打ち切る。余分な </u> は無視する。"""
    a, b = _para_runs("<u>開いたまま\n\n次の段落</u>と</u>余分\n")
    assert all(r.underline for r in a if r.text)
    assert not any(r.underline for r in b)
    assert "".join(r.text for r in b) == "次の段落と余分"


def test_38x35_underline_grid_exact():
    """test_38x35.md の下線テスト: 38 字 × 35 行のまま、各行の下線字数が想定どおり。"""
    src = (ASSETS / "test_38x35.md").read_text(encoding="utf-8")
    i = src.find("-->", src.find("## 下線テスト")) + len("-->")
    lay = layout.resolve("a4-38x35")
    para = next(f for f in Builder(lay).build(src[i:]) if isinstance(f, JParagraph))
    para.wrap(lay.body_width, 1e9)
    chars = [sum(len(a.text) for a in line.atoms) for line in para._lines]
    under = [sum(len(a.text) for a in line.atoms if a.run.underline)
             for line in para._lines]
    assert len(para._lines) == 35
    assert chars == [38] * 35
    # 1 全体 / 5 複数区間 / 8 ルビ / 10 入れ子 / 13 余分な </u> / 14〜16 行またぎ / 17〜 16 字ずつ
    assert under == [38, 10, 10, 10, 16, 10, 6, 3, 10, 12, 10, 10, 0, 8, 38, 8] + [16] * 19


def test_u_tag_not_confused_with_other_tags():
    (runs,) = _para_runs("<ul>a</ul>と<b>b</b>\n")
    assert not any(r.underline for r in runs)


def test_u_tag_in_html_block():
    (runs,) = _para_runs("<u>\n下線ブロック\n</u>\n")
    assert [(r.text, r.underline) for r in runs] == [("下線ブロック", True)]
    (runs,) = _para_runs("<p>前<u>中</u>後</p>\n")
    assert [(r.text, r.underline) for r in runs] == [
        ("前", False), ("中", True), ("後", False)]


def test_u_tag_keeps_grid():
    """下線は字幅を変えない: 38 字の段落は 1 行 38 字のまま。"""
    lay = layout.resolve("a4-38x35")
    text = "あ" * 10 + "<u>" + "い" * 18 + "</u>" + "う" * 10
    para = next(f for f in Builder(lay).build(text + "\n") if isinstance(f, JParagraph))
    para.wrap(lay.body_width, 1e9)
    assert [len(line.atoms) for line in para._lines] == [38]


class _LineRecorder:
    """JParagraph.draw が引く線だけを記録する偽キャンバス。"""

    def __init__(self):
        self.lines = []

    def line(self, x1, y1, x2, y2):
        self.lines.append((x1, x2))

    def __getattr__(self, name):
        return lambda *a, **k: None


def test_u_underline_continuous_when_justified():
    """両端揃えで字間が空いても、下線区間は途切れずにつながる。"""
    lay = layout.resolve("a4-38x35")
    # 2 行目に送られる 1 行目は ragged でないので字間 extra が入る
    text = "<u>" + "あ" * 30 + "abc " * 6 + "</u>"
    para = next(f for f in Builder(lay).build(text + "\n") if isinstance(f, JParagraph))
    para.wrap(lay.body_width, 1e9)
    assert len(para._lines) >= 2
    para.canv = _LineRecorder()
    para._draw_line(para._lines[0], 0.0)
    segs = para.canv.lines
    assert len(segs) == len(para._lines[0].atoms)
    for (_, end), (start, _) in zip(segs, segs[1:]):
        assert abs(end - start) < 1e-6


def _three_pages() -> str:
    return "\n\n".join(f"段落{i}。" + "本文" * 300 for i in range(6)) + "\n"


def test_start_page_nombre_and_labels(tmp_path):
    """--start-page: ノンブルと PDF ページラベルが指定番号から始まり、戻り値は物理ページ数。"""
    out = tmp_path / "s.pdf"
    pages = _convert(_three_pages(), "a4-38x35", out, start_page=21)
    reader = PdfReader(str(out))
    assert pages == len(reader.pages) >= 2
    assert list(reader.page_labels) == [str(21 + i) for i in range(pages)]
    for i, page in enumerate(reader.pages):
        last = page.extract_text().strip().splitlines()[-1]
        assert last.strip() == str(21 + i)


def test_start_page_default_has_no_labels(tmp_path):
    """既定（1 始まり）では /PageLabels を付けず、従来どおりの出力になる。"""
    out = tmp_path / "d.pdf"
    _convert(_three_pages(), "a4-38x35", out)
    reader = PdfReader(str(out))
    assert "/PageLabels" not in reader.trailer["/Root"]
    assert reader.pages[1].extract_text().strip().splitlines()[-1].strip() == "2"


def test_cli_start_page_chains(tmp_path):
    """--merge なしの複数入力では 2 件目以降が前ファイルに続く番号から始まる。"""
    from md2pdf.cli import main
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text(_three_pages(), encoding="utf-8")
    b.write_text("本文。\n", encoding="utf-8")
    assert main(["--start-page", "5", str(a), str(b)]) == 0
    n = _pages(a.with_suffix(".pdf"))
    assert PdfReader(str(a.with_suffix(".pdf"))).page_labels[0] == "5"
    assert PdfReader(str(b.with_suffix(".pdf"))).page_labels[0] == str(5 + n)


def test_cli_without_start_page_does_not_chain(tmp_path):
    """--start-page なしの複数入力は従来どおり各ファイル 1 始まり。"""
    from md2pdf.cli import main
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text(_three_pages(), encoding="utf-8")
    b.write_text("本文。\n", encoding="utf-8")
    assert main([str(a), str(b)]) == 0
    text = PdfReader(str(b.with_suffix(".pdf"))).pages[0].extract_text()
    assert text.strip().splitlines()[-1].strip() == "1"


def test_cli_start_page_merge(tmp_path):
    """--merge --start-page: 結合 PDF 全体の通し番号が指定番号から始まる。"""
    from md2pdf.cli import main
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    for p in (a, b):
        p.write_text("本文。\n", encoding="utf-8")
    out = tmp_path / "m.pdf"
    assert main(["--merge", "--start-page", "3", "-o", str(out), str(a), str(b)]) == 0
    assert list(PdfReader(str(out)).page_labels) == ["3", "4"]


def test_cli_start_page_invalid(tmp_path):
    """--start-page は 1 以上。"""
    from md2pdf.cli import main
    a = tmp_path / "a.md"
    a.write_text("本文。\n", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        main(["--start-page", "0", str(a)])
    assert e.value.code == 2
