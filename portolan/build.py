"""Build: data/ → DuckDB (`build/graph.duckdb`) → per-chain app bundle
`build/app/<chain>.json` + `build/app/sites.geojson`.

Only Portolan's own ODbL data goes in; the GEM layer is never read here. Resolved values and metrics are
computed fresh on every build and never edited by hand. Every displayed value carries its claim IDs, and
every claim its evidence IDs, so the app can open the quote behind any number."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict
from pathlib import Path

import duckdb

from pipeline.sources.wikipedia_places import read_locations
from pipeline.validators.geo import parse_lat_lon
from portolan.chain import ChainPack, load_chain
from portolan.coverage import ISO3_TO_2, coverage
from portolan.estimate import backtest, estimate, last_seen
from portolan.merges import apply as apply_merges
from portolan.merges import id_map
from portolan.metrics import molecule_metrics
from portolan.mustfind import resolved_molecules
from portolan.mustfind import status as must_find_status
from portolan.ownership import apply_transfers, groups, parents_of
from portolan.resolve import Resolved, resolve
from portolan.store import TABLES, Store

PUBLIC_EVIDENCE_FIELDS = (
    "id",
    "url",
    "archive_url",
    "publisher",
    "published_at",
    "source_type",
    "language",
    "quote",
    "quote_en",
    "locator",
    "quote_check",
    "retrieved_at",
)
# What the app shows on first load; the audit's "default view" reads this too.
DISPLAY = {"estimates_default": False, "chain_total": False}
UNIT_FIELDS = (
    "capacity",
    "production",
    "status",
    "start_year",
    "end_year",
    "route",
    "captive_share",
    "operator",
)


def load_duckdb(data_dir: Path, db_path: Path) -> duckdb.DuckDBPyConnection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = duckdb.connect(str(db_path))
    for table, (fname, _) in TABLES.items():
        p = data_dir / fname
        if not p.exists() or p.stat().st_size == 0:
            continue
        reader = (
            f"read_json_auto('{p}', format='newline_delimited')"
            if fname.endswith(".jsonl")
            else f"read_csv_auto('{p}', all_varchar=true, header=true)"
        )
        con.execute(f"CREATE TABLE {table} AS SELECT * FROM {reader}")
    return con


def _res(r: Resolved | None) -> dict | None:
    if r is None:
        return None
    d = asdict(r)
    d["as_of"] = r.as_of.isoformat()
    d.pop("subject_id")
    d.pop("field")
    return d


def build_chain(pack: ChainPack, store: Store, on: dt.date | None = None) -> dict:
    on = on or dt.date.today()
    data_dir = store.root
    chain_mols = {m.id for m in pack.molecules}
    all_units, all_sites = store.load("units"), store.load("sites")
    merged = id_map(store.load("merges"), all_units)
    all_units, all_sites, all_claims, all_events = apply_merges(
        merged, all_units, all_sites, store.load("claims"), store.load("events")
    )
    # A unit exists only through its claims: one whose every claim was rejected is not shown.
    live_subjects = {
        c.subject_id
        for c in all_claims
        if c.review_state not in ("rejected", "superseded") and c.confidence != "D"
    }
    units = [u for u in all_units if u.molecule_id in chain_mols and u.id in live_subjects]
    site_ids = {u.site_id for u in units}
    sites = {s.id: s for s in all_sites if s.id in site_ids}
    claims = [c for c in all_claims if c.review_state not in ("rejected", "superseded")]
    all_evidence = {e.id: e for e in store.load("evidence")}
    transfers = [
        t.model_copy(update={"event_id": merged.get(t.event_id, t.event_id)}) for t in store.load("transfers")
    ]
    claims, applied = apply_transfers(transfers, all_events, claims, all_evidence, on)
    # Groups and the must-find checklist rest on sourced claims only (estimates come later, never feed them).
    sourced_view = resolve(claims, on=on)
    by_claim = {c.id: c for c in claims}
    all_companies = [c for c in store.load("companies") if c.id not in merged]
    parents = {c.id: parents_of(c.id, sourced_view, by_claim) for c in all_companies}
    group = groups(all_companies, parents)
    checklist = must_find_status(pack, units, sourced_view, group)
    tests = backtest([u for u in units if not pack.molecule(u.molecule_id).byproduct], claims, on)
    claims += estimate(  # grade-D gap fillers, derived fresh on every build, only by backtested methods
        units,
        claims,
        on,
        byproducts={m.id for m in pack.molecules if m.byproduct},
        resolved_molecules=resolved_molecules(pack, checklist),
        enabled={k for k, b in tests.items() if b.passed},
    )
    public = resolve(claims, on=on)
    with_est = resolve(claims, on=on, include_estimates=True)

    def fields(subject: str, names: tuple[str, ...]) -> dict:
        out = {}
        for f in names:
            r = public.get((subject, f))
            e = with_est.get((subject, f))
            if r or e:
                out[f] = _res(r)
                if e and (r is None or e.claim_ids != r.claim_ids):
                    out[f + "__estimate"] = _res(e)
        return out

    ev_dates = {e.id: e.published_at for e in all_evidence.values() if e.published_at}
    unconfirmed = last_seen(units, claims, ev_dates)
    unit_rows = [
        {
            "id": u.id,
            "site_id": u.site_id,
            "molecule_id": u.molecule_id,
            "route_id": u.route_id,
            **fields(u.id, UNIT_FIELDS),
            **({"status_unconfirmed": unconfirmed[u.id]} if u.id in unconfirmed else {}),
        }
        for u in sorted(units, key=lambda u: u.id)
    ]
    places = read_locations(data_dir / "site_locations.csv")
    site_rows = []
    for s in sorted(sites.values(), key=lambda s: s.id):
        d = s.model_dump(mode="json", exclude_none=True)
        d.update(fields(s.id, ("operator", "lat_lon")))
        ll = public.get((s.id, "lat_lon"))
        point = parse_lat_lon(str(ll.value)) if ll is not None and ll.outcome == "resolved" else None
        if "lat" not in d and point is not None:
            # Coordinates stated in a document are a claim like any other (never geocoded guesses).
            d["lat"], d["lon"] = point
            d["geo_precision"] = "exact"
        if "lat" not in d and s.id in places:  # town-level placement (data/site_locations.csv)
            pl = places[s.id]
            d["lat"], d["lon"] = float(pl["lat"]), float(pl["lon"])
            d["geo_precision"] = pl["geo_precision"]
            d["location_source"] = pl["source_url"]
        d["unit_ids"] = sorted(u.id for u in units if u.site_id == s.id)
        site_rows.append(d)
    company_ids = {str(r["operator"]["value"]) for r in site_rows + unit_rows if r.get("operator")}
    company_ids |= {cl.subject_id for cl in claims if cl.field == "exists" and cl.value_norm in chain_mols}
    frontier = set(company_ids)
    while frontier:  # parents (and theirs) come along, so the app can name the group
        frontier = {p for c in frontier for p in parents.get(c, [])} - company_ids
        company_ids |= frontier
    subject_ids = {u.id for u in units} | set(sites) | company_ids
    companies = [
        {
            **c.model_dump(mode="json", exclude_none=True),
            **({"parents": parents[c.id]} if parents.get(c.id) else {}),
            **({"parent": _res(public[(c.id, "parent")])} if (c.id, "parent") in public else {}),
            "group": group.get(c.id, c.id),
        }
        for c in all_companies
        if c.id in company_ids
    ]
    subject_ids |= {c["id"] for c in companies}
    used_claims = [c for c in claims if c.subject_id in subject_ids]
    ev_ids = {e for c in used_claims for e in c.evidence_ids}
    events = [
        {
            **e.model_dump(mode="json", exclude_none=True),
            **(
                {"ownership": applied[e.id].model_dump(mode="json", exclude_none=True)}
                if e.id in applied
                else {}
            ),
        }
        for e in all_events
        if set(e.subjects) & subject_ids
    ]
    ev_ids |= {x for e in events for x in e["evidence_ids"]}
    evidence = {
        e.id: {
            k: v
            for k, v in e.model_dump(mode="json").items()
            if k in PUBLIC_EVIDENCE_FIELDS and v is not None
        }
        for e in all_evidence.values()
        if e.id in ev_ids
    }
    metrics = {
        m: molecule_metrics(pack, m, units, sites, claims, on=on, resolved=public).to_dict()
        for m in sorted({u.molecule_id for u in units})
    }
    return {
        "chain": {
            "id": pack.id,
            "name": pack.name,
            "version": pack.version,
            "why": pack.why_this_chain.strip(),
        },
        "built_on": on.isoformat(),
        "licence": "ODbL-1.0",
        "display": {
            **DISPLAY,
            "trade_footnote_codes": sorted({m.hs6[0] for m in pack.molecules if m.hs6 and not m.hs6_exact}),
        },
        "trade_codes": trade_codes(pack, {u.molecule_id for u in units}),
        "attribution": "Portolan contributors (ODbL 1.0); see ATTRIBUTION.md",
        "molecules": [
            {
                **m.model_dump(mode="json", exclude_none=True),
                "role": pack.molecule(m.id).role,
                "hs6_exact": pack.molecule(m.id).hs6_exact,
                "weight": pack.molecule(m.id).weight,
                **({"hs6_scope": pack.molecule(m.id).hs6_scope} if pack.molecule(m.id).hs6_scope else {}),
                **(
                    {"trade_basis": pack.molecule(m.id).trade_basis}
                    if pack.molecule(m.id).trade_basis
                    else {}
                ),
                "byproduct": pack.molecule(m.id).byproduct,
                **({"cn_hs8": pack.molecule(m.id).cn_hs8} if pack.molecule(m.id).cn_hs8 else {}),
                **({"note": pack.molecule(m.id).note} if pack.molecule(m.id).note else {}),
            }
            for m in pack.to_molecules()
        ],
        "routes": [r.model_dump(mode="json", exclude_none=True) for r in pack.to_routes()],
        "sites": site_rows,
        "units": unit_rows,
        "companies": companies,
        "claims": {c.id: c.model_dump(mode="json", exclude_none=True, exclude={"id"}) for c in used_claims},
        "evidence": evidence,
        "events": events,
        "metrics": metrics,
        "coverage": coverage(pack, store, data_dir / "flows", on=on),
        "trade": trade_summary(pack, data_dir / "flows"),
        "cn_exports": _json(data_dir / "flows" / "cn_exports.json"),
        "flows": world_flows(pack, data_dir / "flows"),
        "market": {m.id: fields(m.id, ("world_capacity", "world_demand")) for m in pack.molecules},
        "must_find": checklist,
        "backtest": {
            f"{mol}|{method}": {"n": b.n, "hits": b.hits, "passed": b.passed}
            for (mol, method), b in tests.items()
        },
    }


def _json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _short(name: str) -> str:
    return name.split(" (")[0]


def trade_codes(pack: ChainPack, mapped: set[str]) -> dict:
    """Each trade code shown in the app, with the molecules it covers. A code covering several mapped
    molecules is shown once, labelled with all of them (rule 4: one series must not pass for two)."""
    out: dict = {}
    for m in pack.molecules:
        if m.id not in mapped:
            continue
        if m.cn_hs8:
            out.setdefault(f"CN {m.cn_hs8}", {"molecules": []})["molecules"].append(m.id)
        if m.hs6:
            d = out.setdefault(f"HS {m.hs6[0]}", {"molecules": [], "broad": not m.hs6_exact})
            d["molecules"].append(m.id)
            if m.hs6_scope:
                d["scope"] = m.hs6_scope
    for d in out.values():
        if len(d["molecules"]) > 1:
            names = [_short(pack.molecule(x).name) for x in d["molecules"]]
            common = names[0].rsplit("-", 1)[-1] if all("-" in n for n in names) else None
            if common and all(n.endswith("-" + common) for n in names):
                d["label"] = " + ".join(n[: -len(common)] for n in names) + common + " (shared code)"
            else:
                d["label"] = " + ".join(names) + " (shared code)"
    return out


def world_flows(pack: ChainPack, flows_dir: Path, year: int = 2025, top: int = 15) -> dict:
    """Per molecule: exporters → destinations (tonnes, one year). China from its 8-digit customs code; the EU,
    US, Japan and India only where the 6-digit HS code is the molecule's own (`hs6_exact`)."""
    cn = _json(flows_dir / "cn_exports.json").get("codes", {})
    other = _json(flows_dir / "world_exports.json").get("codes", {})
    out: dict = {}
    for m in pack.molecules:
        ex: dict = {}
        if m.cn_hs8 and m.cn_hs8 in cn:
            c = cn[m.cn_hs8]
            parts = {k: v.get(str(year), 0) for k, v in c["top_destinations"].items() if v.get(str(year))}
            total = c["by_year"].get(str(year), 0)
            ex["CN"] = {
                "total": total,
                "partners": parts,
                "source": "China Customs (GACC), 8-digit code " + m.cn_hs8,
            }
        if m.hs6_exact and m.hs6:
            hs6 = m.hs6[0]
            p = flows_dir / f"{hs6}.parquet"
            if p.exists():
                q = (
                    f"SELECT partner_iso3, sum(qty_kg)/1000 FROM '{p}' WHERE flow='export' "
                    f"AND qty_kg IS NOT NULL AND period = '{year}' GROUP BY 1 ORDER BY 2 DESC"
                )
                rows = [(ISO3_TO_2[a], t) for a, t in duckdb.sql(q).fetchall() if a in ISO3_TO_2 and t >= 1]
                if rows:
                    ex["EU"] = {
                        "total": round(sum(t for _, t in rows)),
                        "partners": {c2: round(t) for c2, t in rows[:top]},
                        "source": f"Eurostat Comext DS-045409, extra-EU exports, HS {hs6}",
                    }
            ex.update(other.get(hs6, {}))
        if ex:
            out[m.id] = {"year": year, "unit": "t", "exporters": ex}
    return out


