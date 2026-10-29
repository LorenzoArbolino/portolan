"""Step 3: planner, runner (stub adapter), collector. Offline."""

import json
import shutil
from pathlib import Path

import pytest

from pipeline import plan as planner
from pipeline.collect import collect, evidence_grade
from pipeline.run import run
from pipeline.validators.quote_check import QuoteResult
from portolan.chain import load_chain
from portolan.store import Store

ROOT = Path(__file__).parent.parent
PACK = ROOT / "chains" / "isoprenoids.yaml"
STUB = [("stub", "stub")]

URL_A = "https://example.com/news/citral"
URL_P = "https://press.example.org/wanhua"
LINES = [
    {
        "kind": "evidence",
        "url": URL_A,
        "retrieved_at": "2026-10-26T10:00:00Z",
        "publisher": "Example Aroma",
        "published_at": "2024-08-29",
        "source_type": "company_primary",
        "language": "en",
        "quote": "The plant has an annual capacity of 48,000 tonnes",
    },
    {
        "kind": "candidate_company",
        "name": "Example Aroma Chemicals Ltd",
        "hq_country": "CN",
        "type": ["producer"],
        "evidence_refs": [0],
    },
    {
        "kind": "candidate_site",
        "name": "Exampletown citral plant",
        "country": "CN",
        "locality": "Exampletown",
        "company_ref": 1,
        "evidence_refs": [0],
    },
    {
        "kind": "claim",
        "subject_ref": {"candidate_site": 2, "molecule": "mol:5392-40-5"},
        "field": "exists",
        "value": "true",
        "as_of": "2024-08-29",
        "evidence_refs": [0],
    },
    {
        "kind": "claim",
        "subject_ref": {"candidate_site": 2, "molecule": "mol:5392-40-5"},
        "field": "capacity",
        "value": "48,000",
        "unit_raw": "tonnes per year",
        "capacity_basis": "nameplate",
        "as_of": "2024-08-29",
        "evidence_refs": [0],
    },
    {
        "kind": "evidence",
        "url": URL_P,
        "retrieved_at": "2026-10-26T10:00:00Z",
        "publisher": "Trade weekly",
        "source_type": "trade_press",
        "language": "en",
        "quote": "the plant runs at 300 TPD",
    },
    {
        "kind": "claim",
        "subject_ref": {"candidate_site": 2, "molecule": "mol:5392-40-5"},
        "field": "capacity",
        "value": "300",
        "unit_raw": "TPD",
        "capacity_basis": "design",
        "as_of": "2025-01-01",
        "evidence_refs": [5],
    },
    {
        "kind": "claim",
        "subject_ref": {"candidate_site": 2, "molecule": "mol:5392-40-5"},
        "field": "status",
        "value": "permanently closed",
        "as_of": "2025-06-01",
        "evidence_refs": [5],
    },
    {"kind": "not_found", "query": "start year of the Exampletown unit", "searched": [URL_A]},
    {
        "kind": "claim",
        "subject_ref": {"candidate_site": 99, "molecule": "mol:5392-40-5"},
        "field": "exists",
        "value": "true",
        "as_of": "2024-08-29",
        "evidence_refs": [0],
    },
]


def fake_checker(quote, url):
    return QuoteResult("pass", 1.0) if url in (URL_A, URL_P) else QuoteResult("fail", 0.2, reason="no")


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "chains").mkdir()
    shutil.copy(PACK, tmp_path / "chains" / "isoprenoids.yaml")
    return tmp_path


def _plan_and_run(ws, run_id, lines):
    jobs = planner.plan(PACK, ["J01"], ["mol:5392-40-5"], ["CN"], data_dir=ws / "data", runs_dir=ws / "runs")
    assert len(jobs) == 1
    jobs[0].inputs["stub_lines"] = lines
    planner.write_queue(jobs, run_id, ws / "queue")
    run(run_id, n=2, override=STUB, runs_dir=ws / "runs", queue_dir=ws / "queue")
    return collect(
        run_id,
        runs_dir=ws / "runs",
        data_dir=ws / "data",
        review_path=ws / "review" / "queue.jsonl",
        checker=fake_checker,
        chains_dir=ws / "chains",
    )


PACK_W = {m.id: m.weight for m in load_chain(PACK).molecules}


