import datetime as dt

from pipeline.validators import dedupe, geo, sanity
from pipeline.validators.licence import quarantined
from portolan.models import Site

D = dt.date


def test_status_transitions():
    ok = [(D(2020, 1, 1), "planned"), (D(2022, 1, 1), "under_construction"), (D(2024, 9, 1), "operating")]
    assert sanity.transition_problems(ok) == []
    assert sanity.transition_problems([(D(2017, 1, 1), "closed"), (D(2018, 1, 1), "operating")])
    assert sanity.transition_problems([(D(2017, 1, 1), "idle"), (D(2018, 1, 1), "operating")]) == []
    assert sanity.transition_problems([(D(2017, 1, 1), "operating"), (D(2018, 1, 1), "cancelled")])


def test_capacity_and_years():
    assert sanity.capacity_problem(48000, 10, 200000) is None
    assert "outside" in sanity.capacity_problem(4_800_000, 10, 200000)
    assert sanity.year_problem(2024, "2024") is None
    assert sanity.year_problem(None, "Feb 2026")


def test_geo_parse_and_country():
    assert geo.parse_lat_lon("37°0′52″N 119°7′47″E") == (37.014444, 119.129722)
    assert geo.parse_lat_lon("北纬 37°0′52″ 东经 119°7′47″") == (37.014444, 119.129722)
    assert geo.parse_lat_lon("49.48, 8.44") == (49.48, 8.44)
    assert geo.parse_lat_lon("18°06.397’N Latitude and 73°29.321’E Longitude") == (18.106617, 73.488683)
    assert geo.parse_lat_lon("near the river") is None
    assert geo.in_country(49.48, 8.44, "DE") is True  # Ludwigshafen
    assert geo.in_country(37.01, 119.13, "CN") is True  # Weifang
    assert geo.in_country(49.48, 8.44, "CN") is False
    assert "outside DE" in geo.check(8.44, 49.48, "DE", "exact")[0]
    assert geo.check(49.48, 8.44, "DE", "exact") == []
    assert geo.check(49.48, 8.44, "DE", "country")  # a point at country precision is invented


def test_geo_france_overseas_does_not_cover_africa():
    assert geo.in_country(14.7, -17.4, "FR") is False  # Dakar is not in France


def _site(i, name, country="DE", locality="Ludwigshafen", lat=None, lon=None, reg=None):
    return Site(
        id=f"site:{country.lower()}-{locality.lower()}-{i:02d}",
        name=name,
        country=country,
        locality=locality,
        geo_precision="exact" if lat else "locality",
        lat=lat,
        lon=lon,
        registry_ids=reg or {},
    )


def test_dedupe():
    a = _site(1, "BASF Ludwigshafen Verbund site", lat=49.497, lon=8.432)
    b = _site(2, "BASF SE Ludwigshafen site", lat=49.500, lon=8.440)
    c = _site(3, "Some other plant Ludwigshafen", lat=49.48, lon=8.40)
    d = _site(4, "Different name", country="DE", locality="Mannheim", reg={"eu_ets": "DE-123"})
    e = _site(5, "Another", country="DE", locality="Mannheim", reg={"eu_ets": "DE-123"})
    pairs = {(x.a, x.b) for x in dedupe.candidates([a, b, c, d, e])}
    assert (a.id, b.id) in pairs and (d.id, e.id) in pairs
    assert not any(c.id in p for p in pairs)
    assert dedupe.candidates([a, b, c], new_ids={c.id}) == []


def test_licence():
    assert quarantined("https://www.imarcgroup.com/beta-ionone-manufacturing-plant-project-report")
    assert quarantined("https://faxiangongchang.com/en/reports/china-vitamin-2026")
    assert quarantined("https://www.basf.com/global/en/media/news-releases/2023/03/p-23-129") is None


def test_glued_json_lines_are_split():
    from pipeline.validators.schema import split_glued

    assert split_glued(["[", '{"a": 1}{"b": 2}', '{"c": 3} {"d": 4},', "]", "not json"]) == [
        '{"a": 1}',
        '{"b": 2}',
        '{"c": 3}',
        '{"d": 4}',
        "not json",
    ]


def test_more_unit_wordings():
    from pipeline.validators.units import normalise_capacity

    for unit in ("tons annually", "Tonnen pro Jahr", "ton per år", "t/jahr"):
        assert normalise_capacity("1,200", unit, "en").value_tpa == 1200.0, unit


def test_world_figures_assume_annual_and_take_range_midpoints():
    from pipeline.collect import world_figure

    assert world_figure("14,000", "metric tons", "en") == (14000.0, "assumed annual (world figure)")
    assert world_figure("25,000 to 30,000", "tonnes per year", "en") == (27500.0, "range midpoint")
    assert world_figure("23182", "MT", "en")[0] is None  # MT = metric or million tonnes: never guessed
