from __future__ import annotations

from contract_extraction.indexing.chunking import chunk_page, normalize, pack, page_section, search_text, table_rows, units

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


# The layout a PDF converter produces for a cover-page parties block: a key/value table whose first
# row is marked as the header and whose role lines continue the row above.
PARTIES = """## **Parties:**

|Name|**Acme Rail Pty Ltd ACN 111 111 111**|
|---|---|
||(**Acme**)|
|Address|1 Sample Street, Exampleton NSW 2000|
|Name|**Widget Services Pty Ltd ACN 222 222 222**|
||**(Service Provider)**|"""


def test_search_text_turns_a_key_value_table_into_rows():
    assert search_text(PARTIES) == (
        "Parties\n"
        "Name: Acme Rail Pty Ltd ACN 111 111 111 (Acme)\n"
        "Address: 1 Sample Street, Exampleton NSW 2000\n"
        "Name: Widget Services Pty Ltd ACN 222 222 222 (Service Provider)")


def test_table_with_named_columns_labels_each_value():
    assert table_rows(["| Item | Rate | Cap |", "|---|---|---|", "| Fees | 5% | $10 |", "| Late | | 2% |"]) == [
        "Item: Fees; Rate: 5%; Cap: $10", "Item: Late; Cap: 2%"]


def test_form_table_lists_cells_and_drops_empty_columns():
    rows = ["|**#**|**ITEM**|**DESCRIPTION**|||", "|---|---|---|---|---|",
            "|||Representative:<br>Jane Sample||Email: jane@example.com|", "|**2**|**Commencement**|The date signed|||"]
    assert table_rows(rows) == ["#; ITEM; DESCRIPTION", "Representative: Jane Sample; Email: jane@example.com",
                                "2; Commencement; The date signed"]


def test_search_text_removes_markdown_and_puts_the_section_first():
    assert search_text("- **Pay** within `30` days<br>of invoice", "Payment") == "Payment\nPay within 30 days of invoice"


def test_chunks_carry_their_section():
    text = f"# Payment\n\n{SENTENCES}"
    chunks = chunk_page(1, text, "md", size=300, overlap=0)
    assert chunks[0].headings == "Payment" and chunks[0].search_text.startswith("Payment\nSentence number 0")
    assert all(c.headings == "Payment" and c.search_text.startswith("Payment\nSentence") for c in chunks[1:])
    assert all(c.text == normalize(text, "md")[c.char_start:c.char_end] for c in chunks)


def test_section_continues_onto_the_next_page():
    section = page_section("# Term\n\nThe term is two years.", "md", None)
    assert section == "Term"
    [chunk] = chunk_page(2, "It renews automatically.", "md", 300, 0, section)
    assert chunk.search_text == "Term\nIt renews automatically." and chunk.headings == "Term"
    assert page_section("No headings here.", "md", section) == "Term"


def test_heading_never_ends_a_chunk():
    text = "First paragraph sentence.\n\n## Next section\n\n" + "Body text goes on here. " * 20
    chunks = chunk_page(1, text, "md", size=60, overlap=0)
    assert not any(c.text.endswith("Next section") for c in chunks)
    assert any(c.text.startswith("## Next section") for c in chunks)
