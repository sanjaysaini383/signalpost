"""Fetchers for the Bronnoysund Register Centre open APIs, and conversion into evidenced facts."""
import json
from datetime import datetime, timezone

BASE = "https://data.brreg.no"
UNIT_URL = BASE + "/enhetsregisteret/api/enheter/{org}"
ROLES_URL = UNIT_URL + "/roller"
ACCOUNTS_URL = BASE + "/regnskapsregisteret/regnskap/{org}"
UPDATES_URL = BASE + "/enhetsregisteret/api/oppdateringer/enheter"
SEARCH_URL = BASE + "/enhetsregisteret/api/enheter"


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fact(field, value, source_url, evidence, explanation, retrieved_at, as_of=None):
    f = {"field": field, "value": value, "source_url": source_url,
         "retrieved_at": retrieved_at, "evidence": evidence, "explanation": explanation}
    if as_of:
        f["as_of"] = as_of
    return f


def fetch_unit(fetcher, org):
    """Return (state, json). state is one of found | deleted | not_found."""
    status, text = fetcher.get(UNIT_URL.format(org=org))
    if status == 200:
        return "found", json.loads(text)
    if status == 410:
        return "deleted", None
    return "not_found", None


def _addr(a):
    if not a:
        return None
    parts = [*a.get("adresse", []), f"{a.get('postnummer', '')} {a.get('poststed', '')}".strip(), a.get("land", "")]
    return ", ".join(p for p in parts if p)


_FLAGS = {"konkurs": "bankrupt", "underAvvikling": "under_liquidation",
          "underTvangsavviklingEllerTvangsopplosning": "under_forced_dissolution"}


def unit_facts(org, u, retrieved_at):
    src = UNIT_URL.format(org=org)
    why = f"Enhetsregisteret record keyed by organisation number {org}"
    out = []

    def add(field, value, key, as_of=None):
        if value in (None, "", []):
            return
        out.append(fact(field, value, src, f"{key}: {value}", why, retrieved_at, as_of))

    add("name", u.get("navn"), "navn")
    of = u.get("organisasjonsform") or {}
    if of.get("kode"):
        out.append(fact("organization_form", f"{of.get('beskrivelse')} ({of['kode']})", src,
                        f"organisasjonsform: {of['kode']}", why, retrieved_at))
    add("registered_in_business_register", u.get("registrertIForetaksregisteret"), "registrertIForetaksregisteret")
    add("founded", u.get("stiftelsesdato"), "stiftelsesdato")
    add("registered_date", u.get("registreringsdatoEnhetsregisteret"), "registreringsdatoEnhetsregisteret")
    for key, field in _FLAGS.items():
        if key in u:
            out.append(fact(field, u[key], src, f"{key}: {str(u[key]).lower()}", why, retrieved_at))
    if u.get("harRegistrertAntallAnsatte") and "antallAnsatte" in u:
        add("employees", u["antallAnsatte"], "antallAnsatte", u.get("registreringsdatoAntallAnsatteEnhetsregisteret"))
    add("business_address", _addr(u.get("forretningsadresse")), "forretningsadresse")
    add("postal_address", _addr(u.get("postadresse")), "postadresse")
    for i in (1, 2, 3):
        n = u.get(f"naeringskode{i}")
        if n:
            out.append(fact("industry_code" if i == 1 else f"industry_code_{i}", f"{n['kode']} {n['beskrivelse']}", src,
                            f"naeringskode{i}: {n['kode']} {n['beskrivelse']}", why, retrieved_at))
    add("website", u.get("hjemmeside"), "hjemmeside")
    add("phone", u.get("telefon") or u.get("mobil"), "telefon")
    add("email", u.get("epostadresse"), "epostadresse")
    if u.get("aktivitet"):
        text = " ".join(u["aktivitet"])
        out.append(fact("activity_description", text, src, f"aktivitet: {text[:200]}", why, retrieved_at))
    if u.get("vedtektsfestetFormaal"):
        text = " ".join(u["vedtektsfestetFormaal"])
        out.append(fact("purpose", text, src, f"vedtektsfestetFormaal: {text[:200]}", why, retrieved_at))
    k = u.get("kapital")
    if k and k.get("belop") is not None:
        out.append(fact("share_capital", {"amount": k["belop"], "currency": k.get("valuta")}, src,
                        f"kapital.belop: {k['belop']} {k.get('valuta')}", why, retrieved_at, k.get("innfortDato")))
    add("part_of_group", u.get("erIKonsern"), "erIKonsern")
    add("vat_registered", u.get("registrertIMvaregisteret"), "registrertIMvaregisteret")
    add("last_annual_accounts_year", u.get("sisteInnsendteAarsregnskap"), "sisteInnsendteAarsregnskap")
    return out


