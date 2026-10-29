"""US EPA Chemical Data Reporting (source U2, docs/spikes/U2-epa-cdr.md): site-level records for the chain's
CAS numbers → a script job's `out.jsonl` in the agent output format, collected like any run.

One public row per site × chemical: site name, city, state, coordinates, activity and production volume
(lb). Only `Manufacture` / `Both` rows are kept (importers aren't producers). Each row becomes evidence whose
quote is a compact rendering of that row; `verify()` checks such quotes against the dataset, standing in for
the page check that agent quotes get. Production volume is output, not capacity (`capacity_basis:
production`). US federal data, public domain; the zip stays in `cache/` (never committed)."""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
import zipfile
from functools import cache
from pathlib import Path

from pipeline.fetch import Fetcher

URL = "https://www.epa.gov/system/files/other-files/2026-04/2024-cdr-public-csv-data.zip"
MEMBER = "2024 CDR Manufacture-Import Information.csv"
YEAR = 2023
PRODUCERS = {"Manufacture", "Both"}


def _rows(content: bytes) -> list[dict[str, str]]:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        text = io.TextIOWrapper(z.open(MEMBER), encoding="cp1252", errors="replace")
        return list(csv.DictReader(text))


@cache
def _dataset() -> list[dict[str, str]]:
    got = Fetcher().get(URL)
    if not got.ok:
        raise RuntimeError(f"CDR download failed: {got.reason}")
    return _rows(got.content)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def quote(r: dict[str, str]) -> str:
    """The row as evidence: who, where, what, activity, volume, coordinates."""
    pv = _clean(r.get(f"{YEAR} DOMESTIC PV", "")) or "not reported"
    return (
        f"{_clean(r['SITE NAME'])} | {_clean(r['SITE CITY'])}, {r['SITE STATE']} | CAS {r['CHEMICAL ID']} | "
        f"activity {r['ACTIVITY']} | {YEAR} domestic production volume {pv} lb | "
        f"lat {r['SITE LATITUDE']}, lon {r['SITE LONGITUDE']}"
    )[:400]


def verify(q: str, rows: list[dict[str, str]] | None = None) -> bool:
    return any(quote(r) == q for r in (rows if rows is not None else _dataset()))


def _point(r: dict[str, str]) -> bool:
    """Coordinates given; the file writes 0.0, 0.0 for a missing point."""
    try:
        return (float(r["SITE LATITUDE"]), float(r["SITE LONGITUDE"])) != (0.0, 0.0)
    except ValueError:
        return False


def _pv(r: dict[str, str]) -> int | None:
    v = r.get(f"{YEAR} DOMESTIC PV", "").replace(",", "").strip()
    return int(v) if v.isdigit() and int(v) > 0 else None


def lines_for(rows: list[dict[str, str]], cas_to_mol: dict[str, str], retrieved: str) -> list[dict]:
    """Agent-format lines: per producing site, evidence + company + site, then per chemical exists/capacity/
    status, and the site's coordinates once."""
    out: list[dict] = []
    site_line: dict[tuple[str, str, str], int] = {}
    located: set[int] = set()
    as_of = f"{YEAR}-12-31"
    for r in rows:
        mol = cas_to_mol.get(r["CHEMICAL ID"])
        if mol is None or r["ACTIVITY"] not in PRODUCERS or r["SITE NAME"] == "CBI":  # site withheld
            continue
        out.append(
            {
                "kind": "evidence",
                "url": URL,
                "retrieved_at": retrieved,
                "publisher": "US EPA, Chemical Data Reporting 2024",
                "published_at": "2026-04-20",
                "source_type": "regulator",
                "language": "en",
                "quote": quote(r),
                "locator": f"{MEMBER}, TSCA program ID {r['EPA-TSCA PROGRAM ID']}",
            }
        )
        ev = len(out) - 1
        key = (_clean(r["SITE NAME"]).upper(), _clean(r["SITE CITY"]).upper(), r["SITE STATE"])
        if key not in site_line:
            company = _clean(r["DOMESTIC PARENT COMPANY NAME"] or r["STANDARDIZED PARENT COMPANY NAME"])
            out.append(
                {
                    "kind": "candidate_company",
                    "name": company.title() if company.isupper() else company,
                    "type": ["producer"],
                    "evidence_refs": [ev],
                }
            )
            site = {
                "kind": "candidate_site",
                "name": _clean(r["SITE NAME"]).title(),
                "country": "US",
                "admin1": r["SITE STATE"],
                "locality": _clean(r["SITE CITY"]).title(),
                "company_ref": len(out) - 1,
                "evidence_refs": [ev],
            }
            if address := _clean(f"{r['SITE ADDRESS LINE1']} {r['SITE ADDRESS LINE2']}"):
                site["address"] = address.title()
            if r["EPA FACILITY REGISTRY ID"]:
                site["registry_ids"] = {"epa_frs": r["EPA FACILITY REGISTRY ID"]}
            out.append(site)
            site_line[key] = len(out) - 1
        site = site_line[key]
        if site not in located and _point(r):
            out.append(
                {
                    "kind": "claim",
                    "subject_ref": {"candidate_site": site},
                    "field": "lat_lon",
                    "value": f"{r['SITE LATITUDE']}, {r['SITE LONGITUDE']}",
                    "as_of": as_of,
                    "evidence_refs": [ev],
                }
            )
            located.add(site)
        ref = {"candidate_site": site, "molecule": mol}
        out.append({"kind": "claim", "subject_ref": ref, "field": "exists", "value": "true", "as_of": as_of,
                    "evidence_refs": [ev]})  # fmt: skip
        pv = _pv(r)
        if pv:
            out.append(
                {
                    "kind": "claim",
                    "subject_ref": ref,
                    "field": "capacity",
                    "value": f"{pv:,}",
                    "unit_raw": "lb/a",
                    "capacity_basis": "production",
                    "as_of": as_of,
                    "evidence_refs": [ev],
                }
            )
            # production reported for the year: the unit ran that year
            out.append({"kind": "claim", "subject_ref": ref, "field": "status", "value": "operating",
                        "as_of": as_of, "evidence_refs": [ev]})  # fmt: skip
    return out


def pull(run_dir: Path, cas_to_mol: dict[str, str], chain_id: str, rows: list[dict] | None = None) -> dict:
    """Write `runs/<run>/cdr/out.jsonl` and a manifest, ready for `portolan collect`."""
    now = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    lines = lines_for(rows if rows is not None else _dataset(), cas_to_mol, now)
    job = run_dir / "cdr"
    job.mkdir(parents=True, exist_ok=True)
    (job / "out.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines), "utf-8")
    manifest = {
        "run_id": run_dir.name,
        "chain_id": chain_id,
        "updated_at": now,
        "jobs": [
            {
                "job_id": "cdr",
                "job_type": "registry_pull",
                "agent": "script",
                "model": "cdr2024",
                "status": "ok",
                "counts": {"lines": len(lines)},
            }
        ],  # fmt: skip
        "status_counts": {"ok": 1},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {"lines": len(lines), "sites": sum(x["kind"] == "candidate_site" for x in lines)}
