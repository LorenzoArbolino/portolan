from pipeline.documents import document_text, focus
from pipeline.fetch import Fetched


def test_short_text_untouched():
    assert focus("short", ["citral"]) == "short"


def test_long_text_keeps_matching_pages_with_neighbours():
    pages = [f"filler page {i} " + "x" * 5000 for i in range(60)]
    pages[40] = "Installed capacity of citral: 30 MT/Month " + "y" * 3000
    out = focus("\f".join(pages), ["citral"], max_chars=20_000)
    assert "[page 41]" in out and "citral" in out
    assert "[page 40]" in out and "[page 42]" in out
    assert "[page 10]" not in out and len(out) <= 21_000


def test_broken_pdf_fails_the_job_not_the_run():
    class Cut:
        def get(self, url):
            return Fetched(url=url, ok=True, content=b"%PDF-1.7 truncated", content_type="application/pdf")

    assert document_text("https://example.com/a.pdf", ["citral"], Cut()) is None
