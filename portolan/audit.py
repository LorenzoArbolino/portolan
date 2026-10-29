"""Audit: what the map shows, how much of it is sourced, where it contradicts itself.

Reads the built bundle (what the app actually displays) and the chain pack. Writes `build/audit.json` and
`build/audit.md`; `portolan audit --compare <old audit.json>` adds a before/after table. Pure functions apart
from `run`, so tests can feed small bundles.

Views: "default" is what a visitor sees on first load (estimates shown only if the bundle's
`display.estimates_default` is true); "all" is with estimates switched on."""

from __future__ import annotations

import datetime as dt
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from rapidfuzz import fuzz

from portolan.chain import ChainPack
from portolan.ids import company_key

EU27 = set("AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split())
UNIT_SHOWN = ("capacity", "production", "status", "start_year", "operator")
EVENT_FAMILY = {"force_majeure": "incident", "divestment": "acquisition"}
OWNERSHIP_EVENTS = {"acquisition", "divestment"}
SHARED_VALUE_LIMIT = 5
EVENT_WINDOW_DAYS = 14
OWNER_TEST_N = 25
CORE_MOLECULES = ("mol:5392-40-5", "mol:127-47-9", "mol:7695-91-2")  # citral, vitamin A and E acetate


def _num(r: dict | None) -> float | None:
    v = (r or {}).get("value")
    return float(v) if isinstance(v, int | float) else None


def shown(u: dict, field: str, estimates: bool) -> dict | None:
    """The resolved record the app displays for a field, or None (unknown)."""
    r = u.get(field)
    if r and r.get("grade") != "D":
        return r
    return u.get(f"{field}__estimate") if estimates else None


def region_of(country: str, pack: ChainPack) -> tuple[str, int | None]:
    codes = {r.code: r.priority for r in pack.regions}
    code = "EU" if country in EU27 else country
    return (code, codes[code]) if code in codes else ("other", None)


def _capacity_bucket(u: dict) -> str:
    r = u.get("capacity")
    if r and r.get("grade") in ("A", "B") and _num(r) is not None:
        return "AB"
    if r and r.get("grade") == "C" and _num(r) is not None:
        return "C"
    if u.get("capacity__estimate") and _num(u["capacity__estimate"]) is not None:
        return "D"
    return "none"


def _status_bucket(u: dict) -> str:
    r = u.get("status")
    if r and r.get("grade") != "D":
        return "sourced"
    if u.get("status__estimate"):
        return "estimated"
    if u.get("status_unconfirmed"):
        return "unconfirmed"
    return "unknown"


def _method(bundle: dict, r: dict | None) -> str | None:
    if not r:
        return None
    for cid in r.get("claim_ids", []):
        est = bundle["claims"].get(cid, {}).get("estimate")
        if est:
            return est["method"]
    return None


def molecules_section(bundle: dict, pack: ChainPack) -> dict:
    names = {m["id"]: m["name"] for m in bundle["molecules"]}
    out: dict = {}
    for mid in sorted({u["molecule_id"] for u in bundle["units"]}):
        us = [u for u in bundle["units"] if u["molecule_id"] == mid]
        cap: dict = {b: {"units": 0, "t": 0.0} for b in ("AB", "C", "D", "none")}
        for u in us:
            b = _capacity_bucket(u)
            cap[b]["units"] += 1
            v = _num(u.get("capacity") if b in ("AB", "C") else u.get("capacity__estimate"))
            cap[b]["t"] = round(cap[b]["t"] + (v or 0))
        st = Counter(_status_bucket(u) for u in us)
        try:
            w = pack.molecule(mid).weight
        except KeyError:
            w = None
        out[mid] = {
            "name": names.get(mid, mid),
            "weight": w,
            "units": len(us),
            "capacity": cap,
            "production_units": sum(1 for u in us if u.get("production")),
            "status": {k: st.get(k, 0) for k in ("sourced", "estimated", "unconfirmed", "unknown")},
        }
    return out


def sites_section(bundle: dict, pack: ChainPack) -> dict:
    by_country = Counter(s["country"] for s in bundle["sites"])
    by_region: Counter = Counter()
    by_priority: Counter = Counter()
    for s in bundle["sites"]:
        code, prio = region_of(s["country"], pack)
        by_region[code] += 1
        by_priority[f"priority {prio}" if prio else "unlisted"] += 1
    return {
        "total": len(bundle["sites"]),
        "by_country": dict(by_country.most_common()),
        "by_region": dict(by_region.most_common()),
        "by_priority": dict(sorted(by_priority.items())),
    }


def estimates_section(bundle: dict) -> dict:
    by_method: Counter = Counter()
    for u in bundle["units"]:
        for f in UNIT_SHOWN:
            m = _method(bundle, u.get(f"{f}__estimate"))
            if m:
                by_method[f"{f}: {m}"] += 1
    return dict(sorted(by_method.items()))


def _operators(bundle: dict) -> set[str]:
    rows = bundle["sites"] + bundle["units"]
    return {str(r["operator"]["value"]) for r in rows if r.get("operator")}


def _group(bundle: dict, co: str) -> str:
    return next((c.get("group", co) for c in bundle["companies"] if c["id"] == co), co)


def must_find_section(bundle: dict) -> list[dict]:
    return bundle.get("must_find", [])


def status_coverage(bundle: dict, molecules: tuple[str, ...]) -> dict:
    """Status coverage test per molecule: every unit on the map has a sourced status (capacity sourced
    or shown as unknown, which the map always does)."""
    out = {}
    for mid in molecules:
        us = [u for u in bundle["units"] if u["molecule_id"] == mid]
        missing = [u["id"] for u in us if not (u.get("status") and u["status"].get("grade") != "D")]
        out[mid] = {"units": len(us), "missing_status": missing, "pass": bool(us) and not missing}
    return out


# ---------------------------------------------------------------- duplicates


def duplicate_companies(bundle: dict) -> list[list[str]]:
    """Displayed companies that look like one: same name key, or a fuzzy match on the key with the same (or an
    unknown) HQ country. Candidates only: a person decides each merge."""
    cos = bundle["companies"]
    keys = {c["id"]: company_key(c["name"]) for c in cos}
    pairs = []
    for i, a in enumerate(cos):
        for b in cos[i + 1 :]:
            ka, kb = keys[a["id"]], keys[b["id"]]
            ca, cb = a.get("hq_country"), b.get("hq_country")
            if ca and cb and ca != cb:
                continue
            first2 = ka.split("-")[:2] == kb.split("-")[:2] and len(ka.split("-")) >= 2
            if ka == kb or first2 or fuzz.token_set_ratio(ka.replace("-", " "), kb.replace("-", " ")) >= 90:
                pairs.append(sorted([a["id"], b["id"]]))
    return sorted(pairs)


def _anchors(bundle: dict, subject: str) -> set[str]:
    """Sites an event is about: a unit's site, a site, or every site a company operates."""
    if subject.startswith("unit:"):
        u = next((u for u in bundle["units"] if u["id"] == subject), None)
        return {u["site_id"]} if u else {subject}
    if subject.startswith("co:"):
        sites = {s["id"] for s in bundle["sites"] if (s.get("operator") or {}).get("value") == subject}
        sites |= {u["site_id"] for u in bundle["units"] if (u.get("operator") or {}).get("value") == subject}
        return sites or {subject}
    return {subject}


def duplicate_events(bundle: dict) -> list[list[str]]:
    evs = sorted(bundle["events"], key=lambda e: e["date"])
    anchors = {e["id"]: set().union(*(_anchors(bundle, s) for s in e["subjects"])) for e in evs}
    groups: list[list[str]] = []
    seen: set[str] = set()
    for i, a in enumerate(evs):
        if a["id"] in seen:
            continue
        grp = [a["id"]]
        fa = EVENT_FAMILY.get(a["type"], a["type"])
        da = dt.date.fromisoformat(a["date"])
        for b in evs[i + 1 :]:
            db = dt.date.fromisoformat(b["date"])
            if (db - da).days > EVENT_WINDOW_DAYS:
                break
            if EVENT_FAMILY.get(b["type"], b["type"]) == fa and anchors[a["id"]] & anchors[b["id"]]:
                grp.append(b["id"])
        if len(grp) > 1:
            seen.update(grp)
            groups.append(grp)
    return groups


def _norm_place(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def duplicate_sites(bundle: dict) -> list[list[str]]:
    by: dict[tuple, list[str]] = defaultdict(list)
    for s in bundle["sites"]:
        op = (s.get("operator") or {}).get("value")
        by[(s["country"], _norm_place(s.get("locality", "")), op)].append(s["id"])
    return sorted(sorted(v) for v in by.values() if len(v) > 1)


# ---------------------------------------------------------------- contradictions


def _site_operators(bundle: dict, sid: str) -> set[str]:
    s = next((x for x in bundle["sites"] if x["id"] == sid), {})
    ops = {(s.get("operator") or {}).get("value")}
    ops |= {(u.get("operator") or {}).get("value") for u in bundle["units"] if u["site_id"] == sid}
    return {o for o in ops if o}


def _parents(bundle: dict, co: str) -> set[str]:
    c = next((x for x in bundle["companies"] if x["id"] == co), {})
    return set(c.get("parents", [])) | {c.get("group", co), co}


def sold_asset_contradictions(bundle: dict, on: dt.date) -> list[dict]:
    """Ownership events (acquisition/divestment) dated on or before the build date. A structured event
    (`ownership: {buyer, sites, kind}`) passes when every listed site's operator, or that operator's parent
    or group, is the new owner. An event without that structure is listed: the map cannot tell whether it
    still credits the seller."""
    out = []
    for e in bundle["events"]:
        if e["type"] not in OWNERSHIP_EVENTS or dt.date.fromisoformat(e["date"]) > on:
            continue
        own = e.get("ownership")
        if not own:
            sites = sorted(
                {a for s in e["subjects"] if s.startswith(("unit:", "site:")) for a in _anchors(bundle, s)}
            )
            out.append(
                {
                    "event": e["id"],
                    "sites": sites,
                    "shown_operators": sorted({o for sid in sites for o in _site_operators(bundle, sid)}),
                    "note": "ownership change without a structured site list and new owner",
                }
            )
            continue
        for sid in own.get("sites", []):
            ops = _site_operators(bundle, sid)
            owners = set().union(*(_parents(bundle, o) for o in ops)) if ops else set()
            if own["buyer"] not in owners:
                out.append(
                    {"event": e["id"], "site": sid, "shown_operators": sorted(ops), "new_owner": own["buyer"]}
                )
    return out


def shared_values(bundle: dict, estimates: bool) -> list[dict]:
    by: dict[tuple, list[str]] = defaultdict(list)
    sourced: dict[tuple, bool] = defaultdict(lambda: True)
    for u in bundle["units"]:
        r = shown(u, "capacity", estimates)
        v = _num(r)
        if v is None:
            continue
        by[("capacity", v)].append(u["id"])
        sourced[("capacity", v)] &= r.get("grade") != "D"
    return [
        {"field": f, "value": v, "units": len(ids), "sourced": sourced[(f, v)], "examples": ids[:4]}
        for (f, v), ids in sorted(by.items(), key=lambda kv: -len(kv[1]))
        if len(ids) > SHARED_VALUE_LIMIT and not sourced[(f, v)]
    ]


def exports_above_capacity(bundle: dict) -> list[dict]:
    out = []
    names = {m["id"]: m["name"] for m in bundle["molecules"]}
    for mid, fl in (bundle.get("flows") or {}).items():
        sourced = sum(
            _num(u.get("capacity")) or 0
            for u in bundle["units"]
            if u["molecule_id"] == mid and (u.get("capacity") or {}).get("grade") not in (None, "D")
        )
        world = _num((bundle.get("market", {}).get(mid) or {}).get("world_capacity"))
        known = max(sourced, world or 0)
        for ex, d in fl["exporters"].items():
            if d.get("estimate"):
                continue
            if d["total"] > known:
                basis = next((m.get("trade_basis") for m in bundle["molecules"] if m["id"] == mid), None)
                out.append(
                    {
                        "basis": basis,
                        "molecule": names.get(mid, mid),
                        "exporter": ex,
                        "exports_t": round(d["total"]),
                        "year": fl["year"],
                        "sourced_capacity_t": round(sourced),
                        "world_capacity_t": world,
                    }
                )
    return out


def shared_trade_series(bundle: dict) -> list[dict]:
    """A trade code shown on more than one molecule's figures (China 8-digit, or an HS6 the EU panel uses)."""
    shown_mols = {u["molecule_id"] for u in bundle["units"]}
    by: dict[str, list[str]] = defaultdict(list)
    for m in bundle["molecules"]:
        if m["id"] not in shown_mols:
            continue
        if m.get("cn_hs8"):
            by[f"CN {m['cn_hs8']}"].append(m["name"])
        if m.get("hs6") and m["hs6"][0] in (bundle.get("trade") or {}):
            by[f"HS {m['hs6'][0]}"].append(m["name"])
    labelled = {k for k, d in (bundle.get("trade_codes") or {}).items() if d.get("label")}
    shared = [{"code": k, "molecules": v} for k, v in sorted(by.items()) if len(v) > 1 and k not in labelled]
    broad = [
        {"code": f"HS {m['hs6'][0]}", "molecule": m["name"]}
        for m in bundle["molecules"]
        if m["id"] in shown_mols
        and m.get("hs6")
        and not m.get("hs6_exact")
        and m["hs6"][0] in (bundle.get("trade") or {})
        and m["hs6"][0] not in (bundle.get("display", {}).get("trade_footnote_codes") or [])
    ]
    return [{"kind": "shared", **s} for s in shared] + [{"kind": "broad_on_figures", **b} for b in broad]


PLACE_WORDS = {
    "US": ("U.S.", " US ", "USA", "America", "Florida", "Georgia", "Carolina", "Texas", "Jacksonville"),
    "DE": ("Germany", "Deutschland", "GmbH"),
    "CN": ("China", "Chinese"),
    "IN": ("India",),
    "JP": ("Japan",),
    "FR": ("France",),
    "CH": ("Switzerland", "Swiss"),
    "MY": ("Malaysia", "Sdn Bhd"),
    "BR": ("Brazil", "Brasil", "Ltda"),
}


def operator_place_mismatch(bundle: dict) -> list[dict]:
    """Sites whose operator's name points at another country ("… US terpene operations" running a German
    plant): usually a company record built from the wrong context."""
    cos = {c["id"]: c for c in bundle["companies"]}
    out = []
    for s in bundle["sites"]:
        op = cos.get((s.get("operator") or {}).get("value"), {})
        name = f" {op.get('name', '')} "
        for cc, words in PLACE_WORDS.items():
            if cc != s["country"] and any(w in name for w in words):
                out.append(
                    {"site": s["id"], "country": s["country"], "operator": op["id"], "name": op["name"]}
                )
                break
    return out


# ---------------------------------------------------------------- plant-owner test


def plant_owner_test(bundle: dict, pack: ChainPack, contradicted_sites: set[str]) -> dict:
    """The 25 plants a buyer is most likely to open (most weight-3 capacity, then most weight-3 units): every
    field the default view shows must be sourced (A–C) or shown as unknown, and the operator must not be
    contradicted by a recorded sale."""
    est_default = bool(bundle.get("display", {}).get("estimates_default", True))
    weights = {m.id: m.weight for m in pack.molecules}
    top_w = max(weights.values(), default=1)
    score: dict[str, list[float]] = defaultdict(lambda: [0.0, 0])
    for u in bundle["units"]:
        if weights.get(u["molecule_id"]) != top_w:
            continue
        s = score[u["site_id"]]
        s[0] += _num(u.get("capacity")) or _num(u.get("capacity__estimate")) or 0
        s[1] += 1
    picked = sorted(score, key=lambda k: (-score[k][1], -score[k][0], k))[:OWNER_TEST_N]
    violations = []
    sites = {s["id"]: s for s in bundle["sites"]}
    for sid in picked:
        s = sites.get(sid, {})
        for f in ("operator",):
            r = shown(s, f, est_default)
            if r and r.get("grade") == "D":
                violations.append({"site": sid, "field": f, "issue": "estimate shown by default"})
        if sid in contradicted_sites:
            violations.append({"site": sid, "field": "operator", "issue": "contradicted by a recorded sale"})
        for u in bundle["units"]:
            if u["site_id"] != sid:
                continue
            for f in UNIT_SHOWN:
                r = shown(u, f, est_default)
                if r and r.get("grade") == "D":
                    violations.append(
                        {"site": sid, "unit": u["id"], "field": f, "issue": "estimate shown by default"}
                    )
    return {
        "estimates_default": est_default,
        "plants": picked,
        "violations": violations,
        "pass": not violations and bool(picked),
    }


# ---------------------------------------------------------------- headline (rule 3)


def cross_molecule_total(bundle: dict) -> dict:
    """What a chain-wide capacity sum would add up to (with estimates). Shown for the record: rule 3 says
    no screen may display it."""
    t = sum(_num(shown(u, "capacity", True)) or 0 for u in bundle["units"])
    return {"t_all_units": round(t), "displayed": bool(bundle.get("display", {}).get("chain_total", True))}


def audit(bundle: dict, pack: ChainPack) -> dict:
    on = dt.date.fromisoformat(bundle["built_on"])
    sold = sold_asset_contradictions(bundle, on)
    a = {
        "built_on": bundle["built_on"],
        "totals": {
            "sites": len(bundle["sites"]),
            "units": len(bundle["units"]),
            "companies": len(bundle["companies"]),
            "operators": len(_operators(bundle)),
            "groups": len({_group(bundle, c) for c in _operators(bundle)}),
            "events": len(bundle["events"]),
        },
        "molecules": molecules_section(bundle, pack),
        "sites": sites_section(bundle, pack),
        "estimates": estimates_section(bundle),
        "must_find": must_find_section(bundle),
        "status_coverage": status_coverage(bundle, CORE_MOLECULES),
        "duplicates": {
            "companies": duplicate_companies(bundle),
            "events": duplicate_events(bundle),
            "sites": duplicate_sites(bundle),
        },
        "contradictions": {
            "sold_assets": sold,
            "shared_values_all": shared_values(bundle, True),
            "shared_values_default": shared_values(
                bundle, bool(bundle.get("display", {}).get("estimates_default", True))
            ),
            "exports_above_capacity": exports_above_capacity(bundle),
            "trade_series": shared_trade_series(bundle),
            "operator_place": operator_place_mismatch(bundle),
        },
        "cross_molecule_total": cross_molecule_total(bundle),
    }
    a["plant_owner_test"] = plant_owner_test(
        bundle, pack, {x.get("site") for x in sold} | {s for x in sold for s in x.get("sites", [])}
    )
    a["summary"] = summary(a)
    a["_molecules"] = [{"id": m["id"], "name": m["name"]} for m in bundle["molecules"]]
    return a


def summary(a: dict) -> dict:
    cap = Counter()
    tonnes = Counter()
    st = Counter()
    for m in a["molecules"].values():
        for b, d in m["capacity"].items():
            cap[b] += d["units"]
            tonnes[b] += d["t"]
        st.update(m["status"])
    mf = a["must_find"]
    c = a["contradictions"]
    return {
        "units": a["totals"]["units"],
        "units_capacity_AB": cap["AB"],
        "units_capacity_C": cap["C"],
        "units_capacity_estimated": cap["D"],
        "units_capacity_unknown": cap["none"],
        "share_of_capacity_tonnes_estimated": round(tonnes["D"] / max(1, sum(tonnes.values())), 3),
        "units_status_sourced": st["sourced"],
        "units_status_estimated": st["estimated"],
        "units_status_unconfirmed": st["unconfirmed"],
        "units_status_unknown": st["unknown"],
        "must_find_total": len(mf),
        "must_find_resolved": sum(1 for x in mf if x.get("state") in ("found", "resolved")),
        "must_find_molecules_open": sum(
            1 for x in mf for d in x.get("molecules", {}).values() if d["state"] == "open"
        ),
        "status_coverage_pass": ", ".join(
            k.split(":")[1] for k, v in a["status_coverage"].items() if v["pass"]
        )
        or "none",
        "sites": a["totals"]["sites"],
        "sites_priority_1": a["sites"]["by_priority"].get("priority 1", 0),
        "sites_priority_2": a["sites"]["by_priority"].get("priority 2", 0),
        "sites_priority_3_or_unlisted": a["sites"]["by_priority"].get("priority 3", 0)
        + a["sites"]["by_priority"].get("unlisted", 0),
        "companies": a["totals"]["companies"],
        "operator_companies": a["totals"]["operators"],
        "operator_groups": a["totals"]["groups"],
        "duplicate_company_pairs": len(a["duplicates"]["companies"]),
        "duplicate_event_groups": len(a["duplicates"]["events"]),
        "duplicate_site_groups": len(a["duplicates"]["sites"]),
        "sold_asset_contradictions": len(c["sold_assets"]),
        "shared_estimated_values_all": len(c["shared_values_all"]),
        "exports_above_capacity": len(c["exports_above_capacity"]),
        "trade_series_issues": len(c["trade_series"]),
        "operator_place_mismatches": len(c["operator_place"]),
        "chain_total_displayed": a["cross_molecule_total"]["displayed"],
        "plant_owner_violations": len(a["plant_owner_test"]["violations"]),
    }


# ---------------------------------------------------------------- markdown


def _kt(t: float) -> str:
    return f"{t / 1000:,.1f} kt" if t >= 1000 else f"{t:,.0f} t"


def compare_table(before: dict, after: dict) -> str:
    rows = ["| Metric | Before | After |", "|---|---:|---:|"]
    for k in after:
        b = before.get(k, "–")
        if b != after[k]:
            rows.append(f"| {k} | {b} | **{after[k]}** |")
        else:
            rows.append(f"| {k} | {b} | {after[k]} |")
    return "\n".join(rows)


def to_markdown(a: dict, before: dict | None = None) -> str:
    s = a["summary"]
    L = [f"# Portolan audit · built {a['built_on']}", ""]
    if before:
        L += ["## Before → after", "", compare_table(before["summary"], s), ""]
    L += ["## Summary", "", "| Metric | Value |", "|---|---:|"]
    L += [f"| {k} | {v} |" for k, v in s.items()]
    L += [
        "",
        "## Capacity and status by molecule",
        "",
        "Units (tonnes). AB = grade A/B source, C = aggregator-grade source, D = estimate, none = unknown.",
        "",
        "| Molecule | w | Units | AB | C | D (est.) | Unknown | Status sourced / est. / unconf. / unknown |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for m in sorted(a["molecules"].values(), key=lambda m: (-(m["weight"] or 0), m["name"])):
        c = m["capacity"]

        def cell(b: str, c: dict = c) -> str:
            return f"{c[b]['units']}" + (f" ({_kt(c[b]['t'])})" if c[b]["t"] else "")

        st = m["status"]
        L.append(
            f"| {m['name']} | {m['weight'] or ''} | {m['units']} | {cell('AB')} | {cell('C')} | "
            f"{cell('D')} | {c['none']['units']} | "
            f"{st['sourced']} / {st['estimated']} / {st['unconfirmed']} / {st['unknown']} |"
        )
    ss = a["sites"]
    L += ["", "## Sites", "", f"{ss['total']} sites.", ""]
    L += ["| Region | Sites |", "|---|---:|"] + [f"| {k} | {v} |" for k, v in ss["by_region"].items()]
    L += [
        "",
        "By priority: " + ", ".join(f"{k} {v}" for k, v in ss["by_priority"].items()),
        "",
        "By country: " + ", ".join(f"{k} {v}" for k, v in ss["by_country"].items()),
        "",
        "## Estimates by method (unit fields)",
        "",
    ]
    L += [f"- {k}: {v}" for k, v in a["estimates"].items()] or ["- none"]
    L += ["", "## Must-find checklist", ""]
    if not a["must_find"]:
        L.append("Not defined in the chain pack yet.")
    else:
        names = {m["id"]: m["name"].split(" (")[0] for m in a.get("_molecules", [])}
        L += ["| Item | w | State | Molecules |", "|---|---:|---|---|"]
        for x in a["must_find"]:
            mols = "; ".join(
                f"{names.get(k, k)}: {d['state']}"
                + (f" (capacity {d['capacity']})" if d["state"] == "found" else "")
                + (f" ({d['detail']})" if d.get("detail") else "")
                for k, d in x["molecules"].items()
            )
            L.append(f"| {x['label']} | {x['weight']} | **{x['state']}** | {mols} |")
    L += ["", "## Status coverage test (every unit has a sourced status)", ""]
    for k, v in a["status_coverage"].items():
        L.append(
            f"- {k}: {'PASS' if v['pass'] else 'FAIL'}, {v['units']} units"
            + (f"; no sourced status: {', '.join(v['missing_status'])}" if v["missing_status"] else "")
        )
    d = a["duplicates"]
    L += ["", "## Duplicate candidates", ""]
    L += ["**Companies**", ""] + ([f"- {' · '.join(p)}" for p in d["companies"]] or ["- none"])
    L += ["", "**Events** (same site, ±14 days, same type family)", ""]
    L += [f"- {' · '.join(g)}" for g in d["events"]] or ["- none"]
    L += ["", "**Sites** (same country, locality, operator)", ""]
    L += [f"- {' · '.join(g)}" for g in d["sites"]] or ["- none"]
    c = a["contradictions"]
    L += ["", "## Contradictions", "", "**Assets credited after a recorded sale**", ""]
    L += [f"- {json.dumps(x, ensure_ascii=False)}" for x in c["sold_assets"]] or ["- none"]
    L += ["", f"**One estimated value shared by more than {SHARED_VALUE_LIMIT} units** (estimates on)", ""]
    L += [
        f"- {x['value']:g} t/a on {x['units']} units, e.g. {', '.join(x['examples'])}"
        for x in c["shared_values_all"]
    ]
    L += ["- none"] if not c["shared_values_all"] else []
    L += ["", "**Exports above the known capacity for the molecule**", ""]
    L += [
        f"- {x['molecule']}: {x['exporter']} exported {_kt(x['exports_t'])} in {x['year']}; sourced capacity "
        f"{_kt(x['sourced_capacity_t'])}"
        + (f", world figure {_kt(x['world_capacity_t'])}" if x["world_capacity_t"] else "")
        + (f". Annotated: {x['basis']}" if x.get("basis") else "")
        for x in c["exports_above_capacity"]
    ] or ["- none"]
    L += ["", "**Operator named after another country**", ""]
    L += [f"- {x['site']} ({x['country']}): {x['name']}" for x in c["operator_place"]] or ["- none"]
    L += ["", "**Trade series**", ""]
    L += [
        f"- {x['code']} shown on: {', '.join(x['molecules'])}"
        if x["kind"] == "shared"
        else f"- {x['code']} is broad but shown on {x['molecule']}'s figures"
        for x in c["trade_series"]
    ] or ["- none"]
    t = a["cross_molecule_total"]
    L += [
        "",
        "## Cross-molecule total (rule 3)",
        "",
        f"All units' capacity added up (estimates on): {_kt(t['t_all_units'])}. Shown in the app: "
        f"{'yes (violation)' if t['displayed'] else 'no'}.",
    ]
    p = a["plant_owner_test"]
    L += [
        "",
        "## Plant-owner test",
        "",
        f"{len(p['plants'])} plants on the highest-weight molecules; estimates shown by default: "
        f"{p['estimates_default']}. **{'PASS' if p['pass'] else 'FAIL'}**, "
        f"{len(p['violations'])} violations.",
        "",
    ]
    by_site = Counter(v["site"] for v in p["violations"])
    L += [f"- {sid}: {n}" for sid, n in by_site.most_common()]
    return "\n".join(L) + "\n"


def run(bundle_path: Path, pack: ChainPack, out_dir: Path, compare: Path | None = None) -> dict:
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    a = audit(bundle, pack)
    before = json.loads(compare.read_text(encoding="utf-8")) if compare and compare.exists() else None
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "audit.json").write_text(json.dumps(a, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "audit.md").write_text(to_markdown(a, before), encoding="utf-8")
    return a
