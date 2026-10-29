"""Export JSON Schemas for entities, agent output kinds and chain packs to `schema/`."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from portolan.chain import ChainPack
from portolan.models import ENTITY_MODELS, OUT_MODELS, OutLine


def all_schemas() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for name, model in ENTITY_MODELS.items():
        out[f"entity/{name}"] = model.model_json_schema()
    for name, model in OUT_MODELS.items():
        out[f"out/{name}"] = model.model_json_schema()
    out["out/line"] = TypeAdapter(OutLine).json_schema()
    out["chain_pack"] = ChainPack.model_json_schema()
    return out


def _dump(schema: dict) -> str:
    return json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def write_schemas(root: str | Path = "schema") -> list[Path]:
    root = Path(root)
    written = []
    for name, schema in all_schemas().items():
        path = root / f"{name}.schema.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_dump(schema), encoding="utf-8")
        written.append(path)
    return written


def stale_schemas(root: str | Path = "schema") -> list[str]:
    """Names whose file on disk differs from the models (missing files count as stale)."""
    root = Path(root)
    stale = []
    for name, schema in all_schemas().items():
        path = root / f"{name}.schema.json"
        if not path.exists() or path.read_text(encoding="utf-8") != _dump(schema):
            stale.append(name)
    return stale


__all__ = ["all_schemas", "stale_schemas", "write_schemas"]
