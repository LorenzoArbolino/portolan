"""`schema` validator: each out.jsonl line must match its kind's model, and every `*_refs` index must
point at a line of the right kind in the same file. Failing lines are rejected."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from portolan.models import OutClaim, OutEvent, OutLine, SubjectRef

_LINE = TypeAdapter(OutLine)


@dataclass
class LineResult:
    index: int  # 0-based line index, the same index agents use in *_refs
    ok: bool
    obj: object | None = None
    errors: list[str] = field(default_factory=list)


def _fmt(e: ValidationError) -> list[str]:
    return [f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()]


def validate_lines(lines: list[str]) -> list[LineResult]:
    results: list[LineResult] = []
    for i, raw in enumerate(lines):
        if not raw.strip():
            results.append(LineResult(i, False, errors=["empty line"]))
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            results.append(LineResult(i, False, errors=[f"invalid JSON: {e.msg}"]))
            continue
        try:
            results.append(LineResult(i, True, obj=_LINE.validate_python(data)))
        except ValidationError as e:
            results.append(LineResult(i, False, errors=_fmt(e)))

    kinds = {r.index: getattr(r.obj, "kind", None) for r in results if r.ok}

    def need(r: LineResult, ref: int | None, kind: str, what: str) -> None:
        if ref is None:
            return
        if kinds.get(ref) != kind:
            r.ok = False
            r.errors.append(f"{what} → line {ref} is not a valid {kind}")

    def check_subject(r: LineResult, s: SubjectRef) -> None:
        need(r, s.candidate_site, "candidate_site", "subject_ref.candidate_site")
        need(r, s.candidate_company, "candidate_company", "subject_ref.candidate_company")

    for r in results:
        if not r.ok:
            continue
        for ref in getattr(r.obj, "evidence_refs", []) or []:
            need(r, ref, "evidence", "evidence_refs")
        need(r, getattr(r.obj, "company_ref", None), "candidate_company", "company_ref")
        if isinstance(r.obj, OutClaim):
            check_subject(r, r.obj.subject_ref)
        if isinstance(r.obj, OutEvent):
            for s in r.obj.subject_refs:
                check_subject(r, s)
    return results


def split_glued(lines: list[str]) -> list[str]:
    """`{...}{...}`, `{...} {...}` or `{...},` (array style) → one object per line (refs count objects)."""
    out: list[str] = []
    dec = json.JSONDecoder()
    for raw in lines:
        rest, parts = raw.strip().strip("[]").strip(), []
        if not rest:
            continue
        try:
            while rest:
                obj, end = dec.raw_decode(rest)
                parts.append(json.dumps(obj, ensure_ascii=False))
                rest = rest[end:].lstrip(" \t,")
        except json.JSONDecodeError:
            parts = [raw]
        out += parts or [raw]
    return out


def validate_file(path: str | Path) -> list[LineResult]:
    text = Path(path).read_text(encoding="utf-8")
    return validate_lines(split_glued(text.splitlines()))
