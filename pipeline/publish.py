"""Turn a collected run into a branch and a PR (the merge is the review).

Commits only the run's public record: `data/`, `review/`, `queue/<run-id>.jsonl`, and from `runs/<run-id>/`
the `out*.jsonl` files, `manifest.json` and `summary.md`. The PR is opened through the GitHub REST API via
`gh api` (works with any token gh can use); without gh the branch is pushed and the summary printed."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def run_paths(run_id: str, runs_dir: Path = Path("runs")) -> list[str]:
    """Public record of one or more runs (comma-separated ids)."""
    paths: list[str] = []
    for rid in run_id.split(","):
        run_dir = runs_dir / rid
        paths += [p.as_posix() for p in sorted(run_dir.glob("*/out*.jsonl"))]
        paths += [(run_dir / f).as_posix() for f in ("manifest.json", "summary.md") if (run_dir / f).exists()]
        paths += [f"queue/{rid}.jsonl"] if Path(f"queue/{rid}.jsonl").exists() else []
    paths += [p for p in ("data", "review") if Path(p).exists()]
    return paths


def publish(
    run_id: str,
    branch_prefix: str = "run/",
    base: str | None = None,
    push: bool = True,
    repo: str | None = None,
) -> dict:
    ids = run_id.split(",")
    summary = "\n".join((Path("runs") / rid / "summary.md").read_text(encoding="utf-8") for rid in ids)
    base = base or _git("rev-parse", "--abbrev-ref", "HEAD")
    branch = f"{branch_prefix}{ids[-1]}"
    _git("checkout", "-b", branch)
    _git("add", "--", *run_paths(run_id))
    first = next((ln for ln in summary.splitlines() if ln.startswith("| Claims by grade")), "")
    _git("commit", "-m", f"Runs {', '.join(ids)}: proposals\n\n{first}")
    result = {"branch": branch, "base": base, "pr": None}
    if not push:
        return result
    _git("push", "-u", "origin", branch)
    if shutil.which("gh") and repo:
        out = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{repo}/pulls",
                "-f",
                f"title=Run {run_id}",
                "-f",
                f"head={branch}",
                "-f",
                f"base={base}",
                "-f",
                f"body={summary}",
            ],
            capture_output=True,
            text=True,
        )
        if out.returncode == 0:
            result["pr"] = json.loads(out.stdout).get("html_url")
        else:
            result["pr_error"] = (out.stderr or out.stdout)[:300]
    return result
