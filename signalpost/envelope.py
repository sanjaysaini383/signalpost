"""Turn an internal profile into the Signalpost terminal envelope (one per input organisation number).

Contract: claims with availability states and evidence ids, evidence with source, retrieval time, content hash and
claim span, source snapshots, refresh metadata (changes against an explicit previous snapshot) and errors."""
import hashlib
import json

from .website import normalize_url

ENVELOPE_SCHEMA = "signalpost-envelope/1"
STATES = ("available", "not_available", "blocked", "not_applicable", "ambiguous", "failed")

# Required envelope sections, in the brief's order, with the claim field used for an explicit absence.
SECTIONS = {
    "legal_identity": "legal_name",
    "annual_accounts": "annual_accounts",
    "leadership": "role",
    "registered_workplaces": "registered_workplace",
    "official_website": "official_website",
    "company_profiles": "company_profile",
    "hiring": "job_posting",
    "public_activity": "news_item",
}

_IDENTITY = {
    "name": "legal_name", "organization_form": "legal_form", "founded": "founded", "registered_date": "registered_date",
    "business_register_registered_date": "business_register_registered_date", "vat_registered_date": "vat_registered_date",
    "articles_date": "articles_date", "deleted_date": "deleted_date", "bankrupt": "bankrupt",
    "under_liquidation": "under_liquidation", "under_forced_dissolution": "under_forced_dissolution",
    "bankruptcy_date": "bankruptcy_date", "liquidation_date": "liquidation_date",
    "forced_dissolution_date": "forced_dissolution_date", "business_address": "registered_address",
    "postal_address": "postal_address", "municipality": "municipality", "industry_code": "industry",
    "industry_code_2": "industry_secondary", "industry_code_3": "industry_secondary", "institutional_sector": "institutional_sector",
    "former_names": "former_names", "language_form": "language_form", "parent_organization_number": "parent_organisation",
    "part_of_group": "part_of_group", "vat_registered": "vat_registered", "registered_in_business_register": "registered_in_business_register",
    "registered_in_foundation_register": "registered_in_foundation_register",
    "registered_in_voluntary_register": "registered_in_voluntary_register", "registered_in_party_register": "registered_in_party_register",
    "voluntary_vat_activities": "voluntary_vat_activities", "register_notes": "register_notes", "share_capital": "share_capital",
    "activity_description": "registered_activity", "purpose": "statutory_purpose", "public_brand": "public_brand",
    "website_description": "company_site_description", "geo_location": "geo_location", "started": "started",
    "phone": "phone", "mobile": "mobile", "email": "email", "website_email": "email", "website_phone": "phone",
    "website_address": "company_site_address", "business_summary": "business_summary",
    "product_or_service": "product_or_service", "location": "operating_location",
}
_MATERIAL = {"legal_name", "legal_form", "organisation_status", "bankrupt", "under_liquidation", "under_forced_dissolution",
             "deleted_date", "registered_address", "industry", "registered_employees", "official_website", "role",
             "revenue", "net_profit", "equity", "total_assets", "operating_profit", "parent_organisation", "share_capital"}

_SOURCE_CLASS = (
    ("/regnskapsregisteret/", "official_annual_accounts"),
    ("/roller", "official_roles"),
    ("/underenheter", "official_subunits"),
    ("data.brreg.no/enhetsregisteret", "official_registry"),
    ("ws.geonorge.no", "official_address_register"),
)


def _h(*parts, n=16):
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:n]


def _canon(v):
    return json.dumps(v, sort_keys=True, ensure_ascii=False)


