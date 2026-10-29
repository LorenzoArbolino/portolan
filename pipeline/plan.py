"""Planner: chain pack + current data → job list `queue/<run-id>.jsonl`.

Job types: J01 `enumerate_producers` per molecule × region; J03 `site_profile` per chain site; J04
`unit_claims` per unit; J05/J06 `document_extract` per permit or filing already cited; J07 `ownership_chain`
per operating company; J14 `geocode` (published coordinates only) per site without a location.

A job's ID is a hash of its type, inputs and prompt hash, so the same job always has the same ID; jobs that
already succeeded in an earlier run are skipped."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from portolan.chain import ChainPack, load_chain
from portolan.ids import slugify
from portolan.merges import apply as apply_merges
from portolan.merges import id_map
from portolan.store import Store

JOBS_DIR = Path(__file__).parent / "jobs"
QUEUE_DIR = Path("queue")
RUNS_DIR = Path("runs")

JOB_FILES = {
    "J01": "enumerate_producers",
    "J03": "site_profile",
    "J04": "unit_claims",
    "J05": "document_extract",  # J05 permits and J06 filings share one template
    "J07": "ownership_chain",
    "J14": "geocode",
    "MF": "must_find",
}
SHORT = {
    "enumerate_producers": "j01",
    "site_profile": "j03",
    "unit_claims": "j04",
    "document_extract": "j05",
    "ownership_chain": "j07",
    "geocode": "j14",
    "market_overview": "j15",
    "must_find": "mf",
}
DOC_SOURCE_TYPES = {
    "permit": "permit / environmental clearance / EIA",
    "regulator": "regulator document",
    "exchange_filing": "filing / prospectus / annual report",
}

REGION_NAMES = {
    "EU": "the European Union",
    "CH": "Switzerland",
    "CN": "China",
    "IN": "India",
    "US": "the United States",
    "JP": "Japan",
    "MY": "Malaysia",
    "BR": "Brazil",
    "ID": "Indonesia",
    "ROW": "the rest of the world",
}
REGION_COUNTRIES = {
    "EU": {
        "AT",
        "BE",
        "BG",
        "HR",
        "CY",
        "CZ",
        "DK",
        "EE",
        "FI",
        "FR",
        "DE",
        "GR",
        "HU",
        "IE",
        "IT",
        "LV",
        "LT",
        "LU",
        "MT",
        "NL",
        "PL",
        "PT",
        "RO",
        "SK",
        "SI",
        "ES",
        "SE",
    },
}


@dataclass
class Job:
    job_id: str
    job_type: str  # enumerate_producers | unit_claims
    inputs: dict
    prompt_hash: str
    chain_id: str


def template(job_type: str) -> str:
    return (
        (JOBS_DIR / "_preamble.md").read_text(encoding="utf-8")
        + "\n"
        + (JOBS_DIR / f"{job_type}.md").read_text(encoding="utf-8")
    )


def prompt_hash(job_type: str) -> str:
    return hashlib.sha1(template(job_type).encode("utf-8")).hexdigest()[:12]


def render(job_type: str, inputs: dict) -> str:
    text = template(job_type)

    def sub(m: re.Match) -> str:
        v = inputs.get(m.group(1), "")
        if isinstance(v, list):
            return (
                ", ".join(map(str, v))
                if m.group(1) != "leads"
                else "\n".join(f"- {x}" for x in v) or "- none"
            )
        return str(v)

    return re.sub(r"\{\{(\w+)\}\}", sub, text)


def job_id(job_type: str, inputs: dict, phash: str) -> str:
    key = json.dumps(
        {"type": job_type, "inputs": inputs, "prompt": phash}, sort_keys=True, ensure_ascii=False
    )
    short = SHORT[job_type]
    return f"{short}-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:10]}"


def _region_leads(pack: ChainPack, region: str) -> list[str]:
    codes = REGION_COUNTRIES.get(region, {region})
    out = []
    for h in pack.seed_hypotheses:
        tags = set(re.findall(r"\(([A-Z]{2})(?:/[A-Z]{2})*\)", h)) | {
            c for grp in re.findall(r"\(([A-Z/]{2,})\)", h) for c in grp.split("/")
        }
        if tags & codes:
            out.append(h)
    return out


def plan_j01(
    pack: ChainPack,
    molecules: list[str] | None = None,
    regions: list[str] | None = None,
    max_fetches: int = 60,
    min_weight: int = 2,
    max_jobs: int | None = None,
) -> list[Job]:
    """Research effort follows importance (rule 5): without an explicit molecule list, every molecule of
    weight ≥ `min_weight` in every region, ordered by weight × region priority (priority 1 → 3 points,
    3 → 1), and cut at `max_jobs`. Weight-1 molecules get no new jobs unless named."""
    phash = prompt_hash("enumerate_producers")
    pairs = []
    for m in pack.molecules:
        if molecules and m.id not in molecules:
            continue
        if not molecules and (m.weight < min_weight or m.role == "context"):
            continue
        for r in pack.regions:
            if regions and r.code not in regions:
                continue
            pairs.append((m.weight * (4 - r.priority), m, r))
    pairs.sort(key=lambda x: -x[0])
    if max_jobs:
        pairs = pairs[:max_jobs]
    jobs = []
    for _, m, r in pairs:
        inputs = {
            "job_type": "enumerate_producers",
            "chain_id": pack.id,
            "molecule_id": m.id,
            "molecule_name": m.name,
            "cas": m.cas or "n/a",
            "search_names": [m.name, m.cas or ""],
            "region": r.code,
            "region_name": REGION_NAMES.get(r.code, r.code),
            "languages": r.languages,
            "leads": _region_leads(pack, r.code),
            "max_fetches": max_fetches,
        }
        jobs.append(
            Job(
                job_id("enumerate_producers", inputs, phash),
                "enumerate_producers",
                inputs,
                phash,
                pack.id,
            )
        )
    return jobs


def plan_j04(
    pack: ChainPack, store: Store, molecules: list[str] | None = None, max_fetches: int = 60
) -> list[Job]:
    phash = prompt_hash("unit_claims")
    sites = {s.id: s for s in store.load("sites")}
    companies = {c.id: c for c in store.load("companies")}
    claims = store.load("claims")
    chain_mols = {m.id for m in pack.molecules}
    lang_by_country = {}
    for r in pack.regions:
        for c in REGION_COUNTRIES.get(r.code, {r.code}):
            lang_by_country[c] = r.languages
    # plan on merged IDs, so a merged site's units and claims count once, under the surviving site
    units = store.load("units")
    units, _, claims, _ = apply_merges(id_map(store.load("merges"), units), units, [], claims, [])
    accepted = {(c.subject_id, c.field) for c in claims if c.review_state == "accepted"}
    jobs = []
    units = sorted(
        units, key=lambda u: -pack.molecule(u.molecule_id).weight if u.molecule_id in chain_mols else 0
    )
    for u in units:
        if u.molecule_id not in chain_mols or (molecules and u.molecule_id not in molecules):
            continue
        if (u.id, "status") in accepted and (u.id, "capacity") in accepted:  # nothing left to find
            continue
        site = sites.get(u.site_id)
        if site is None:
            continue
        m = pack.molecule(u.molecule_id)
        ops = [
            c
            for c in claims
            if c.subject_id in (u.id, site.id)
            and c.field == "operator"
            and c.review_state not in ("rejected", "superseded")
        ]
        operator = companies.get(str(ops[-1].value_norm or ops[-1].value)) if ops else None
        known = sorted(
            {
                f"{c.field}={c.value}{' ' + c.unit_raw if c.unit_raw else ''} (as of {c.as_of})"
                for c in claims
                if c.subject_id == u.id
                and c.field != "exists"
                and c.review_state not in ("rejected", "superseded")
            }
        )
        inputs = {
            "job_type": "unit_claims",
            "chain_id": pack.id,
            "unit_id": u.id,
            "molecule_id": m.id,
            "molecule_name": m.name,
            "cas": m.cas or "n/a",
            "site_name": site.name,
            "locality": site.locality,
            "country": site.country,
            "operator_name": operator.name if operator else "unknown operator",
            "languages": lang_by_country.get(site.country, ["en"]),
            "known": "; ".join(known) or "nothing",
            "max_fetches": max_fetches,
        }
        jobs.append(Job(job_id("unit_claims", inputs, phash), "unit_claims", inputs, phash, pack.id))
    return jobs


def _languages(pack: ChainPack) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for r in pack.regions:
        for c in REGION_COUNTRIES.get(r.code, {r.code}):
            out.setdefault(c, r.languages)
    return out


def _chain_molecules(pack: ChainPack) -> list[str]:
    return [
        f"{m.name} (`{m.id}`{'; also written ' + ', '.join(m.names) if m.names else ''})"
        for m in pack.molecules
        if m.tier != "base" and m.role != "context"
    ]


def _known(claims: list, subject_ids: set[str]) -> str:
    rows = sorted(
        {
            f"{c.subject_id.split(':', 1)[1]} {c.field}={c.value}{' ' + c.unit_raw if c.unit_raw else ''}"
            f" (as of {c.as_of})"
            for c in claims
            if c.subject_id in subject_ids and c.review_state not in ("rejected", "superseded")
        }
    )
    return "; ".join(rows) or "nothing"


def _chain_sites(pack: ChainPack, store: Store):
    chain_mols = {m.id for m in pack.molecules}
    units = [u for u in store.load("units") if u.molecule_id in chain_mols]
    site_ids = {u.site_id for u in units}
    return [s for s in store.load("sites") if s.id in site_ids], units


def _operator_name(site_id: str, claims: list, companies: dict) -> str:
    ops = [
        c
        for c in claims
        if c.subject_id == site_id
        and c.field == "operator"
        and c.review_state not in ("rejected", "superseded")
    ]
    if not ops:
        return "unknown operator"
    co = companies.get(str(ops[-1].value_norm or ops[-1].value))
    return co.name if co else str(ops[-1].value)


def plan_j03(pack: ChainPack, store: Store, max_fetches: int = 60) -> list[Job]:
    phash = prompt_hash("site_profile")
    sites, units = _chain_sites(pack, store)
    claims, companies, langs = (
        store.load("claims"),
        {c.id: c for c in store.load("companies")},
        _languages(pack),
    )
    jobs = []
    for s in sites:
        unit_ids = {u.id for u in units if u.site_id == s.id}
        inputs = {
            "job_type": "site_profile",
            "chain_id": pack.id,
            "site_id": s.id,
            "site_name": s.name,
            "locality": s.locality,
            "country": s.country,
            "operator_name": _operator_name(s.id, claims, companies),
            "languages": langs.get(s.country, ["en"]),
            "chain_molecules": _chain_molecules(pack),
            "known": _known(claims, unit_ids | {s.id}),
            "max_fetches": max_fetches,
        }
        jobs.append(Job(job_id("site_profile", inputs, phash), "site_profile", inputs, phash, pack.id))
    return jobs


def plan_j14(pack: ChainPack, store: Store, max_fetches: int = 30) -> list[Job]:
    """Sites with no coordinates and no live lat_lon claim."""
    phash = prompt_hash("geocode")
    sites, _ = _chain_sites(pack, store)
    claims, langs = store.load("claims"), _languages(pack)
    located = {
        c.subject_id
        for c in claims
        if c.field == "lat_lon" and c.review_state not in ("rejected", "superseded")
    }
    jobs = []
    for s in sites:
        if s.lat is not None or s.id in located:
            continue
        inputs = {
            "job_type": "geocode",
            "chain_id": pack.id,
            "site_id": s.id,
            "site_name": s.name,
            "locality": s.locality,
            "country": s.country,
            "address": s.address or "not known",
            "languages": langs.get(s.country, ["en"]),
            "max_fetches": max_fetches,
        }
        jobs.append(Job(job_id("geocode", inputs, phash), "geocode", inputs, phash, pack.id))
    return jobs


def plan_j05(pack: ChainPack, store: Store, extra_urls: list[str] | None = None) -> list[Job]:
    """One document job per permit, regulator document or filing already cited as evidence (they usually
    hold more than the one claim they were cited for), plus any `extra_urls`."""
    phash = prompt_hash("document_extract")
    docs: dict[str, dict] = {}
    for e in store.load("evidence"):
        if e.source_type in DOC_SOURCE_TYPES and e.url not in docs:
            docs[e.url] = {
                "title": e.locator or e.url.rsplit("/", 1)[-1],
                "publisher": e.publisher or "unknown",
                "kind": DOC_SOURCE_TYPES[e.source_type],
            }
    for u in extra_urls or []:
        docs.setdefault(u, {"title": u.rsplit("/", 1)[-1], "publisher": "unknown", "kind": "document"})
    jobs = []
    for url, d in sorted(docs.items()):
        inputs = {
            "job_type": "document_extract",
            "chain_id": pack.id,
            "url": url,
            "document_url": url,
            "doc_title": d["title"][:160],
            "doc_kind": d["kind"],
            "publisher": d["publisher"],
            "chain_molecules": _chain_molecules(pack),
            "search_terms": sorted(
                {n for m in pack.molecules if m.role != "context" for n in [m.name, *m.names]}
            ),
            "max_fetches": 0,
        }
        jobs.append(
            Job(job_id("document_extract", inputs, phash), "document_extract", inputs, phash, pack.id)
        )
    return jobs


def plan_j07(pack: ChainPack, store: Store, max_fetches: int = 40) -> list[Job]:
    """Every company that operates a chain site and has no live parent claim yet."""
    phash = prompt_hash("ownership_chain")
    sites, _ = _chain_sites(pack, store)
    site_ids = {s.id for s in sites}
    claims = store.load("claims")
    live = [c for c in claims if c.review_state not in ("rejected", "superseded")]
    operators = {
        str(c.value_norm or c.value) for c in live if c.field == "operator" and c.subject_id in site_ids
    }
    has_parent = {c.subject_id for c in live if c.field == "parent"}
    langs = _languages(pack)
    jobs = []
    for co in store.load("companies"):
        if co.id not in operators or co.id in has_parent:
            continue
        inputs = {
            "job_type": "ownership_chain",
            "chain_id": pack.id,
            "company_id": co.id,
            "company_name": co.name,
            "hq_country": co.hq_country or "unknown",
            "languages": langs.get(co.hq_country or "", ["en"]),
            "max_fetches": max_fetches,
        }
        jobs.append(Job(job_id("ownership_chain", inputs, phash), "ownership_chain", inputs, phash, pack.id))
    return jobs


def succeeded_job_ids(runs_dir: Path = RUNS_DIR) -> set[str]:
    done: set[str] = set()
    for mf in runs_dir.glob("*/manifest.json"):
        for j in json.loads(mf.read_text(encoding="utf-8")).get("jobs", []):
            if j.get("status") == "ok":
                done.add(j["job_id"])
    return done


def default_run_id(pack: ChainPack, jobs: list[Job]) -> str:
    h = hashlib.sha1("".join(sorted(j.job_id for j in jobs)).encode()).hexdigest()[:6]
    return f"{dt.date.today().isoformat()}-{slugify(pack.slug)}-{h}"


def write_queue(jobs: list[Job], run_id: str, queue_dir: Path = QUEUE_DIR) -> Path:
    queue_dir.mkdir(parents=True, exist_ok=True)
    p = queue_dir / f"{run_id}.jsonl"
    p.write_text(
        "".join(json.dumps(asdict(j), ensure_ascii=False, sort_keys=True) + "\n" for j in jobs),
        encoding="utf-8",
    )
    return p


def read_queue(run_id: str, queue_dir: Path = QUEUE_DIR) -> list[Job]:
    p = queue_dir / f"{run_id}.jsonl"
    return [Job(**json.loads(line)) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


# J15 runs once per language group: Chinese-language market analyses are a source of their own.
J15_LANGUAGES = [["en", "de", "fr", "ja"], ["zh"]]


def plan_j15(
    pack: ChainPack, store: Store, molecules: list[str] | None = None, max_fetches: int = 40
) -> list[Job]:
    """Producer league table + world totals per molecule (market reports, trade press, filings)."""
    phash = prompt_hash("market_overview")
    units, sites = store.load("units"), {s.id: s for s in store.load("sites")}
    companies = {c.id: c.name for c in store.load("companies")}
    claims = [c for c in store.load("claims") if c.review_state not in ("rejected", "superseded")]
    operator = {c.subject_id: str(c.value_norm or c.value) for c in claims if c.field == "operator"}
    capacity = {
        c.subject_id: f"{c.value} {c.unit_raw or ''}".strip() for c in claims if c.field == "capacity"
    }
    jobs = []
    for mol_id in molecules or [m.id for m in pack.molecules if m.role in ("core", "downstream")]:
        m = pack.molecule(mol_id)
        known = []
        for u in units:
            if u.molecule_id != m.id or u.site_id not in sites:
                continue
            s = sites[u.site_id]
            who = companies.get(operator.get(s.id, ""), "operator unknown")
            known.append(f"- {who}, {s.locality} ({s.country}): {capacity.get(u.id, 'capacity unknown')}")
        for langs in J15_LANGUAGES:
            inputs = {
                "job_type": "market_overview",
                "chain_id": pack.id,
                "molecule_id": m.id,
                "molecule_name": m.name,
                "cas": m.cas or "n/a",
                "search_names": [m.name, m.cas or "", "and its names in the search languages"],
                "languages": langs,
                "known": "\n".join(sorted(set(known))) or "none yet",
                "max_fetches": max_fetches,
            }
            jobs.append(
                Job(job_id("market_overview", inputs, phash), "market_overview", inputs, phash, pack.id)
            )
    return jobs


def _mf_known(item, units, sites: dict, companies: dict, claims: list) -> str:
    wanted = set(item.company_ids)
    ops = {
        c.subject_id: str(c.value_norm)
        for c in claims
        if c.field == "operator" and c.review_state not in ("rejected", "superseded")
    }
    lines = []
    for u in units:
        op = ops.get(u.id) or ops.get(u.site_id)
        if op not in wanted or u.molecule_id not in item.molecules:
            continue
        s = sites.get(u.site_id)
        facts = _known([c for c in claims if c.subject_id == u.id], {u.id}) or "nothing sourced yet"
        lines.append(f"- `{u.id}` ({s.locality if s else '?'}, {s.country if s else '?'}): {facts}")
    cos = [f"`{c}` ({companies[c].name})" for c in item.company_ids if c in companies]
    return "\n".join(lines + ([f"- company ids: {', '.join(cos)}"] if cos else [])) or "- nothing yet"


def plan_mf(
    pack: ChainPack,
    store: Store,
    items: list[str] | None = None,
    open_only: bool = True,
    max_fetches: int = 60,
) -> list[Job]:
    """One job per must-find item (company × molecules), for its molecules still open, highest weight
    first."""
    from portolan.build import build_chain

    phash = prompt_hash("must_find")
    status = {x["id"]: x for x in build_chain(pack, store)["must_find"]}
    units = store.load("units")
    units, _, claims, _ = apply_merges(
        id_map(store.load("merges"), units), units, [], store.load("claims"), []
    )
    sites = {s.id: s for s in store.load("sites")}
    companies = {c.id: c for c in store.load("companies")}
    langs = _languages(pack)
    jobs = []
    for mf in sorted(pack.must_find, key=lambda x: -x.weight):
        if items and mf.id not in items:
            continue
        st = status.get(mf.id, {}).get("molecules", {})
        mols = [m for m in mf.molecules if not open_only or st.get(m, {}).get("state") == "open"]
        if not mols:
            continue
        countries = {sites[s].country for s in mf.sites if s in sites} or {
            c.hq_country for c in (companies.get(x) for x in mf.company_ids) if c and c.hq_country
        }
        languages = sorted({lang for c in countries for lang in langs.get(c, ["en"])} | {"en"})
        targets = "\n".join(
            f"- {pack.molecule(m).name} (CAS {pack.molecule(m).cas}, id `{m}`)"
            + (f": {st[m]['detail']}" if st.get(m, {}).get("detail") else "")
            for m in mols
        )
        inputs = {
            "job_type": "must_find",
            "chain_id": pack.id,
            "must_find_id": mf.id,
            "company": mf.company,
            "aliases": mf.aliases or [mf.company],
            "places": mf.places or ["any"],
            "languages": languages,
            "targets": targets,
            "known": _mf_known(mf, units, sites, companies, claims),
            "max_fetches": max_fetches,
        }
        jobs.append(Job(job_id("must_find", inputs, phash), "must_find", inputs, phash, pack.id))
    return jobs


def plan(
    chain_path: str | Path,
    job_types: list[str],
    molecules: list[str] | None = None,
    regions: list[str] | None = None,
    data_dir: str | Path = "data",
    runs_dir: Path = RUNS_DIR,
    skip_done: bool = True,
    max_fetches: int = 60,
) -> list[Job]:
    pack = load_chain(chain_path)
    jobs: list[Job] = []
    if "J01" in job_types:
        jobs += plan_j01(pack, molecules, regions, max_fetches)
    if "J04" in job_types:
        jobs += plan_j04(pack, Store(data_dir), molecules, max_fetches)
    if "J03" in job_types:
        jobs += plan_j03(pack, Store(data_dir), max_fetches)
    if "J05" in job_types or "J06" in job_types:
        jobs += plan_j05(pack, Store(data_dir))
    if "J07" in job_types:
        jobs += plan_j07(pack, Store(data_dir))
    if "J14" in job_types:
        jobs += plan_j14(pack, Store(data_dir))
    if "MF" in job_types:
        jobs += plan_mf(pack, Store(data_dir), max_fetches=max_fetches)
    if "J15" in job_types:
        jobs += plan_j15(pack, Store(data_dir), molecules)
    if skip_done:
        done = succeeded_job_ids(runs_dir)
        jobs = [j for j in jobs if j.job_id not in done]
    return jobs
