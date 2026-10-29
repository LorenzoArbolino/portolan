"""Pydantic models for every entity in the data model and for the agent output contract.

JSON Schemas in `schema/` are generated from these (`portolan schemas`)."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

# --- ID patterns -----------------------------------------------------------------------------------

_SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
MoleculeId = Annotated[str, Field(pattern=rf"^mol:(\d{{2,7}}-\d{{2}}-\d|x-{_SLUG})$")]
RouteId = Annotated[str, Field(pattern=rf"^rte:{_SLUG}:{_SLUG}$")]
SiteId = Annotated[str, Field(pattern=rf"^site:[a-z]{{2}}-{_SLUG}-\d{{2}}$")]
UnitId = Annotated[str, Field(pattern=rf"^unit:[a-z]{{2}}-{_SLUG}-\d{{2}}:{_SLUG}(:\d{{2}})?$")]
CompanyId = Annotated[str, Field(pattern=rf"^co:{_SLUG}$")]
EventId = Annotated[str, Field(pattern=rf"^ev:\d{{4}}-\d{{2}}-\d{{2}}:{_SLUG}$")]
EvidenceId = Annotated[str, Field(pattern=r"^src:[0-9a-f]{12}$")]
ClaimId = Annotated[str, Field(pattern=r"^clm:[0-9a-f]{12}$")]
MeasureId = Annotated[str, Field(pattern=rf"^tm:{_SLUG}:{_SLUG}$")]
ChainId = Annotated[str, Field(pattern=rf"^chain:{_SLUG}$")]
SubjectId = Annotated[str, Field(pattern=r"^(mol|rte|site|unit|co|ev|tm):\S+$")]
Iso2 = Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
Iso3 = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
Hs6 = Annotated[str, Field(pattern=r"^\d{6}$")]
Lang = Annotated[str, Field(pattern=r"^[a-z]{2}$", description="ISO 639-1")]
Quote = Annotated[str, Field(min_length=1, max_length=400)]

# --- Vocabularies ---------------------------------------------------------------------------------

Tier = Literal["base", "intermediate", "specialty"]
PhysicalForm = Literal["solid", "liquid", "gas", "solution"]
InputRole = Literal["feedstock", "reagent", "catalyst"]
CompanyType = Literal["producer", "trader", "distributor", "converter", "brand_owner", "investor", "licensor"]
GeoPrecision = Literal["exact", "park", "locality", "country"]
ClaimField = Literal[
    "capacity",
    "status",
    "operator",
    "parent",
    "share_pct",
    "start_year",
    "end_year",
    "route",
    "lat_lon",
    "captive_share",
    "exists",
    "world_capacity",  # subject: a molecule (market-level figure)
    "world_demand",
]
CapacityBasis = Literal["nameplate", "permitted", "design", "estimated", "production"]
Grade = Literal["A", "B", "C", "D"]
ReviewState = Literal["proposed", "validated", "accepted", "rejected", "superseded"]
SourceType = Literal[
    "regulator",
    "permit",
    "company_primary",
    "exchange_filing",
    "trade_measure",
    "trade_press",
    "aggregator",
    "association",
    "operator_claimed",
    "other",
]
QuoteCheck = Literal["pass", "fail", "unreachable", "pdf_ok", "manual"]
Status = Literal[
    "planned",
    "under_construction",
    "commissioning",
    "operating",
    "idle",
    "closing",
    "closed",
    "cancelled",
    "unknown",
]
DatePrecision = Literal["day", "month", "quarter", "year"]
EventType = Literal[
    "announced_closure",
    "closed",
    "idled",
    "restarted",
    "announced_expansion",
    "commissioned",
    "construction_started",
    "acquisition",
    "divestment",
    "jv_formed",
    "insolvency",
    "force_majeure",
    "incident",
    "trade_measure",
    "regulatory",
    "project_cancelled",
]
Instrument = Literal["ad", "cvd", "safeguard", "quota", "ban", "restriction"]

STATUS_VOCAB: tuple[str, ...] = Status.__args__  # type: ignore[attr-defined]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)


# --- Entities --------------------------------------------------------------------------------------


class Molecule(_Model):
    id: MoleculeId
    name: str
    tier: Tier
    synonyms: list[str] = []
    cas: str | None = None
    ec: str | None = None
    inchikey: str | None = None
    hs6: list[Hs6] = []
    cn8: list[Annotated[str, Field(pattern=r"^\d{8}$")]] = []
    prodcom: list[str] = []
    ets_activity: str | None = None
    un_number: str | None = None
    physical_form: PhysicalForm | None = None
    family_tags: list[str] = []
    chain_ids: list[ChainId] = []
    notes: str | None = None

    @model_validator(mode="after")
    def _cas_matches_id(self) -> Molecule:
        if self.cas and self.id != f"mol:{self.cas}":
            raise ValueError(f"molecule {self.id} has CAS {self.cas}; id must be mol:<cas>")
        return self


class RouteInput(_Model):
    molecule_id: MoleculeId
    role: InputRole = "feedstock"


class RouteCoproduct(_Model):
    molecule_id: MoleculeId


class Route(_Model):
    id: RouteId
    product_id: MoleculeId
    inputs: list[RouteInput] = []
    coproducts: list[RouteCoproduct] = []
    route_name: str
    tech_owner: str | None = None
    notes: str | None = None


class Company(_Model):
    id: CompanyId
    name: str
    aliases: list[str] = []
    hq_country: Iso2 | None = None
    website: str | None = None
    type: list[CompanyType] = []
    listed_ticker: str | None = None
    registry_ids: dict[str, str] = {}


class Site(_Model):
    id: SiteId
    name: str
    country: Iso2
    admin1: str | None = None
    locality: str
    address: str | None = None
    lat: Annotated[float, Field(ge=-90, le=90)] | None = None
    lon: Annotated[float, Field(ge=-180, le=180)] | None = None
    geo_precision: GeoPrecision
    park_name: str | None = None
    registry_ids: dict[str, str] = {}
    external_ids: dict[str, str] = {}
    claimed_by_operator: bool = False
    claimed_by_operator_at: dt.date | None = None

    @model_validator(mode="after")
    def _latlon_pair(self) -> Site:
        if (self.lat is None) != (self.lon is None):
            raise ValueError("lat and lon must be given together")
        return self


class Unit(_Model):
    """One site × one molecule × one process route. Capacity, status, operator etc. are claims."""

    id: UnitId
    site_id: SiteId
    molecule_id: MoleculeId
    route_id: RouteId | None = None


class Estimate(_Model):
    """How a grade-D value was estimated (methodology, rule 1): method, sourced inputs, a range."""

    method: str
    inputs: list[ClaimId] = Field(min_length=1)
    low: float | None = None
    high: float | None = None
    confidence: Literal["low", "medium", "high"]


class Claim(_Model):
    id: ClaimId
    subject_id: SubjectId
    field: ClaimField
    value: str | float | int
    value_norm: str | float | int | None = None
    unit_raw: str | None = None
    capacity_basis: CapacityBasis | None = None
    as_of: dt.date
    valid_from: dt.date | None = None
    valid_to: dt.date | None = None
    evidence_ids: list[EvidenceId] = Field(min_length=1)
    extracted_by: str
    confidence: Grade
    review_state: ReviewState = "proposed"
    review_note: str | None = None
    flags: list[str] = []
    estimate: Estimate | None = None  # set only on grade-D estimates (portolan/estimate.py)


class Evidence(_Model):
    id: EvidenceId
    url: str
    archive_url: str | None = None
    retrieved_at: dt.datetime
    publisher: str | None = None
    published_at: dt.date | None = None
    source_type: SourceType
    language: Lang
    quote: Quote
    quote_en: str | None = None
    locator: str | None = None
    cites_url: str | None = None
    quote_check: QuoteCheck | None = None
    content_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None


class Magnitude(_Model):
    value: float
    unit: str


class Event(_Model):
    id: EventId
    date: dt.date
    date_precision: DatePrecision = "day"
    type: EventType
    subjects: list[SubjectId] = Field(min_length=1)
    summary: Annotated[str, Field(max_length=280)]
    evidence_ids: list[EvidenceId] = Field(min_length=1)
    magnitude: Magnitude | None = None


class Flow(_Model):
    reporter_iso3: Iso3
    partner_iso3: Iso3
    flow: Literal["import", "export"]
    hs6: Hs6
    period: Annotated[str, Field(pattern=r"^\d{4}(-\d{2})?$")]
    qty_kg: float | None = None
    value_usd: float | None = None
    value_eur: float | None = None
    source: str


class CompanyRate(_Model):
    company_id: CompanyId
    rate: float


class Measure(_Model):
    id: MeasureId
    jurisdiction: str
    instrument: Instrument | None = None
    product_desc: str
    cn_codes: list[str] = []
    origin_iso3: list[Iso3] = []
    rate_min: float | None = None
    rate_max: float | None = None
    company_rates: list[CompanyRate] = []
    in_force_from: dt.date | None = None
    in_force_to: dt.date | None = None
    legal_ref: str
    url: str


class Signal(_Model):
    subject_id: SubjectId
    kind: str
    period: str
    value: float
    unit: str
    source: str


class Transfer(_Model):
    """An ownership change read from an event (`data/transfers.csv`, a judgement kept as data like merges).
    `operator`: the buyer takes over the listed sites. `parent`: the target company keeps operating them, but
    its parent becomes the buyer. The build turns each into claims dated on the event."""

    event_id: EventId
    kind: Literal["operator", "parent"]
    seller: CompanyId | None = None
    buyer: CompanyId
    target: CompanyId | None = None
    sites: list[SiteId] = []
    decided_by: str
    date: dt.date
    note: str | None = None

    @model_validator(mode="after")
    def _parent_has_target(self) -> Transfer:
        if self.kind == "parent" and not self.target:
            raise ValueError("a parent transfer needs the target company")
        return self


class Merge(_Model):
    from_id: str
    to_id: str
    reason: str
    decided_by: str
    date: dt.date


# --- Agent output contract -----------------------------------------------
# Agents write one JSON object per line to out.jsonl. `*_refs` are 0-based line indexes in the same
# file; the collector rewrites them to IDs. Agents never write quote_check or IDs.

LineRef = Annotated[int, Field(ge=0)]


def _partial_date(v: object) -> object:
    """Agents often have only a month or a year ("2026-02", "2024"). Read it as the period's first day; the
    collector records the precision in the claim's flags."""
    if isinstance(v, str):
        s = v.strip()
        if len(s) == 7 and s[4] == "-" and s[:4].isdigit() and s[5:].isdigit():
            return f"{s}-01"
        if len(s) == 4 and s.isdigit():
            return f"{s}-01-01"
    return v


