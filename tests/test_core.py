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
