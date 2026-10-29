"""`portolan` command line."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from portolan import schemas
from portolan.chain import load_chain

PUBLIC_DIRS = ("data", "notes", "eval", "build/app")

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command("schemas")
def schemas_cmd(
    root: Path = typer.Option(Path("schema"), help="Output directory"),
    check: bool = typer.Option(False, "--check", help="Fail if the files on disk are stale"),
) -> None:
    """Generate JSON Schemas from the pydantic models."""
    if check:
        stale = schemas.stale_schemas(root)
        if stale:
            typer.echo("stale schemas (run `uv run portolan schemas`): " + ", ".join(stale), err=True)
            raise typer.Exit(1)
        typer.echo("schemas up to date")
        return
    for p in schemas.write_schemas(root):
        typer.echo(p)


@app.command("chain")
def chain_cmd(path: Path) -> None:
    """Load a chain pack and check that every reference resolves."""
    pack = load_chain(path)
    typer.echo(f"{pack.id}: {len(pack.molecules)} molecules, {len(pack.routes)} routes, status {pack.status}")


@app.command("leak-check")
def leak_check_cmd(
    paths: list[Path] = typer.Argument(None, help="Files or folders (default: public data)"),
) -> None:
    """people_leak: fail if public files contain emails, phone numbers or person names."""
    from pipeline.validators.people_leak import scan_paths

    targets = paths or [p for p in map(Path, PUBLIC_DIRS) if p.exists()]
    findings = scan_paths(targets)
    for f in findings:
        typer.echo(f"{f.path}:{f.where}: {f.kind}: {f.match}", err=True)
    if findings:
        raise typer.Exit(1)
    typer.echo(f"people_leak: clean ({', '.join(map(str, targets)) or 'nothing to scan'})")


@app.command("plan")
def plan_cmd(
    chain: Path = typer.Option(Path("chains/isoprenoids.yaml")),
    jobs: str = typer.Option("J01", help="Comma-separated job types: J01,J04"),
    molecule: list[str] = typer.Option(None, help="Molecule id(s); default: the pack's first_molecules"),
    region: list[str] = typer.Option(None, help="Region code(s); default: priority-1 regions"),
    run_id: str = typer.Option(None, "--run", help="Run id; default: <date>-<chain>-<hash>"),
    rerun: bool = typer.Option(False, help="Include jobs that already succeeded"),
) -> None:
    """Chain pack + data → queue/<run-id>.jsonl."""
    from pipeline import plan as planner

    js = planner.plan(chain, jobs.split(","), molecule or None, region or None, skip_done=not rerun)
    if not js:
        typer.echo("nothing to do (all jobs already succeeded; use --rerun)")
        raise typer.Exit(0)
    rid = run_id or planner.default_run_id(load_chain(chain), js)
    path = planner.write_queue(js, rid)
    typer.echo(f"{rid}: {len(js)} jobs → {path}")


@app.command("run")
def run_cmd(
    run_id: str = typer.Argument(..., help="Run id (from `portolan plan`)"),
    n: int = typer.Option(8, help="Parallel workers"),
    agent: str = typer.Option(None, help="Force one candidate, e.g. stub:stub or claude_code:sonnet"),
    timeout: float = typer.Option(None, help="Seconds per job (default from models.yaml)"),
    retry_failed: bool = typer.Option(False, help="Only jobs that aren't ok in the run's manifest"),
) -> None:
    """Run a planned job list with N parallel workers."""
    from pipeline.run import run

    override = [tuple(agent.split(":", 1))] if agent else None
    m = run(run_id, n=n, override=override, timeout_s=timeout, retry_failed=retry_failed)
    typer.echo(json.dumps(m["status_counts"]))


@app.command("collect")
def collect_cmd(
    run_id: str = typer.Argument(...),
    no_fetch: bool = typer.Option(False, "--no-fetch", help="Skip quote fetching (quote_check = manual)"),
) -> None:
    """Validate a run's out.jsonl files and write proposals to data/ + review/queue.jsonl."""
    from pipeline.collect import collect, offline_checker

    _, text = collect(run_id, checker=offline_checker if no_fetch else None)
    typer.echo(text)


@app.command("publish")
def publish_cmd(
    run_id: str = typer.Argument(...),
    branch_prefix: str = typer.Option("run/", help="Branch name = prefix + run id"),
    base: str = typer.Option(None, help="PR base branch (default: current branch)"),
    repo: str = typer.Option(None, help="owner/repo for the PR (needs gh); omit to only push"),
    push: bool = typer.Option(True, help="Push the branch"),
) -> None:
    """Commit a collected run to a new branch, push it and open a PR with the summary table."""
    from pipeline.publish import publish

    typer.echo(json.dumps(publish(run_id, branch_prefix, base, push, repo), indent=2))


