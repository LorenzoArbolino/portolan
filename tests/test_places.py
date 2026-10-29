"""Town-level placement: Wikipedia page parsing and the Natural Earth fallback (offline fixtures)."""

from pipeline.fetch import Fetched
from pipeline.sources.wikipedia_places import locate, locate_ne
from portolan.models import Site


def site(locality: str, country: str = "MY", admin1: str | None = None) -> Site:
    return Site(
        id="site:my-x-01",
        name="x",
        country=country,
        locality=locality,
        admin1=admin1,
        geo_precision="locality",
    )


class FakeFetcher:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages

    def get(self, url: str) -> Fetched:
        html = self.pages.get(url.rsplit("/", 1)[-1])
        return Fetched(url=url, ok=html is not None, content=(html or "").encode())


def test_wikipedia_geo_span():
    f = FakeFetcher({"Kuantan": 'Malaysia <span class="geo">3.8; 103.33</span>'})
    r = locate(site("Kuantan"), f)
    assert (r["lat"], r["lon"], r["geo_precision"]) == (3.8, 103.33, "locality")


def test_wikipedia_wrong_country_or_refused():
    assert locate(site("Kuantan"), FakeFetcher({"Kuantan": 'Brazil <span class="geo">1; 2</span>'})) is None
    assert locate(site("Kuantan"), FakeFetcher({})) is None


PLACES = [
    {
        "name": "Kuantan",
        "nameascii": "Kuantan",
        "iso_a2": "MY",
        "adm1name": "Pahang",
        "latitude": 3.83,
        "longitude": 103.32,
    },
    {
        "name": "Springfield",
        "nameascii": "Springfield",
        "iso_a2": "US",
        "adm1name": "Illinois",
        "latitude": 39.8,
        "longitude": -89.6,
    },
    {
        "name": "Springfield",
        "nameascii": "Springfield",
        "iso_a2": "US",
        "adm1name": "Missouri",
        "latitude": 37.2,
        "longitude": -93.3,
    },
]


def test_ne_matches_any_locality_part():
    r = locate_ne(site("Gebeng, Kuantan"), PLACES)
    assert (r["lat"], r["lon"]) == (3.83, 103.32) and "Natural Earth" in r["note"]


def test_ne_ambiguous_needs_admin1():
    assert locate_ne(site("Springfield", "US"), PLACES) is None
    assert locate_ne(site("Springfield", "US", "Missouri"), PLACES)["lat"] == 37.2


def test_ne_wrong_country():
    assert locate_ne(site("Kuantan", "ID"), PLACES) is None
