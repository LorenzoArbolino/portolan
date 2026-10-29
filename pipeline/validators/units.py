"""Normalise capacity values to tonnes per year, driven by `units.yaml`.

Never guesses: an ambiguous unit, a range or an ambiguous number format returns `ok=False` with a reason,
and the claim goes to review instead of getting a number."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import yaml

UNITS_YAML = Path(__file__).with_name("units.yaml")


@dataclass(frozen=True)
class UnitSpec:
    name: str
    factor: float | None
    assumption: str | None = None
    ambiguous: bool = False


@dataclass
class Normalised:
    ok: bool
    value_tpa: float | None = None
    unit: str | None = None
    factor: float | None = None
    assumption: str | None = None
    flags: list[str] = field(default_factory=list)
    reason: str | None = None

    @property
    def estimated(self) -> bool:
        """An assumed factor makes the basis `estimated` and costs one grade."""
        return self.assumption is not None


def normalise_unit_text(raw: str) -> str:
    s = unicodedata.normalize("NFKC", raw).lower().strip()
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s).strip()  # "吨/年 (VE 50%粉)": the basis note is read elsewhere
    s = re.sub(r"(?:\s+|-)(?:per|pro)(?:\s+|-)", "/", s)  # "tonnes per year", "Tonnen pro Jahr"
    s = re.sub(r"\s+(?:annually|annual|a year|each year|yearly)$", "/a", s)  # "tons annually"
    s = re.sub(r"\s+", "", s)
    s = s.replace("p.a.", "/a").replace("perannum", "/a").replace("peryear", "/a")
    s = s.replace("//", "/")
    s = re.sub(r"/(years?|annum|yr|y|år|ar|jahr|año|anno|an)$", "/a", s)
    s = re.sub(r"/(months?)$", "/month", s)
    s = re.sub(r"/(days?)$", "/day", s)
    s = re.sub(r"/(hours?)$", "/h", s)
    s = re.sub(r"^(metric)?(tonnes|tons|tonne|ton)(?=/)", r"\1t", s)
    s = re.sub(r"^(kilotonnes|kilotons|thousandtonnes|thousandtons|thousandmetrictons)(?=/)", "kt", s)
    s = re.sub(r"^(milliontonnes|milliontons|millionmetrictons)(?=/)", "milliont", s)
    return s


@cache
def load_units(path: str = str(UNITS_YAML)) -> tuple[dict[str, UnitSpec], dict[str, UnitSpec]]:
    """Returns (normalised alias → spec, case-sensitive raw alias → spec)."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))["units"]
    by_alias: dict[str, UnitSpec] = {}
    by_raw: dict[str, UnitSpec] = {}
    for name, d in data.items():
        spec = UnitSpec(
            name=name,
            factor=d.get("factor"),
            assumption=d.get("assumption"),
            ambiguous=bool(d.get("ambiguous", False)),
        )
        for alias in d.get("aliases", []):
            key = normalise_unit_text(str(alias))
            if key in by_alias and by_alias[key] != spec:
                raise ValueError(f"units.yaml: alias {alias!r} maps to both {by_alias[key].name} and {name}")
            by_alias[key] = spec
        for alias in d.get("case_sensitive", []):
            by_raw[re.sub(r"\s+", "", str(alias))] = spec
    return by_alias, by_raw


def lookup_unit(unit_raw: str) -> UnitSpec | None:
    by_alias, by_raw = load_units()
    compact = re.sub(r"\s+", "", unicodedata.normalize("NFKC", unit_raw))
    if compact in by_raw:
        return by_raw[compact]
    return by_alias.get(normalise_unit_text(unit_raw))


_RANGE = re.compile(r"\d\s*(?:-|–|—|to|bis|à|~|～)\s*\d")


# Languages that write 48.000 for forty-eight thousand and 4,8 for four point eight.
DECIMAL_COMMA_LANGS = frozenset(
    {"de", "fr", "it", "es", "pt", "nl", "da", "sv", "fi", "no", "pl", "cs", "tr", "id", "ru", "ms"}
)


