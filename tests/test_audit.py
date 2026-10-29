"""Audit: counts, duplicates and contradictions on a small hand-made bundle."""

from pathlib import Path

from portolan.audit import audit, to_markdown
from portolan.chain import load_chain

PACK = load_chain(Path(__file__).parents[1] / "chains" / "isoprenoids.yaml")
CITRAL = "mol:5392-40-5"


def R(value, grade="A", claim="clm:000000000001", as_of="2025-01-01"):
    return {"outcome": "resolved", "value": value, "grade": grade, "claim_ids": [claim], "as_of": as_of}


def bundle(**over):
    b = {
        "built_on": "2026-10-28",
        "molecules": [{"id": CITRAL, "name": "citral", "hs6": ["291219"]}],
        "sites": [
            {"id": "site:de-a-01", "country": "DE", "locality": "A", "operator": R("co:x")},
            {"id": "site:cn-b-01", "country": "CN", "locality": "B", "operator": R("co:y")},
        ],
        "units": [
            {
                "id": "unit:de-a-01:citral",
                "site_id": "site:de-a-01",
                "molecule_id": CITRAL,
                "capacity": R(40000),
            },
            {
                "id": "unit:cn-b-01:citral",
                "site_id": "site:cn-b-01",
                "molecule_id": CITRAL,
                "capacity__estimate": R(2800, "D", "clm:00000000000e"),
                "status__estimate": R("operating", "D", "clm:00000000000f"),
            },
        ],
        "companies": [
            {"id": "co:x", "name": "Acme Paper Co", "hq_country": "US"},
            {"id": "co:x2", "name": "Acme Paper - Mill One"},
            {"id": "co:y", "name": "Other"},
        ],
        "claims": {
            "clm:00000000000e": {"estimate": {"method": "capacity_from_chain_peers"}},
            "clm:00000000000f": {"estimate": {"method": "status_from_recent_evidence"}},
        },
        "events": [],
        "flows": {CITRAL: {"year": 2025, "exporters": {"CN": {"total": 90000}}}},
        "market": {},
        "trade": {},
        "display": {"estimates_default": False, "chain_total": False},
    }
    b.update(over)
    return b


def test_counts_and_buckets():
    a = audit(bundle(), PACK)
    m = a["molecules"][CITRAL]
    assert m["weight"] == 3
    assert m["capacity"]["AB"] == {"units": 1, "t": 40000}
    assert m["capacity"]["D"]["units"] == 1
    assert m["status"] == {"sourced": 0, "estimated": 1, "unconfirmed": 0, "unknown": 1}
    assert a["sites"]["by_priority"] == {"priority 1": 2}
    assert a["estimates"] == {
        "capacity: capacity_from_chain_peers": 1,
        "status: status_from_recent_evidence": 1,
    }
    assert to_markdown(a, before=a).startswith("# Portolan audit")


def test_duplicate_companies_and_events():
    ev = [
        {
            "id": "ev:2024-07-29:a",
            "date": "2024-07-29",
            "type": "incident",
            "subjects": ["unit:de-a-01:citral"],
        },
        {"id": "ev:2024-07-30:b", "date": "2024-07-30", "type": "force_majeure", "subjects": ["co:x"]},
        {"id": "ev:2024-09-30:c", "date": "2024-09-30", "type": "incident", "subjects": ["site:de-a-01"]},
    ]
    a = audit(bundle(events=ev), PACK)
    assert a["duplicates"]["companies"] == [["co:x", "co:x2"]]
    assert a["duplicates"]["events"] == [["ev:2024-07-29:a", "ev:2024-07-30:b"]]


def test_contradictions():
    ev = [
        {
            "id": "ev:2026-09-01:sale",
            "date": "2026-09-01",
            "type": "divestment",
            "subjects": ["site:de-a-01"],
        },
        {
            "id": "ev:2026-09-02:sale2",
            "date": "2026-09-02",
            "type": "acquisition",
            "subjects": ["co:x"],
            "ownership": {"buyer": "co:new", "sites": ["site:de-a-01"], "kind": "operator"},
        },
    ]
    a = audit(bundle(events=ev), PACK)
    sold = a["contradictions"]["sold_assets"]
    assert len(sold) == 2 and sold[1]["new_owner"] == "co:new"
    assert a["contradictions"]["exports_above_capacity"][0]["exporter"] == "CN"
    # once the site shows the buyer, the structured event passes
    b = bundle(events=ev[1:])
    b["sites"][0]["operator"] = R("co:new")
    assert audit(b, PACK)["contradictions"]["sold_assets"] == []


def test_shared_estimated_value_and_owner_test():
    units = [
        {
            "id": f"unit:cn-t{i}-01:citral",
            "site_id": f"site:cn-t{i}-01",
            "molecule_id": CITRAL,
            "capacity__estimate": R(2800, "D", "clm:00000000000e"),
        }
        for i in range(6)
    ]
    sites = [{"id": f"site:cn-t{i}-01", "country": "CN", "locality": f"T{i}"} for i in range(6)]
    b = bundle(units=units, sites=sites)
    a = audit(b, PACK)
    assert a["contradictions"]["shared_values_all"][0]["units"] == 6
    assert a["contradictions"]["shared_values_default"] == []  # estimates off by default
    assert a["plant_owner_test"]["pass"]
    b["display"]["estimates_default"] = True
    assert not audit(b, PACK)["plant_owner_test"]["pass"]
