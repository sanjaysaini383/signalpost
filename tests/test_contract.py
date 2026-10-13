import json

import pytest

from signalpost.batch import read_batch
from signalpost.budget import UnsafeURL, check_public_url
from signalpost.envelope import SECTIONS, build_envelope
from signalpost.website import email_domain, parse_feed, parse_page, website_facts


def _profile(employees=5, status="active"):
    src = "https://data.brreg.no/enhetsregisteret/api/enheter/923609016"
    facts = [
        {"field": "name", "value": "TEST AS", "source_url": src, "retrieved_at": "t", "evidence": "navn: TEST AS",
         "explanation": "x"},
        {"field": "employees", "value": employees, "source_url": src, "retrieved_at": "t",
         "evidence": f"antallAnsatte: {employees}", "explanation": "x"},
        {"field": "financials:selskap:revenue", "value": {"amount": 100.0, "currency": "NOK"},
         "source_url": "https://data.brreg.no/regnskapsregisteret/regnskap/923609016", "retrieved_at": "t",
         "evidence": "resultatregnskapResultat.driftsresultat.driftsinntekter.sumDriftsinntekter: 100.0 NOK",
         "explanation": "x", "as_of": "2025-12-31"},
    ]
    return {"organization_number": "923609016", "status": status, "facts": facts, "warnings": [], "checks": {},
            "summary": "s", "coverage_notes": [], "identity_check": []}


def _env(profile, previous=None):
    snaps = {"https://data.brreg.no/enhetsregisteret/api/enheter/923609016":
             {"final_url": "u", "status": 200, "retrieved_at": "t", "content_sha256": "a" * 64}}
    return build_envelope(profile, run_id="r", started_at="t0", completed_at="t1", snapshots=snaps, requests=3,
                          runtime_ms=10, previous=previous)


def test_envelope_has_every_section_with_a_state():
    e = _env(_profile())
    assert set(e["sections"]) == set(SECTIONS)
    assert all(v["availability"] in ("available", "not_available", "blocked", "not_applicable", "ambiguous", "failed")
               for v in e["sections"].values())
    assert e["sections"]["official_website"]["availability"] == "not_available"


def test_absence_is_an_explicit_null_claim_never_zero():
    e = _env(_profile())
    absent = [c for c in e["claims"] if c["availability"] != "available"]
    assert absent and all(c["value"] is None and c["evidence_ids"] == [] for c in absent)


def test_every_available_claim_has_hashed_evidence():
    e = _env(_profile())
    ev = {x["id"]: x for x in e["evidence"]}
    for c in e["claims"]:
        if c["availability"] == "available":
            assert c["evidence_ids"] and all(i in ev for i in c["evidence_ids"])
    assert ev[next(c for c in e["claims"] if c["field"] == "legal_name")["evidence_ids"][0]]["content_sha256"] == "a" * 64


def test_financial_claim_keeps_reporting_period_and_currency():
    c = next(c for c in _env(_profile())["claims"] if c["field"] == "revenue")
    assert c["reporting_period"] == "2025-12-31" and c["value"]["currency"] == "NOK"


def test_rerun_of_same_snapshot_is_idempotent():
    first = _env(_profile())
    second = _env(_profile(), previous=first)
    assert second["changes"] == []
    assert [c["id"] for c in first["claims"]] == [c["id"] for c in second["claims"]]


def test_refresh_reports_material_change_with_both_evidence_sides():
    first = _env(_profile(employees=5))
    second = _env(_profile(employees=9), previous=first)
    ch = [c for c in second["changes"] if c["field"] == "registered_employees"]
    assert ch and ch[0]["change_type"] == "changed" and ch[0]["materiality"] == "material"
    assert ch[0]["previous_value"] == 5 and ch[0]["current_value"] == 9
    assert ch[0]["previous_evidence"] and ch[0]["current_evidence"]


def test_status_change_is_detected():
    first = _env(_profile(status="active"))
    second = _env(_profile(status="deleted"), previous=first)
    assert any(c["field"] == "organisation_status" and c["change_type"] == "changed" for c in second["changes"])


def test_read_batch_formats(tmp_path):
    (tmp_path / "a.jsonl").write_text('{"organisation_number":"923609016"}\n{"organisation_number":"923609016"}\n'
                                      '{"organisation_number":"914368448","name":"X"}\n', "utf-8")
    assert read_batch(tmp_path / "a.jsonl") == (["923609016", "914368448"], ["923609016"])
    (tmp_path / "b.json").write_text(json.dumps({"organisation_numbers": ["923 609 016", 914368448]}), "utf-8")
    assert read_batch(tmp_path / "b.json")[0] == ["923609016", "914368448"]
    (tmp_path / "c.txt").write_text("# header\n923609016  # Equinor\n914368448\n", "utf-8")
    assert read_batch(tmp_path / "c.txt")[0] == ["923609016", "914368448"]


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://localhost/", "file:///etc/passwd", "ftp://example.com/",
                                 "http://10.0.0.5/", "http://example.com:8080/", "http://user:pw@example.com/",
                                 "http://169.254.169.254/latest/meta-data/"])
def test_unsafe_urls_are_refused(url):
    with pytest.raises(UnsafeURL):
        check_public_url(url)


