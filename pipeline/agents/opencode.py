"""OpenCode adapter (non-interactive `opencode run`). Works with v1.19.4 and v2.1.4 (no `--dir` in v2).

Never uses `--auto`. Instead each job workdir gets an `opencode.json` that denies everything except reading
and writing inside the workdir and web fetch/search: no shell, no subagents, no paths outside the job.
OpenCode can hang on provider errors (e.g. "Free usage limit reached") instead of exiting, so the adapter
watches OpenCode's own log and stops the run when it sees a rate limit.

The prompt goes in `prompt.md` and the command line carries only a one-line instruction: on Windows, npm
installs `opencode.cmd`; cmd.exe mangles multi-line arguments and caps command lines at 8191 chars."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from pipeline.agents.base import AgentAdapter, AgentResult, classify, isolated, run_process, with_output_path

PERMISSIONS = {
    "*": "deny",
    "read": "allow",
    "glob": "allow",
    "grep": "allow",
    "edit": "allow",
    "webfetch": "allow",
    "websearch": "allow",
    "external_directory": "deny",
    "bash": "deny",
    "task": "deny",
    "question": "deny",
    "doom_loop": "deny",
}


class OpenCodeAdapter(AgentAdapter):
    name = "opencode"
    binary = "opencode"

    message = "Read the file prompt.md in the current directory and follow its instructions exactly."

    def command(self, exe: str, workdir: Path, model: str) -> list[str]:
        # No --dir: removed in OpenCode v2; the process runs in `workdir`.
        return [exe, "run", "-m", model, "--format", "json", self.message]

    def run(
        self, prompt_path: Path, inputs: dict, workdir: Path, model: str, timeout_s: float = 1200
    ) -> AgentResult:
        out = workdir / "out.jsonl"
        log = workdir / "log.txt"
        exe = shutil.which(self.binary)  # full path, incl. opencode.cmd on Windows
        if exe is None:
            log.write_text("[opencode] binary not found\n", encoding="utf-8")
            return AgentResult("failed", out, log, error="opencode not installed")
        cli_log = (
            Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "opencode/log/opencode.log"
        )
        config = json.dumps({"$schema": "https://opencode.ai/config.json", "permission": PERMISSIONS})
        (workdir / "opencode.json").write_text(config, encoding="utf-8")  # audit copy (gitignored)
        with isolated(workdir) as cwd:
            (cwd / "opencode.json").write_text(config, encoding="utf-8")
            prompt = with_output_path(prompt_path.read_text(encoding="utf-8"), cwd)
            (cwd / "prompt.md").write_text(prompt, encoding="utf-8")
            rc, _, dur, timed_out, rate_limited = run_process(
                self.command(exe, cwd, model),
                cwd=cwd,
                timeout_s=timeout_s,
                log_path=log,
                watch_files=[cli_log],
            )
        status = classify(out, rc, timed_out, rate_limited)
        return AgentResult(
            status, out, log, returncode=rc, duration_s=dur, error=None if status == "ok" else status
        )
