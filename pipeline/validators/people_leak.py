"""`people_leak` validator: public files must not contain emails, phone numbers or
person names. Names are allowed only inside the quote of evidence from a public company document.
A finding fails the build. Heuristic, deterministic, offline; extend `people_leak.yaml` as leaks appear."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

CONFIG = Path(__file__).with_name("people_leak.yaml")
SCANNED_SUFFIXES = {".csv", ".jsonl", ".json", ".geojson", ".md", ".txt", ".yaml", ".yml", ".html"}
# "a quote from a public company document" (methodology, rule 3)
COMPANY_DOC_TYPES = {"company_primary", "exchange_filing", "permit", "regulator", "operator_claimed"}
QUOTE_FIELDS = {"quote", "quote_en"}
# Job-workspace files: gitignored, never published (full documents, prompts, logs).
WORKSPACE_FILES = {"document.txt", "prompt.md", "log.txt", "inputs.json", "opencode.json"}

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(
    r"(?:\+\d{1,3}[\s.-]?(?:\(\d{1,4}\)[\s.-]?)?\d{1,4}(?:[\s.-]?\d{2,4}){2,4})"
    r"|(?:\b(?:tel|phone|fax|mobile|mob|ph|telefon|téléphone|telefono|电话|電話)\.?\s*(?:no\.?)?\s*[:：]?\s*"
    r"[+(]?\d[\d\s().-]{6,}\d)",
    re.IGNORECASE,
)
_CAP = r"[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ'’-]+"
_NAME = rf"{_CAP}(?:\s+(?:[A-Z]\.\s*)?{_CAP}){{1,2}}"


@dataclass
class Finding:
    path: str
    where: str
    kind: str  # email | phone | name
    match: str


@cache
def _patterns() -> dict[str, re.Pattern]:
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    alt = lambda xs: "|".join(re.escape(x) for x in sorted(xs, key=len, reverse=True))  # noqa: E731
    return {
        "honorific": re.compile(rf"\b(?:{alt(cfg['honorifics'])})\.?\s+{_NAME}"),
        "role_before": re.compile(rf"\b(?i:{alt(cfg['roles'])})\s*,?\s+{_NAME}"),
        "role_after": re.compile(rf"{_NAME}\s*,\s*(?:the\s+)?(?i:{alt(cfg['roles'])})\b"),
        "speech": re.compile(rf"\b(?:{alt(cfg['speech_verbs'])})\s+{_NAME}"),
        "speech_after": re.compile(rf"{_NAME}\s+(?:{alt(cfg['speech_verbs'])})\b"),
        "given": re.compile(rf"\b(?:{alt(cfg['given_names'])})\s+(?:[A-Z]\.\s*)?{_CAP}"),
        "cjk": re.compile(
            rf"[\u4e00-\u9fff]{{2,3}}(?:{alt(cfg['cjk_after_name'])})"
            rf"|(?:{alt(cfg['cjk_before_name'])})[\u4e00-\u9fff]{{2,3}}"
        ),
        "not_names": re.compile(alt(cfg["not_names"])),
        "street": re.compile(rf"\b(?i:{alt(cfg['street_words'])})\.?\s*(?:\w+\s+){{0,2}}$"),
    }


def scan_text(text: str, names: bool = True) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = [("email", m.group()) for m in EMAIL.finditer(text)]
    out += [("phone", m.group().strip()) for m in PHONE.finditer(text)]
    if names:
        p = _patterns()
        for key in ("honorific", "role_before", "role_after", "speech", "speech_after", "given", "cjk"):
            for m in p[key].finditer(text):
                if p["not_names"].search(m.group()) or p["street"].search(
                    text[max(0, m.start() - 30) : m.start()]
                ):
                    continue  # streets named after people ("Av. José Erineu Ortigosa") are addresses
                out.append(("name", m.group().strip()))
    seen: set[tuple[str, str]] = set()
    return [x for x in out if not (x in seen or seen.add(x))]


def scan_record(record: object, path: str, where: str = "") -> list[Finding]:
    """Walk a JSON value. Evidence quotes from company documents may contain names (not emails/phones)."""
    findings: list[Finding] = []
    company_doc = isinstance(record, dict) and record.get("source_type") in COMPANY_DOC_TYPES

    def walk(v: object, loc: str, key: str | None) -> None:
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, f"{loc}.{k}" if loc else k, k)
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f"{loc}[{i}]", key)
        elif isinstance(v, str):
            allow_names = company_doc and key in QUOTE_FIELDS
            for kind, m in scan_text(v, names=not allow_names):
                findings.append(Finding(path, loc, kind, m))

    walk(record, where, None)
    return findings


def scan_file(path: str | Path) -> list[Finding]:
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    if p.suffix == ".jsonl":
        out: list[Finding] = []
        for i, line in enumerate(text.splitlines()):
            if not line.strip():
                continue
            try:
                out += scan_record(json.loads(line), str(p), f"line {i + 1}")
            except json.JSONDecodeError:
                out += [Finding(str(p), f"line {i + 1}", k, m) for k, m in scan_text(line)]
        return out
    if p.suffix in {".json", ".geojson"}:
        try:
            return scan_record(json.loads(text), str(p))
        except json.JSONDecodeError:
            pass
    return [
        Finding(str(p), f"line {n}", k, m)
        for n, line in enumerate(text.splitlines(), 1)
        for k, m in scan_text(line)
    ]


def scan_paths(paths: list[str | Path]) -> list[Finding]:
    out: list[Finding] = []
    for root in map(Path, paths):
        files = [root] if root.is_file() else sorted(f for f in root.rglob("*") if f.is_file())
        for f in files:
            if f.suffix in SCANNED_SUFFIXES and f.name not in WORKSPACE_FILES:
                out += scan_file(f)
    return out
