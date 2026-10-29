"""Adapters against fake CLIs (offline). The real CLIs are exercised in recorded runs, not in CI."""

import json
import os
import stat
import sys
import textwrap
from pathlib import Path

from pipeline.agents import candidates, get_adapter
from pipeline.agents.claude_code import ClaudeCodeAdapter
from pipeline.agents.opencode import OpenCodeAdapter


def _fake_cli(tmp_path: Path, name: str, body: str) -> Path:
    """A stand-in CLI: a Python script, launched like npm launches tools (a shebang file on POSIX, a .cmd
    wrapper on Windows, so the cmd.exe argument path is exercised too)."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    script = bindir / f"{name}_impl.py"
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    if os.name == "nt":
        (bindir / f"{name}.cmd").write_text(
            f'@"{sys.executable}" "%~dp0{name}_impl.py" %*\r\n', encoding="utf-8"
        )
    else:
        p = bindir / name
        p.write_text(f"#!{sys.executable}\n" + textwrap.dedent(body), encoding="utf-8")
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return bindir


def _job(tmp_path):
    wd = tmp_path / "job"
    wd.mkdir()
    prompt = wd / "prompt.md"
    prompt.write_text("Write out.jsonl", encoding="utf-8")
    return wd, prompt


def test_models_yaml_candidates():
    assert candidates("enumerate_producers")[0][0] in ("opencode", "claude_code")
    assert get_adapter("stub").name == "stub"


def test_claude_code_ok(tmp_path, monkeypatch):
    bindir = _fake_cli(
        tmp_path,
        "claude",
        """
        import sys, json
        prompt = sys.stdin.read()
        assert "--permission-mode" in sys.argv and "dontAsk" in sys.argv and "Bash" not in " ".join(sys.argv)
        open("out.jsonl", "w").write(json.dumps({"kind": "not_found", "query": "q"}) + "\\n")
        print(json.dumps({"is_error": False, "num_turns": 3, "total_cost_usd": 0.01, "result": "done"}))
    """,
    )
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    wd, prompt = _job(tmp_path)
    res = ClaudeCodeAdapter().run(prompt, {}, wd, "sonnet", timeout_s=30)
    assert res.status == "ok" and res.meta["num_turns"] == 3
    assert (wd / "log.txt").exists()


def test_opencode_rate_limit_is_detected_even_if_cli_hangs(tmp_path, monkeypatch):
    bindir = _fake_cli(
        tmp_path,
        "opencode",
        """
        import time
        print("AI_APICallError: Free usage limit reached.", flush=True)
        time.sleep(60)
    """,
    )
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    wd, prompt = _job(tmp_path)
    res = OpenCodeAdapter().run(prompt, {}, wd, "opencode/some-free-model", timeout_s=30)
    assert res.status == "rate_limited" and res.duration_s < 20
    cfg = (wd / "opencode.json").read_text()
    assert '"bash": "deny"' in cfg and '"*": "deny"' in cfg


def test_timeout_keeps_partial_output(tmp_path, monkeypatch):
    bindir = _fake_cli(
        tmp_path,
        "opencode",
        """
        import time
        open("out.jsonl", "w").write('{"kind": "not_found", "query": "q"}\\n')
        time.sleep(60)
    """,
    )
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    wd, prompt = _job(tmp_path)
    res = OpenCodeAdapter().run(prompt, {}, wd, "m", timeout_s=2)
    assert res.status == "partial"


def test_agent_runs_outside_the_repo_and_output_comes_back(tmp_path, monkeypatch):
    bindir = _fake_cli(
        tmp_path,
        "claude",
        """
        import os, json, pathlib
        cwd = pathlib.Path.cwd()
        assert not any((p / "CLAUDE.md").exists() for p in [cwd, *cwd.parents]), "agent can see a CLAUDE.md"
        assert (cwd / "prompt.md").exists()
        open("out.jsonl", "w").write(json.dumps({"kind": "not_found", "query": str(cwd)}) + "\\n")
        print(json.dumps({"is_error": False}))
    """,
    )
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    wd = Path(__file__).parent.parent / "runs" / "_test_isolation"
    wd.mkdir(parents=True, exist_ok=True)
    try:
        (wd / "prompt.md").write_text("x")
        res = ClaudeCodeAdapter().run(wd / "prompt.md", {}, wd, "sonnet", timeout_s=30)
        assert res.status == "ok"
        assert "portolan-job-" in (wd / "out.jsonl").read_text()
    finally:
        import shutil

        shutil.rmtree(wd)


def test_opencode_gets_prompt_via_file_and_one_line_message(tmp_path, monkeypatch):
    bindir = _fake_cli(
        tmp_path,
        "opencode",
        """
        import sys, json, pathlib
        args = sys.argv[1:]
        msg = args[-1]
        assert "\\n" not in msg and "prompt.md" in msg, msg
        prompt = pathlib.Path("prompt.md").read_text(encoding="utf-8")
        assert "out.jsonl" in prompt and "Résumé 柠檬醛" in prompt
        assert json.loads(pathlib.Path("opencode.json").read_text(encoding="utf-8"))["permission"]["bash"] == "deny"
        open("out.jsonl", "w", encoding="utf-8").write(json.dumps({"kind": "not_found", "query": "柠檬醛"}) + "\\n")
        print(json.dumps({"type": "done", "text": "柠檬醛 ok"}))
    """,
    )
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    wd, prompt = _job(tmp_path)
    prompt.write_text('Line one\nRésumé 柠檬醛 "quoted" & <tags> %PATH%\nWrite out.jsonl', encoding="utf-8")
    res = OpenCodeAdapter().run(prompt, {}, wd, "opencode/free", timeout_s=60)
    assert res.status == "ok", (wd / "log.txt").read_text(encoding="utf-8")
    assert json.loads((wd / "out.jsonl").read_text(encoding="utf-8"))["query"] == "柠檬醛"