@app.command("build")
def build_cmd(
    chain: list[Path] = typer.Option(None, help="Chain pack(s); default: every chains/*.yaml"),
    on: str = typer.Option(None, help="Resolve as of this date (YYYY-MM-DD); default today"),
) -> None:
    """data/ → build/graph.duckdb → build/app/<chain>.json + sites.geojson."""
    import datetime as dt

    from portolan.build import build

    packs = chain or sorted(p for p in Path("chains").glob("*.yaml") if not p.name.startswith("_"))
    for p in build(packs, on=dt.date.fromisoformat(on) if on else None):
        typer.echo(f"{p} ({p.stat().st_size:,} bytes)")


@app.command("audit")
def audit_cmd(
    chain: Path = typer.Option(Path("chains/isoprenoids.yaml")),
    bundle: Path = typer.Option(None, help="Built bundle; default build/app/<chain>.json"),
    out: Path = typer.Option(Path("build")),
    compare: Path = typer.Option(None, help="An earlier audit.json for a before/after table"),
) -> None:
    """Coverage, estimates, duplicates and contradictions of the built map → build/audit.{md,json}."""
    from portolan.audit import run
    from portolan.chain import load_chain

    pack = load_chain(chain)
    a = run(bundle or Path("build/app") / f"{pack.slug}.json", pack, out, compare)
    for k, v in a["summary"].items():
        typer.echo(f"{k}: {v}")


@app.command("backtest")
def backtest_cmd(
    chain: Path = typer.Option(Path("chains/isoprenoids.yaml")),
    out: Path = typer.Option(Path("eval/estimates.md")),
    check: bool = typer.Option(False, help="Fail if the committed file differs (CI)"),
    on: str = typer.Option(None, help="Resolve as of this date; default: the date in the committed file"),
) -> None:
    """Leave-one-out backtest of every imputing estimate method, per molecule → eval/estimates.md."""
    import datetime as dt
    import re

    from portolan.chain import load_chain
    from portolan.estimate import backtest, backtest_markdown
    from portolan.merges import apply, id_map
    from portolan.store import Store

    pack = load_chain(chain)
    store = Store(Path("data"))
    if on is None and out.exists() and (m := re.search(r"Built (\d{4}-\d{2}-\d{2})", out.read_text("utf-8"))):
        on = m.group(1)
    day = dt.date.fromisoformat(on) if on else dt.date.today()
    units = store.load("units")
    units, _, claims, _ = apply(id_map(store.load("merges"), units), units, store.load("sites"),
                                store.load("claims"), store.load("events"))  # fmt: skip
    mols = {m.id for m in pack.molecules}
    units = [u for u in units if u.molecule_id in mols and not pack.molecule(u.molecule_id).byproduct]
    md = backtest_markdown(backtest(units, claims, day), {m.id: m.name for m in pack.molecules}, day) + "\n"
    if check:
        if not out.exists() or out.read_text("utf-8") != md:
            typer.echo(f"{out} is stale: run `uv run portolan backtest`")
            raise typer.Exit(1)
        typer.echo(f"{out} up to date")
        return
    out.write_text(md, encoding="utf-8")
    typer.echo(md)


@app.command("trade-pull")
def trade_pull_cmd(
    chain: Path = typer.Option(Path("chains/isoprenoids.yaml")),
    first: int = typer.Option(2015),
    last: int = typer.Option(2025),
) -> None:
    """EU27 imports/exports by partner for the chain's HS6 codes (Eurostat Comext) → data/flows/."""
    from pipeline.sources.comext import trade_pull

    codes = sorted({h for m in load_chain(chain).molecules for h in m.hs6})
    typer.echo(json.dumps(trade_pull(codes, list(range(first, last + 1)))))


@app.command("cdr-pull")
def cdr_pull_cmd(
    run_id: str = typer.Option(..., "--run", help="Run id, e.g. 2026-10-28-isoprenoids-cdr"),
    chain: Path = typer.Option(Path("chains/isoprenoids.yaml")),
) -> None:
    """US EPA CDR site records for the chain's CAS numbers → runs/<run>/cdr/out.jsonl (then `collect`)."""
    from pipeline.sources.cdr import pull

    pack = load_chain(chain)
    cas = {
        m.cas: m.id for m in pack.molecules if m.cas and m.role != "context"
    }  # context: GEM's, or out of scope
    typer.echo(json.dumps(pull(Path("runs") / run_id, cas, pack.id)))