AgentDate = Annotated[dt.date, BeforeValidator(_partial_date)]


class OutEvidence(_Model):
    kind: Literal["evidence"]
    url: str
    retrieved_at: dt.datetime
    publisher: str | None = None
    published_at: AgentDate | None = None
    source_type: SourceType
    language: Lang
    quote: Quote
    quote_en: str | None = None
    locator: str | None = None
    cites_url: str | None = None


class OutCandidateCompany(_Model):
    kind: Literal["candidate_company"]
    name: str
    aliases: list[str] = []
    hq_country: Iso2 | None = None
    website: str | None = None
    type: list[CompanyType] = []
    evidence_refs: list[LineRef] = Field(min_length=1)


class OutCandidateSite(_Model):
    kind: Literal["candidate_site"]
    name: str
    country: Iso2
    admin1: str | None = None
    locality: Annotated[str, Field(min_length=1)]  # a site needs a town; "unknown" belongs in not_found
    address: str | None = None
    park_name: str | None = None
    company_ref: LineRef | None = None
    registry_ids: dict[str, str] = {}
    evidence_refs: list[LineRef] = Field(min_length=1)


class SubjectRef(_Model):
    """What a claim is about: a known ID, or a candidate on another line (+ molecule for a unit)."""

    unit: UnitId | None = None
    site: SiteId | None = None
    company: CompanyId | None = None
    candidate_site: LineRef | None = None
    candidate_company: LineRef | None = None
    molecule: MoleculeId | None = None

    @model_validator(mode="after")
    def _one_subject(self) -> SubjectRef:
        anchors = [
            x
            for x in (self.unit, self.site, self.company, self.candidate_site, self.candidate_company)
            if x is not None
        ]
        if len(anchors) > 1 or (not anchors and self.molecule is None):
            raise ValueError(
                "subject_ref needs exactly one of unit, site, company, candidate_site, candidate_company, "
                "or a molecule alone (market-level claims)"
            )
        return self


