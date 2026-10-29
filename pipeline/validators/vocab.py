"""Normalise status and year values to the data model's status vocabulary. Unknown → None (review)."""

from __future__ import annotations

import re

from portolan.models import STATUS_VOCAB

STATUS_ALIASES = {
    "operating": [
        "operating",
        "operational",
        "in operation",
        "running",
        "producing",
        "in production",
        "active",
        "started up",
        "start-up",
        "commercial operation",
        "online",
        "on stream",
        "on-stream",
        "in betrieb",
        "en service",
        "in esercizio",
        "投产",
        "已投产",
        "运行",
        "生产",
        "稼働",
        "稼働中",
    ],
    "planned": [
        "planned",
        "proposed",
        "announced",
        "under planning",
        "geplant",
        "projet",
        "拟建",
        "规划",
        "计划",
    ],
    "under_construction": [
        "under construction",
        "construction",
        "being built",
        "im bau",
        "en construction",
        "in costruzione",
        "在建",
        "建设中",
        "建設中",
    ],
    "commissioning": [
        "commissioning",
        "trial production",
        "trial run",
        "mechanically complete",
        "mechanical completion",
        "试生产",
        "试运行",
        "试车",
    ],
    "idle": [
        "idle",
        "idled",
        "mothballed",
        "suspended",
        "temporarily shut",
        "temporarily closed",
        "stillgelegt",
        "停产",
        "停車",
    ],
    "closing": ["closing", "closure announced", "to be closed", "phase out", "phasing out", "wind down"],
    "closed": [
        "closed",
        "shut down",
        "shutdown",
        "permanently closed",
        "decommissioned",
        "dismantled",
        "demolished",
        "geschlossen",
        "fermé",
        "chiuso",
        "关闭",
        "关停",
        "拆除",
        "閉鎖",
    ],
    "cancelled": ["cancelled", "canceled", "abandoned", "scrapped", "取消", "终止"],
}
_LOOKUP = {a: k for k, aliases in STATUS_ALIASES.items() for a in aliases} | {s: s for s in STATUS_VOCAB}


def normalise_status(value: object) -> str | None:
    s = re.sub(r"\s+", " ", str(value).strip().lower().replace("_", " "))
    if s in _LOOKUP:
        return _LOOKUP[s]
    s2 = s.replace(" ", "_")
    return s2 if s2 in STATUS_VOCAB else None


def normalise_year(value: object, lo: int = 1900, hi: int = 2035) -> int | None:
    m = re.fullmatch(r"\s*(?:ca\.?\s*|约)?(\d{4})\s*(?:年)?\s*", str(value))
    if not m:
        return None
    y = int(m.group(1))
    return y if lo <= y <= hi else None
