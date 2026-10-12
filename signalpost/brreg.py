"""Fetchers for the Bronnoysund Register Centre open APIs, and conversion into evidenced facts."""
import json
from datetime import datetime, timezone

BASE = "https://data.brreg.no"
UNIT_URL = BASE + "/enhetsregisteret/api/enheter/{org}"
SUBUNIT_RECORD_URL = BASE + "/enhetsregisteret/api/underenheter/{org}"
ROLES_URL = UNIT_URL + "/roller"
ACCOUNTS_URL = BASE + "/regnskapsregisteret/regnskap/{org}"
UPDATES_URL = BASE + "/enhetsregisteret/api/oppdateringer/enheter"
SEARCH_URL = BASE + "/enhetsregisteret/api/enheter"
SUBUNITS_URL = BASE + "/enhetsregisteret/api/underenheter"


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fact(field, value, source_url, evidence, explanation, retrieved_at, as_of=None):
    f = {"field": field, "value": value, "source_url": source_url,
         "retrieved_at": retrieved_at, "evidence": evidence, "explanation": explanation}
    if as_of:
        f["as_of"] = as_of
    return f


def _loads(text):
    try:
        return json.loads(text)
    except ValueError:
        return None


def fetch_unit(fetcher, org):
    """Return (state, json). state: found | deleted | sub_unit | not_found.

    The register keeps deleted companies for a while: they answer HTTP 200 (or 410) with a `slettedato`
    field, so a 200 alone does not mean the company is active."""
    status, text = fetcher.get(UNIT_URL.format(org=org))
    if status in (200, 410):
        u = _loads(text)
        if isinstance(u, dict):
            return ("deleted" if status == 410 or u.get("slettedato") else "found"), u
        return ("deleted", {}) if status == 410 else ("not_found", None)
    # Not a main unit. The number may belong to a sub-unit (establishment).
    status, text = fetcher.get(SUBUNIT_RECORD_URL.format(org=org))
    if status in (200, 410):
        u = _loads(text)
        if isinstance(u, dict):
            return ("deleted" if status == 410 or u.get("slettedato") else "sub_unit"), u
    return "not_found", None


def _addr(a):
    if not a:
        return None
    parts = [*a.get("adresse", []), f"{a.get('postnummer', '')} {a.get('poststed', '')}".strip(), a.get("land", "")]
    return ", ".join(p for p in parts if p)


_FLAGS = {"konkurs": "bankrupt", "underAvvikling": "under_liquidation",
          "underTvangsavviklingEllerTvangsopplosning": "under_forced_dissolution"}


