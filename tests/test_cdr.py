"""EPA CDR script job: producer rows only, withheld sites and missing points skipped, quotes verifiable."""

from pipeline.sources import cdr
from portolan.models import OutLineModel


def row(**kw):
    base = {
        "SITE NAME": "IFF CHEMICAL HOLDINGS INC",
        "SITE CITY": "JACKSONVILLE",
        "SITE STATE": "FL",
        "SITE ADDRESS LINE1": "2051 N LANE AVE",
        "SITE ADDRESS LINE2": "",
        "SITE LATITUDE": "30.34774",
        "SITE LONGITUDE": "-81.7494",
        "CHEMICAL ID": "80-56-8",
        "ACTIVITY": "Manufacture",
        "2023 DOMESTIC PV": "15,246,111",
        "DOMESTIC PARENT COMPANY NAME": "INTERNATIONAL FLAVORS & FRAGRANCES INC",
        "STANDARDIZED PARENT COMPANY NAME": "",
        "EPA FACILITY REGISTRY ID": "110000000001",
        "EPA-TSCA PROGRAM ID": "TSCA1",
    }
    return base | kw


CAS = {"80-56-8": "mol:80-56-8", "123-35-3": "mol:123-35-3"}


def kinds(lines):
    return [(x["kind"], x.get("field")) for x in lines]


def test_producer_row_becomes_site_with_point_volume_and_status():
    lines = cdr.lines_for(
        [row(), row(**{"CHEMICAL ID": "123-35-3", "2023 DOMESTIC PV": "CBI"})], CAS, "2026-10-28T00:00:00Z"
    )
    for x in lines:  # every line is valid agent output
        OutLineModel.model_validate({"line": x})
    assert kinds(lines).count(("candidate_site", None)) == 1  # one site for two chemicals
    assert ("claim", "lat_lon") in kinds(lines)
    cap = next(x for x in lines if x.get("field") == "capacity")
    assert (cap["value"], cap["unit_raw"], cap["capacity_basis"]) == ("15,246,111", "lb/a", "production")
    assert sum(x.get("field") == "status" for x in lines) == 1  # none for the CBI volume
    assert all(cdr.verify(x["quote"], [row(), row(**{"CHEMICAL ID": "123-35-3", "2023 DOMESTIC PV": "CBI"})])
               for x in lines if x["kind"] == "evidence")  # fmt: skip


def test_importers_withheld_sites_unknown_cas_and_null_points_skipped():
    rows = [
        row(ACTIVITY="Import"),
        row(**{"SITE NAME": "CBI"}),
        row(**{"CHEMICAL ID": "50-00-0"}),
    ]
    assert cdr.lines_for(rows, CAS, "2026-10-28T00:00:00Z") == []
    lines = cdr.lines_for(
        [row(**{"SITE LATITUDE": "0.0", "SITE LONGITUDE": "0.0"})], CAS, "2026-10-28T00:00:00Z"
    )
    assert ("claim", "lat_lon") not in kinds(lines)


def test_verify_rejects_edited_quote():
    q = cdr.quote(row())
    assert cdr.verify(q, [row()])
    assert not cdr.verify(q.replace("15,246,111", "25,246,111"), [row()])
