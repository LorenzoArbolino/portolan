"""Agent adapters: one per CLI, same interface. CLI flags live only here."""

from __future__ import annotations

import importlib
from functools import cache
from pathlib import Path

import yaml

from pipeline.agents.base import AgentAdapter

MODELS_YAML = Path(__file__).parent.parent / "models.yaml"


@cache
def load_models(path: str = str(MODELS_YAML)) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def candidates(job_type: str) -> list[tuple[str, str]]:
    """Ordered (agent, model) candidates for a job type."""
    out = []
    for c in load_models()["jobs"].get(job_type, []):
        agent, _, model = c.partition(":")
        out.append((agent, model))
    if not out:
        raise KeyError(f"no candidates for job type {job_type!r} in models.yaml")
    return out


def get_adapter(agent: str) -> AgentAdapter:
    target = load_models()["agents"][agent]
    module, _, cls = target.partition(":")
    return getattr(importlib.import_module(module), cls)()


def limits() -> dict:
    return load_models().get("limits", {})