def unit_facts(org, u, retrieved_at, sub_unit=False):
    src = (SUBUNIT_RECORD_URL if sub_unit else UNIT_URL).format(org=org)
    why = (f"{'Sub-unit' if sub_unit else 'Enhetsregisteret'} record keyed by organisation number {org}")
    out = []

    def add(field, value, key, as_of=None):
        if value in (None, "", []):
            return
        out.append(fact(field, value, src, f"{key}: {value}", why, retrieved_at, as_of))

    add("name", u.get("navn"), "navn")
    add("deleted_date", u.get("slettedato"), "slettedato")
    of = u.get("organisasjonsform") or {}
    if of.get("kode"):
        out.append(fact("organization_form", f"{of.get('beskrivelse')} ({of['kode']})", src,
                        f"organisasjonsform: {of['kode']}", why, retrieved_at))
    if sub_unit:
        parent = u.get("overordnetEnhet")
        add("parent_organization_number", parent, "overordnetEnhet")
        add("started", u.get("oppstartsdato"), "oppstartsdato")
    else:
        add("registered_in_business_register", u.get("registrertIForetaksregisteret"), "registrertIForetaksregisteret")
        add("parent_organization_number", u.get("overordnetEnhet"), "overordnetEnhet")
    add("founded", u.get("stiftelsesdato"), "stiftelsesdato")
    add("registered_date", u.get("registreringsdatoEnhetsregisteret"), "registreringsdatoEnhetsregisteret")
    if not sub_unit:
        add("business_register_registered_date", u.get("registreringsdatoForetaksregisteret"),
            "registreringsdatoForetaksregisteret")
        add("vat_registered_date", u.get("registreringsdatoMerverdiavgiftsregisteret"),
            "registreringsdatoMerverdiavgiftsregisteret")
        add("articles_date", u.get("vedtektsdato"), "vedtektsdato")
    for key, field in _FLAGS.items():
        if key in u:
            out.append(fact(field, u[key], src, f"{key}: {str(u[key]).lower()}", why, retrieved_at))
    add("bankruptcy_date", u.get("konkursdato"), "konkursdato")
    add("liquidation_date", u.get("underAvviklingDato"), "underAvviklingDato")
    add("forced_dissolution_date", u.get("underTvangsavviklingEllerTvangsopplosningDato"),
        "underTvangsavviklingEllerTvangsopplosningDato")
    if u.get("harRegistrertAntallAnsatte") and "antallAnsatte" in u:
        add("employees", u["antallAnsatte"], "antallAnsatte", u.get("registreringsdatoAntallAnsatteEnhetsregisteret"))
    biz = u.get("forretningsadresse") or u.get("beliggenhetsadresse")
    add("business_address", _addr(biz), "forretningsadresse")
    add("postal_address", _addr(u.get("postadresse")), "postadresse")
    if biz and biz.get("kommune"):
        out.append(fact("municipality", f"{biz['kommune']} ({biz.get('kommunenummer')})", src,
                        f"kommune: {biz['kommune']}, kommunenummer: {biz.get('kommunenummer')}", why, retrieved_at))
    for i in (1, 2, 3):
        n = u.get(f"naeringskode{i}")
        if n:
            out.append(fact("industry_code" if i == 1 else f"industry_code_{i}", f"{n['kode']} {n['beskrivelse']}", src,
                            f"naeringskode{i}: {n['kode']} {n['beskrivelse']}", why, retrieved_at))
    sector = u.get("institusjonellSektorkode")
    if sector:
        out.append(fact("institutional_sector", f"{sector.get('kode')} {sector.get('beskrivelse')}", src,
                        f"institusjonellSektorkode: {sector.get('kode')} {sector.get('beskrivelse')}", why, retrieved_at))
    add("website", u.get("hjemmeside"), "hjemmeside")
    add("phone", u.get("telefon"), "telefon")
    add("mobile", u.get("mobil"), "mobil")
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
    hist = [{"name": h.get("navn"), "from": (h.get("fraDato") or "")[:10], "to": (h.get("tilDato") or "")[:10]}
            for h in u.get("historiskeNavn", []) if h.get("navn")]
    if hist:
        out.append(fact("former_names", hist, src, f"historiskeNavn: {len(hist)} earlier name(s), "
                        f"latest '{hist[-1]['name']}'", why, retrieved_at))
    add("language_form", u.get("maalform"), "maalform")
    if not sub_unit:
        add("part_of_group", u.get("erIKonsern"), "erIKonsern")
        add("vat_registered", u.get("registrertIMvaregisteret"), "registrertIMvaregisteret")
        if u.get("frivilligMvaRegistrertBeskrivelser"):
            add("voluntary_vat_activities", u["frivilligMvaRegistrertBeskrivelser"], "frivilligMvaRegistrertBeskrivelser")
        for key, field in (("registrertIStiftelsesregisteret", "registered_in_foundation_register"),
                           ("registrertIFrivillighetsregisteret", "registered_in_voluntary_register"),
                           ("registrertIPartiregisteret", "registered_in_party_register")):
            if u.get(key):
                add(field, True, key)
        add("last_annual_accounts_year", u.get("sisteInnsendteAarsregnskap"), "sisteInnsendteAarsregnskap")
        notes = [f"{p.get('infotype', '')}: {p.get('tekst', '')}".strip(": ") if isinstance(p, dict) else str(p)
                 for p in u.get("paategninger", [])]
        if notes:
            add("register_notes", notes, "paategninger")
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
            value = {"role": desc, "name": name}
            if r.get("fratraadt"):
                continue  # has stepped down
            out.append(fact(f"role:{code}", value, src, f"{code} ({desc}): {name}", why, retrieved_at,
                            group.get("sistEndret")))
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
    ("operating_costs", ("resultatregnskapResultat", "driftsresultat", "driftskostnad", "sumDriftskostnad")),
    ("operating_profit", ("resultatregnskapResultat", "driftsresultat", "driftsresultat")),
    ("profit_before_tax", ("resultatregnskapResultat", "ordinaertResultatFoerSkattekostnad")),
    ("net_profit", ("resultatregnskapResultat", "aarsresultat")),
    ("total_assets", ("eiendeler", "sumEiendeler")),
    ("current_assets", ("eiendeler", "omloepsmidler", "sumOmloepsmidler")),
    ("fixed_assets", ("eiendeler", "anleggsmidler", "sumAnleggsmidler")),
    ("cash", ("eiendeler", "sumBankinnskuddOgKontanter")),
    ("equity", ("egenkapitalGjeld", "egenkapital", "sumEgenkapital")),
    ("total_debt", ("egenkapitalGjeld", "gjeldOversikt", "sumGjeld")),
    ("current_debt", ("egenkapitalGjeld", "gjeldOversikt", "kortsiktigGjeld", "sumKortsiktigGjeld")),
    ("long_term_debt", ("egenkapitalGjeld", "gjeldOversikt", "langsiktigGjeld", "sumLangsiktigGjeld")),
]
_HISTORY_FIELDS = {"revenue", "net_profit", "total_assets", "equity"}
HISTORY_YEARS = 2  # earlier fiscal years kept in addition to the latest


