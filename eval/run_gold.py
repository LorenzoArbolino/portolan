"""Score agent:model candidates on the gold set. See pipeline/gold.py and eval/README.md.

uv run python eval/run_gold.py check                         # verify every gold quote at its source
uv run python eval/run_gold.py run --agent claude_code:sonnet [--n 4] [--only g01,g02]
uv run python eval/run_gold.py report                        # rebuild eval/README.md from eval/results/
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import gold  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "run", "rescore", "report"])
    ap.add_argument("--agent", default="claude_code:sonnet")
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--only", default="")
    ap.add_argument("--timeout", type=float, default=600)
    a = ap.parse_args()
    if a.cmd == "check":
        bad = 0
        for gid, status, url in gold.check_gold():
            print(f"{gid} {status:12} {url}")
            bad += status != "pass"
        sys.exit(1 if bad else 0)
    elif a.cmd == "run":
        agent, model = a.agent.split(":", 1)
        r = gold.run_gold(agent, model, n=a.n, timeout_s=a.timeout, only=[x for x in a.only.split(",") if x])
        print(json.dumps({k: v for k, v in r.items() if k != "records"}, indent=2))
        errors = [x["run"]["error"] for x in r["records"] if x["run"].get("error")]
        if errors:
            print(f"\n{len(errors)} question(s) failed to run. First error (end of its log):\n{errors[0]}")
    elif a.cmd == "rescore":
        agent, model = a.agent.split(":", 1)
        r = gold.rescore(agent, model)
        print(json.dumps({k: v for k, v in r.items() if k != "records"}, indent=2))
    else:
        print(gold.report())
