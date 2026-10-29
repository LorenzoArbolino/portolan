"""Adapter interface: `run(prompt_path, inputs, workdir, model) -> AgentResult` (out.jsonl in workdir).

The process is run with a wall-clock timeout; stdout/stderr go to `log.txt`; the run is killed early
when the output shows a rate limit (some CLIs hang on provider errors instead of exiting)."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Status = Literal["ok", "partial", "failed", "rate_limited", "timeout"]

RATE_LIMIT = re.compile(
    r"rate.?limit|usage limit|too many requests|\b429\b|quota exceeded|free usage limit|overloaded",
    re.IGNORECASE,
)


@dataclass
class AgentResult:
    status: Status
    out_path: Path
    log_path: Path
    returncode: int | None = None
    duration_s: float = 0.0
    error: str | None = None
    meta: dict = field(default_factory=dict)


class AgentAdapter(ABC):
    name: str = "base"

    @abstractmethod
    def run(
        self, prompt_path: Path, inputs: dict, workdir: Path, model: str, timeout_s: float = 1200
    ) -> AgentResult: ...


# Start the agent in its own process group so a timeout can stop it and everything it spawned.
_NEW_GROUP = (
    {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
)


def _kill_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":  # no process groups to signal: taskkill /T stops the whole tree
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False)
        proc.wait(timeout=10)
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        os.killpg(proc.pid, signal.SIGKILL)


def run_process(
    cmd: list[str],
    cwd: Path,
    timeout_s: float,
    log_path: Path,
    env: dict | None = None,
    watch_files: list[Path] | None = None,
    stdin_text: str | None = None,
) -> tuple[int | None, str, float, bool, bool]:
    """Run `cmd`, tee output to `log_path`. Returns (returncode, output, seconds, timed_out, rate_limited).

    Kills the process group on timeout, or as soon as the output (or a watched log file) shows a rate limit.
    """
    start = time.monotonic()
    out_chunks: list[str] = []
    rate_limited = threading.Event()
    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"$ {' '.join(cmd[:1] + ['…'])}  (cwd={cwd})\n")
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env={**os.environ, **(env or {})},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_NEW_GROUP,
        )
        if stdin_text is not None:
            proc.stdin.write(stdin_text)
            proc.stdin.close()

        def reader() -> None:
            for line in proc.stdout:
                out_chunks.append(line)
                log.write(line)
                log.flush()
                if RATE_LIMIT.search(line):
                    rate_limited.set()

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        sizes = {p: (p.stat().st_size if p.exists() else 0) for p in watch_files or []}
        timed_out = False
        while proc.poll() is None:
            if time.monotonic() - start > timeout_s:
                timed_out = True
                break
            for p in watch_files or []:
                if p.exists() and p.stat().st_size > sizes[p]:
                    with open(p, encoding="utf-8", errors="replace") as fh:
                        fh.seek(sizes[p])
                        new = fh.read()
                    sizes[p] += len(new.encode("utf-8"))
                    if RATE_LIMIT.search(new):
                        log.write("[adapter] rate limit seen in CLI log\n")
                        rate_limited.set()
            if rate_limited.is_set():
                break
            time.sleep(0.5)
        if proc.poll() is None:
            _kill_tree(proc)
        t.join(timeout=5)
        dur = time.monotonic() - start
        log.write(
            f"[adapter] exit={proc.returncode} seconds={dur:.1f} timeout={timed_out} "
            f"rate_limited={rate_limited.is_set()}\n"
        )
    return proc.returncode, "".join(out_chunks), dur, timed_out, rate_limited.is_set()


# Files an agent may read; copied into the isolated directory (never the repo).
INPUT_FILES = ("prompt.md", "inputs.json", "document.txt")


@contextmanager
def isolated(workdir: Path) -> Iterator[Path]:
    """Run an agent outside the repo: agent CLIs auto-load CLAUDE.md / AGENTS.md from parent directories,
    which would turn an extraction worker into a builder. Inputs are copied in; `out.jsonl` is copied back."""
    tmp = Path(tempfile.mkdtemp(prefix="portolan-job-"))
    try:
        for name in INPUT_FILES:
            if (workdir / name).exists():
                shutil.copy(workdir / name, tmp / name)
        yield tmp
    finally:
        if (tmp / "out.jsonl").exists():
            shutil.copy(tmp / "out.jsonl", workdir / "out.jsonl")
        shutil.rmtree(tmp, ignore_errors=True)


def with_output_path(prompt: str, cwd: Path) -> str:
    """Tell the agent exactly where to write (agents guessing absolute paths wrote to sibling folders)."""
    return (
        f"Your working directory is `{cwd}`. Write your output to exactly `{cwd / 'out.jsonl'}` and nowhere "
        f"else; any other files you read are in that directory too.\n\n{prompt}"
    )


def classify(out_path: Path, rc: int | None, timed_out: bool, rate_limited: bool) -> Status:
    has_out = out_path.exists() and out_path.stat().st_size > 0
    if rate_limited and not has_out:
        return "rate_limited"
    if timed_out:
        return "partial" if has_out else "timeout"
    if rc == 0 and has_out:
        return "ok"
    return "partial" if has_out else "failed"


class StubAdapter(AgentAdapter):
    """Deterministic offline adapter: writes a canned out.jsonl derived only from the inputs.

    If inputs contain `stub_lines`, those are written verbatim; otherwise one `not_found` line."""

    name = "stub"

    def run(
        self, prompt_path: Path, inputs: dict, workdir: Path, model: str, timeout_s: float = 1200
    ) -> AgentResult:
        out = workdir / "out.jsonl"
        log = workdir / "log.txt"
        lines = inputs.get("stub_lines") or [
            {
                "kind": "not_found",
                "query": f"stub: {inputs.get('job_type')} {inputs.get('molecule_name', '')} "
                f"{inputs.get('region', '')}".strip(),
                "searched": [],
            }
        ]
        out.write_text(
            "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in lines), encoding="utf-8"
        )
        log.write_text(f"[stub] model={model} lines={len(lines)}\n", encoding="utf-8")
        return AgentResult("ok", out, log, returncode=0)
