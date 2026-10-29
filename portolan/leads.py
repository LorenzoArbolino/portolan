"""Company-level findings → units. "Company X makes molecule M" (no plant named) still counts for market
shares, so it becomes a unit: at the company's only known plant if it has exactly one, otherwise at an
"undisclosed plant" site in the company's home country (`geo_precision: country`, placed approximately).

`promote_leads` converts the older lead claims (subject = company, value_norm = molecule) the same way."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from portolan import ids
from portolan.models import Claim, Company, Site, Unit
from portolan.store import Store

COUNTRY = {
    "CN": "China", "IN": "India", "DE": "Germany", "FR": "France", "CH": "Switzerland", "IT": "Italy",
    "ES": "Spain", "NL": "Netherlands", "BE": "Belgium", "FI": "Finland", "SE": "Sweden",
    "US": "United States", "JP": "Japan", "MY": "Malaysia", "BR": "Brazil", "ID": "Indonesia",
    "GB": "United Kingdom", "KR": "South Korea", "SG": "Singapore", "AT": "Austria", "PL": "Poland",
    "MX": "Mexico", "PT": "Portugal", "TR": "Turkey", "TW": "Taiwan", "VN": "Vietnam", "TH": "Thailand",
    "RU": "Russia", "AR": "Argentina", "ZA": "South Africa",
}  # fmt: skip
UNIT_FIELDS = {"exists", "capacity", "status", "start_year", "end_year", "route"}


def company_sites(cid: str, claims: list[Claim]) -> set[str]:
    return {
        c.subject_id
        for c in claims
        if c.field == "operator"
        and c.subject_id.startswith("site:")
        and str(c.value_norm or c.value) == cid
        and c.review_state not in ("rejected", "superseded")
    }


def site_for_company(
    company: Company,
    sites: list[Site],
    claims: list[Claim],
    molecule: str | None = None,
    units: list[Unit] | None = None,
) -> tuple[str, Site | None] | None:
    """(site id, new site or None). The company's plant if one stands out: the only one already making the
    molecule, else its only plant, else its only plant at home. Otherwise an undisclosed plant at home.
    None when the company's country is unknown."""
    known = company_sites(company.id, claims)
    making = {u.site_id for u in units or [] if u.molecule_id == molecule} & known
    home = {s.id for s in sites if s.id in known and s.country == company.hq_country}
    for pick in (making, known, home):
        if len(pick) == 1:
            return next(iter(pick)), None
    if not company.hq_country:
        return None
    name = f"{company.name} (plant location not public)"
    for s in sites:
        if s.name == name:
            return s.id, None
    country = COUNTRY.get(company.hq_country, company.hq_country)
    sid = ids.next_site_id(company.hq_country, f"{ids.slugify(company.name)[:30]}", [s.id for s in sites])
    return sid, Site(id=sid, name=name, country=company.hq_country, locality=country, geo_precision="country")


def promote_leads(store: Store, review_path: Path, pack_molecules: dict[str, str]) -> dict[str, int]:
    """Lead claims (company makes molecule) → units with an accepted `exists` claim; closes review items."""
    claims, sites, units = store.load("claims"), store.load("sites"), store.load("units")
    companies = {c.id: c for c in store.load("companies")}
    new_sites: list[Site] = []
    new_units: list[Unit] = []
    new_claims: list[Claim] = []
    promoted: set[str] = set()
    today = dt.date.today().isoformat()
    for c in claims:
        mol = str(c.value_norm or "")
        if c.field != "exists" or not c.subject_id.startswith("co:") or mol not in pack_molecules:
            continue
        if c.review_state in ("rejected", "superseded") or c.subject_id not in companies:
            continue
        got = site_for_company(
            companies[c.subject_id], sites + new_sites, claims + new_claims, mol, units + new_units
        )
        if got is None:
            continue
        sid, site = got
        if site:
            new_sites.append(site)
            new_claims.append(_claim(sid, "operator", c.subject_id, c, "operator of its undisclosed plant"))
        uid = ids.unit_id(sid, pack_molecules[mol])
        if not any(u.id == uid for u in units + new_units):
            new_units.append(Unit(id=uid, site_id=sid, molecule_id=mol))
        new_claims.append(
            _claim(uid, "exists", "true", c, f"promoted on {today} from company-level lead {c.id}")
        )
        promoted.add(c.id)
    store.append("sites", new_sites)
    store.append("units", new_units)
    written = store.append("claims", new_claims)
    closed = 0
    if review_path.exists():
        lines = review_path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            r = json.loads(line) if line.strip() else None
            if r and r.get("state") == "open" and set(r.get("claim_ids", [])) & promoted:
                r.update(state="closed", decision="accepted", decided_by="code", decided_on=today,
                         decision_note="promoted to a unit (portolan/leads.py)")  # fmt: skip
                lines[i] = json.dumps(r, ensure_ascii=False, sort_keys=True)
                closed += 1
        review_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"sites": len(new_sites), "units": len(new_units), "claims": len(written), "review_closed": closed}


def _claim(subject: str, field: str, value: str, src: Claim, note: str) -> Claim:
    return Claim(
        id=ids.claim_id(subject, field, value, src.evidence_ids),
        subject_id=subject,
        field=field,
        value=value,
        value_norm=value,
        as_of=src.as_of,
        evidence_ids=src.evidence_ids,
        extracted_by=src.extracted_by,
        confidence=src.confidence,
        review_state="accepted",
        review_note=note,
    )
