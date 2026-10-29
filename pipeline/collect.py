"""Collector: `runs/<run-id>/*/out.jsonl` → validators → proposals in
`data/` + `review/queue.jsonl` + `runs/<run-id>/summary.md`. The only code path (with the resolver) that
writes canonical data; the result goes to a branch and PR, and the merge is the review.

Grades, per evidence: primary source + quote pass → A; trade press/association + pass → B; aggregator,
or primary/press whose quote couldn't be machine-checked → C; failed quote → D. A claim takes the best grade
of its evidence; an assumed unit factor costs one grade. Auto-accept: grade A/B, every quote passes,
values normalise, sanity passes, no conflict with an accepted claim, not a move to closing/closed, not a
capacity change > 25%. Everything else that needs a look goes to the review queue."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.sources import cdr
from pipeline.validators import dedupe, geo, sanity
from pipeline.validators.licence import quarantined
from pipeline.validators.people_leak import scan_record
from pipeline.validators.quote_check import QuoteResult, check_quote
from pipeline.validators.schema import validate_file
from pipeline.validators.units import downgrade, has_product_bases, normalise_capacity, product_basis
from pipeline.validators.vocab import normalise_status, normalise_year
from portolan import ids
from portolan.chain import ChainPack, load_chain
from portolan.estimate import BASIS_UNSTATED
from portolan.leads import UNIT_FIELDS as LEAD_FIELDS
from portolan.leads import site_for_company
from portolan.merges import id_map
from portolan.models import Claim, Company, Event, Evidence, OutClaim, OutEvent, Site, SubjectRef, Unit
from portolan.store import Store

PRIMARY = {"regulator", "permit", "company_primary", "exchange_filing", "trade_measure"}
SECONDARY = {"trade_press", "association"}
REVIEW_PATH = Path("review/queue.jsonl")

QuoteChecker = Callable[[str, str], QuoteResult]


def gold_passed(path: Path = Path(__file__).parent / "models.yaml") -> set[str]:
    import yaml

    return set(yaml.safe_load(path.read_text(encoding="utf-8")).get("gold_passed", []))


def evidence_grade(source_type: str, quote_check: str) -> str:
    if quote_check == "fail":
        return "D"
    if source_type == "operator_claimed":
        return "B"
    if source_type in PRIMARY:
        return "A" if quote_check == "pass" else "C"
    if source_type in SECONDARY:
        return "B" if quote_check == "pass" else "C"
    return "C"


def world_figure(value, unit_raw: str | None, language: str | None) -> tuple[float | None, str | None]:
    """A market-level figure in t/a. World figures are annual by convention, so a bare "tons" means per year;
    a range is taken at its midpoint. Both are flagged."""
    import re

    flag = None
    unit = unit_raw or "t"
    if "/" not in unit and not re.search(r"\b(per|pro|annu|year|yr|jahr|år|年)", unit, re.IGNORECASE):
        unit, flag = f"{unit} per year", "assumed annual (world figure)"
    nums = re.findall(r"\d[\d,.' ]*\d|\d", str(value))
    if len(nums) == 2 and re.search(r"\d\s*(?:-|–|to|~|至|〜)\s*\d", str(value)):
        lo, hi = (normalise_capacity(x.strip(), unit, language) for x in nums)
        if lo.ok and hi.ok:
            return (lo.value_tpa + hi.value_tpa) / 2, "range midpoint" + (f"; {flag}" if flag else "")
    n = normalise_capacity(value, unit, language)
    return (n.value_tpa, flag) if n.ok else (None, n.reason)


def offline_checker(quote: str, url: str) -> QuoteResult:
    return QuoteResult("manual", reason="collected with --no-fetch")


def online_checker(fetcher=None) -> QuoteChecker:
    from pipeline.fetch import Fetcher

    f = fetcher or Fetcher()

    def check(quote: str, url: str) -> QuoteResult:
        if url == cdr.URL:  # a dataset row: checked against the dataset, not a page
            ok = cdr.verify(quote)
            return QuoteResult(
                "pass" if ok else "fail", source="dataset", reason=None if ok else "row not found"
            )
        return check_quote(quote, url=url, fetcher=f)

    return check


@dataclass
class Batch:
    run_id: str
    pack: ChainPack
    store: Store
    companies: list[Company] = field(default_factory=list)
    sites: list[Site] = field(default_factory=list)
    units: list[Unit] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    review: list[dict] = field(default_factory=list)
    stats: Counter = field(default_factory=Counter)
    rejected: list[str] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)


def _review(batch: Batch, kind: str, subject: str, note: str, claim_ids: list[str] | None = None) -> None:
    item_id = (
        "rv:"
        + hashlib.sha1(
            f"{kind}\n{subject}\n{','.join(sorted(claim_ids or []))}\n{note}".encode()
        ).hexdigest()[:12]
    )
    batch.review.append(
        {
            "id": item_id,
            "run_id": batch.run_id,
            "kind": kind,
            "subject_id": subject,
            "claim_ids": claim_ids or [],
            "note": note,
            "state": "open",
            "created": dt.date.today().isoformat(),
        }
    )


class Collector:
    def __init__(self, run_dir: Path, store: Store, checker: QuoteChecker, chains_dir: Path = Path("chains")):
        self.run_dir = run_dir
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.manifest = manifest
        pack = load_chain(chains_dir / f"{manifest['chain_id'].removeprefix('chain:')}.yaml")
        self.batch = Batch(run_id=manifest["run_id"], pack=pack, store=store)
        self.checker = checker
        self._ev_cache: dict[str, Evidence] = {}
        self.existing = {t: store.load(t) for t in ("companies", "sites", "units", "claims", "evidence")}
        self.gold_passed = gold_passed()

    # --- entity matching ----------------------------------------------------------------------------

    def _all(self, table: str) -> list:
        return self.existing[table] + getattr(self.batch, table)

    def company_for(self, name: str, aliases: list[str], **kw) -> str:
        keys = {ids.company_key(x) for x in [name, *aliases]}
        merged_away = {m.from_id for m in self.batch.store.load("merges")}
        for c in self._all("companies"):
            if c.id in merged_away:  # no longer an entity; its old aliases must not capture new names
                continue
            if {ids.company_key(x) for x in [c.name, *c.aliases]} & keys:
                return c.id
        cid = ids.company_id(name)
        self.batch.companies.append(Company(id=cid, name=name, aliases=aliases, **kw))
        return cid

    def site_for(self, name: str, country: str, locality: str, company: str | None, **kw) -> str:
        operators = {c.subject_id: c.value_norm for c in self._all("claims") if c.field == "operator"}
        for s in self._all("sites"):
            if s.country != country or not dedupe.same_locality(s.locality, locality):
                continue
            if ids.slugify(s.name) == ids.slugify(name) or (company and operators.get(s.id) == company):
                return s.id
        sid = ids.next_site_id(country, locality, [s.id for s in self._all("sites")])
        self.batch.sites.append(
            Site(id=sid, name=name, country=country, locality=locality, geo_precision="locality", **kw)
        )
        return sid

    def unit_for(self, site_id: str, molecule_id: str) -> str:
        m = self.batch.pack.molecule(molecule_id)
        uid = ids.unit_id(site_id, m.name)
        if not any(u.id == uid for u in self._all("units")):
            self.batch.units.append(Unit(id=uid, site_id=site_id, molecule_id=molecule_id))
        return uid

    # --- evidence ------------------------------------------------------------------------------------

    def evidence_for(self, line) -> Evidence:
        eid = ids.evidence_id(line.url, line.quote)
        if eid in self._ev_cache:
            return self._ev_cache[eid]
        prior = next((e for e in self.existing["evidence"] if e.id == eid), None)
        if prior:
            self._ev_cache[eid] = prior
            return prior
        res = self.checker(line.quote, line.url)
        # Agents' timestamps are unreliable; when we fetched the page ourselves, that is the retrieval time.
        fetched = res.source in ("url", "archive")
        ev = Evidence(
            id=eid,
            url=ids.canonical_url(line.url),
            retrieved_at=dt.datetime.now(dt.UTC).replace(microsecond=0) if fetched else line.retrieved_at,
            publisher=line.publisher,
            published_at=line.published_at,
            source_type=line.source_type,
            language=line.language,
            quote=line.quote,
            quote_en=line.quote_en,
            locator=line.locator,
            cites_url=line.cites_url,
            quote_check=res.status,
            content_sha256=res.content_sha256,
        )
        self.batch.stats[f"quote_{res.status}"] += 1
        if res.status == "fail" and line.source_type in PRIMARY:
            _review(self.batch, "quote_fail_primary", eid, res.reason or "quote not found")
        self._ev_cache[eid] = ev
        self.batch.evidence.append(ev)
        return ev

    # --- claims --------------------------------------------------------------------------------------

    def subject_for(self, ref: SubjectRef, local: dict[int, str]) -> str | None:
        anchors = (ref.unit, ref.site, ref.company, ref.candidate_site, ref.candidate_company)
        if all(a is None for a in anchors):  # market-level claim about a molecule (world capacity…)
            return ref.molecule if ref.molecule in {m.id for m in self.batch.pack.molecules} else None
        if ref.candidate_site is not None:
            site = local.get(ref.candidate_site)
            if site is None:
                return None
            return self.unit_for(site, ref.molecule) if ref.molecule else site
        if ref.candidate_company is not None:
            return local.get(ref.candidate_company)
        known = ref.unit or ref.site or ref.company
        table = {"unit": "units", "site": "sites", "co": "companies"}[known.split(":")[0]]
        if not any(x.id == known for x in self._all(table)):
            # a unit that exists only under a merged-away site ID: keep the stored ID, the build maps it
            merged = {v: k for k, v in id_map(self.batch.store.load("merges"), self._all("units")).items()}
            if known not in merged:
                return None
            known = merged[known]
        if ref.site and ref.molecule:  # a product of a known site (J03): that's a unit
            if ref.molecule not in {m.id for m in self.batch.pack.molecules}:
                return None
            return self.unit_for(ref.site, ref.molecule)
        return known

    def claim_from(
        self,
        line: OutClaim,
        subject: str,
        evs: list[Evidence],
        job_id: str,
        agent: str,
        molecule: str | None = None,
    ) -> None:
        b = self.batch
        grades = [evidence_grade(e.source_type, e.quote_check or "manual") for e in evs]
        grade = min(grades)  # "A" < "B" < …
        flags: list[str] = []
        value_norm: object = None
        basis = line.capacity_basis
        problems: list[str] = []
        if line.field == "capacity":
            n = normalise_capacity(line.value, line.unit_raw, evs[0].language)
            if n.ok:
                value_norm = n.value_tpa
                flags += n.flags
                mol = molecule or next((u.molecule_id for u in self._all("units") if u.id == subject), None)
                if pb := product_basis(mol, line.unit_raw, *(e.quote for e in evs)):
                    value_norm = round(n.value_tpa * pb[0], 1)
                    flags.append(f"product basis: {pb[1]}")
                elif has_product_bases(mol) and any(e.language == "zh" for e in evs):
                    # Chinese vitamin figures are usually quoted per product (50% powder, 500,000 IU/g):
                    # without a stated basis the number isn't comparable; it shows, never counts in totals.
                    flags.append(BASIS_UNSTATED)
                if n.estimated:
                    basis, grade = "estimated", downgrade(grade)
                rng = b.pack.sanity.capacity_tpa
                if p := sanity.capacity_problem(n.value_tpa, rng.min, rng.max):
                    problems.append(p)
            elif n.reason == "range" and (mid := world_figure(line.value, line.unit_raw, evs[0].language))[0]:
                value_norm = mid[0]
                flags.append("range midpoint")
            else:
                problems.append(f"units: {n.reason}")
        elif line.field in ("world_capacity", "world_demand"):
            value_norm, why = world_figure(line.value, line.unit_raw, evs[0].language)
            if value_norm is None:
                problems.append(f"units: {why}")
            elif why:
                flags.append(why)
        elif line.field == "status":
            value_norm = normalise_status(line.value)
            if value_norm is None:
                problems.append(f"status not in vocabulary: {line.value!r}")
        elif line.field in ("start_year", "end_year"):
            value_norm = normalise_year(line.value)
            if p := sanity.year_problem(value_norm, line.value):
                problems.append(p)
        elif line.field == "lat_lon":
            point = geo.parse_lat_lon(str(line.value))
            site = next((s for s in self._all("sites") if s.id == subject), None)
            if point is None:
                problems.append(f"geo: can't read coordinates {line.value!r}")
            else:
                value_norm = f"{point[0]},{point[1]}"
                if site is not None:
                    problems += geo.check(point[0], point[1], site.country, "exact")
        elif line.field == "exists" and molecule and subject.startswith("co:"):
            # Company-level lead: makes this molecule, site unknown. Feeds site discovery (J03/J11).
            value_norm = molecule
            problems.append(f"lead: company makes {molecule}, site unknown")
        elif line.field == "exists":
            value_norm = str(line.value).strip().lower() in ("true", "yes", "1")
        else:
            value_norm = line.value
            if line.field in ("operator", "parent") and not str(line.value).startswith("co:"):
                # A company named as operator/parent becomes a company record; the claim points at its id.
                value_norm = self.company_for(str(line.value).strip(), [])
        if line.as_of.day == 1 and line.as_of.month == 1:
            flags.append("as_of may be year precision")
        elif line.as_of.day == 1:
            flags.append("as_of may be month precision")
        ev_ids = sorted({e.id for e in evs})
        cid = ids.claim_id(subject, line.field, value_norm if value_norm is not None else line.value, ev_ids)
        if any(c.id == cid for c in self._all("claims")):
            b.stats["claims_duplicate"] += 1
            return
        claim = Claim(
            id=cid,
            subject_id=subject,
            field=line.field,
            value=line.value,
            value_norm=value_norm,
            unit_raw=line.unit_raw,
            capacity_basis=basis,
            as_of=line.as_of,
            valid_from=line.valid_from,
            valid_to=line.valid_to,
            evidence_ids=ev_ids,
            extracted_by=f"run:{b.run_id}/job:{job_id}/agent:{agent}",
            confidence=grade,
            review_state="validated",
            flags=flags,
        )
        reasons = problems + self._conflicts(claim)
        blocked = [quarantined(e.url) for e in evs]
        if all(blocked):  # 03 §7: a quarantined source can guide search, never support a public number
            claim.review_state = "rejected"
            claim.review_note = "licence: " + "; ".join(sorted(set(blocked)))
            _review(b, "licence", subject, claim.review_note, [cid])
            b.stats["claims_licence_rejected"] += 1
            b.claims.append(claim)
            return
        if agent not in self.gold_passed and agent != "stub:stub":
            reasons.append(f"model {agent} has not passed the gold set: a person reviews its claims")
        if all(e.quote_check == "pass" for e in evs) and grade in ("A", "B") and not reasons:
            claim.review_state = "accepted"
            claim.review_note = "auto-accepted: grade A/B, quotes pass, no conflict"
        elif reasons:
            claim.review_note = "; ".join(reasons)
            _review(b, "claim", subject, claim.review_note, [cid])
        b.stats[f"grade_{grade}"] += 1
        b.claims.append(claim)

    def _conflicts(self, c: Claim) -> list[str]:
        out = []
        if c.field == "status" and c.value_norm in ("closing", "closed"):
            out.append(f"move to {c.value_norm}: always reviewed")
        if c.field == "status" and isinstance(c.value_norm, str):
            history = [
                (x.as_of, x.value_norm)
                for x in self._all("claims")
                if x.subject_id == c.subject_id
                and x.field == "status"
                and isinstance(x.value_norm, str)
                and x.review_state not in ("rejected", "superseded")
            ]
            before = set(sanity.transition_problems(history))
            out += [
                p for p in sanity.transition_problems([*history, (c.as_of, c.value_norm)]) if p not in before
            ]
        accepted = [
            x
            for x in self._all("claims")
            if x.subject_id == c.subject_id and x.field == c.field and x.review_state == "accepted"
        ]
        for x in accepted:
            if (
                c.field == "capacity"
                and isinstance(x.value_norm, int | float)
                and isinstance(c.value_norm, float)
            ):
                change = abs(c.value_norm - x.value_norm) / max(x.value_norm, 1)
                if x.as_of == c.as_of and change > 0.10:
                    out.append(f"conflict with {x.id} (same as_of, ±{change:.0%})")
                elif change > 0.25:
                    out.append(f"capacity change {change:.0%} vs {x.id}")
            elif x.as_of == c.as_of and x.value_norm != c.value_norm:
                out.append(f"conflict with {x.id} ({x.value_norm} vs {c.value_norm})")
        return out

    # --- one job -------------------------------------------------------------------------------------

    def company_unit_claim(
        self, o, local, evidence, job_id: str, agent: str, job_molecule: str | None
    ) -> bool:
        """A unit-level claim about a company with no plant named lands on its unit (portolan/leads.py)."""
        ref = o.subject_ref
        company_level = ref.candidate_company is not None or ref.company is not None
        molecule = ref.molecule or (job_molecule if company_level else None)
        if not company_level or molecule is None or o.field not in LEAD_FIELDS:
            return False
        if molecule not in {m.id for m in self.batch.pack.molecules}:
            return False
        cid = local.get(ref.candidate_company) if ref.candidate_company is not None else ref.company
        company = next((c for c in self._all("companies") if c.id == cid), None)
        got = (
            site_for_company(company, self._all("sites"), self._all("claims"), molecule, self._all("units"))
            if company
            else None
        )
        if got is None:
            return False
        sid, site = got
        evs = [evidence[i] for i in o.evidence_refs]
        if site:
            self.batch.sites.append(site)
            op = OutClaim(kind="claim", subject_ref=SubjectRef(site=sid), field="operator", value=cid,
                          as_of=o.as_of, evidence_refs=o.evidence_refs)  # fmt: skip
            self.claim_from(op, sid, evs, job_id, agent)
        self.claim_from(o, self.unit_for(sid, molecule), evs, job_id, agent)
        return True

    def collect_job(self, job_dir: Path, agent: str, job_molecule: str | None = None) -> None:
        b = self.batch
        out = job_dir / "out.jsonl"
        if not out.exists():
            return
        results = validate_file(out)
        local: dict[int, str] = {}
        evidence: dict[int, Evidence] = {}
        for r in results:
            if not r.ok:
                b.stats["lines_rejected"] += 1
                b.rejected.append(f"{job_dir.name} line {r.index}: {'; '.join(r.errors)[:200]}")
        ok = [r for r in results if r.ok]
        for r in ok:
            if r.obj.kind == "evidence":
                evidence[r.index] = self.evidence_for(r.obj)
        for r in ok:
            o = r.obj
            if o.kind == "candidate_company":
                local[r.index] = self.company_for(
                    o.name, o.aliases, hq_country=o.hq_country, website=o.website, type=o.type
                )
        for r in ok:
            o = r.obj
            if o.kind == "candidate_site":
                company = local.get(o.company_ref) if o.company_ref is not None else None
                sid = self.site_for(
                    o.name,
                    o.country,
                    o.locality,
                    company,
                    admin1=o.admin1,
                    address=o.address,
                    park_name=o.park_name,
                    registry_ids=o.registry_ids,
                )
                local[r.index] = sid
                if company:
                    evs = [evidence[i] for i in o.evidence_refs]
                    self.claim_from(
                        OutClaim(
                            kind="claim",
                            subject_ref=SubjectRef(site=sid),
                            field="operator",
                            value=company,
                            as_of=(evs[0].published_at or evs[0].retrieved_at.date()),
                            evidence_refs=o.evidence_refs,
                        ),
                        sid,
                        evs,
                        job_dir.name,
                        agent,
                    )
        for r in ok:
            o = r.obj
            if o.kind == "claim" and self.company_unit_claim(
                o, local, evidence, job_dir.name, agent, job_molecule
            ):
                continue
            if o.kind == "claim":
                subject = self.subject_for(o.subject_ref, local)
                if subject is None:
                    b.stats["claims_unresolved"] += 1
                    b.rejected.append(f"{job_dir.name} line {r.index}: subject not found")
                    continue
                ref = o.subject_ref
                company_level = ref.candidate_company is not None or ref.company is not None
                molecule = ref.molecule or (job_molecule if company_level else None)
                evs = [evidence[i] for i in o.evidence_refs]
                self.claim_from(o, subject, evs, job_dir.name, agent, molecule)
            elif o.kind == "event":
                self.event_from(o, local, [evidence[i] for i in o.evidence_refs], job_dir.name)
            elif o.kind == "not_found":
                b.stats["not_found"] += 1
                b.not_found.append(f"{job_dir.name}: {o.query}"[:200])

    def event_from(self, o: OutEvent, local: dict[int, str], evs: list[Evidence], job: str) -> None:
        subjects = [s for s in (self.subject_for(ref, local) for ref in o.subject_refs) if s]
        if not subjects:
            self.batch.rejected.append(f"{job}: event subjects not found")
            return
        short = subjects[0].split(":", 1)[1].replace(":", "-")
        ev = Event(
            id=ids.event_id(o.date.isoformat(), f"{short}-{o.type}"),
            date=o.date,
            date_precision=o.date_precision,
            type=o.type,
            subjects=subjects,
            summary=o.summary,
            evidence_ids=sorted({e.id for e in evs}),
            magnitude=o.magnitude,
        )
        if not any(e.id == ev.id for e in self.batch.events):
            self.batch.events.append(ev)
            self.batch.stats["events"] += 1

    # --- whole run -----------------------------------------------------------------------------------

    def collect(self) -> Batch:
        jobs = {j["job_id"]: j for j in self.manifest["jobs"]}
        for job_dir in sorted(p for p in self.run_dir.iterdir() if p.is_dir()):
            j = jobs.get(job_dir.name, {})
            # J01 is about one molecule: a company-level claim without one is about that molecule.
            mol = (
                j.get("inputs", {}).get("molecule_id")
                if j.get("job_type") in ("enumerate_producers", "market_overview")
                else None
            )
            self.collect_job(job_dir, f"{j.get('agent', '?')}:{j.get('model', '?')}", mol)
        self._leak_check()
        self._dedupe()
        return self.batch

    def _dedupe(self) -> None:
        """Propose merges for new sites that look like existing ones (02 §5 dedupe). Never merges."""
        new = {s.id for s in self.batch.sites}
        if not new:
            return
        for cand in dedupe.candidates(self._all("sites"), new_ids=new):
            _review(self.batch, "merge", cand.a, f"possible duplicate of {cand.b}: {cand.reason}")

    def _leak_check(self) -> None:
        """Drop any new record that leaks personal data, and everything that depends on it."""
        b = self.batch
        dropped: set[str] = set()
        for table in ("companies", "sites", "evidence", "claims", "events"):
            kept = []
            for rec in getattr(b, table):
                findings = scan_record(rec.model_dump(mode="json"), table)
                if findings:
                    dropped.add(rec.id)
                    b.stats["people_leak_dropped"] += 1
                    _review(
                        b,
                        "people_leak",
                        rec.id,
                        "dropped: " + ", ".join(sorted({f"{f.kind} in {f.where}" for f in findings})),
                    )
                else:
                    kept.append(rec)
            setattr(b, table, kept)
        if not dropped:
            return
        b.units = [u for u in b.units if u.site_id not in dropped]
        dropped |= {u.id for u in self.batch.units if u.site_id in dropped}
        live_units = {u.id for u in b.units} | {u.id for u in self.existing["units"]}
        b.claims = [
            c
            for c in b.claims
            if c.subject_id not in dropped
            and not set(c.evidence_ids) & dropped
            and (not c.subject_id.startswith("unit:") or c.subject_id in live_units)
        ]
        b.events = [e for e in b.events if not (set(e.subjects) | set(e.evidence_ids)) & dropped]


def write(batch: Batch, review_path: Path = REVIEW_PATH) -> dict[str, int]:
    written = {
        t: len(batch.store.append(t, getattr(batch, t)))
        for t in ("companies", "sites", "units", "evidence", "claims", "events")
    }
    review_path.parent.mkdir(parents=True, exist_ok=True)
    have = set()
    if review_path.exists():
        have = {
            json.loads(x)["id"] for x in review_path.read_text(encoding="utf-8").splitlines() if x.strip()
        }
    with open(review_path, "a", encoding="utf-8") as f:
        for item in batch.review:
            if item["id"] not in have:
                have.add(item["id"])
                f.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
                written["review"] = written.get("review", 0) + 1
    return written


def summary(batch: Batch, written: dict[str, int], manifest: dict) -> str:
    s = batch.stats
    jobs = manifest["jobs"]
    rows = [
        (
            "Jobs (ok / partial / failed)",
            f"{sum(j['status'] == 'ok' for j in jobs)} / "
            f"{sum(j['status'] == 'partial' for j in jobs)} / "
            f"{sum(j['status'] not in ('ok', 'partial') for j in jobs)}",
        ),
        ("Claims by grade A / B / C / D", " / ".join(str(s[f"grade_{g}"]) for g in "ABCD")),
        ("Claims auto-accepted", str(sum(c.review_state == "accepted" for c in batch.claims))),
        (
            "Quote check pass / fail / unreachable / manual",
            " / ".join(str(s[f"quote_{k}"]) for k in ("pass", "fail", "unreachable", "manual")),
        ),
        ("not_found", str(s["not_found"])),
        ("Lines rejected (schema/refs)", str(s["lines_rejected"] + s["claims_unresolved"])),
        (
            "New companies / sites / units",
            f"{written.get('companies', 0)} / {written.get('sites', 0)} / {written.get('units', 0)}",
        ),
        (
            "New evidence / claims / events",
            f"{written.get('evidence', 0)} / {written.get('claims', 0)} / {written.get('events', 0)}",
        ),
        ("Review items opened", str(written.get("review", 0))),
        ("Dropped by people_leak", str(s["people_leak_dropped"])),
    ]
    agents = Counter(f"{j.get('agent', '-')}:{j.get('model', '-')}" for j in jobs)
    out = [f"# Run `{batch.run_id}`", "", "| | |", "|---|---|"] + [f"| {a} | {b} |" for a, b in rows]
    out += ["", "Agents: " + ", ".join(f"`{k}` × {v}" for k, v in sorted(agents.items()))]
    if batch.claims:
        out += ["", "## Claims", "", "| Subject | Field | Value | Grade | State |", "|---|---|---|---|---|"]
        for c in sorted(batch.claims, key=lambda c: (c.subject_id, c.field)):
            val = f"{c.value}{' ' + c.unit_raw if c.unit_raw else ''}"
            out.append(f"| `{c.subject_id}` | {c.field} | {val} | {c.confidence} | {c.review_state} |")
    if batch.not_found:
        out += ["", "## not_found", ""] + [f"- {x}" for x in batch.not_found]
    if batch.rejected:
        out += ["", "## Rejected lines", ""] + [f"- {x}" for x in batch.rejected[:50]]
    return "\n".join(out) + "\n"


def collect(
    run_id: str,
    runs_dir: Path = Path("runs"),
    data_dir: Path = Path("data"),
    review_path: Path = REVIEW_PATH,
    checker: QuoteChecker | None = None,
    chains_dir: Path = Path("chains"),
) -> tuple[Batch, str]:
    run_dir = runs_dir / run_id
    c = Collector(run_dir, Store(data_dir), checker or online_checker(), chains_dir)
    batch = c.collect()
    written = write(batch, review_path)
    text = summary(batch, written, c.manifest)
    if any(written.values()) or not (run_dir / "summary.md").exists():  # a re-collect keeps the first summary
        (run_dir / "summary.md").write_text(text, encoding="utf-8")
    return batch, text
