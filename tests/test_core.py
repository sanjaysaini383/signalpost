from signalpost import orgno
from signalpost.brreg import account_facts, role_facts, unit_facts
from signalpost.profile import apply_history, diff_profiles


def test_orgno_valid():
    assert orgno.is_valid("923609016")  # Equinor
    assert orgno.is_valid("923 609 016")


def test_orgno_invalid():
    assert not orgno.is_valid("923609017")
    assert not orgno.is_valid("12345")
    assert not orgno.is_valid("abcdefghi")


def test_unit_facts_carry_evidence():
    u = {"navn": "TEST AS", "antallAnsatte": 5, "harRegistrertAntallAnsatte": True, "konkurs": False}
    facts = {f["field"]: f for f in unit_facts("923609016", u, "2026-10-12T00:00:00Z")}
    assert facts["employees"]["value"] == 5
    assert facts["bankrupt"]["value"] is False
    for f in facts.values():
        assert f["source_url"].endswith("923609016") and f["evidence"] and f["explanation"]


def test_account_facts_use_latest_period_and_keep_currency():
    recs = [
        {"regnskapstype": "SELSKAP", "valuta": "NOK", "regnskapsperiode": {"fraDato": "2022-01-01", "tilDato": "2022-12-31"},
         "eiendeler": {"sumEiendeler": 1}},
        {"regnskapstype": "SELSKAP", "valuta": "NOK", "regnskapsperiode": {"fraDato": "2023-01-01", "tilDato": "2023-12-31"},
         "eiendeler": {"sumEiendeler": 2}},
    ]
    facts = account_facts("923609016", recs, "t")
    assert [f["value"] for f in facts] == [{"amount": 2, "currency": "NOK"}]


def test_role_facts_skip_deregistered_and_dead():
    data = {"rollegrupper": [{"roller": [
        {"avregistrert": True, "type": {"kode": "LEDE", "beskrivelse": "Styrets leder"}, "person": {"navn": {"fornavn": "A", "etternavn": "B"}}},
        {"avregistrert": False, "type": {"kode": "DAGL", "beskrivelse": "Daglig leder"}, "person": {"navn": {"fornavn": "C", "etternavn": "D"}}},
    ]}]}
    facts = role_facts("923609016", data, "t")
    assert len(facts) == 1 and facts[0]["value"]["name"] == "C D"


def test_diff_detects_change():
    def prof(emp):
        return {"status": "active", "generated_at": "t", "facts": [
            {"field": "employees", "value": emp, "source_url": "u", "retrieved_at": "t"}]}
    ch = diff_profiles(prof(5), prof(7))
    assert ch == [{"field": "employees", "change": "changed", "old": 5, "new": 7, "source_url": "u"}]
    assert diff_profiles(prof(5), prof(5)) == []
    new = apply_history(prof(7), prof(5))
    assert new["changes_since_previous_run"][0]["new"] == 7


from signalpost.website import normalize_url, parse_page, ties_to_company, verify_llm_items, website_facts


def test_normalize_url():
    assert normalize_url("www.equinor.com") == "https://www.equinor.com/"
    assert normalize_url("http://a.no/x") == "http://a.no/x"
    assert normalize_url("post@a.no") is None
    assert normalize_url("") is None


def test_ties_to_company():
    assert ties_to_company("923609016", "EQUINOR ASA", ["Org.nr 923 609 016"])
    assert ties_to_company("923609016", "EQUINOR ASA", ["Welcome to Equinor"])
    assert ties_to_company("923609016", "KJØITA NÆRING AS", ["a page about cats"]) is None


def test_parse_page_extracts_meta_and_links():
    p = parse_page('<title>X</title><meta name="description" content="hello"><a href="mailto:a@b.no">m</a><script>no</script>hi')
    assert p.title == "X" and p.meta["description"] == "hello" and p.links == ["mailto:a@b.no"] and p.text == "m hi"


def test_llm_items_dropped_when_quote_not_on_page():
    data = {"business_summary": {"value": "Sells fish", "quote": "We sell fresh fish daily"},
            "products_services": [{"value": "Cars", "quote": "We build luxury cars worldwide"}]}
    kept = verify_llm_items(data, [("u", "Hello. We sell   fresh fish daily to everyone.")])
    assert [k[0] for k in kept] == ["business_summary"]


class _F:  # fetcher stub: website without any tie to the company
    class client:
        headers = {}

    def get(self, url, params=None, accept=None):
        return (404, "") if url.endswith("robots.txt") else (200, "<title>Cats</title>cats everywhere")


def test_wrong_site_is_discarded():
    w = []
    out = website_facts(_F(), "923609016", {"hjemmeside": "cats.example", "navn": "EQUINOR ASA"}, "t", w)
    assert out == [] and "discarded" in w[0]
