"""Claude Code adapter (headless `claude -p`). Flags checked against `claude --help`, v2.1.

Scoped on purpose: only web search/fetch and file read/write tools exist in the session (`--tools`, no
shell), permission mode `dontAsk` refuses anything not pre-allowed, no MCP servers, no saved session.
The job workdir is the working directory, so the agent writes `out.jsonl` there."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from pipeline.agents.base import AgentAdapter, AgentResult, classify, isolated, run_process, with_output_path

TOOLS = ["WebSearch", "WebFetch", "Read", "Write", "Edit", "Glob", "Grep"]


class ClaudeCodeAdapter(AgentAdapter):
    name = "claude_code"
    binary = "claude"

    def command(self, workdir: Path, model: str) -> list[str]:
        return [
            shutil.which(self.binary) or self.binary,
            "-p",
            "--model",
            model,
            "--output-format",
            "json",
            "--tools",
            ",".join(TOOLS),
            "--allowedTools",
            ",".join(TOOLS),
            "--permission-mode",
            "dontAsk",
            "--strict-mcp-config",
            "--no-session-persistence",
        ]

    def run(
        self, prompt_path: Path, inputs: dict, workdir: Path, model: str, timeout_s: float = 1200
    ) -> AgentResult:
        out = workdir / "out.jsonl"
        log = workdir / "log.txt"
        if shutil.which(self.binary) is None:
            log.write_text("[claude_code] binary not found\n", encoding="utf-8")
            return AgentResult("failed", out, log, error="claude not installed")
        with isolated(workdir) as cwd:
            prompt = with_output_path(prompt_path.read_text(encoding="utf-8"), cwd)
            rc, output, dur, timed_out, rate_limited = run_process(
                self.command(cwd, model), cwd=cwd, timeout_s=timeout_s, log_path=log, stdin_text=prompt
            )
        meta = {}
        try:
            res = json.loads(output.strip().splitlines()[-1]) if output.strip() else {}
            meta = {k: res.get(k) for k in ("num_turns", "total_cost_usd", "duration_ms", "is_error")}
            if res.get("is_error") and RATE_HINT in str(res.get("result", "")).lower():
                rate_limited = True
        except (json.JSONDecodeError, IndexError):
            pass
        status = classify(out, rc, timed_out, rate_limited)
        return AgentResult(
            status,
            out,
            log,
            returncode=rc,
            duration_s=dur,
            meta=meta,
            error=None if status == "ok" else status,
        )


RATE_HINT = "limit"
