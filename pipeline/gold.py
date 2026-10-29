"""Gold set runner: score agent:model on hand-checked items in `eval/gold.jsonl`.

Each item is one document, one unit, one field, with the right answer (or `not_found` for traps). The
document is pre-fetched once and given to the agent as `document.txt` (agents read files rather than
fight downloads). Scores are deterministic, no LLM judge:

- recall: share of answerable items where a claim matches an expected value (capacity ±1% after unit
  normalisation; status after vocabulary normalisation);
- precision: share of claims on the asked field that match an expected value (claims on traps count wrong);
- not_found honesty: share of traps with no claim on the asked field;
- quote pass: share of cited evidence whose quote is found in the document (quote_check, ≥ 0.92 + numbers)."""

from __future__ import annotations

import datetime as dt
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pipeline.agents import get_adapter
from pipeline.fetch import Fetcher
from pipeline.plan import render
from pipeline.validators.quote_check import check_quote_in_text, extract_text
from pipeline.validators.schema import validate_file
from pipeline.validators.units import normalise_capacity
from pipeline.validators.vocab import normalise_status
from portolan.ids import site_id, unit_id

GOLD = Path("eval/gold.jsonl")
RUNS = Path("eval/runs")
RESULTS = Path("eval/results")
CAS = {"mol:5392-40-5": "5392-40-5"}


def load_gold(path: Path = GOLD) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def item_unit(item: dict) -> str:
    s = item["subject"]
    return unit_id(site_id(s["country"], s["locality"]), s["molecule_name"].split(" (")[0])


def document_text(url: str, fetcher: Fetcher, for_agent: bool = False) -> str | None:
    got = fetcher.get(url)
    return extract_text(got.content, got.content_type, for_agent=for_agent) if got.ok else None


def check_gold(fetcher: Fetcher | None = None, path: Path = GOLD) -> list[tuple[str, str, str]]:
    """Every gold quote must be found in its source (this is how the gold set itself is checked)."""
    f = fetcher or Fetcher()
    out = []
    for item in load_gold(path):
        text = document_text(item["url"], f)
        status = "unreachable" if text is None else check_quote_in_text(item["quote"], text).status
        out.append((item["id"], status, item["url"]))
    return out


def inputs_for(item: dict) -> dict:
    s = item["subject"]
    return {
        "job_type": "doc_claims",
        "url": item["url"],
        "field": item["field"],
        "unit_id": item_unit(item),
        "molecule_id": s["molecule_id"],
        "molecule_name": s["molecule_name"],
        "cas": s["molecule_id"].removeprefix("mol:"),
        "site_name": s["site_name"],
        "locality": s["locality"],
        "country": s["country"],
        "operator_name": s["operator_name"],
        "max_fetches": 0,
    }


def run_item(item: dict, agent: str, model: str, root: Path, fetcher: Fetcher, timeout_s: float) -> dict:
    wd = root / item["id"]
    wd.mkdir(parents=True, exist_ok=True)
    text = document_text(item["url"], fetcher, for_agent=True)
    if text is None:
        return {"id": item["id"], "status": "document_unreachable"}
    (wd / "document.txt").write_text(text, encoding="utf-8")
    inputs = inputs_for(item)
    prompt = wd / "prompt.md"
    prompt.write_text(render("doc_claims", inputs), encoding="utf-8")
    res = get_adapter(agent).run(prompt, inputs, wd, model, timeout_s=timeout_s)
    rec = {"id": item["id"], "status": res.status, "seconds": round(res.duration_s, 1), "meta": res.meta}
    if res.status not in ("ok", "partial"):
        # Workspaces are gitignored: keep the end of the log in the results so a failure can be diagnosed.
        log = res.log_path.read_text(encoding="utf-8", errors="replace") if res.log_path.exists() else ""
        rec["error"] = (res.error or res.status) + " | " + log[-800:]
    return rec


def _matches(item: dict, claim, language: str) -> bool:
    exp = item["expected"]
    if exp.get("not_found"):
        return False
    if item["field"] == "capacity":
        n = normalise_capacity(claim.value, claim.unit_raw, language)
        return n.ok and any(abs(n.value_tpa - v) <= 0.01 * v for v in exp["capacity_tpa"])
    if item["field"] == "status":
        return normalise_status(claim.value) in exp["status"]
    return str(claim.value).strip() in map(str, exp.get("values", []))


