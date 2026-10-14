from __future__ import annotations

from contract_extraction.indexing.chunking import chunk_page, normalize, pack, units

SENTENCES = " ".join(f"Sentence number {i} explains a contract term in some detail." for i in range(60))


def test_offsets_are_exact():
    text = f"# Title\n\n{SENTENCES}\n\n- item one\n- item two"
    norm = normalize(text, "md")
    for c in chunk_page(1, text, "md", size=300, overlap=60):
        assert norm[c.char_start:c.char_end] == c.text
        assert len(c.text) <= 300


def test_overlap_shares_whole_sentences():
    chunks = chunk_page(1, SENTENCES, "md", size=300, overlap=80)
    assert len(chunks) > 3
    for a, b in zip(chunks, chunks[1:]):
        assert b.char_start < a.char_end, "neighbours overlap"
        assert a.char_end - b.char_start <= 80
        assert b.text.startswith("Sentence number")


def test_no_overlap():
    chunks = chunk_page(1, SENTENCES, "md", size=300, overlap=0)
    assert all(b.char_start >= a.char_end for a, b in zip(chunks, chunks[1:]))


def test_long_unit_is_windowed():
    word = "x" * 1000
    chunks = chunk_page(2, word, "md", size=300, overlap=50)
    assert [len(c.text) for c in chunks][:3] == [300, 300, 300]
    assert chunks[1].char_start == 250
    assert chunks[-1].char_end == 1000
    assert all(c.page_number == 2 for c in chunks)


def test_markdown_structures_stay_whole():
    text = "Intro sentence one. Intro sentence two.\n\n| a | b |\n|---|---|\n| 1 | 2 |"
    spans = units(normalize(text, "md"), "md")
    norm = normalize(text, "md")
    assert [norm[s:e] for s, e in spans] == ["Intro sentence one.", "Intro sentence two.", "| a | b |\n|---|---|\n| 1 | 2 |"]


def test_html_is_stripped():
    text = "<section><h2>Payment</h2><p>Pay within 30 days &amp; on time.</p><table><tr><td>A</td><td>B</td></tr></table></section>"
    norm = normalize(text, "html")
    assert "<" not in norm and "Pay within 30 days & on time." in norm and "A" in norm


def test_empty_page():
    assert chunk_page(1, "   \n\n ", "md", 100, 10) == []
    assert pack([], 100, 10) == []