def parse_number(value: str | float | int, language: str | None = None) -> tuple[float | None, str | None]:
    """Parse a raw number. Returns (value, None) or (None, reason). Never guesses a separator: without a
    language hint, 48.000 is ambiguous; with a decimal-comma language it is forty-eight thousand."""
    if isinstance(value, bool):
        return None, "not a number"
    if isinstance(value, int | float):
        return float(value), None
    s = unicodedata.normalize("NFKC", str(value)).strip()
    s = re.sub(r"^(approx\.?|about|ca\.?|c\.|~|约|約|circa|rund|environ)\s*", "", s, flags=re.IGNORECASE)
    s = s.replace("\u202f", " ").replace("\u00a0", " ")
    if _RANGE.search(s):
        return None, "range"
    s = re.sub(r"(?<=\d)[ '’](?=\d{3}\b)", "", s)  # 48 000, 48'000
    if not re.fullmatch(r"\d[\d.,]*", s):
        return None, f"not a plain number: {value!r}"
    if "," in s and "." in s:
        dec = "." if s.rfind(".") > s.rfind(",") else ","
        thou = "," if dec == "." else "."
        return float(s.replace(thou, "").replace(dec, ".")), None
    comma_lang = language in DECIMAL_COMMA_LANGS
    if comma_lang and "." in s and "," not in s and re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        return float(s.replace(".", "")), None
    if comma_lang and re.fullmatch(r"\d+,\d+", s):
        if len(s.split(",")[1]) == 3:
            return None, f"ambiguous separator (thousands or decimal?): {value!r}"
        return float(s.replace(",", ".")), None
    if "," in s:
        parts = s.split(",")
        # 48,000 / 1,20,000 (Indian grouping) are thousands; 4,8 is a decimal comma.
        if len(parts) > 2 or (len(parts[-1]) == 3 and all(1 <= len(p) <= 3 for p in parts[:-1])):
            if re.fullmatch(r"\d{1,3}(,\d{2})*,\d{3}|\d{1,3}(,\d{3})+", s):
                return float(s.replace(",", "")), None
            return None, f"unclear grouping: {value!r}"
        return float(s.replace(",", ".")), None
    if s.count(".") > 1:
        if re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
            return float(s.replace(".", "")), None
        return None, f"unclear grouping: {value!r}"
    if "." in s and len(s.split(".")[1]) == 3:
        return None, f"ambiguous separator (thousands or decimal?): {value!r}"
    return float(s), None


def normalise_capacity(
    value: str | float | int, unit_raw: str | None, language: str | None = None
) -> Normalised:
    if not unit_raw:
        return Normalised(ok=False, reason="no unit")
    spec = lookup_unit(unit_raw)
    if spec is None:
        return Normalised(ok=False, reason=f"unknown unit {unit_raw!r} (add it to units.yaml)")
    if spec.ambiguous or spec.factor is None:
        return Normalised(
            ok=False, unit=spec.name, reason=f"ambiguous unit {unit_raw!r}", flags=["ambiguous_unit"]
        )
    number, why = parse_number(value, language)
    if number is None:
        return Normalised(ok=False, unit=spec.name, reason=why, flags=["unparsed_value"])
    flags = [f"assumed: {spec.assumption}"] if spec.assumption else []
    return Normalised(
        ok=True,
        value_tpa=round(number * spec.factor, 6),
        unit=spec.name,
        factor=spec.factor,
        assumption=spec.assumption,
        flags=flags,
    )


GRADES = "ABCD"


def downgrade(grade: str, steps: int = 1) -> str:
    return GRADES[min(GRADES.index(grade) + steps, len(GRADES) - 1)]


@cache
def _product_bases() -> list[dict]:
    return yaml.safe_load(UNITS_YAML.read_text(encoding="utf-8")).get("product_basis", [])


def product_basis(molecule_id: str | None, *texts: str | None) -> tuple[float, str] | None:
    """(factor, label) when a capacity is stated on a product basis (e.g. "VE 50% powder") for a molecule
    whose figures we keep as the pure substance; None otherwise. Matching ignores case, spaces and width."""
    if not molecule_id:
        return None
    hay = "".join(unicodedata.normalize("NFKC", t or "").lower().replace(" ", "") for t in texts)
    for b in _product_bases():
        if molecule_id in b["molecules"] and any(p.replace(" ", "") in hay for p in b["patterns"]):
            return float(b["factor"]), b["label"]
    return None


def has_product_bases(molecule_id: str | None) -> bool:
    """Molecules whose figures are often quoted on a product basis (vitamins)."""
    return bool(molecule_id) and any(molecule_id in b["molecules"] for b in _product_bases())