def classify(f):
    """(contract field, section, extra claim attributes) for an internal fact."""
    field = f["field"]
    if field.startswith("financials:") or field.startswith("financials_history:"):
        parts = field.split(":")
        extra = {"scope": "group" if parts[1] == "konsern" else "company"}
        return parts[2], "annual_accounts", extra
    if field.startswith("accounts_info:"):
        return "accounts_filing", "annual_accounts", {"scope": "group" if field.endswith("konsern") else "company"}
    if field == "last_annual_accounts_year":
        return "last_annual_accounts_year", "annual_accounts", {}
    if field.startswith("role:"):
        return "role", "leadership", {"role_code": field.split(":", 1)[1]}
    if field == "establishment":
        return "registered_workplace", "registered_workplaces", {}
    if field == "establishment_count":
        return "registered_workplace_count", "registered_workplaces", {}
    if field == "employees":
        return "registered_employees", "legal_identity", {}
    if field == "website":
        return "registered_website", "official_website", {}
    if field == "website_verified":
        return None, "official_website", {}
    if field.startswith("social:"):
        return "company_profile", "company_profiles", {"platform": field.split(":", 1)[1]}
    if field in ("job_posting", "hiring_channel", "careers_page"):
        return field, "hiring", {}
    if field == "news_item":
        return "news_item", "public_activity", {}
    return _IDENTITY.get(field, field), "legal_identity", {}


def _source_class(f):
    if f.get("source_class"):
        return f["source_class"]
    url = f.get("source_url", "")
    for needle, cls in _SOURCE_CLASS:
        if needle in url:
            return cls
    return "other"


def _selector(f):
    """JSON pointer into the registry/API document for register facts (their evidence is 'key: value')."""
    ev = f.get("evidence") or ""
    key = ev.split(":", 1)[0].strip()
    if key and " " not in key and "." not in key:
        return f"/{key}"
    if key and " " not in key:
        return "/" + key.replace(".", "/")
    return None


def _snapshot_for(url, snapshots):
    if url in snapshots:
        return snapshots[url]
    base = url.split("?")[0]
    for k, v in snapshots.items():
        if k.split("?")[0] == base:
            return v
    return {}


def _confidence(f, cls):
    if cls.startswith("official"):
        return 0.99
    if "organisation number" in (f.get("explanation") or ""):
        return 0.95
    return 0.85