def trade_summary(pack: ChainPack, flows_dir: Path, first_year: int = 2015) -> dict:
    """EU27 imports by origin: hs6 → partner ISO2 → year → tonnes (Eurostat Comext)."""
    out: dict = {}
    for hs6 in sorted({h for m in pack.molecules for h in m.hs6}):
        p = flows_dir / f"{hs6}.parquet"
        if not p.exists():
            continue
        q = (
            f"SELECT partner_iso3, period, sum(qty_kg)/1000 FROM '{p}' WHERE flow='import' "
            f"AND qty_kg IS NOT NULL AND CAST(period AS INT) >= {first_year} GROUP BY 1,2"
        )
        for p3, year, t in duckdb.sql(q).fetchall():
            if p3 in ISO3_TO_2 and t >= 1:
                out.setdefault(hs6, {}).setdefault(ISO3_TO_2[p3], {})[str(year)] = round(t)
    return out


def sites_geojson(bundles: list[dict]) -> dict:
    """Sites with coordinates only. A site without lat/lon is not placed on the map (never invented)."""
    feats = []
    for b in bundles:
        for s in b["sites"]:
            if s.get("lat") is None or s.get("lon") is None:
                continue
            feats.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
                    "properties": {
                        "id": s["id"],
                        "name": s["name"],
                        "country": s["country"],
                        "geo_precision": s["geo_precision"],
                        "chain": b["chain"]["id"],
                        "unit_ids": s["unit_ids"],
                    },
                }
            )
    return {"type": "FeatureCollection", "features": feats}


def build(
    chains: list[Path],
    data_dir: Path = Path("data"),
    out_dir: Path = Path("build"),
    on: dt.date | None = None,
) -> list[Path]:
    store = Store(data_dir)
    con = load_duckdb(data_dir, out_dir / "graph.duckdb")
    con.close()
    app = out_dir / "app"
    app.mkdir(parents=True, exist_ok=True)
    written, bundles = [], []
    for path in chains:
        pack = load_chain(path)
        bundle = build_chain(pack, store, on)
        bundles.append(bundle)
        p = app / f"{pack.slug}.json"
        p.write_text(
            json.dumps(bundle, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8"
        )
        written.append(p)
    g = app / "sites.geojson"
    g.write_text(json.dumps(sites_geojson(bundles), ensure_ascii=False), encoding="utf-8")
    written.append(g)
    return written