def test_email_domain_skips_mailbox_providers():
    assert email_domain({"epostadresse": "post@gangstadbygg.no"}) == "gangstadbygg.no"
    assert email_domain({"epostadresse": "ola@gmail.com"}) is None
    assert email_domain({"epostadresse": "ola@online.no"}) is None


def test_parse_feed_needs_title_link_and_date():
    rss = ("<rss><channel><item><title>Ny avtale</title><link>https://a.no/n/1</link>"
           "<pubDate>Mon, 12 Oct 2026 08:00:00 +0200</pubDate></item><item><title>No date</title>"
           "<link>https://a.no/n/2</link></item></channel></rss>")
    assert parse_feed(rss) == [("Ny avtale", "https://a.no/n/1", "2026-10-12T06:00:00Z")]


class _Site:
    """Fetcher stub: a company site with an org number, a careers page with a JSON-LD job and a feed."""
    client = type("c", (), {"headers": {}})()
    home = ('<html><head><title>Test Bygg</title><link rel="alternate" type="application/rss+xml" href="/feed/">'
            '</head><body>Test Bygg AS, org.nr 923 609 016 <a href="/karriere">Karriere</a>'
            '<a href="https://www.facebook.com/testbygg">Facebook</a>'
            '<a href="https://testbygg.webcruiter.no/main/recruit">Ledige stillinger</a></body></html>')
    careers = ('<html><body><script type="application/ld+json">{"@type":"JobPosting","title":"Tømrer",'
               '"datePosted":"2026-10-01","jobLocation":{"address":{"addressLocality":"Oslo"}}}</script></body></html>')
    feed = ("<rss><item><title>Nytt prosjekt</title><link>https://testbygg.no/nytt</link>"
            "<pubDate>Fri, 09 Oct 2026 10:00:00 GMT</pubDate></item></rss>")

    def get(self, url, params=None, accept=None, **kw):
        if url.endswith("robots.txt"):
            return 404, ""
        if url.rstrip("/").endswith("karriere"):
            return 200, self.careers
        if url.rstrip("/").endswith("feed"):
            return 200, self.feed
        return 200, self.home


def test_site_research_finds_profiles_jobs_and_activity():
    checks, warnings = {}, []
    unit = {"hjemmeside": "testbygg.no", "navn": "TEST BYGG AS", "organisasjonsform": {"kode": "AS"}}
    facts = website_facts(_Site(), "923609016", unit, "t", warnings, checks=checks)
    fields = {f["field"] for f in facts}
    assert {"website_verified", "social:facebook", "careers_page", "job_posting", "hiring_channel", "news_item"} <= fields
    assert all(checks[k]["availability"] == "available"
               for k in ("official_website", "company_profiles", "hiring", "public_activity"))
    job = next(f for f in facts if f["field"] == "job_posting")
    assert job["value"]["title"] == "Tømrer" and job["value"]["date_posted"] == "2026-10-01"


def test_group_domain_holding_part_of_the_name_is_not_the_company():
    from signalpost.website import _domain_matches_name, _name_core
    assert not _domain_matches_name("www.amestoaccounthouse.no", _name_core("AMESTO ACCOUNTHOUSE SØR AS"))
    assert _domain_matches_name("kontinent-transport.no", _name_core("KONTINENT TRANSPORT AS"))


def test_sister_brand_domain_needs_more_than_name_and_postcode():
    from signalpost.website import tie_evidence
    assert tie_evidence("923609016", "FJORDANE BILUTLEIGE AS", ["Fjordane Bilutleige 6800 Førde"],
                        postcode="6800", domain="firda-billag.no") is None


def test_page_listing_several_org_numbers_is_not_a_tie_on_its_own():
    from signalpost.website import tie_evidence
    page = ["Våre selskaper: Små AS org.nr 923 609 016, Store AS org.nr 914 368 448"]
    assert tie_evidence("923609016", "SMÅ AS", page, domain="groupco.no") is None
    assert tie_evidence("923609016", "SMÅ AS", ["Små AS, org.nr 923 609 016"], domain="smaa.no")


class _GroupSite(_Site):
    home = ('<html><head><title>Group</title><link rel="alternate" type="application/rss+xml" href="/feed/"></head>'
            '<body>Test Bygg Sør AS, 0150 Oslo <a href="https://www.facebook.com/group">Facebook</a>'
            '<a href="/karriere">Karriere</a></body></html>')


def test_group_site_publishes_the_page_but_not_group_signals():
    checks = {}
    unit = {"hjemmeside": "https://testbygg-gruppen.no/sor", "navn": "TEST BYGG SØR AS",
            "organisasjonsform": {"kode": "AS"}, "forretningsadresse": {"postnummer": "0150"}}
    facts = website_facts(_GroupSite(), "923609016", unit, "t", [], checks=checks)
    fields = {f["field"] for f in facts}
    assert "website_verified" in fields and not fields & {"social:facebook", "careers_page", "news_item"}
    assert checks["company_profiles"]["availability"] == "ambiguous"


def test_unrelated_group_domain_is_not_verified_at_all():
    unit = {"hjemmeside": "https://group.no/test-bygg-sor", "navn": "TEST BYGG SØR AS",
            "organisasjonsform": {"kode": "AS"}, "forretningsadresse": {"postnummer": "0150"}}
    checks = {}
    assert website_facts(_GroupSite(), "923609016", unit, "t", [], checks=checks) == []
    assert checks["official_website"]["availability"] == "ambiguous"