def build_envelope(profile, *, run_id, started_at, completed_at, snapshots, requests, runtime_ms,
                   cost_usd=0.0, previous=None, state="complete", errors=None):
    org = profile["organization_number"]
    evidence, ev_index, claims = [], {}, []

    def evidence_id(f):
        cls = _source_class(f)
        snap = _snapshot_for(f.get("source_url", ""), snapshots)
        span = f.get("span") or f.get("evidence")
        key = (f.get("source_url"), span)
        if key in ev_index:
            return ev_index[key]
        eid = "ev-" + _h(org, f.get("source_url", ""), str(span), n=12)
        item = {"id": eid, "source_url": f.get("source_url"), "final_url": snap.get("final_url", f.get("source_url")),
                "source_class": cls, "retrieved_at": snap.get("retrieved_at", f.get("retrieved_at")),
                "content_sha256": snap.get("content_sha256") or f.get("content_sha256"), "http_status": snap.get("status"),
                "claim_span": span, "extraction_method": f.get("method") or ("registry_json" if cls.startswith("official") else "html")}
        sel = _selector(f) if cls.startswith("official") and not f.get("span") else None
        if sel:
            item["selector"] = sel
        if f.get("stale"):
            item["stale"] = True
        evidence.append(item)
        ev_index[key] = eid
        return eid

    tie_ids = [evidence_id(f) for f in profile["facts"] if f["field"] == "website_verified"]
    for f in profile["facts"]:
        field, section, extra = classify(f)
        if field is None:
            continue
        cls = _source_class(f)
        eids = [evidence_id(f)]
        claim = {"id": "cl-" + _h(org, field, _canon(f["value"])), "field": field, "value": f["value"],
                 "availability": "available", "confidence": _confidence(f, cls), "evidence_ids": eids,
                 "section": section, "source_class": cls, "explanation": f.get("explanation"),
                 "observed_at": f.get("retrieved_at"), "first_observed": f.get("first_seen", f.get("retrieved_at"))}
        claim.update(extra)
        if f.get("as_of"):
            claim["reporting_period" if section == "annual_accounts" else "effective_date"] = f["as_of"]
        if f.get("stale"):
            claim["stale"] = True
            claim["confidence"] = round(claim["confidence"] * 0.9, 2)
        claims.append(claim)
        # The registered website becomes the official website only once its pages tie to this entity.
        if field == "registered_website" and tie_ids:
            url = normalize_url(f["value"]) or f["value"]
            off = dict(claim, id="cl-" + _h(org, "official_website", _canon(url)), field="official_website", value=url,
                       evidence_ids=eids + tie_ids, confidence=0.95,
                       explanation=(f.get("explanation") or "") + "; verified: " +
                       next((x["evidence"] for x in profile["facts"] if x["field"] == "website_verified"), ""))
            claims.append(off)

    status = profile.get("status")
    name_fact = next((f for f in profile["facts"] if f["field"] == "name"), None)
    if name_fact and status:
        claims.append({"id": "cl-" + _h(org, "organisation_status", status), "field": "organisation_status",
                       "value": status, "availability": "available", "confidence": 0.99,
                       "evidence_ids": [evidence_id(name_fact)], "section": "legal_identity",
                       "source_class": "official_registry", "observed_at": name_fact.get("retrieved_at"),
                       "explanation": f"Register record for {org}: deleted date, bankruptcy and dissolution flags read from it"})

    checks = profile.get("checks") or {}
    failed = set(profile.get("failed_sources") or [])
    sections = {}
    for section, absent_field in SECTIONS.items():
        if section == "official_website":
            n = sum(1 for c in claims if c["field"] == "official_website")
        else:
            n = sum(1 for c in claims if c["section"] == section and c["availability"] == "available")
        if n:
            sections[section] = {"availability": "available", "claims": n}
            continue
        if state in ("source_error", "budget_exhausted"):
            sections[section] = {"availability": "failed", "note": f"run state {state}"}
        elif status in ("deleted", "invalid_org_number", "not_found", "mismatch") and section != "legal_identity":
            sections[section] = {"availability": "not_applicable", "note": f"entity status is {status}"}
        elif section in checks:
            sections[section] = dict(checks[section])
        elif {"annual_accounts": "accounts", "leadership": "roles", "registered_workplaces": "sub-units"}.get(section) in failed:
            sections[section] = {"availability": "failed", "note": "source unavailable during this run"}
        elif status == "sub_unit" and section in ("annual_accounts", "leadership", "registered_workplaces"):
            sections[section] = {"availability": "not_applicable", "note": "a sub-unit files no accounts or roles of its own"}
        else:
            notes = {"annual_accounts": "no annual accounts in Regnskapsregisteret for this organisation number",
                     "leadership": "no active roles registered",
                     "registered_workplaces": "no registered sub-units",
                     "legal_identity": "no register record for this organisation number"}
            sections[section] = {"availability": "not_available", "note": notes.get(section, "not found")}
        if section == "official_website" and any(c["field"] == "registered_website" for c in claims)                 and sections[section]["availability"] == "not_available":
            sections[section] = {"availability": "ambiguous", "note": "a website is registered but could not be verified"}
        # Explicit, evidence-free absence claim: never a zero, never a silent gap.
        claims.append({"id": "cl-" + _h(org, absent_field, "absent", section), "field": absent_field, "value": None,
                       "availability": sections[section]["availability"], "section": section,
                       "evidence_ids": [], "note": sections[section].get("note")})

    def pick(field):
        return next((c["value"] for c in claims if c["field"] == field and c["availability"] == "available"), None)

    identity = {"organisation_number": org, "legal_name": pick("legal_name"), "legal_form": pick("legal_form"),
                "status": status, "registered_address": pick("registered_address"), "municipality": pick("municipality"),
                "industry": pick("industry"), "public_brand": pick("public_brand"),
                "official_website": pick("official_website")}

    changes = build_changes(org, claims, evidence, previous, completed_at) if previous else []
    unknowns = list(profile.get("coverage_notes", []))
    text = profile.get("summary") or ""
    if previous:
        material = [c for c in changes if c["materiality"] == "material"]
        when = ((previous.get("run") or {}).get("completed_at") or "")[:10]
        if material:
            what = ", ".join(sorted({f"{c['field'].replace('_', ' ')} {c['change_type']}" for c in material})[:6])
            text += f" Since the previous run ({when}): {what}."
        else:
            text += f" No material change since the previous run ({when})."
    missing = [s.replace("_", " ") for s, v in sections.items() if v["availability"] != "available"]
    if missing and text:
        text += " Not found or not verifiable: " + ", ".join(missing) + "."
    snaps = sorted(({"url": k, **v} for k, v in snapshots.items() if "?" in k or not any(
        kk.split("?")[0] == k and kk != k for kk in snapshots)), key=lambda s: s["url"])
    return {
        "schema": ENVELOPE_SCHEMA,
        "organisation_number": org,
        "state": state,
        "run": {"run_id": run_id, "started_at": started_at, "completed_at": completed_at,
                "terminal_status": "completed" if state in ("complete", "not_found") else "failed"},
        "legal_identity": identity,
        "sections": sections,
        "summary": {"text": text or None, "unknowns": unknowns,
                    "identity_check": profile.get("identity_check", [])},
        "claims": claims,
        "evidence": evidence,
        "source_snapshots": snaps,
        "changes": changes,
        "refresh": {"previous_run_id": (previous or {}).get("run", {}).get("run_id"),
                    "previous_completed_at": (previous or {}).get("run", {}).get("completed_at"),
                    "material_changes": sum(1 for c in changes if c["materiality"] == "material"),
                    "stale_claims": sum(1 for c in claims if c.get("stale"))},
        "errors": list(errors or []) + [{"type": "warning", "message": w} for w in profile.get("warnings", [])],
        "operations": {"requests": requests, "runtime_ms": runtime_ms, "third_party_cost_usd": round(cost_usd, 6)},
        "profile": profile,
    }


