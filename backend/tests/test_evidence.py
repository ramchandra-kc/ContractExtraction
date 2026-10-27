"""Evidence recall: quotes from label notes, fragments, and fuzzy matching against chunk text."""

from __future__ import annotations

from contract_extraction.evidence import Matcher, covered, fragments, quote_from_notes, tokens
from contract_extraction.labels import notes_for

CHUNK = ("## 6. Payment\n\nInvoices are **payable** within thirty (30) days of receipt.\n"
         "Late payments attract interest of 2% per month.")


def test_quote_round_trips_through_label_notes():
    entry = {"confidence": "high", "location": "§ 6", "evidence": "Invoices are payable · within 30 days", "note": "x"}
    assert quote_from_notes(notes_for(entry, "cowork")) == "Invoices are payable · within 30 days"
    assert quote_from_notes(notes_for({"confidence": "high", "evidence": ""}, "cowork")) is None
    assert quote_from_notes(None) is None and quote_from_notes("edited by hand") is None


def test_fragments_split_on_ellipses_and_drop_short_ones():
    assert fragments("the “Effective Date” … terminate at the end of the term ... 30 days") == [
        ("the", "effective", "date"), ("terminate", "at", "the", "end", "of", "the", "term")]
    assert fragments("30 days") == [("30", "days")], "kept when nothing longer is left"


def test_covered_ignores_markdown_case_and_small_ocr_noise():
    chunk = tokens(CHUNK)
    assert covered(tokens("invoices are payable within thirty (30) days of receipt"), chunk)
    assert covered(tokens("Invoices are payab~e within thirty (30) days of receipt"), chunk), "one garbled word"
    assert not covered(tokens("invoices are payable within sixty days of the end of the month"), chunk)


def test_matcher_reports_any_all_rank_and_indexed():
    matcher = Matcher()
    matcher.add_chunks({"a": "The parties are Acme Pty Ltd and Contoso Limited.", "b": CHUNK, "c": "Force majeure applies."})
    quote = "between Acme Pty Ltd and Contoso Limited … Late payments attract interest of 2% per month"

    full = matcher.match(quote, [(2, "a"), (1, "b")], ["a", "b", "c"])
    assert (full.fragments, full.any, full.all, full.rank, full.indexed) == (2, True, True, 1, True)

    part = matcher.match(quote, [(1, "c"), (2, "b")], ["a", "b", "c"])
    assert (part.any, part.all, part.rank) == (True, False, 2)

    lost = matcher.match("a clause about liquidated damages for late delivery", [(1, "a")], ["a", "b", "c"])
    assert (lost.any, lost.rank, lost.indexed) == (False, None, False), "not in any chunk: lost before retrieval"
    assert matcher.match("…", [], None) is None
