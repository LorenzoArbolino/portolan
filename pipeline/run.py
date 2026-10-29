"""Executor: run a planned job list with N parallel workers.

Workspace per job: `runs/<run-id>/<job-id>/` with `prompt.md`, `inputs.json`, `out.jsonl`, `log.txt`.
Only `out.jsonl` and `runs/<run-id>/manifest.json` are committed. Candidates come from `models.yaml`; a
rate-limited candidate is benched for a backoff period and the job falls through to the next candidate.
Re-runs never overwrite: an earlier attempt's output is kept as `out.<n>.jsonl`."""

from __future__ import annotations

import datetime as dt
import json
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pipeline.agents import candidates, get_adapter, limits
from pipeline.plan import RUNS_DIR, Job, read_queue, render

_bench_lock = threading.Lock()


class Bench:
    """Per-candidate backoff after a rate limit: 30 s, 2 min, 10 min (models.yaml limits)."""

    def __init__(self, steps: list[float]) -> None:
        self.steps = steps or [30, 120, 600]
        self.until: dict[str, float] = {}
        self.hits: Counter[str] = Counter()

    def benched(self, key: str) -> bool:
        with _bench_lock:
            return self.until.get(key, 0) > time.monotonic()

    def hit(self, key: str) -> None:
        with _bench_lock:
            step = self.steps[min(self.hits[key], len(self.steps) - 1)]
            self.hits[key] += 1
            self.until[key] = time.monotonic() + step


def _counts(out: Path) -> dict[str, int]:
    c: Counter[str] = Counter()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            try:
                c[json.loads(line).get("kind", "?")] += 1
            except (json.JSONDecodeError, AttributeError):
                c["invalid"] += 1
    return dict(c)


def _keep_previous(workdir: Path) -> None:
    out = workdir / "out.jsonl"
    if out.exists():
        n = 1
        while (workdir / f"out.{n}.jsonl").exists():
            n += 1
        out.rename(workdir / f"out.{n}.jsonl")


def run_job(
    job: Job,
    run_dir: Path,
    bench: Bench,
    override: list[tuple[str, str]] | None = None,
    timeout_s: float = 1200,
) -> dict:
    workdir = run_dir / job.job_id
    workdir.mkdir(parents=True, exist_ok=True)
    _keep_previous(workdir)
    if job.inputs.get("document_url"):  # pre-fetched long document
        from pipeline.documents import write_document

        terms = job.inputs.get("search_terms") or [
            m.split(" (`")[0] for m in job.inputs.get("chain_molecules", [])
        ]
        if not write_document(workdir, job.inputs["document_url"], terms):
            return {
                "job_id": job.job_id,
                "job_type": job.job_type,
                "prompt_hash": job.prompt_hash,
                "inputs": {"document_url": job.inputs["document_url"]},
                "attempts": [],
                "status": "document_unreachable",
                "counts": {},
            }
    prompt = workdir / "prompt.md"
    prompt.write_text(render(job.job_type, job.inputs), encoding="utf-8")
    (workdir / "inputs.json").write_text(
        json.dumps(job.inputs, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    record = {
        "job_id": job.job_id,
        "job_type": job.job_type,
        "prompt_hash": job.prompt_hash,
        "inputs": {k: v for k, v in job.inputs.items() if k in ("molecule_id", "region", "unit_id")},
        "attempts": [],
    }
    started = dt.datetime.now(dt.UTC)
    status = "failed"
    for agent, model in override or candidates(job.job_type):
        key = f"{agent}:{model}"
        if bench.benched(key):
            record["attempts"].append({"agent": agent, "model": model, "status": "skipped_benched"})
            continue
        res = get_adapter(agent).run(prompt, job.inputs, workdir, model, timeout_s=timeout_s)
        record["attempts"].append(
            {
                "agent": agent,
                "model": model,
                "status": res.status,
                "seconds": round(res.duration_s, 1),
                **({"meta": res.meta} if res.meta else {}),
            }
        )
        status = res.status
        if res.status == "rate_limited":
            bench.hit(key)
            continue
        if res.status in ("ok", "partial"):
            record.update(agent=agent, model=model)
            break
    record.update(
        status=status,
        started_at=started.isoformat(timespec="seconds"),
        seconds=round((dt.datetime.now(dt.UTC) - started).total_seconds(), 1),
        counts=_counts(workdir / "out.jsonl"),
    )
    return record


def run(
    run_id: str,
    n: int = 8,
    override: list[tuple[str, str]] | None = None,
    runs_dir: Path = RUNS_DIR,
    queue_dir: Path | None = None,
    timeout_s: float | None = None,
    retry_failed: bool = False,
) -> dict:
    jobs = read_queue(run_id, queue_dir) if queue_dir else read_queue(run_id)
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    if retry_failed and (run_dir / "manifest.json").exists():
        done = {
            j["job_id"]
            for j in json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))["jobs"]
            if j["status"] == "ok"
        }
        jobs = [j for j in jobs if j.job_id not in done]
    lim = limits()
    bench = Bench(lim.get("rate_limit_backoff_s", []))
    timeout = timeout_s or lim.get("timeout_s", 1200)
    with ThreadPoolExecutor(max_workers=max(1, n)) as ex:
        records = list(ex.map(lambda j: run_job(j, run_dir, bench, override, timeout), jobs))
    manifest_path = run_dir / "manifest.json"
    previous = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    by_id = {r["job_id"]: r for r in previous.get("jobs", [])}
    by_id.update({r["job_id"]: r for r in records})
    manifest = {
        "run_id": run_id,
        "chain_id": jobs[0].chain_id if jobs else None,
        "updated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "jobs": sorted(by_id.values(), key=lambda r: r["job_id"]),
        "status_counts": dict(Counter(r["status"] for r in by_id.values())),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest
