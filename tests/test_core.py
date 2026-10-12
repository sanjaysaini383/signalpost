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
    facts = {f["field"]: f for f in account_facts("923609016", recs, "t")}
    assert facts["financials:selskap:total_assets"]["value"] == {"amount": 2, "currency": "NOK"}
    assert facts["financials_history:selskap:total_assets:2022"]["value"] == {"amount": 1, "currency": "NOK"}
    assert all(f["value"].get("currency") == "NOK" for k, f in facts.items() if k.startswith("financials"))


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
    assert ties_to_company("923609016", "EQUINOR ASA", ["Org.nr 923609016"])
    assert ties_to_company("923609016", "EQUINOR ASA", ["Welcome to Equinor, 4035 Stavanger"], postcode="4035")
    assert ties_to_company("923609016", "EQUINOR ASA", ["Welcome to Equinor"]) is None  # a name alone is not enough
    assert ties_to_company("923609016", "EQUINOR ASA", ["Equinor, tlf 51 99 00 00"], phones=["51 99 00 00"])
    assert ties_to_company("923609016", "EQUINOR ASA", ["Equinor 4035"], postcode="4035", strong_only=True) is None
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


from signalpost import brreg, geo
from signalpost.budget import Fetcher
from signalpost.profile import apply_history, build_profile
from signalpost.summary import build_summary
from signalpost.website import candidate_domains, discover_site


class _Reg:
    """Fetcher stub answering from a dict of url -> (status, body)."""
    def __init__(self, routes):
        self.routes, self.client = routes, type("c", (), {"headers": {}})()

    def get(self, url, params=None, accept=None, **kw):
        for key, resp in self.routes.items():
            if url.startswith(key):
                return resp
        return 404, ""

    def get_json(self, url, params=None, **kw):
        import json
        st, text = self.get(url, params)
        return st, (json.loads(text) if st == 200 else None)


def test_deleted_company_is_not_reported_active():
    body = '{"organisasjonsnummer":"923609016","navn":"GONE AS","slettedato":"2026-10-10"}'
    prof = build_profile(_Reg({brreg.UNIT_URL.format(org="923609016"): (200, body)}), "923609016")
    assert prof["status"] == "deleted"
    assert any(f["field"] == "deleted_date" and f["value"] == "2026-10-10" for f in prof["facts"])
    assert "deleted" in prof["summary"]


def test_mismatched_register_record_is_never_published():
    body = '{"organisasjonsnummer":"999999999","navn":"OTHER AS"}'
    prof = build_profile(_Reg({brreg.UNIT_URL.format(org="923609016"): (200, body)}), "923609016")
    assert prof["status"] == "mismatch" and prof["facts"] == []


def test_sub_unit_number_is_handled():
    body = '{"organisasjonsnummer":"973861883","navn":"EQUINOR AVD X","overordnetEnhet":"923609016","antallAnsatte":3,"harRegistrertAntallAnsatte":true}'
    prof = build_profile(_Reg({brreg.SUBUNIT_RECORD_URL.format(org="973861883"): (200, body)}), "973861883")
    assert prof["status"] == "sub_unit"
    assert any(f["field"] == "parent_organization_number" and f["value"] == "923609016" for f in prof["facts"])


def test_failed_source_keeps_previous_facts_flagged_stale():
    old = {"generated_at": "t0", "status": "active", "facts": [
        {"field": "financials:selskap:revenue", "value": {"amount": 5, "currency": "NOK"}, "source_url": "u", "retrieved_at": "t0"}]}
    new = {"generated_at": "t1", "status": "active", "facts": [], "failed_sources": ["accounts"]}
    out = apply_history(new, old)
    assert out["facts"][0]["stale"] is True and out["changes_since_previous_run"] == []


def test_geocode_requires_exact_address_match():
    unit = {"forretningsadresse": {"adresse": ["Forusbeen 50"], "postnummer": "4035", "kommunenummer": "1103", "landkode": "NO"}}
    hit = {"adressetekst": "Forusbeen 50", "postnummer": "4035", "kommunenummer": "1103", "poststed": "STAVANGER",
           "representasjonspunkt": {"lat": 58.9, "lon": 5.7, "epsg": "EPSG:4258"}}
    ok = _Reg({geo.SEARCH: (200, '{"adresser":[' + __import__("json").dumps(hit) + ']}')})
    assert geo.geo_facts(ok, "923609016", unit, "t")[0]["value"]["lat"] == 58.9
    hit["postnummer"] = "5000"
    bad = _Reg({geo.SEARCH: (200, '{"adresser":[' + __import__("json").dumps(hit) + ']}')})
    assert geo.geo_facts(bad, "923609016", unit, "t") == []


def test_candidate_domains():
    assert candidate_domains("KJØITA NÆRING AS")[0] == "kjoitanaering.no"
    assert candidate_domains("AB AS") == []


def test_discovery_needs_org_number_on_page():
    unit = {"navn": "TEST BYGG AS", "organisasjonsform": {"kode": "AS"}}
    good = _Reg({"https://testbygg.no/": (200, "<title>Test Bygg</title>Org.nr 923 609 016")})
    assert discover_site(good, "923609016", unit) == "https://testbygg.no/"
    bad = _Reg({"https://testbygg.no/": (200, "<title>Test Bygg</title>no number here")})
    assert discover_site(bad, "923609016", unit) is None
    assert discover_site(good, "923609016", {**unit, "organisasjonsform": {"kode": "ENK"}}) is None


def test_cache_expires(tmp_path):
    import os, time
    f = Fetcher(cache_dir=tmp_path, cache_ttl=60)
    path = f._cache_path("http://x", None)
    path.write_text('{"status": 200, "text": "old"}', "utf-8")
    assert f._cached(path) == (200, "old")
    os.utime(path, (time.time() - 3600, time.time() - 3600))
    assert f._cached(path) is None


def test_summary_mentions_key_facts():
    p = {"organization_number": "923609016", "name": "EQUINOR ASA", "status": "active", "facts": [
        {"field": "organization_form", "value": "Allmennaksjeselskap (ASA)"},
        {"field": "employees", "value": 21272}, {"field": "bankrupt", "value": False}]}
    s = build_summary(p)
    assert "EQUINOR ASA" in s and "21,272" in s


def test_llm_numbers_must_come_from_the_quote():
    data = {"business_summary": {"value": "Turns over 500 million", "quote": "We are a family firm founded long ago"},
            "products_services": [{"value": "Founded in 1998", "quote": "The company was founded in 1998 by two friends"}]}
    kept = verify_llm_items(data, [("u", "We are a family firm founded long ago. The company was founded in 1998 by two friends.")])
    assert [k[0] for k in kept] == ["product_or_service"]


def test_llm_step_end_to_end_with_fake_client():
    from signalpost.website import llm_facts, parse_page
    page = parse_page("<title>Acme</title>We repair bicycles and sell spare parts in Oslo.")

    class Msg:
        usage = type("u", (), {"input_tokens": 10, "output_tokens": 5})()
        content = [type("b", (), {"type": "text", "text": '{"business_summary": {"value": "Repairs bicycles", '
                    '"quote": "We repair bicycles and sell spare parts"}, "products_services": [{"value": "Cars", '
                    '"quote": "We build luxury cars for everyone"}], "locations": []}'})()]

    class Client:
        class messages:
            @staticmethod
            def create(**kw):
                return Msg()

    f = Fetcher()
    out = llm_facts(f, [("https://acme.no/", "", page)], "why", "t", [], client=Client())
    assert [x["field"] for x in out] == ["business_summary"] and f.requests_made == 1 and f.llm_input_tokens == 10
