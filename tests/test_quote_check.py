from pathlib import Path

import pytest

from pipeline.validators.quote_check import check_quote, check_quote_in_text, extract_text, normalise
from tests.pdfgen import make_pdf

FX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def html_text():
    return extract_text((FX / "press_release.html").read_bytes(), "text/html")


@pytest.fixture(scope="module")
def zh_text():
    return extract_text((FX / "eia_notice_zh.html").read_bytes(), "text/html")


@pytest.fixture
def pdf_path(tmp_path):
    p = tmp_path / "report.pdf"
    p.write_bytes(
        make_pdf(
            [
                "Annual Report 2023 (test fixture, fictitious company)",
                "Our Exampletown site produced vitamin A acetate throughout the year.",
                "Installed capacity: 5,000 tonnes per annum of vitamin A acetate.",
            ]
        )
    )
    return p


# --- HTML -----------------------------------------------------------------------------------------


def test_html_known_quote_passes(html_text):
    assert (
        check_quote_in_text("The plant has an annual capacity of 48,000 tonnes", html_text).status == "pass"
    )


def test_html_quote_in_table_passes(html_text):
    assert check_quote_in_text("Citral 48,000 2024", html_text).status == "pass"


def test_html_quote_with_ellipsis_passes(html_text):
    q = "successful start-up of its new citral plant … annual capacity of 48,000 tonnes"
    assert check_quote_in_text(q, html_text).status == "pass"


def test_html_small_typo_still_passes(html_text):
    r = check_quote_in_text("The plant has an anual capacity of 48,000 tonnes", html_text)
    assert r.status == "pass" and 0.92 <= r.score < 1


def test_altered_number_fails(html_text):
    r = check_quote_in_text("The plant has an annual capacity of 40,000 tonnes", html_text)
    assert r.status == "fail"
    assert "40000" in r.reason


def test_altered_words_fail(html_text):
    q = "The plant has been closed permanently and will be demolished next year"
    assert check_quote_in_text(q, html_text).status == "fail"


def test_curly_quotes_and_dashes_normalised(html_text):
    assert check_quote_in_text("uses the company's own isoprenol route", html_text).status == "pass"
    assert normalise("start–up “X”") == 'start-up "x"'


# --- PDF ------------------------------------------------------------------------------------------


def test_pdf_known_quote_passes(pdf_path):
    r = check_quote("Installed capacity: 5,000 tonnes per annum of vitamin A acetate", document=pdf_path)
    assert r.status == "pass"
    assert r.source == "file" and len(r.content_sha256) == 64


def test_pdf_altered_quote_fails(pdf_path):
    assert check_quote("Installed capacity: 6,000 tonnes per annum", document=pdf_path).status == "fail"


def test_pdf_without_text_layer_is_manual(tmp_path):
    p = tmp_path / "scan.pdf"
    p.write_bytes(make_pdf([]))
    assert check_quote("Installed capacity: 5,000 tonnes", document=p).status == "manual"


def test_pdf_pypdf_fallback(pdf_path, monkeypatch):
    import pipeline.validators.quote_check as qc

    monkeypatch.setattr(qc.shutil, "which", lambda _: None)
    text = qc.pdf_to_text(pdf_path.read_bytes())
    assert "5,000 tonnes" in text


# --- Chinese --------------------------------------------------------------------------------------


def test_chinese_quote_passes(zh_text):
    q = "示例化工有限公司拟在示例市化工园区建设年产4.8万吨柠檬醛项目"
    assert check_quote_in_text(q, zh_text).status == "pass"


def test_chinese_quote_with_pdf_style_spacing_passes(zh_text):
    assert check_quote_in_text("年产 4.8 万吨 柠 檬 醛 项目", zh_text).status == "pass"


def test_chinese_altered_number_fails(zh_text):
    q = "示例化工有限公司拟在示例市化工园区建设年产6.8万吨柠檬醛项目"
    assert check_quote_in_text(q, zh_text).status == "fail"


def test_fullwidth_digits_normalised(zh_text):
    assert check_quote_in_text("年产４.８万吨柠檬醛项目", zh_text).status == "pass"


# --- plain-text table (Indian EC style) -----------------------------------------------------------


def test_ec_table_row():
    text = (FX / "ec_letter.txt").read_text(encoding="utf-8")
    assert check_quote_in_text("Dihydromyrcenol 150 250 400", text).status == "pass"
    assert check_quote_in_text("Dihydromyrcenol 150 250 450", text).status == "fail"


# --- fetching (offline: fake fetcher) -------------------------------------------------------------


class _FakeFetched:
    def __init__(self, ok, content=b"", reason=None):
        self.ok, self.content, self.reason = ok, content, reason
        self.content_type, self.sha256, self.status = "text/html", "0" * 64, 200


class _FakeFetcher:
    def __init__(self, pages):
        self.pages = pages

    def get(self, url):
        return self.pages.get(url, _FakeFetched(False, reason="HTTP 404"))


def test_unreachable_without_archive():
    r = check_quote("anything", url="https://example.invalid/x", fetcher=_FakeFetcher({}), use_archive=False)
    assert r.status == "unreachable"


def test_url_fetch_pass():
    page = (FX / "press_release.html").read_bytes()
    f = _FakeFetcher({"https://example.com/news": _FakeFetched(True, page)})
    r = check_quote("annual capacity of 48,000 tonnes", url="https://example.com/news", fetcher=f)
    assert r.status == "pass" and r.source == "url"


def test_fetcher_retries_transient_errors(tmp_path):
    import httpx

    from pipeline.fetch import Fetcher

    calls = {"n": 0}

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("Connection reset by peer")
        return httpx.Response(200, html="<p>annual capacity of 48,000 tonnes</p>")

    f = Fetcher(
        cache_dir=tmp_path, min_interval=0, client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    got = f.get("https://example.com/news")
    assert got.ok and calls["n"] == 2
    assert not f.get("https://example.com/private/x").ok  # robots.txt respected
    assert f.get("https://example.com/news").from_cache


def test_gbk_page_declared_in_meta_decodes():
    html = (
        '<html><head><meta http-equiv="Content-Type" content="text/html; charset=gb2312"></head>'
        "<body><p>前者位于昌海生物工业园的VE年产能已达到2万吨；后者VE产能也已达到12000吨/年。</p></body></html>"
    ).encode("gbk")
    text = extract_text(html, "text/html")
    assert "昌海生物工业园" in text
    assert check_quote_in_text("位于昌海生物工业园的VE年产能已达到2万吨", text).status == "pass"


def test_header_charset_wins():
    html = "<html><body><p>Kapazität von 40.000 Jahrestonnen</p></body></html>".encode("latin-1")
    assert "Kapazität" in extract_text(html, "text/html; charset=ISO-8859-1")


@pytest.mark.skipif(not __import__("shutil").which("tesseract"), reason="tesseract not installed")
def test_scanned_pdf_is_ocred_and_flagged(tmp_path):
    from tests.pdfgen import make_scanned_pdf

    data = make_scanned_pdf(
        ["Environmental Clearance (test fixture)", "Distilled Turpentine 00 215 215 MT/Month"]
    )
    p = tmp_path / "scan.pdf"
    p.write_bytes(data)
    r = check_quote("Distilled Turpentine 00 215 215", document=p)
    assert r.status == "pass" and "ocr" in r.details