def test_job_ids_are_deterministic():
    a = planner.plan(PACK, ["J01"], skip_done=False, data_dir="/nonexistent")
    b = planner.plan(PACK, ["J01"], skip_done=False, data_dir="/nonexistent")
    assert [j.job_id for j in a] == [j.job_id for j in b]
    # effort follows importance: weight >= 2 (10 molecules; TMHQ is context), every region, best score first
    assert len(a) == 10 * 9
    assert len({j.job_id for j in a}) == len(a)
    first, last = a[0].inputs, a[-1].inputs
    assert PACK_W[first["molecule_id"]] == 3 and first["region"] in ("EU", "CH", "CN", "IN")
    assert PACK_W[last["molecule_id"]] == 2 and last["region"] == "ID"
    assert not any(PACK_W[j.inputs["molecule_id"]] == 1 for j in a)  # no new weight-1 jobs
    capped = planner.plan_j01(load_chain(PACK), max_jobs=5)
    assert len(capped) == 5 and all(PACK_W[j.inputs["molecule_id"]] == 3 for j in capped)


def test_leads_filtered_by_region():
    jobs = planner.plan(PACK, ["J01"], ["mol:5392-40-5"], ["CN"], skip_done=False, data_dir="/nonexistent")
    leads = jobs[0].inputs["leads"]
    assert any("Wanhua" in x for x in leads) and not any("Ludwigshafen" in x for x in leads)
    prompt = planner.render("enumerate_producers", jobs[0].inputs)
    assert "No quote, no claim." in prompt and "{{" not in prompt and "citral" in prompt


def test_dry_run_is_deterministic(tmp_path):
    results = []
    for k in (1, 2):
        ws = tmp_path / f"ws{k}"
        (ws / "chains").mkdir(parents=True)
        shutil.copy(PACK, ws / "chains" / "isoprenoids.yaml")
        _plan_and_run(ws, "dry", LINES)
        store = Store(ws / "data")
        results.append(
            {t: sorted(store.ids(t)) for t in ("companies", "sites", "units", "claims", "evidence")}
        )
    assert results[0] == results[1]
    assert results[0]["units"] == ["unit:cn-exampletown-01:citral"]