def score_item(item: dict, workdir: Path) -> dict:
    out = workdir / "out.jsonl"
    rec = {
        "id": item["id"],
        "difficulty": item["difficulty"],
        "trap": bool(item["expected"].get("not_found")),
        "claims": 0,
        "correct": 0,
        "hit": False,
        "quotes": 0,
        "quotes_pass": 0,
        "not_found": False,
        "invalid_lines": 0,
    }
    if not out.exists():
        rec["missing_output"] = True
        return rec
    results = validate_file(out)
    ok = {r.index: r.obj for r in results if r.ok}
    rec["invalid_lines"] = sum(not r.ok for r in results)
    doc = (
        (workdir / "document.txt").read_text(encoding="utf-8") if (workdir / "document.txt").exists() else ""
    )
    cited: set[int] = set()
    for obj in ok.values():
        if obj.kind == "not_found":
            rec["not_found"] = True
        if obj.kind == "claim" and obj.field == item["field"]:
            rec["claims"] += 1
            lang = next((ok[i].language for i in obj.evidence_refs if i in ok), None)
            if _matches(item, obj, lang):
                rec["correct"] += 1
                rec["hit"] = True
            cited.update(obj.evidence_refs)
    for i in cited:
        if i in ok and ok[i].kind == "evidence":
            rec["quotes"] += 1
            rec["quotes_pass"] += check_quote_in_text(ok[i].quote, doc).status == "pass"
    return rec


def summarise(records: list[dict]) -> dict:
    ans = [r for r in records if not r["trap"]]
    traps = [r for r in records if r["trap"]]
    ran = [r for r in records if not r.get("missing_output")]

    def honest(r: dict) -> bool:  # a trap is passed by answering "not found", not by producing nothing
        return r["claims"] == 0 and not r.get("missing_output")

    claims = sum(r["claims"] for r in records)
    quotes = sum(r["quotes"] for r in records)

    def ratio(a: float, b: float) -> float | None:
        return round(a / b, 3) if b else None

    by_diff = {}
    for d in ("easy", "hard", "trap"):
        rs = [r for r in records if r["difficulty"] == d]
        by_diff[d] = {
            "n": len(rs),
            "ok": sum((r["hit"] and r["claims"] == r["correct"]) if not r["trap"] else honest(r) for r in rs),
        }
    return {
        "items": len(records),
        "recall": ratio(sum(r["hit"] for r in ans), len(ans)),
        "precision": ratio(sum(r["correct"] for r in records), claims),
        "not_found_honesty": ratio(sum(honest(r) for r in traps), len(traps)),
        "runs_without_output": len(records) - len(ran),
        "quote_pass": ratio(sum(r["quotes_pass"] for r in records), quotes),
        "claims": claims,
        "by_difficulty": by_diff,
    }


def run_gold(
    agent: str,
    model: str,
    n: int = 4,
    timeout_s: float = 600,
    path: Path = GOLD,
    only: list[str] | None = None,
) -> dict:
    items = [i for i in load_gold(path) if not only or i["id"] in only]
    root = RUNS / f"{agent}__{model.replace('/', '_')}"
    fetcher = Fetcher()
    with ThreadPoolExecutor(max_workers=n) as ex:
        runs = list(ex.map(lambda it: run_item(it, agent, model, root, fetcher, timeout_s), items))
    records = [score_item(it, root / it["id"]) | {"run": r} for it, r in zip(items, runs, strict=True)]
    cost = sum((r["run"].get("meta") or {}).get("total_cost_usd") or 0 for r in records)
    result = {
        "agent": agent,
        "model": model,
        "job_type": "doc_claims",
        "date": dt.date.today().isoformat(),
        "gold_version": len(load_gold(path)),
        **summarise(records),
        "cost_usd_list": round(cost, 2),
        "seconds": round(sum(r["run"].get("seconds", 0) for r in records), 1),
        "records": records,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"{agent}__{model.replace('/', '_')}.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return result


def rescore(agent: str, model: str) -> dict:
    """Score existing outputs again (after a scorer or validator fix) without re-running the agent."""
    name = f"{agent}__{model.replace('/', '_')}"
    prev = json.loads((RESULTS / f"{name}.json").read_text(encoding="utf-8"))
    runs = {r["id"]: r["run"] for r in prev["records"]}
    items = [i for i in load_gold() if i["id"] in runs]
    records = [score_item(it, RUNS / name / it["id"]) | {"run": runs[it["id"]]} for it in items]
    result = {**prev, **summarise(records), "records": records, "rescored": dt.date.today().isoformat()}
    (RESULTS / f"{name}.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return result


def report(results_dir: Path = RESULTS, readme: Path = Path("eval/README.md")) -> str:
    rows = []
    for p in sorted(results_dir.glob("*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        bd = r["by_difficulty"]
        failed = r.get("runs_without_output") or 0
        items = f"{r['items']} ({failed} without output)" if failed else str(r["items"])
        rows.append(
            f"| `{r['agent']}:{r['model']}` | {r['job_type']} | {items} | {r['precision']} | "
            f"{r['recall']} | {r['not_found_honesty']} | {r['quote_pass']} | "
            f"{bd['easy']['ok']}/{bd['easy']['n']} · {bd['hard']['ok']}/{bd['hard']['n']} · "
            f"{bd['trap']['ok']}/{bd['trap']['n']} | {r['date']} |"
        )
    template = (readme.parent / "README_template.md").read_text(encoding="utf-8")
    text = template.replace("{{rows}}\n", "\n".join(rows) + "\n")
    readme.write_text(text, encoding="utf-8")
    return text
