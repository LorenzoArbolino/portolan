"""Chain packs (`chains/<slug>.yaml`, format in `chains/_template.yaml`) loaded into models."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from portolan.ids import cas_is_valid, duplicates
from portolan.models import (
    ChainId,
    Hs6,
    Lang,
    Molecule,
    MoleculeId,
    PhysicalForm,
    Route,
    RouteCoproduct,
    RouteId,
    RouteInput,
    Tier,
)

Role = Literal["core", "feedstock", "downstream", "context"]


class _Pack(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChainMolecule(_Pack):
    id: MoleculeId
    name: str
    tier: Tier
    cas: str | None = None
    hs6: list[Hs6] = []
    hs6_exact: bool = False  # the HS code covers only this molecule (trade figures are the molecule's own)
    cn_hs8: str | None = None  # China's 8-digit customs code that isolates the molecule (or its close group)
    cn8: list[str] = []
    ets_activity: str | None = None
    role: Role
    weight: int = Field(1, ge=1, le=3)  # research and display priority: 3 = must cover, 1 = context
    names: list[str] = []  # other-language and trade names, for search and document page selection
    # Made as a by-product (turpentine from kraft pulp): output shown, capacity never estimated.
    byproduct: bool = False
    hs6_scope: str | None = None  # what the HS6 code covers when it is not the molecule's own
    trade_basis: str | None = None  # how trade tonnage relates to the molecule (e.g. product weight)
    form: PhysicalForm | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _check_cas(self) -> ChainMolecule:
        if self.cas:
            if not cas_is_valid(self.cas):
                raise ValueError(f"{self.id}: CAS check digit fails for {self.cas}")
            if self.id != f"mol:{self.cas}":
                raise ValueError(f"{self.id}: id must be mol:{self.cas}")
        return self


class ChainRoute(_Pack):
    id: RouteId
    product: MoleculeId
    inputs: list[MoleculeId] = []
    coproducts: list[MoleculeId] = []
    note: str | None = None


class Region(_Pack):
    code: str
    priority: int = Field(ge=1, le=3)
    languages: list[Lang]


class Range(_Pack):
    min: float
    max: float


class Sanity(_Pack):
    capacity_tpa: Range


class MustFind(_Pack):
    """One item research must resolve before breadth (rule 5): a company (and optionally its sites) and the
    molecules it is believed to make. Its state is computed from the data at build time (`portolan.mustfind`):
    a molecule is found when the company's group has a unit with a sourced status, or explicitly unfound when
    `unfound` records what was searched."""

    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    company: str  # display name and search name
    company_ids: list[str] = []  # co: ids (or their groups) that count as this company
    aliases: list[str] = []
    sites: list[str] = []  # site ids; empty = any site of the company
    places: list[str] = []  # where to look, in words (e.g. "Xinchang, Zhejiang")
    molecules: list[MoleculeId]
    weight: int = Field(3, ge=1, le=3)
    unfound: dict[str, str] = {}  # molecule id → what was searched without result
    note: str | None = None

    @property
    def label(self) -> str:
        return f"{self.company}{' (' + ', '.join(self.places) + ')' if self.places else ''}"


class Budget(_Pack):
    usd_max: float = 0


class ChainPack(_Pack):
    id: ChainId
    name: str
    version: str
    status: Literal["draft", "approved", "building", "live", "paused"]
    approved_by: str | None = None
    why_this_chain: str
    molecules: list[ChainMolecule]
    routes: list[ChainRoute]
    regions: list[Region]
    seed_sources: list[str] = []
    seed_hypotheses: list[str] = []
    must_find: list[MustFind] = []
    sanity: Sanity
    buyer_segments: list[str] = []
    adjacent_chains: list[str] = []
    budget: Budget = Budget()
    first_molecules: list[MoleculeId] = []
    open_questions: list[str] = []

    @field_validator("version", mode="before")
    @classmethod
    def _version_str(cls, v: object) -> str:
        return str(v)

    @model_validator(mode="after")
    def _references_resolve(self) -> ChainPack:
        errors: list[str] = []
        mol_ids = [m.id for m in self.molecules]
        for d in duplicates(mol_ids):
            errors.append(f"duplicate molecule {d}")
        for d in duplicates(r.id for r in self.routes):
            errors.append(f"duplicate route {d}")
        known = set(mol_ids)
        for r in self.routes:
            for ref in [r.product, *r.inputs, *r.coproducts]:
                if ref not in known:
                    errors.append(f"{r.id}: unknown molecule {ref}")
        for mf in self.must_find:
            for ref in mf.molecules:
                if ref not in known:
                    errors.append(f"must_find {mf.id}: unknown molecule {ref}")
        for d in duplicates(mf.id for mf in self.must_find):
            errors.append(f"duplicate must_find {d}")
        for ref in self.first_molecules:
            if ref not in known:
                errors.append(f"first_molecules: unknown molecule {ref}")
        if self.status != "draft" and not self.approved_by:
            errors.append(f"status {self.status} needs approved_by")
        if errors:
            raise ValueError("; ".join(errors))
        return self

    @property
    def slug(self) -> str:
        return self.id.removeprefix("chain:")

    def molecule(self, mol_id: str) -> ChainMolecule:
        for m in self.molecules:
            if m.id == mol_id:
                return m
        raise KeyError(mol_id)

    def to_molecules(self) -> list[Molecule]:
        return [
            Molecule(
                id=m.id,
                name=m.name,
                tier=m.tier,
                cas=m.cas,
                hs6=m.hs6,
                cn8=m.cn8,
                ets_activity=m.ets_activity,
                physical_form=m.form,
                chain_ids=[self.id],
                notes=m.note,
            )
            for m in self.molecules
        ]

    def to_routes(self) -> list[Route]:
        return [
            Route(
                id=r.id,
                product_id=r.product,
                inputs=[RouteInput(molecule_id=i) for i in r.inputs],
                coproducts=[RouteCoproduct(molecule_id=c) for c in r.coproducts],
                route_name=r.id.split(":")[-1],
                notes=r.note,
            )
            for r in self.routes
        ]


def load_chain(path: str | Path) -> ChainPack:
    with open(path, encoding="utf-8") as f:
        return ChainPack.model_validate(yaml.safe_load(f))