def test_collector_grades_and_review(ws):
    batch, summary = _plan_and_run(ws, "r1", LINES)
    claims = {(c.field, str(c.value)): c for c in batch.claims}
    cap = claims[("capacity", "48,000")]
    assert cap.value_norm == 48000 and cap.confidence == "A" and cap.review_state == "accepted"
    tpd = claims[("capacity", "300")]
    assert tpd.value_norm == 99000 and tpd.capacity_basis == "estimated" and tpd.confidence == "C"
    assert any("assumed" in f for f in tpd.flags)
    closed = claims[("status", "permanently closed")]
    assert closed.value_norm == "closed" and closed.review_state == "validated"
    assert claims[("operator", "co:example-aroma-chemicals-ltd")].subject_id == "site:cn-exampletown-01"
    review = [json.loads(x) for x in (ws / "review" / "queue.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any("closed" in r["note"] for r in review)
    assert any("capacity change 106%" in r["note"] for r in review)  # 99,000 vs accepted 48,000
    assert "| not_found | 1 |" in summary
    assert "line 99 is not a valid candidate_site" in summary


def test_rerun_collect_adds_nothing(ws):
    _plan_and_run(ws, "r1", LINES)
    before = (ws / "data" / "claims.jsonl").read_text(encoding="utf-8")
    batch, _ = collect(
        "r1",
        runs_dir=ws / "runs",
        data_dir=ws / "data",
        review_path=ws / "review" / "q.jsonl",
        checker=fake_checker,
        chains_dir=ws / "chains",
    )
    assert (ws / "data" / "claims.jsonl").read_text(encoding="utf-8") == before
    assert batch.claims == []


def test_people_leak_drops_record_and_dependents(ws):
    lines = json.loads(json.dumps(LINES[:5]))
    lines[0]["source_type"] = "trade_press"
    lines[0]["quote"] = "The plant has an annual capacity of 48,000 tonnes, contact sales@example.com"
    batch, _ = _plan_and_run(ws, "leak", lines)
    assert batch.evidence == [] and batch.claims == []
    assert batch.stats["people_leak_dropped"] == 1


def test_evidence_grade_table():
    assert evidence_grade("company_primary", "pass") == "A"
    assert evidence_grade("permit", "manual") == "C"
    assert evidence_grade("trade_press", "pass") == "B"
    assert evidence_grade("aggregator", "pass") == "C"
    assert evidence_grade("company_primary", "fail") == "D"


def test_skip_done_jobs(ws):
    _plan_and_run(ws, "r1", LINES)
    again = planner.plan(PACK, ["J01"], ["mol:5392-40-5"], ["CN"], data_dir=ws / "data", runs_dir=ws / "runs")
    assert again == []
    j04 = planner.plan(PACK, ["J04"], data_dir=ws / "data", runs_dir=ws / "runs")
    assert [j.inputs["unit_id"] for j in j04] == ["unit:cn-exampletown-01:citral"]
    assert j04[0].inputs["operator_name"] == "Example Aroma Chemicals Ltd"


def test_company_level_lead_takes_job_molecule(ws):
    lines = LINES[:2] + [
        {
            "kind": "claim",
            "subject_ref": {"candidate_company": 1},
            "field": "exists",
            "value": "true",
            "as_of": "2024-08-29",
            "evidence_refs": [0],
        },
    ]
    batch, _ = _plan_and_run(ws, "lead", lines)
    (unit_claim,) = [c for c in batch.claims if c.field == "exists"]
    # no plant named: the claim lands on the company's "plant location not public" unit in its home country
    (site,) = batch.sites
    assert site.country == "CN" and site.geo_precision == "country" and "not public" in site.name
    assert unit_claim.subject_id == f"unit:{site.id.removeprefix('site:')}:citral"
    assert any(c.field == "operator" and c.subject_id == site.id for c in batch.claims)


def test_company_level_claim_uses_only_known_plant(ws):
    lines = LINES + [
        {
            "kind": "claim",
            "subject_ref": {"candidate_company": 1, "molecule": "mol:5392-40-5"},
            "field": "capacity",
            "value": "48000",
            "unit_raw": "t/a",
            "as_of": "2024-08-29",
            "evidence_refs": [0],
        },
    ]
    batch, _ = _plan_and_run(ws, "known", lines)
    cap = [c for c in batch.claims if c.field == "capacity"]
    assert cap and all(c.subject_id.startswith("unit:cn-") and "not-public" not in c.subject_id for c in cap)


def test_publish_paths_are_the_public_record(ws, monkeypatch):
    from pipeline.publish import run_paths

    _plan_and_run(ws, "r1", LINES)
    (ws / "runs" / "r1" / "summary.md").write_text("x")
    monkeypatch.chdir(ws)
    paths = run_paths("r1")
    assert any(p.endswith("out.jsonl") for p in paths) and "runs/r1/manifest.json" in paths
    assert not any(p.endswith(("prompt.md", "inputs.json", "log.txt")) for p in paths)
    assert "data" in paths and "review" in paths


def test_licence_quarantine_rejects_claim(ws):
    lines = json.loads(json.dumps(LINES[:5]))
    lines[0]["url"] = "https://www.imarcgroup.com/citral-report"
    batch, _ = _plan_and_run(ws, "lic", lines)
    caps = [c for c in batch.claims if c.field == "capacity"]
    assert caps and all(c.review_state == "rejected" and c.review_note.startswith("licence") for c in caps)


def test_lat_lon_claim_is_parsed_and_checked(ws):
    lines = LINES[:3] + [
        {
            "kind": "claim",
            "subject_ref": {"candidate_site": 2},
            "field": "lat_lon",
            "value": "37°0′52″N 119°7′47″E",
            "as_of": "2020-06-30",
            "evidence_refs": [0],
        },
        {
            "kind": "claim",
            "subject_ref": {"candidate_site": 2},
            "field": "lat_lon",
            "value": "49.48, 8.44",
            "as_of": "2020-06-30",
            "evidence_refs": [0],
        },
    ]
    batch, _ = _plan_and_run(ws, "geo", lines)
    ll = {c.value: c for c in batch.claims if c.field == "lat_lon"}
    assert ll["37°0′52″N 119°7′47″E"].value_norm == "37.014444,119.129722"
    assert ll["37°0′52″N 119°7′47″E"].review_state == "accepted"
    assert "outside CN" in ll["49.48, 8.44"].review_note


def test_m1_planners_and_collector(ws):
    _plan_and_run(ws, "base", LINES)  # creates site cn-exampletown-01, unit citral, operator claim
    j03 = planner.plan(PACK, ["J03"], data_dir=ws / "data", runs_dir=ws / "runs")
    assert [j.inputs["site_id"] for j in j03] == ["site:cn-exampletown-01"]
    assert "linalool (`mol:78-70-6`; also written 芳樟醇, リナロール)" in j03[0].inputs["chain_molecules"]
    assert "methanol" not in " ".join(j03[0].inputs["chain_molecules"])  # base molecules aren't mapped
    j05 = planner.plan(PACK, ["J05"], data_dir=ws / "data", runs_dir=ws / "runs")
    assert j05 == []  # company_primary pages are not long-document jobs; permits and filings are
    j07 = planner.plan(PACK, ["J07"], data_dir=ws / "data", runs_dir=ws / "runs")
    assert [j.inputs["company_id"] for j in j07] == ["co:example-aroma-chemicals-ltd"]
    j14 = planner.plan(PACK, ["J14"], data_dir=ws / "data", runs_dir=ws / "runs")
    assert [j.inputs["site_id"] for j in j14] == ["site:cn-exampletown-01"]

    # J03-style output: a second product at the known site, and a parent claim naming a company
    lines = [
        LINES[0],
        {
            "kind": "claim",
            "subject_ref": {"site": "site:cn-exampletown-01", "molecule": "mol:78-70-6"},
            "field": "exists",
            "value": "true",
            "as_of": "2024-08-29",
            "evidence_refs": [0],
        },
        {
            "kind": "claim",
            "subject_ref": {"company": "co:example-aroma-chemicals-ltd"},
            "field": "parent",
            "value": "Example Holdings Group",
            "as_of": "2024-08-29",
            "evidence_refs": [0],
        },
    ]
    batch, _ = _plan_and_run_more(ws, "j03", lines)
    subjects = {c.subject_id: c for c in batch.claims}
    assert "unit:cn-exampletown-01:linalool" in subjects
    assert subjects["co:example-aroma-chemicals-ltd"].value_norm == "co:example-holdings-group"


def _plan_and_run_more(ws, run_id, lines):
    from pipeline.plan import Job

    job = Job(
        "j03-test000001",
        "site_profile",
        {"job_type": "site_profile", "stub_lines": lines},
        "x",
        "chain:isoprenoids",
    )
    planner.write_queue([job], run_id, ws / "queue")
    run(run_id, n=1, override=STUB, runs_dir=ws / "runs", queue_dir=ws / "queue")
    return collect(
        run_id,
        runs_dir=ws / "runs",
        data_dir=ws / "data",
        review_path=ws / "review" / "queue.jsonl",
        checker=fake_checker,
        chains_dir=ws / "chains",
    )


def test_claim_on_merged_unit_id_is_kept_under_stored_id(ws):
    """A J04 written for unit:<to-site>:<mol> lands on the stored unit:<from-site>:<mol>."""
    from pipeline.collect import Collector
    from portolan.models import Merge, Site, Unit
    from portolan.store import Store

    store = Store(ws / "data")
    store.append(
        "sites",
        [
            Site(id="site:de-a-01", name="A", country="DE", locality="A", geo_precision="locality"),
            Site(id="site:de-b-01", name="B", country="DE", locality="A", geo_precision="locality"),
        ],
    )
    store.append(
        "units", [Unit(id="unit:de-b-01:citral", site_id="site:de-b-01", molecule_id="mol:5392-40-5")]
    )
    store.append(
        "merges",
        [
            Merge(
                from_id="site:de-b-01", to_id="site:de-a-01", reason="same", decided_by="t", date="2026-10-28"
            )
        ],
    )
    c = Collector.__new__(Collector)
    c.existing = {t: store.load(t) for t in ("companies", "sites", "units", "claims", "evidence")}
    c.batch = type("B", (), {"store": store, "units": [], "sites": [], "companies": []})()
    from portolan.models import SubjectRef

    assert c.subject_for(SubjectRef(unit="unit:de-a-01:citral"), {}) == "unit:de-b-01:citral"
    assert c.subject_for(SubjectRef(unit="unit:de-a-01:linalool"), {}) is None
