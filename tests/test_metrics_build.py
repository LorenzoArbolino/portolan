import json
from pathlib import Path

from portolan.build import build
from portolan.chain import load_chain
from portolan.metrics import downstream_dependants, molecule_metrics
from portolan.models import Claim, Company, Evidence, Site, Unit
from portolan.store import Store

PACK = Path(__file__).parent.parent / "chains" / "isoprenoids.yaml"
CITRAL = "mol:5392-40-5"
EV = "src:000000000001"
_n = iter(range(10_000))


def C(subject, field, value, grade="B", as_of="2024-08-29"):
    return Claim(
        id=f"clm:{next(_n):012x}",
        subject_id=subject,
        field=field,
        value=str(value),
        value_norm=value,
        capacity_basis="nameplate" if field == "capacity" else None,
        as_of=as_of,
        evidence_ids=[EV],
        extracted_by="test",
        confidence=grade,
        review_state="accepted",
    )


def world():
    sites = [
        Site(
            id="site:cn-yantai-01",
            name="A plant",
            country="CN",
            locality="Yantai",
            geo_precision="locality",
            lat=37.5,
            lon=121.4,
        ),
        Site(
            id="site:de-ludwigshafen-01",
            name="B plant",
            country="DE",
            locality="Ludwigshafen",
            geo_precision="locality",
        ),
        Site(
            id="site:cn-zhanjiang-01",
            name="C plant",
            country="CN",
            locality="Zhanjiang",
            geo_precision="locality",
        ),
    ]
    units = [Unit(id=f"unit:{s.id[5:]}:citral", site_id=s.id, molecule_id=CITRAL) for s in sites]
    claims = [
        C(units[0].id, "capacity", 48000.0),
        C(units[0].id, "status", "operating"),
        C(sites[0].id, "operator", "co:alpha"),
        C(units[1].id, "capacity", 32000.0),
        C(units[1].id, "status", "operating"),
        C(sites[1].id, "operator", "co:beta"),
        C(units[2].id, "status", "operating"),  # capacity unknown
    ]
    return sites, units, claims


def test_metrics_shares_hhi_and_traceability():
    pack = load_chain(PACK)
    sites, units, claims = world()
    m = molecule_metrics(pack, CITRAL, units, {s.id: s for s in sites}, claims)
    assert m.world_capacity_tpa.value == 80000
    assert m.units_counted == 2 and m.units_unknown_capacity == ["unit:cn-zhanjiang-01:citral"]
    assert m.share_by_company == {"co:alpha": 0.6, "co:beta": 0.4}
    assert m.share_by_country == {"CN": 0.6, "DE": 0.4}
    assert m.hhi_company.value == 3600 + 1600
    used = set(m.world_capacity_tpa.claim_ids)
    assert {c.id for c in claims if c.field in ("capacity", "operator")} <= used
    assert m.route_mix.value == {"unknown": 1.0}


def test_closed_units_do_not_count():
    pack = load_chain(PACK)
    sites, units, claims = world()
    claims.append(C(units[1].id, "status", "closed", as_of="2025-01-01"))
    m = molecule_metrics(pack, CITRAL, units, {s.id: s for s in sites}, claims)
    assert m.world_capacity_tpa.value == 48000


def test_pinch_point_dependants():
    pack = load_chain(PACK)
    deps = downstream_dependants(pack, CITRAL)
    assert "mol:79-77-6" in deps and "mol:127-47-9" in deps  # beta-ionone → vitamin A
    sites, units, claims = world()
    m = molecule_metrics(pack, CITRAL, units, {s.id: s for s in sites}, claims)
    assert m.pinch_point_score.value == round(0.6 * len(deps), 3)  # top site share 60%


def test_build_writes_bundle_and_geojson(tmp_path):
    sites, units, claims = world()
    store = Store(tmp_path / "data")
    store.append("sites", sites)
    store.append("units", units)
    store.append("claims", claims)
    store.append("companies", [Company(id="co:alpha", name="Alpha"), Company(id="co:beta", name="Beta")])
    store.append(
        "evidence",
        [
            Evidence(
                id=EV,
                url="https://example.com",
                retrieved_at="2026-10-26T10:00:00Z",
                source_type="trade_press",
                language="en",
                quote="q",
                quote_check="pass",
            )
        ],
    )
    paths = build([PACK], data_dir=tmp_path / "data", out_dir=tmp_path / "build")
    bundle = json.loads((tmp_path / "build/app/isoprenoids.json").read_text(encoding="utf-8"))
    assert bundle["licence"] == "ODbL-1.0"
    u = {x["id"]: x for x in bundle["units"]}["unit:cn-yantai-01:citral"]
    assert u["capacity"]["value"] == 48000 and u["capacity"]["claim_ids"]
    assert all(cid in bundle["claims"] for cid in u["capacity"]["claim_ids"])
    assert EV in bundle["evidence"] and bundle["evidence"][EV]["quote"] == "q"
    assert bundle["metrics"][CITRAL]["world_capacity_tpa"]["value"] == 80000
    geo = json.loads((tmp_path / "build/app/sites.geojson").read_text(encoding="utf-8"))
    assert [f["properties"]["id"] for f in geo["features"]] == ["site:cn-yantai-01"]  # only sites with coords
    assert (tmp_path / "build/graph.duckdb").exists() and len(paths) == 2


def test_merges_are_applied_at_build(tmp_path):
    from portolan.models import Merge

    sites, units, claims = world()
    dup = Site(
        id="site:de-ludwigshafen-am-rhein-01",
        name="BASF Ludwigshafen",
        country="DE",
        locality="Ludwigshafen am Rhein",
        geo_precision="locality",
    )
    dup_unit = Unit(
        id="unit:de-ludwigshafen-am-rhein-01:beta-ionone", site_id=dup.id, molecule_id="mol:79-77-6"
    )
    store = Store(tmp_path / "data")
    store.append("sites", [*sites, dup])
    store.append("units", [*units, dup_unit])
    store.append("claims", [*claims, C(dup_unit.id, "status", "operating")])
    store.append(
        "merges",
        [
            Merge(
                from_id=dup.id,
                to_id="site:de-ludwigshafen-01",
                reason="same Verbund site",
                decided_by="claude",
                date="2026-10-27",
            )
        ],
    )
    build([PACK], data_dir=tmp_path / "data", out_dir=tmp_path / "build")
    b = json.loads((tmp_path / "build/app/isoprenoids.json").read_text(encoding="utf-8"))
    assert dup.id not in {s["id"] for s in b["sites"]}
    lu = {s["id"]: s for s in b["sites"]}["site:de-ludwigshafen-01"]
    assert "unit:de-ludwigshafen-01:beta-ionone" in lu["unit_ids"]
    u = {x["id"]: x for x in b["units"]}["unit:de-ludwigshafen-01:beta-ionone"]
    assert u["status"]["value"] == "operating"


def test_trade_codes_label_shared_and_broad_codes():
    from portolan.build import trade_codes

    pack = load_chain(Path(__file__).parents[1] / "chains" / "isoprenoids.yaml")
    codes = trade_codes(pack, {"mol:80-56-8", "mol:127-91-3", "mol:2216-51-5", "mol:5392-40-5"})
    assert codes["CN 29021910"]["label"] == "alpha- + beta-pinene (shared code)"
    assert codes["HS 290219"]["broad"] and "pinenes" in codes["HS 290219"]["scope"]
    assert "label" not in codes["CN 29061100"] and not codes["HS 290611"]["broad"]  # menthol's own codes
    assert codes["HS 291219"]["broad"]  # citral: a family code, a footnote only
