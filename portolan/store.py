"""Read and write canonical data in `data/`: CSV for entities, JSONL for
claims, evidence and events. Records are only ever added; an existing ID is never rewritten here
(merges go through `data/merges.csv`, review-state changes through the resolver)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from pydantic import BaseModel

from portolan.models import Claim, Company, Event, Evidence, Merge, Site, Transfer, Unit

TABLES: dict[str, tuple[str, type[BaseModel]]] = {
    "companies": ("companies.csv", Company),
    "sites": ("sites.csv", Site),
    "units": ("units.csv", Unit),
    "claims": ("claims.jsonl", Claim),
    "evidence": ("evidence.jsonl", Evidence),
    "events": ("events.jsonl", Event),
    "merges": ("merges.csv", Merge),
    "transfers": ("transfers.csv", Transfer),
}


def _csv_cell(v: object) -> str:
    if v is None:
        return ""
    if isinstance(v, list | dict):
        return json.dumps(v, ensure_ascii=False, sort_keys=True) if v else ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _from_csv(row: dict[str, str], model: type[BaseModel]) -> BaseModel:
    data: dict[str, object] = {}
    for name, f in model.model_fields.items():
        raw = row.get(name, "")
        if raw == "":
            continue
        ann = str(f.annotation)
        if raw[:1] in "[{" and ("list" in ann or "dict" in ann):
            data[name] = json.loads(raw)
        elif ann == "<class 'bool'>":
            data[name] = raw == "true"
        else:
            data[name] = raw
    return model.model_validate(data)


class Store:
    def __init__(self, root: str | Path = "data") -> None:
        self.root = Path(root)

    def path(self, table: str) -> Path:
        return self.root / TABLES[table][0]

    def load(self, table: str) -> list[BaseModel]:
        fname, model = TABLES[table]
        p = self.root / fname
        if not p.exists():
            return []
        if fname.endswith(".jsonl"):
            return [
                model.model_validate_json(line)
                for line in p.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        with open(p, encoding="utf-8", newline="") as f:
            return [_from_csv(row, model) for row in csv.DictReader(f)]

    def ids(self, table: str) -> set[str]:
        key = {"merges": "from_id", "transfers": "event_id"}.get(table, "id")
        return {getattr(r, key) for r in self.load(table)}

    def append(self, table: str, records: list[BaseModel]) -> list[BaseModel]:
        """Append records whose ID isn't already present. Returns the records actually written."""
        fname, model = TABLES[table]
        p = self.root / fname
        existing = self.ids(table)
        new: list[BaseModel] = []
        for r in records:
            rid = getattr(r, {"merges": "from_id", "transfers": "event_id"}.get(table, "id"))
            if rid not in existing:
                existing.add(rid)
                new.append(r)
        if not new:
            return []
        p.parent.mkdir(parents=True, exist_ok=True)
        if fname.endswith(".jsonl"):
            with open(p, "a", encoding="utf-8") as f:
                for r in new:
                    f.write(r.model_dump_json(exclude_none=True) + "\n")
        else:
            cols = list(model.model_fields)
            write_header = not p.exists() or p.stat().st_size == 0
            with open(p, "a", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
                if write_header:
                    w.writeheader()
                for r in new:
                    d = r.model_dump(mode="json")
                    w.writerow({c: _csv_cell(d.get(c)) for c in cols})
        return new