@app.command("coverage")
def coverage_cmd(chain: Path = typer.Option(Path("chains/isoprenoids.yaml"))) -> None:
    """Coverage notes per country × molecule → data/coverage.csv."""
    from portolan.coverage import coverage, write_coverage
    from portolan.store import Store

    rows = coverage(load_chain(chain), Store("data"))
    typer.echo(
        f"{write_coverage(rows)}: {len(rows)} rows, {sum(r['note'].startswith('gap') for r in rows)} gaps"
    )


@app.command("locate")
def locate_cmd() -> None:
    """Town-level placement for sites with no published coordinates → data/site_locations.csv."""
    from pipeline.fetch import Fetcher
    from pipeline.sources.wikipedia_places import (
        locate,
        locate_ne,
        locate_region,
        ne_places,
        read_locations,
        write_locations,
    )
    from portolan.store import Store

    store = Store("data")
    located = {
        c.subject_id for c in store.load("claims") if c.field == "lat_lon" and c.review_state == "accepted"
    }
    rows = read_locations()
    fetcher, missing, places = Fetcher(), [], None
    wiki = fetcher.get("https://en.wikipedia.org/wiki/Ludwigshafen").ok  # blocked for bots since 2026-10-28
    for s in store.load("sites"):
        if s.lat is not None or s.id in located or s.id in rows:
            continue
        r = locate(s, fetcher) if wiki and s.geo_precision != "country" else None
        if r is None:
            places = ne_places(fetcher) if places is None else places
            r = (locate_ne(s, places) if s.geo_precision != "country" else None) or locate_region(s, places)
        if r:
            rows[s.id] = r
        else:
            missing.append(s.id)
    write_locations(rows)
    typer.echo(f"{len(rows)} sites placed at town level; not located: {', '.join(missing) or 'none'}")


@app.command("review")
def review_cmd(
    items: list[str] = typer.Argument(..., help="Review ids (rv:…) or claim ids (clm:…)"),
    accept: bool = typer.Option(False, "--accept/--reject", help="Decision"),
    note: str = typer.Option(..., help="Why, in one line (checked against the quote)"),
    unit: str = typer.Option(None, help="Correct unit_raw (re-normalised), e.g. MTPM"),
    basis: str = typer.Option(None, help="Correct capacity_basis, e.g. permitted"),
    flag: str = typer.Option(None, help='Add a flag, e.g. "product basis not stated"'),
) -> None:
    """Accept or reject claims and close their review-queue items."""
    from portolan.review import decide

    changed, closed = decide(items, accept, note, unit=unit, basis=basis, flag=flag)
    typer.echo(f"{'accepted' if accept else 'rejected'} {changed} claims; closed {closed} review items")


@app.command("promote-leads")
def promote_leads_cmd(chain: Path = typer.Option(Path("chains/isoprenoids.yaml"))) -> None:
    """Company-level leads ("X makes M, plant not named") → units, so they count in market shares."""
    from portolan.leads import promote_leads
    from portolan.store import Store

    pack = load_chain(chain)
    names = {m.id: m.name for m in pack.molecules}
    typer.echo(json.dumps(promote_leads(Store("data"), Path("review/queue.jsonl"), names)))


@app.command("merge")
def merge_cmd(
    from_id: str,
    to_id: str,
    reason: str = typer.Option(..., help="Why these are the same thing"),
    name: str = typer.Option(None, help="Create the target company with this name if it doesn't exist"),
    by: str = typer.Option("claude", help="Who decided"),
) -> None:
    """Record a merge in data/merges.csv. IDs aren't rewritten; the build applies merges."""
    import datetime as dt

    from portolan.models import Company, Merge
    from portolan.store import Store

    store = Store("data")
    if name and to_id.startswith("co:") and to_id not in store.ids("companies"):
        store.append("companies", [Company(id=to_id, name=name)])
    known = store.ids("sites") | store.ids("companies")
    if from_id not in known or to_id not in known:
        raise typer.BadParameter(f"unknown id: {from_id if from_id not in known else to_id}")
    store.append(
        "merges", [Merge(from_id=from_id, to_id=to_id, reason=reason, decided_by=by, date=dt.date.today())]
    )
    typer.echo(f"merged {from_id} → {to_id}")


if __name__ == "__main__":
    app()
