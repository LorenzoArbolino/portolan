"""portolan review: decisions rewrite only the touched lines and close the matching queue items."""

import json

import pytest

from portolan.review import decide

CLAIM = {
    "id": "clm:aaaaaaaaaaaa",
    "subject_id": "unit:in-x-01:myrcene",
    "field": "capacity",
    "value": "400.0",
    "unit_raw": "Qty MTPM (proposed)",
    "as_of": "2020-04-01",
    "evidence_ids": ["src:111111111111"],
    "extracted_by": "run:r/job:j01-0000000000/agent:stub:x",
    "confidence": "A",
    "review_state": "validated",
}


@pytest.fixture
def files(tmp_path):
    claims = tmp_path / "claims.jsonl"
    other = json.dumps(
        dict(CLAIM, id="clm:bbbbbbbbbbbb"), separators=(", ", ": ")
    )  # odd formatting stays as is
    claims.write_text(json.dumps(CLAIM) + "\n" + other + "\n", encoding="utf-8")
    queue = tmp_path / "queue.jsonl"
    queue.write_text(
        json.dumps({"id": "rv:1", "claim_ids": ["clm:aaaaaaaaaaaa"], "state": "open", "note": "unit"})
        + "\n"
        + json.dumps({"id": "rv:2", "claim_ids": ["clm:bbbbbbbbbbbb"], "state": "open", "note": "x"})
        + "\n",
        encoding="utf-8",
    )
    return claims, queue, other


def test_accept_with_unit_fix(files):
    claims, queue, other = files
    assert decide(
        ["rv:1"],
        True,
        "EC table, proposed column",
        unit="MTPM",
        basis="permitted",
        claims_path=claims,
        queue_path=queue,
    ) == (1, 1)
    a, b = claims.read_text(encoding="utf-8").splitlines()
    a = json.loads(a)
    assert (a["review_state"], a["unit_raw"], a["value_norm"], a["capacity_basis"]) == (
        "accepted",
        "MTPM",
        4800.0,
        "permitted",
    )
    assert b == other
    q = [json.loads(x) for x in queue.read_text(encoding="utf-8").splitlines()]
    assert q[0]["state"] == "closed" and q[0]["decision"] == "accepted" and q[1]["state"] == "open"


def test_reject_by_claim_id(files):
    claims, queue, _ = files
    assert decide(["clm:bbbbbbbbbbbb"], False, "duplicate", claims_path=claims, queue_path=queue) == (1, 1)
    assert json.loads(claims.read_text(encoding="utf-8").splitlines()[1])["review_state"] == "rejected"


def test_unknown_ids_change_nothing(files):
    claims, queue, _ = files
    before = claims.read_text(encoding="utf-8")
    with pytest.raises(KeyError):
        decide(["clm:zzz"], False, "x", claims_path=claims, queue_path=queue)
    with pytest.raises(ValueError):
        decide(["clm:aaaaaaaaaaaa"], True, "x", unit="furlongs", claims_path=claims, queue_path=queue)
    assert claims.read_text(encoding="utf-8") == before
