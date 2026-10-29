"""Pre-fetched documents for document jobs (agents read files rather than fight downloads).

A document is fetched once (PortolanBot, cached in `cache/`, never committed), turned into agent-readable text
(layout PDF text, OCR for scanned pages) and, when long, cut to the pages that mention the chain's products or
capacity, so a 400-page prospectus becomes the few pages that matter."""

from __future__ import annotations

import re
from pathlib import Path

from pipeline.fetch import Fetcher
from pipeline.validators.quote_check import extract_text

MAX_CHARS = 150_000
CAPACITY_TERMS = [
    "capacity",
    "installed",
    "mt/month",
    "mtpm",
    "tpa",
    "t/a",
    "tonnes",
    "metric",
    "产能",
    "万吨",
    "吨/年",
    "规模",
    "kapazität",
    "jahrestonnen",
    "capacité",
    "capacità",
    "生産能力",
]


def focus(text: str, terms: list[str], max_chars: int = MAX_CHARS) -> str:
    """Whole text if short; otherwise the pages (form-feed separated, else 4,000-char blocks) that mention a
    chain term, each with its neighbours, marked `[page N]`, capped at `max_chars`."""
    if len(text) <= max_chars:
        return text
    pages = text.split("\f") if "\f" in text else [text[i : i + 4000] for i in range(0, len(text), 4000)]
    low = [p.lower() for p in pages]
    names = [t.lower() for t in terms if t]
    hits = [i for i, p in enumerate(low) if any(n in p for n in names)]
    hits = [i for i in hits if any(c in low[i] for c in CAPACITY_TERMS)] or hits
    keep = sorted({j for i in hits for j in (i - 1, i, i + 1) if 0 <= j < len(pages)})
    out, size = [], 0
    for i in keep:
        chunk = f"[page {i + 1}]\n{pages[i]}"
        if size + len(chunk) > max_chars:
            out.append("[… further matching pages omitted …]")
            break
        out.append(chunk)
        size += len(chunk)
    return "\n\n".join(out) if out else text[:max_chars]


def document_text(url: str, terms: list[str], fetcher: Fetcher | None = None) -> str | None:
    got = (fetcher or Fetcher()).get(url)
    if not got.ok:
        return None
    try:
        text = extract_text(got.content, got.content_type, for_agent=True)
    except Exception:  # noqa: BLE001 - a broken file fails this job, not the whole run
        return None
    return focus(text, terms)


def write_document(workdir: Path, url: str, terms: list[str], fetcher: Fetcher | None = None) -> bool:
    text = document_text(url, terms, fetcher)
    if text is None:
        return False
    (workdir / "document.txt").write_text(re.sub(r"[ \t]+\n", "\n", text), encoding="utf-8")
    return True