def fetch_roles(fetcher, org):
    status, data = fetcher.get_json(ROLES_URL.format(org=org))
    return data if status == 200 else None


def role_facts(org, data, retrieved_at):
    if not data:
        return []
    src = ROLES_URL.format(org=org)
    why = f"Role listed on the Enhetsregisteret record of organisation number {org}"
    out = []
    for group in data.get("rollegrupper", []):
        for r in group.get("roller", []):
            if r.get("avregistrert"):
                continue
            code = (r.get("type") or {}).get("kode")
            desc = (r.get("type") or {}).get("beskrivelse")
            if r.get("person"):
                if r["person"].get("erDoed"):
                    continue
                n = r["person"].get("navn", {})
                name = " ".join(x for x in (n.get("fornavn"), n.get("mellomnavn"), n.get("etternavn")) if x)
            elif r.get("enhet"):
                name = " ".join(r["enhet"].get("navn", []))
                if r["enhet"].get("organisasjonsnummer"):
                    name += f" (org {r['enhet']['organisasjonsnummer']})"
            else:
                continue
            if not name:
                continue
            out.append(fact(f"role:{code}", {"role": desc, "name": name}, src,
                            f"{code} ({desc}): {name}", why, retrieved_at, group.get("sistEndret")))
    return out


def fetch_accounts(fetcher, org):
    status, data = fetcher.get_json(ACCOUNTS_URL.format(org=org))
    return data if status == 200 and isinstance(data, list) else []


def _dig(d, *path):
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d


_ACCOUNT_FIELDS = [
    ("revenue", ("resultatregnskapResultat", "driftsresultat", "driftsinntekter", "sumDriftsinntekter")),
    ("operating_profit", ("resultatregnskapResultat", "driftsresultat", "driftsresultat")),
    ("net_profit", ("resultatregnskapResultat", "aarsresultat")),
    ("total_assets", ("eiendeler", "sumEiendeler")),
    ("equity", ("egenkapitalGjeld", "egenkapital", "sumEgenkapital")),
    ("total_debt", ("egenkapitalGjeld", "gjeldOversikt", "sumGjeld")),
]


def account_facts(org, records, retrieved_at):
    """Latest filed accounts only. Values are copied verbatim from the register, never generated."""
    if not records:
        return []
    latest_end = max(_dig(r, "regnskapsperiode", "tilDato") or "" for r in records)
    src = ACCOUNTS_URL.format(org=org)
    out = []
    for r in records:
        period = r.get("regnskapsperiode", {})
        if period.get("tilDato") != latest_end:
            continue
        kind = (r.get("regnskapstype") or "SELSKAP").lower()
        cur = r.get("valuta")
        why = (f"Annual accounts ({kind}) filed under organisation number {org} in Regnskapsregisteret, "
               f"period {period.get('fraDato')} to {period.get('tilDato')}")
        for name, path in _ACCOUNT_FIELDS:
            v = _dig(r, *path)
            if v is None:
                continue
            out.append(fact(f"financials:{kind}:{name}", {"amount": v, "currency": cur}, src,
                            f"{'.'.join(path)}: {v} {cur} (journalnr {r.get('journalnr')})", why,
                            retrieved_at, period.get("tilDato")))
    return out
