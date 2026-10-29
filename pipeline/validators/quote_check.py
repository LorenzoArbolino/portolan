"""`quote_check` validator: does the quote really appear in the document at the URL?

Deterministic, no LLM. Document → text (HTML: trafilatura + plain text; PDF: pdftotext, else pypdf) →
normalise → fuzzy match (rapidfuzz, ≥ 0.92). On top of the fuzzy score, every number in the quote must
appear verbatim near the match: a quote with one digit changed fails even if it is 99% similar.

Results: `pass`, `fail` (text read, quote not there), `unreachable` (fetch failed, archive too),
`manual` (no machine-readable text, e.g. a scanned PDF before OCR)."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from rapidfuzz import fuzz

THRESHOLD = 0.92
MIN_TEXT_CHARS = 40  # below this a document is treated as having no text layer (scanned)

Status = Literal["pass", "fail", "unreachable", "manual"]


@dataclass
class QuoteResult:
    status: Status
    score: float = 0.0
    reason: str | None = None
    content_sha256: str | None = None
    source: str | None = None  # "url", "archive" or "file"
    details: list[str] = field(default_factory=list)


# --- text extraction ------------------------------------------------------------------------------


def _is_pdf(content: bytes, content_type: str) -> bool:
    return content[:5] == b"%PDF-" or "pdf" in content_type.lower()


def _is_html(content: bytes, content_type: str) -> bool:
    if "html" in content_type.lower():
        return True
    head = content[:2048].lower()
    return b"<html" in head or b"<!doctype html" in head or b"<body" in head


_CHARSET = re.compile(rb"""charset\s*=\s*["']?([A-Za-z0-9_.:-]+)""", re.IGNORECASE)


