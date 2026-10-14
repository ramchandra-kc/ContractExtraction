from __future__ import annotations

from contract_extraction.decomposition.headers_footers import PageText, normalize, strip_headers_footers


def _page(i: int, n: int) -> PageText:
    # Body lines differ in letters, not just digits (digits are normalised away).
    body = "\n".join(f"Clause {'abc'[i - 1]}{chr(97 + k)} body text." for k in range(8))
    return PageText(text=f"# ACME Agreement\n{body}\nPage {i} of {n}")


def test_normalize_matches_page_numbers():
    assert normalize("## Page 3 of 10 ") == normalize("Page 4 of 10")


def test_repeating_edges_are_moved():
    pages = strip_headers_footers([_page(i, 3) for i in range(1, 4)])
    for i, p in enumerate(pages, start=1):
        assert p.header == "# ACME Agreement"
        assert p.footer == f"Page {i} of 3"
        assert "ACME Agreement" not in p.text and "Page" not in p.text
        assert f"Clause {'abc'[i - 1]}a body text." in p.text


def test_single_page_is_untouched():
    page = _page(1, 1)
    original = page.text
    strip_headers_footers([page])
    assert page.text == original and page.header is None and page.footer is None


def test_matching_line_mid_page_is_kept():
    def lines(page: str, n: int) -> list[str]:
        return [f"text {page} {chr(97 + k)}" for k in range(n)]

    pages = [PageText(text="\n".join(["Confidential", *lines(p, 3), "Confidential", *lines(p + p, 13)]))
             for p in ("a", "b", "c")]
    strip_headers_footers(pages)
    for p in pages:
        assert p.header == "Confidential"
        assert p.text.count("Confidential") == 1
