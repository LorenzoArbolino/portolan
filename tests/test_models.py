import json

import pytest
from pydantic import TypeAdapter, ValidationError

from portolan import ids
from portolan.models import Claim, Evidence, Molecule, OutLine, Site, SubjectRef

LINE = TypeAdapter(OutLine)

# Example agent output lines, one of each kind.
SPEC_EXAMPLE = [
    {
        "kind": "evidence",
        "url": "https://example.org/ec.pdf",
        "retrieved_at": "2026-10-26T10:12:00Z",
        "publisher": "SEIAA Gujarat",
        "published_at": "2022-11-23",
        "source_type": "permit",
        "language": "en",
        "quote": "Galaxmusk pure & its derivatives … 400",
        "locator": "p.3, table 1",
    },
    {
        "kind": "candidate_site",
        "name": "Privi Speciality Chemicals Unit VI",
        "country": "IN",
        "locality": "Jhagadia",
        "address": "Plot 765, Jhagadia Industrial Estate, Bharuch, Gujarat",
        "evidence_refs": [0],
    },
    {
        "kind": "claim",
        "subject_ref": {"candidate_site": 0, "molecule": "mol:1222-05-5"},
        "field": "capacity",
        "value": "400",
        "unit_raw": "MT/Month",
        "capacity_basis": "permitted",
        "as_of": "2022-11-23",
        "evidence_refs": [0],
    },
    {
        "kind": "not_found",
        "query": "capacity of X at Y",
        "searched": ["url1", "url2"],
        "note": "site page lists product, no capacity",
    },
]


@pytest.mark.parametrize("line", SPEC_EXAMPLE)
def test_spec_example_lines_validate(line):
    assert LINE.validate_python(line).kind == line["kind"]


def test_agent_cannot_write_quote_check():
    bad = dict(SPEC_EXAMPLE[0], quote_check="pass")
    with pytest.raises(ValidationError):
        LINE.validate_python(bad)


def test_quote_length_capped():
    with pytest.raises(ValidationError):
        LINE.validate_python(dict(SPEC_EXAMPLE[0], quote="x" * 401))


def test_capacity_claim_needs_unit():
    bad = dict(SPEC_EXAMPLE[2])
    bad.pop("unit_raw")
    with pytest.raises(ValidationError):
        LINE.validate_python(bad)


def test_subject_ref_exactly_one_anchor():
    with pytest.raises(ValidationError):
        SubjectRef(site="site:de-ludwigshafen-01", company="co:basf-se")
    with pytest.raises(ValidationError):
        SubjectRef()
    assert SubjectRef(molecule="mol:5392-40-5").molecule  # market-level claim (world capacity)


def test_unknown_kind_rejected():
    with pytest.raises(ValidationError):
        LINE.validate_python({"kind": "opinion", "text": "big plant"})


def test_molecule_cas_must_match_id():
    Molecule(id="mol:5392-40-5", name="citral", tier="specialty", cas="5392-40-5")
    with pytest.raises(ValidationError):
        Molecule(id="mol:5392-40-5", name="citral", tier="specialty", cas="78-70-6")


def test_site_latlon_pair():
    with pytest.raises(ValidationError):
        Site(
            id="site:de-ludwigshafen-01",
            name="x",
            country="DE",
            locality="Ludwigshafen",
            geo_precision="locality",
            lat=49.5,
        )


def test_claim_and_evidence_roundtrip():
    ev_id = ids.evidence_id("https://example.com", "48,000 tonnes")
    ev = Evidence(
        id=ev_id,
        url="https://example.com",
        retrieved_at="2026-10-26T10:00:00Z",
        source_type="trade_press",
        language="en",
        quote="48,000 tonnes",
    )
    cl = Claim(
        id=ids.claim_id("unit:cn-yantai-01:citral", "capacity", "48000", [ev_id]),
        subject_id="unit:cn-yantai-01:citral",
        field="capacity",
        value="48000",
        unit_raw="t",
        as_of="2024-08-29",
        evidence_ids=[ev_id],
        extracted_by="claude",
        confidence="B",
    )
    assert Claim.model_validate(json.loads(cl.model_dump_json())) == cl
    assert Evidence.model_validate(json.loads(ev.model_dump_json())) == ev
    with pytest.raises(ValidationError):
        Claim(**{**cl.model_dump(), "evidence_ids": []})


def test_agent_partial_dates_are_accepted():
    line = dict(SPEC_EXAMPLE[2], as_of="2026-02")
    assert str(LINE.validate_python(line).as_of) == "2026-02-01"
    assert str(LINE.validate_python(dict(line, as_of="2024")).as_of) == "2024-01-01"
    with pytest.raises(ValidationError):
        LINE.validate_python(dict(line, as_of="Feb 2026"))