def _decode(content: bytes, content_type: str = "") -> str:
    """Declared charset first (HTTP header, then <meta>), then UTF-8, then detection.

    GB2312 is decoded as its superset GBK: pages labelled gb2312 routinely contain GBK-only characters."""
    declared = [
        m.group(1).decode("ascii", "ignore")
        for m in [_CHARSET.search(content_type.encode("ascii", "ignore")), _CHARSET.search(content[:4096])]
        if m
    ]
    for enc in [*declared, "utf-8"]:
        enc = {"gb2312": "gbk", "gb_2312-80": "gbk"}.get(enc.lower(), enc)
        try:
            text = content.decode(enc, errors="replace")
        except LookupError:
            continue
        # a declared charset with a few bad bytes is still right; a wrong guess produces many
        if text.count("\ufffd") <= max(2, len(text) // 200):
            return text
    from charset_normalizer import from_bytes

    best = from_bytes(content).best()
    return str(best) if best else content.decode("utf-8", errors="replace")


def ocr_page(pdf: Path, page: int, lang: str = "eng") -> str:
    """OCR one page (pdftoppm 300 dpi → tesseract). Used only for pages without a text layer."""
    with tempfile.TemporaryDirectory() as d:
        base = Path(d) / "p"
        subprocess.run(
            [
                "pdftoppm",
                "-r",
                "300",
                "-f",
                str(page),
                "-l",
                str(page),
                "-png",
                "-singlefile",
                str(pdf),
                str(base),
            ],
            capture_output=True,
            timeout=180,
            check=False,
        )
        img = base.with_suffix(".png")
        if not img.exists():
            return ""
        out = subprocess.run(
            ["tesseract", str(img), "-", "-l", lang], capture_output=True, timeout=300, check=False
        )
        return out.stdout.decode("utf-8", errors="replace")


def pdf_to_text(content: bytes, layout: bool = False, ocr: bool = True) -> str:
    """pdftotext (poppler) if installed, else pypdf. `layout=True` keeps table rows on one line. Pages with no
    text layer (scans) are OCRed with tesseract when it is installed, marked `[ocr page N]` in the text."""
    if shutil.which("pdftotext"):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "doc.pdf"
            src.write_bytes(content)
            args = ["pdftotext", "-enc", "UTF-8", *(["-layout"] if layout else []), str(src), "-"]
            out = subprocess.run(args, capture_output=True, timeout=120, check=False)
            if out.returncode == 0:
                pages = out.stdout.decode("utf-8", errors="replace").split("\f")
                if ocr and shutil.which("tesseract"):
                    n = len(pages) - 1 if pages and not pages[-1].strip() else len(pages)  # trailing \f
                    for i in range(n):
                        if len(pages[i].strip()) < MIN_TEXT_CHARS:
                            ocr_text = ocr_page(src, i + 1)
                            if ocr_text.strip():
                                pages[i] = f"[ocr page {i + 1}]\n{ocr_text}"
                return "\f".join(pages)
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    mode = {"extraction_mode": "layout"} if layout else {}
    return "\n".join(page.extract_text(**mode) or "" for page in reader.pages)


def html_to_text(html: str) -> str:
    """Main text (trafilatura, tables kept) plus the whole page's text: quotes in tables, captions or
    sidebars that readability drops must still be found."""
    import trafilatura

    main = trafilatura.extract(html, include_tables=True, include_comments=False, favor_recall=True) or ""
    full = trafilatura.html2txt(html) or ""
    return main + "\n" + full


def extract_text(content: bytes, content_type: str = "", for_agent: bool = False) -> str:
    """Text to match quotes against. PDFs give both the layout text (table rows on one line) and the raw
    reading-order text, so a quote copied from either is found. `for_agent=True` returns one readable
    version (layout for PDFs), e.g. the `document.txt` handed to agents."""
    if _is_pdf(content, content_type):
        layout = pdf_to_text(content, layout=True)
        return layout if for_agent else layout + "\n\n" + pdf_to_text(content)
    text = _decode(content, content_type)
    if _is_html(content, content_type):
        return html_to_text(text)
    return text


# --- normalisation and matching ---------------------------------------------------------------------

_CJK = r"\u3000-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uff00-\uffef"
_TRANSLATE = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u2032": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u00ab": '"',
        "\u00bb": '"',
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u00a0": " ",
        "\u202f": " ",
        "\u2009": " ",
        "\u3000": " ",
        "\u00ad": None,
        "\u200b": None,
        "\u200c": None,
        "\u200d": None,
        "\ufeff": None,
    }
)
_ELLIPSIS = re.compile(r"\s*(?:\u2026|\.\.\.|\[\s*(?:\.\.\.|\u2026)\s*\])\s*")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def normalise(text: str) -> str:
    s = unicodedata.normalize("NFKC", text).translate(_TRANSLATE).casefold()
    s = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", s)  # de-hyphenate line breaks
    s = re.sub(r"\s+", " ", s)
    s = re.sub(rf"(?<=[{_CJK}])\s+(?=[{_CJK}])", "", s)  # PDF spacing between CJK characters
    return s.strip()


_SQUASH = re.compile(r"[\s|]")


def _squash(s: str) -> str:
    return _SQUASH.sub("", s)


def _squash_map(s: str) -> tuple[str, list[int]]:
    """Text without whitespace and table pipes, plus the index in `s` of each kept character."""
    keep = [i for i, ch in enumerate(s) if not _SQUASH.match(ch)]
    return "".join(s[i] for i in keep), keep


def _numbers(s: str) -> set[str]:
    return {re.sub(r"[.,]", "", n) for n in _NUMBER.findall(s)}


