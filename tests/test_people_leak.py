import json

from pipeline.validators.people_leak import scan_file, scan_paths, scan_record, scan_text


def kinds(text):
    return {k for k, _ in scan_text(text)}


def test_catches_planted_email():
    assert kinds("For details write to sales.team@example-aroma.com today") == {"email"}


def test_catches_planted_phone():
    assert "phone" in kinds("Tel: +49 621 60-0")
    assert "phone" in kinds("call +86 535 3388 222")


def test_catches_planted_names():
    assert "name" in kinds("Contact: Dr. Hans Müller")
    assert "name" in kinds('"We are proud," said John Smith, CEO of Example Aroma.')
    assert "name" in kinds("Plant manager Priya Sharma confirmed the restart")
    assert "name" in kinds("示例化工董事长张三丰出席了仪式")


def test_no_false_positives_on_ordinary_data():
    for text in [
        "capacity of 48,000 t/a since 2024-08-29, CAS 5392-40-5",
        "BASF SE, Ludwigshafen am Rhein",
        "Wanhua Chemical announced its citral plant",
        "Plot 765, Jhagadia Industrial Estate, Bharuch, Gujarat",
        "示例化工有限公司年产4.8万吨柠檬醛项目",
        "unit:de-ludwigshafen-01:citral",
        "HS 291219, CN 29121900",
    ]:
        assert scan_text(text) == [], text


def test_company_document_quote_may_contain_a_name_but_not_an_email():
    ev = {"source_type": "company_primary", "quote": "said John Smith, CEO", "publisher": "Example"}
    assert scan_record(ev, "x") == []
    ev_press = dict(ev, source_type="trade_press")
    assert {f.kind for f in scan_record(ev_press, "x")} == {"name"}
    ev_email = dict(ev, quote="contact john.smith@example.com")
    assert [f.kind for f in scan_record(ev_email, "x")] == ["email"]


def test_name_outside_quote_field_is_caught_even_for_company_docs():
    ev = {"source_type": "company_primary", "quote": "ok", "locator": "Mr. Peter Example's letter"}
    assert scan_record(ev, "x")


def test_scan_paths(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    (d / "evidence.jsonl").write_text(
        json.dumps({"source_type": "trade_press", "quote": "capacity 48,000 t"})
        + "\n"
        + json.dumps({"source_type": "trade_press", "quote": "mail info@example.com"})
        + "\n",
        encoding="utf-8",
    )
    (d / "notes.md").write_text("Finding: citral is concentrated.\n", encoding="utf-8")
    findings = scan_paths([d])
    assert [(f.kind, f.where) for f in findings] == [("email", "line 2.quote")]
    assert scan_file(d / "notes.md") == []


def test_street_named_after_a_person_is_an_address():
    assert scan_text("Av. Industrial José Erineu Ortigosa, 827, Distrito Industrial, Barra Bonita/SP") == []
    assert "name" in kinds("Contact José Silva for prices")  # a person, not a street


def test_same_locality():
    from pipeline.validators.dedupe import same_locality

    assert same_locality("Ludwigshafen", "Ludwigshafen am Rhein")
    assert not same_locality("Mahad", "Mahadevapura")
