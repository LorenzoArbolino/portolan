from pipeline.sources.eurlex import parse_measure, union_industry_rows

# Shaped like the CELLAR text of Regulation (EU) 2026/913 (short excerpt, EU legal text, Decision 2011/833/EU).
ADIPIC = """COMMISSION IMPLEMENTING REGULATION (EU) 2026/913
of 4 May 2026
imposing a definitive anti-dumping duty ... on imports of adipic acid originating in the People’s Republic of China
Article 1
1. A definitive anti-dumping duty is imposed on imports of adipic acid, currently falling under CN code 2917 12 00 (TARIC code 2917 12 00 10) and originating in the People’s Republic of China.
2. The rate of the definitive anti-dumping duty ... shall be as follows:
| Company | Definitive anti-dumping duty | TARIC additional code |
| Chongqing Huafon Chemical Co., Ltd | 29,1 % | 89ZW |
| Tangshan Zhonghao Chemical Co., Ltd | 42,3 % | 89ZX |
| Other cooperating companies listed in Annex | 31,5 % | See Annex |
| All other imports originating in the People’s Republic of China | 42,3 % | 8999 |
Article 2
"""

VANILLIN_TABLE = """| Production capacity (tonnes) | [3 900 – 4 500 ] | [3 900 – 4 500 ] | [4 300 – 4 900 ] | [4 300 – 4 900 ] |
| Index | 100 | 100 | 110 | 111 |
| Capacity utilisation | 98 % | 99 % | 81 % | 35 % |
"""


def test_parse_company_rates():
    m = parse_measure(ADIPIC, "32026R0913")
    assert m.id == "tm:eu:2026-913" and m.instrument == "ad" and m.origin_iso3 == ["CHN"]
    assert m.cn_codes == ["29171200"]
    assert [(r.company_id, r.rate) for r in m.company_rates] == [
        ("co:chongqing-huafon-chemical-co-ltd", 29.1),
        ("co:tangshan-zhonghao-chemical-co-ltd", 42.3),
    ]
    assert (m.rate_min, m.rate_max) == (29.1, 42.3)
    assert m.product_desc == "adipic acid"


def test_single_rate():
    text = (
        "REGULATION (EU) 2025/1151\nArticle 1\n1. A definitive anti-dumping duty is imposed on imports of "
        "vanillin, currently falling under CN code ex 2912 41 00 and originating in the People’s Republic of "
        "China.\n3. The rate of the definitive anti-dumping duty ... shall be 131,1 %.\nArticle 2\n"
    )
    m = parse_measure(text, "32025R1151")
    assert m.rate_min == m.rate_max == 131.1 and m.company_rates == []


def test_union_rows_keep_ranges():
    rows = union_industry_rows(VANILLIN_TABLE)
    assert rows[0].indicator == "Production capacity (tonnes)" and rows[0].values[0] == "[3 900 – 4 500 ]"
    assert rows[1].values == ["98 %", "99 %", "81 %", "35 %"]
