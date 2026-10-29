import json

from pipeline.validators.schema import validate_lines

EV = {
    "kind": "evidence",
    "url": "https://example.com/a",
    "retrieved_at": "2026-10-26T10:00:00Z",
    "source_type": "company_primary",
    "language": "en",
    "quote": "annual capacity of 48,000 tonnes",
}
CO = {"kind": "candidate_company", "name": "Example Aroma Chemicals Ltd", "evidence_refs": [0]}
SITE = {
    "kind": "candidate_site",
    "name": "Exampletown plant",
    "country": "CN",
    "locality": "Exampletown",
    "company_ref": 1,
    "evidence_refs": [0],
}
CLAIM = {
    "kind": "claim",
    "subject_ref": {"candidate_site": 2, "molecule": "mol:5392-40-5"},
    "field": "capacity",
    "value": "48,000",
    "unit_raw": "t/a",
    "capacity_basis": "nameplate",
    "as_of": "2024-08-29",
    "evidence_refs": [0],
}


def _lines(*objs):
    return [json.dumps(o, ensure_ascii=False) for o in objs]


def test_valid_file():
    res = validate_lines(_lines(EV, CO, SITE, CLAIM))
    assert all(r.ok for r in res), [r.errors for r in res]


def test_bad_json_and_empty_line_rejected():
    res = validate_lines(["{not json", ""])
    assert [r.ok for r in res] == [False, False]


def test_ref_to_wrong_kind_rejected():
    bad = dict(CLAIM, evidence_refs=[1])
    res = validate_lines(_lines(EV, CO, SITE, bad))
    assert not res[3].ok and "not a valid evidence" in res[3].errors[0]


def test_ref_out_of_range_rejected():
    bad = dict(SITE, evidence_refs=[9])
    assert not validate_lines(_lines(EV, CO, bad))[2].ok


def test_subject_ref_must_point_to_candidate_site():
    bad = dict(CLAIM, subject_ref={"candidate_site": 1, "molecule": "mol:5392-40-5"})
    assert not validate_lines(_lines(EV, CO, SITE, bad))[3].ok


def test_ref_to_rejected_line_rejected():
    bad_ev = dict(EV, quote_check="pass")  # agents may not write quote_check
    res = validate_lines(_lines(bad_ev, CO))
    assert not res[0].ok and not res[1].ok