def account_facts(org, records, retrieved_at):
    """Annual accounts. Values are copied verbatim from the register (with currency), never generated."""
    if not records:
        return []
    src = ACCOUNTS_URL.format(org=org)
    by_key = {}  # (kind, period end) -> newest filing
    for r in records:
        kind = (r.get("regnskapstype") or "SELSKAP").lower()
        end = _dig(r, "regnskapsperiode", "tilDato")
        if not end:
            continue
        cur = by_key.get((kind, end))
        if cur is None or (r.get("id") or 0) > (cur.get("id") or 0):
            by_key[(kind, end)] = r
    ends = sorted({e for _, e in by_key}, reverse=True)
    latest = ends[0]
    keep_hist = set(ends[1:1 + HISTORY_YEARS])
    out = []
    for (kind, end), r in sorted(by_key.items(), key=lambda kv: kv[0][1], reverse=True):
        if end != latest and end not in keep_hist:
            continue
        cur = r.get("valuta")
        period = r.get("regnskapsperiode", {})
        is_latest = end == latest
        why = (f"Annual accounts ({kind}) filed under organisation number {org} in Regnskapsregisteret, "
               f"period {period.get('fraDato')} to {period.get('tilDato')}")
        if is_latest:
            info = {"period_start": period.get("fraDato"), "period_end": end, "currency": cur,
                    "accounting_rules": _dig(r, "regnkapsprinsipper", "regnskapsregler"),
                    "small_company_rules": _dig(r, "regnkapsprinsipper", "smaaForetak"),
                    "unaudited": _dig(r, "revisjon", "ikkeRevidertAarsregnskap"),
                    "audit_waived": _dig(r, "revisjon", "fravalgRevisjon"),
                    "liquidation_accounts": r.get("avviklingsregnskap")}
            info = {k: v for k, v in info.items() if v is not None}
            out.append(fact(f"accounts_info:{kind}", info, src, f"journalnr {r.get('journalnr')}, "
                            f"regnskapsperiode {period.get('fraDato')}..{end}", why, retrieved_at, end))
        for name, path in _ACCOUNT_FIELDS:
            if not is_latest and name not in _HISTORY_FIELDS:
                continue
            v = _dig(r, *path)
            if v is None:
                continue
            field = f"financials:{kind}:{name}" if is_latest else f"financials_history:{kind}:{name}:{end[:4]}"
            out.append(fact(field, {"amount": v, "currency": cur}, src,
                            f"{'.'.join(path)}: {v} {cur} (journalnr {r.get('journalnr')})", why, retrieved_at, end))
    return out


def fetch_subunits(fetcher, org):
    status, data = fetcher.get_json(SUBUNITS_URL, {"overordnetEnhet": org, "size": 20})
    if status != 200 or not data:
        return {"items": [], "total": 0}
    items = data.get("_embedded", {}).get("underenheter", [])
    return {"items": items, "total": (data.get("page") or {}).get("totalElements", len(items))}


def subunit_facts(org, result, retrieved_at):
    """Establishments (branches) registered under the parent organisation number."""
    subs = result["items"] if isinstance(result, dict) else result
    total = result.get("total", len(subs)) if isinstance(result, dict) else len(subs)
    src = f"{SUBUNITS_URL}?overordnetEnhet={org}"
    out = []
    for s in subs:
        if s.get("overordnetEnhet") != org:
            continue  # never attach a sub-unit that the register does not tie to this parent
        addr = _addr(s.get("beliggenhetsadresse")) or _addr(s.get("postadresse"))
        value = {"organization_number": s.get("organisasjonsnummer"), "name": s.get("navn"), "address": addr}
        if "antallAnsatte" in s:
            value["employees"] = s["antallAnsatte"]
        out.append(fact("establishment", value, src,
                        f"underenhet {s.get('organisasjonsnummer')} overordnetEnhet: {org}",
                        f"Sub-unit registered in Enhetsregisteret with parent organisation number {org}", retrieved_at,
                        s.get("registreringsdatoEnhetsregisteret")))
    if out:
        out.append(fact("establishment_count", total, src, f"page.totalElements: {total}",
                        f"Number of sub-units the register lists under organisation number {org}", retrieved_at))
    return out
