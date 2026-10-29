"""Deterministic IDs and slugs.

An ID never encodes something that can change (owner, status). Same inputs always give the same ID.
Hash-based IDs join their parts with a newline so that ("ab", "c") and ("a", "bc") never collide.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_GREEK = {
    "α": "alpha",
    "β": "beta",
    "γ": "gamma",
    "δ": "delta",
    "ε": "epsilon",
    "ω": "omega",
}

_CAS_RE = re.compile(r"^(\d{2,7})-(\d{2})-(\d)$")
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TRACKING_PARAMS = re.compile(r"^(utm_[a-z]+|fbclid|gclid|mc_cid|mc_eid)$", re.IGNORECASE)


def _sha1(*parts: str, n: int = 12) -> str:
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()[:n]


def slugify(text: str) -> str:
    """Lowercase ASCII slug. Greek letters are spelled out; text with no ASCII left gets a hash slug."""
    s = "".join(_GREEK.get(ch, ch) for ch in text.strip().lower())
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    if not s:
        # Non-Latin names (e.g. 万华化学) still need a stable slug; transliteration is a human decision.
        return "x" + _sha1(text.strip(), n=8)
    return s


def is_slug(s: str) -> bool:
    return bool(_SLUG_RE.match(s))


def cas_is_valid(cas: str) -> bool:
    """CAS registry number check digit."""
    m = _CAS_RE.match(cas)
    if not m:
        return False
    digits = (m.group(1) + m.group(2))[::-1]
    return sum((i + 1) * int(d) for i, d in enumerate(digits)) % 10 == int(m.group(3))


def canonical_url(url: str) -> str:
    """Lowercase scheme and host, drop fragment and tracking parameters. Path and other params are kept."""
    parts = urlsplit(url.strip())
    query = urlencode(
        [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING_PARAMS.match(k)]
    )
    netloc = parts.netloc.lower()
    if netloc.endswith(":80") and parts.scheme.lower() == "http":
        netloc = netloc[:-3]
    if netloc.endswith(":443") and parts.scheme.lower() == "https":
        netloc = netloc[:-4]
    return urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", query, ""))


def molecule_id(cas: str | None = None, name: str | None = None) -> str:
    if cas:
        if not cas_is_valid(cas):
            raise ValueError(f"invalid CAS number: {cas!r}")
        return f"mol:{cas}"
    if not name:
        raise ValueError("molecule_id needs a CAS number or a name")
    return f"mol:x-{slugify(name)}"


def route_id(product_slug: str, route_slug: str) -> str:
    return f"rte:{slugify(product_slug)}:{slugify(route_slug)}"


_LEGAL = {
    "co", "company", "ltd", "limited", "inc", "incorporated", "corp", "corporation", "plc", "llc", "lp", "se",
    "ag", "gmbh", "kg", "sa", "spa", "srl", "bv", "nv", "ab", "oy", "oyj", "as", "sdn", "bhd", "pvt", "pte",
    "kk", "group", "holdings", "holding", "the", "of", "and",
}  # fmt: skip
_PAREN = re.compile(r"\s*[(（].*?[)）]")


def company_key(name: str) -> str:
    """Name without legal form or parenthetical notes: 'BASF SE' and 'BASF' share a key, as do
    'Wanhua Chemical Group Co., Ltd.' and 'Wanhua Chemical'. Used to match companies, never as an ID."""
    words = [w for w in slugify(_PAREN.sub("", name)).split("-") if w not in _LEGAL]
    return "-".join(words) or slugify(name)


def company_id(name: str) -> str:
    return f"co:{slugify(name)}"


def site_id(iso2: str, locality: str, nn: int = 1) -> str:
    if not re.fullmatch(r"[A-Za-z]{2}", iso2):
        raise ValueError(f"country must be ISO 3166-1 alpha-2: {iso2!r}")
    if not 1 <= nn <= 99:
        raise ValueError("site number must be 1..99")
    return f"site:{iso2.lower()}-{slugify(locality)}-{nn:02d}"


def next_site_id(iso2: str, locality: str, existing: Iterable[str]) -> str:
    """Lowest free site number for this country and locality. Existing IDs are never reused."""
    taken = set(existing)
    for nn in range(1, 100):
        candidate = site_id(iso2, locality, nn)
        if candidate not in taken:
            return candidate
    raise ValueError(f"no free site number for {iso2}-{locality}")


def unit_id(site: str, molecule_slug: str, nn: int | None = None) -> str:
    if not site.startswith("site:"):
        raise ValueError(f"not a site id: {site!r}")
    base = f"unit:{site.removeprefix('site:')}:{slugify(molecule_slug)}"
    return base if nn is None else f"{base}:{nn:02d}"


def event_id(date: str, slug: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError(f"event date must be YYYY-MM-DD: {date!r}")
    return f"ev:{date}:{slugify(slug)}"


def evidence_id(url: str, quote: str) -> str:
    return f"src:{_sha1(canonical_url(url), quote.strip())}"


def claim_id(subject_id: str, field: str, value: object, evidence_ids: Iterable[str]) -> str:
    return f"clm:{_sha1(subject_id, field, str(value).strip(), *sorted(evidence_ids))}"


def measure_id(jurisdiction: str, instrument_id: str) -> str:
    return f"tm:{slugify(jurisdiction)}:{slugify(instrument_id)}"


def chain_id(slug: str) -> str:
    return f"chain:{slugify(slug)}"


def duplicates(ids: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    dup: list[str] = []
    for i in ids:
        if i in seen and i not in dup:
            dup.append(i)
        seen.add(i)
    return dup