def _claim_key(c):
    v = c.get("value")
    if c["field"] == "role" and isinstance(v, dict):
        return f"role|{c.get('role_code')}|{v.get('name')}"
    if c["field"] == "registered_workplace" and isinstance(v, dict):
        return f"registered_workplace|{v.get('organization_number')}"
    if c["field"] in ("company_profile",):
        return f"company_profile|{c.get('platform')}"
    if c["field"] in ("job_posting", "news_item", "hiring_channel", "email", "phone", "industry_secondary",
                      "product_or_service", "operating_location", "company_site_address"):
        return f"{c['field']}|{_canon(v)}"
    if c["section"] == "annual_accounts":
        return f"{c['field']}|{c.get('scope')}|{c.get('reporting_period')}"
    return c["field"]


def build_changes(org, claims, evidence, previous, detected_at):
    """Material and minor changes against the previous envelope, with the evidence for both sides."""
    prev_claims = [c for c in previous.get("claims", []) if c.get("availability") == "available"]
    cur_claims = [c for c in claims if c.get("availability") == "available"]
    prev_ev = {e["id"]: e for e in previous.get("evidence", [])}
    cur_ev = {e["id"]: e for e in evidence}
    old = {_claim_key(c): c for c in prev_claims}
    new = {_claim_key(c): c for c in cur_claims}
    out = []

    def ev(ids, pool):
        return [{k: pool[i].get(k) for k in ("source_url", "retrieved_at", "content_sha256", "claim_span")}
                for i in ids or [] if i in pool]

    def change(kind, key, o, n):
        field = (n or o)["field"]
        out.append({"id": "chg-" + _h(org, key, kind, _canon((o or {}).get("value")), _canon((n or {}).get("value"))),
                    "claim_key": key, "field": field, "change_type": kind,
                    "materiality": "material" if field in _MATERIAL else "minor",
                    "previous_value": (o or {}).get("value"), "current_value": (n or {}).get("value"),
                    "previous_evidence": ev((o or {}).get("evidence_ids"), prev_ev),
                    "current_evidence": ev((n or {}).get("evidence_ids"), cur_ev),
                    "previous_observed_at": (o or {}).get("observed_at"), "detected_at": detected_at})

    for k, c in new.items():
        if k not in old:
            change("added", k, None, c)
        elif _canon(old[k]["value"]) != _canon(c["value"]):
            change("changed", k, old[k], c)
    for k, c in old.items():
        if k not in new:
            change("removed", k, c, None)
    return sorted(out, key=lambda x: (x["materiality"] != "material", x["claim_key"]))
