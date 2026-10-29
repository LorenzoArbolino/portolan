"""`licence` validator: evidence from a quarantined domain can't support a public number."""

from __future__ import annotations

from functools import cache
from pathlib import Path
from urllib.parse import urlsplit

import yaml

LICENCE_YAML = Path(__file__).with_name("licence.yaml")


@cache
def _rules() -> list[dict]:
    return yaml.safe_load(LICENCE_YAML.read_text(encoding="utf-8")).get("quarantine", [])


def quarantined(url: str) -> str | None:
    """The reason, if the URL's domain is quarantined."""
    host = (urlsplit(url).hostname or "").lower()
    for r in _rules():
        m = r["match"].lower()
        if host == m or host.endswith("." + m):
            return r["reason"]
    return None
