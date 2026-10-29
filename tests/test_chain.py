from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from portolan.chain import ChainPack, load_chain

PACK = Path(__file__).parent.parent / "chains" / "isoprenoids.yaml"


def test_isoprenoids_loads_and_counts():
    pack = load_chain(PACK)
    assert pack.id == "chain:isoprenoids"
    assert len(pack.molecules) == 23
    assert len(pack.routes) == 17
    assert pack.first_molecules[0] == "mol:5392-40-5"


def test_every_route_reference_resolves():
    pack = load_chain(PACK)
    known = {m.id for m in pack.molecules}
    for r in pack.to_routes():
        assert r.product_id in known
        assert all(i.molecule_id in known for i in r.inputs)
        assert all(c.molecule_id in known for c in r.coproducts)


def test_converts_to_entity_models():
    pack = load_chain(PACK)
    mols = pack.to_molecules()
    assert {m.tier for m in mols} == {"base", "intermediate", "specialty"}
    assert all(m.chain_ids == ["chain:isoprenoids"] for m in mols)


def _raw():
    return yaml.safe_load(PACK.read_text(encoding="utf-8"))


def test_dangling_route_reference_fails():
    raw = _raw()
    raw["routes"][0]["inputs"] = ["mol:64-17-5"]
    with pytest.raises(ValidationError, match="unknown molecule mol:64-17-5"):
        ChainPack.model_validate(raw)


def test_bad_cas_fails():
    raw = _raw()
    raw["molecules"][0]["cas"] = "67-56-2"
    raw["molecules"][0]["id"] = "mol:67-56-2"
    with pytest.raises(ValidationError, match="check digit"):
        ChainPack.model_validate(raw)


def test_template_is_a_valid_shape_once_filled():
    # The template uses placeholders; it must at least parse as YAML with the same top-level keys.
    tmpl = yaml.safe_load((PACK.parent / "_template.yaml").read_text(encoding="utf-8"))
    assert set(tmpl) <= set(ChainPack.model_fields)