class OutClaim(_Model):
    kind: Literal["claim"]
    subject_ref: SubjectRef
    field: ClaimField
    value: str | float | int
    unit_raw: str | None = None
    capacity_basis: CapacityBasis | None = None
    as_of: AgentDate
    valid_from: AgentDate | None = None
    valid_to: AgentDate | None = None
    evidence_refs: list[LineRef] = Field(min_length=1)

    @model_validator(mode="after")
    def _capacity_has_unit(self) -> OutClaim:
        if self.field == "capacity" and not self.unit_raw:
            raise ValueError("a capacity claim needs unit_raw")
        return self


class OutEvent(_Model):
    kind: Literal["event"]
    date: AgentDate
    date_precision: DatePrecision = "day"
    type: EventType
    subject_refs: list[SubjectRef] = Field(min_length=1)
    summary: Annotated[str, Field(max_length=280)]
    magnitude: Magnitude | None = None
    evidence_refs: list[LineRef] = Field(min_length=1)


class OutNotFound(_Model):
    kind: Literal["not_found"]
    query: str
    searched: list[str] = []
    note: str | None = None


OutLine = Annotated[
    OutEvidence | OutCandidateCompany | OutCandidateSite | OutClaim | OutEvent | OutNotFound,
    Field(discriminator="kind"),
]


class OutLineModel(BaseModel):
    """Wrapper so a single out.jsonl line can be validated against the discriminated union."""

    line: OutLine


ENTITY_MODELS: dict[str, type[BaseModel]] = {
    "molecule": Molecule,
    "route": Route,
    "company": Company,
    "site": Site,
    "unit": Unit,
    "claim": Claim,
    "evidence": Evidence,
    "event": Event,
    "flow": Flow,
    "measure": Measure,
    "signal": Signal,
    "merge": Merge,
    "transfer": Transfer,
}

OUT_MODELS: dict[str, type[BaseModel]] = {
    "evidence": OutEvidence,
    "candidate_company": OutCandidateCompany,
    "candidate_site": OutCandidateSite,
    "claim": OutClaim,
    "event": OutEvent,
    "not_found": OutNotFound,
}
