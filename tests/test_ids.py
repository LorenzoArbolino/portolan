import pytest

from portolan import ids


def test_slugify_basic_and_greek():
    assert ids.slugify("BASF SE") == "basf-se"
    assert ids.slugify("β-Ionone") == "beta-ionone"
    assert ids.slugify("  Ludwigshafen am Rhein ") == "ludwigshafen-am-rhein"
    assert ids.slugify("Zürich") == "zurich"


def test_slugify_non_latin_is_stable_hash():
    a = ids.slugify("万华化学")
    assert a == ids.slugify("万华化学")
    assert a.startswith("x") and ids.is_slug(a)
    assert a != ids.slugify("新和成")


@pytest.mark.parametrize("cas", ["5392-40-5", "78-70-6", "79-77-6", "7695-91-2", "67-56-1", "50-00-0"])
def test_cas_valid(cas):
    assert ids.cas_is_valid(cas)


@pytest.mark.parametrize("cas", ["7695-91-5", "5392-40-4", "5392405", "12-3-4"])
def test_cas_invalid(cas):
    assert not ids.cas_is_valid(cas)


def test_molecule_id():
    assert ids.molecule_id("5392-40-5") == "mol:5392-40-5"
    assert ids.molecule_id(name="Iso E Super") == "mol:x-iso-e-super"
    with pytest.raises(ValueError):
        ids.molecule_id("5392-40-4")


def test_examples_from_spec():
    assert ids.site_id("DE", "Ludwigshafen") == "site:de-ludwigshafen-01"
    assert ids.unit_id("site:de-ludwigshafen-01", "citral") == "unit:de-ludwigshafen-01:citral"
    assert ids.unit_id("site:de-ludwigshafen-01", "citral", 2) == "unit:de-ludwigshafen-01:citral:02"
    assert ids.company_id("BASF SE") == "co:basf-se"
    assert ids.route_id("citral", "isoprenol prenal") == "rte:citral:isoprenol-prenal"
    assert ids.event_id("2017-10-31", "BASF citral fire") == "ev:2017-10-31:basf-citral-fire"
    assert ids.measure_id("EU", "2025/1151") == "tm:eu:2025-1151"
    assert ids.chain_id("isoprenoids") == "chain:isoprenoids"


def test_evidence_id_stable_and_canonical():
    q = "Citral … 48,000 t/a"
    a = ids.evidence_id("https://Example.com/news?id=3&utm_source=x#top", q)
    b = ids.evidence_id("https://example.com/news?id=3", q + "  ")
    assert a == b
    assert a.startswith("src:") and len(a) == 16
    assert a != ids.evidence_id("https://example.com/news?id=4", q)
    assert a != ids.evidence_id("https://example.com/news?id=3", q + " plant")


def test_evidence_id_no_concatenation_collision():
    assert ids.evidence_id("https://a.com/x", "yz") != ids.evidence_id("https://a.com/xy", "z")


def test_claim_id_stable_and_order_independent():
    a = ids.claim_id("unit:cn-yantai-01:citral", "capacity", 48000, ["src:aaa", "src:bbb"])
    b = ids.claim_id("unit:cn-yantai-01:citral", "capacity", "48000", ["src:bbb", "src:aaa"])
    assert a == b
    assert a != ids.claim_id("unit:cn-yantai-01:citral", "capacity", 40000, ["src:aaa", "src:bbb"])
    assert a != ids.claim_id("unit:cn-yantai-01:citral", "status", 48000, ["src:aaa", "src:bbb"])


def test_next_site_id_avoids_collisions():
    existing = ["site:de-ludwigshafen-01", "site:de-ludwigshafen-02"]
    assert ids.next_site_id("DE", "Ludwigshafen", existing) == "site:de-ludwigshafen-03"
    assert ids.next_site_id("DE", "Ludwigshafen", []) == "site:de-ludwigshafen-01"
    assert ids.next_site_id("FR", "Ludwigshafen", existing) == "site:fr-ludwigshafen-01"


def test_site_id_rejects_bad_input():
    with pytest.raises(ValueError):
        ids.site_id("DEU", "x")
    with pytest.raises(ValueError):
        ids.site_id("DE", "x", 100)


def test_duplicates():
    assert ids.duplicates(["a", "b", "a", "c", "a"]) == ["a"]
