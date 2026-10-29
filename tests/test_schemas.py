from pathlib import Path

from portolan import schemas

ROOT = Path(__file__).parent.parent


def test_schemas_generate(tmp_path):
    paths = schemas.write_schemas(tmp_path)
    assert any(p.name == "claim.schema.json" for p in paths)
    assert schemas.stale_schemas(tmp_path) == []


def test_committed_schemas_are_fresh():
    assert schemas.stale_schemas(ROOT / "schema") == [], "run `uv run portolan schemas`"