def _match_segment(seg: str, text: str, text_sq: str, idx: list[int]) -> tuple[float, str]:
    """Best score (0..1) of one quote segment in the text, plus the matched window of the spaced text
    (so numbers can be compared with their boundaries intact)."""
    seg_sq = _squash(seg)
    if not seg_sq:
        return 1.0, ""

    def window_sq(start: int, end: int) -> str:
        lo = idx[max(0, min(start, len(idx) - 1))]
        hi = idx[max(0, min(end - 1, len(idx) - 1))] + 1
        return text[max(0, lo - 20) : hi + 20]

    pos = text_sq.find(seg_sq)
    if pos >= 0:
        return 1.0, window_sq(pos, pos + len(seg_sq))
    if len(seg_sq) < 8:  # too short to fuzz meaningfully: exact only
        return 0.0, ""
    best, window = 0.0, ""
    cutoff = THRESHOLD * 100 - 10
    al = fuzz.partial_ratio_alignment(seg, text, score_cutoff=cutoff)
    if al:
        best, window = al.score / 100, text[max(0, al.dest_start - 20) : al.dest_end + 20]
    al = fuzz.partial_ratio_alignment(seg_sq, text_sq, score_cutoff=cutoff)
    if al and al.score / 100 > best:
        best, window = al.score / 100, window_sq(al.dest_start, al.dest_end)
    return best, window


def check_quote_in_text(quote: str, text: str) -> QuoteResult:
    if len(_squash(text)) < MIN_TEXT_CHARS:
        return QuoteResult("manual", reason="no machine-readable text (scanned? needs OCR)")
    q = normalise(quote)
    t = normalise(text)
    t_sq, idx = _squash_map(t)
    segments = [s for s in _ELLIPSIS.split(q) if s.strip()]
    if not segments:
        return QuoteResult("fail", reason="empty quote")
    scores: list[float] = []
    details: list[str] = []
    for seg in segments:
        score, window = _match_segment(seg, t, t_sq, idx)
        scores.append(score)
        if score < THRESHOLD:
            details.append(f"segment not found ({score:.2f}): {seg[:60]!r}")
            continue
        missing = sorted(_numbers(seg) - _numbers(window))
        if missing:
            scores[-1] = min(score, THRESHOLD - 0.01)
            details.append(f"numbers not in source near the match: {', '.join(missing)}")
    score = min(scores)
    if score >= THRESHOLD and not details:
        return QuoteResult("pass", score=score)
    return QuoteResult("fail", score=score, reason="; ".join(details) or "below threshold", details=details)


# --- entry point ------------------------------------------------------------------------------------


def check_quote(
    quote: str,
    url: str | None = None,
    document: str | Path | None = None,
    content_type: str = "",
    fetcher=None,
    use_archive: bool = True,
) -> QuoteResult:
    """Check `quote` against a pre-fetched `document` if given, else fetch `url` (then the Wayback copy)."""
    import hashlib

    if document is not None:
        content = Path(document).read_bytes()
        sha = hashlib.sha256(content).hexdigest()
        text = extract_text(content, content_type)
        res = check_quote_in_text(quote, text)
        res.content_sha256, res.source = sha, "file"
        if "[ocr page " in text:
            res.details.append("ocr")
        return res
    if url is None:
        raise ValueError("check_quote needs a url or a document")
    if fetcher is None:
        from pipeline.fetch import Fetcher

        fetcher = Fetcher()
    got = fetcher.get(url)
    source = "url"
    if not got.ok and use_archive:
        snap = _archive_url(fetcher, url)
        if snap:
            got = fetcher.get(snap)
            source = "archive"
    if not got.ok:
        return QuoteResult("unreachable", reason=got.reason)
    text = extract_text(got.content, got.content_type)
    res = check_quote_in_text(quote, text)
    res.content_sha256, res.source = got.sha256, source
    if "[ocr page " in text:
        res.details.append("ocr")
    return res


def _archive_url(fetcher, url: str) -> str | None:
    """Latest Wayback snapshot, raw (`id_`) so the archive's toolbar isn't in the text."""
    import json

    try:
        r = fetcher.client.get("https://archive.org/wayback/available", params={"url": url})
        snap = json.loads(r.text).get("archived_snapshots", {}).get("closest", {})
    except Exception:  # noqa: BLE001 - archive lookup is best effort
        return None
    if not snap.get("available"):
        return None
    m = re.match(r"(https?://web\.archive\.org/web/\d+)(/.*)", snap["url"])
    return f"{m.group(1)}id_{m.group(2)}" if m else snap["url"]
