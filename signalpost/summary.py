"""Plain-language explanation of a profile, built only from the facts already in it (no model, no new data)."""
from urllib.parse import urlparse


def _first(facts, field):
    return next((f for f in facts if f["field"] == field), None)


def _money(v):
    if not isinstance(v, dict) or "amount" not in v:
        return None
    a = float(v["amount"])
    for div, suffix in ((1e9, " billion"), (1e6, " million"), (1e3, " thousand")):
        if abs(a) >= div:
            return f"{a / div:,.1f}{suffix} {v.get('currency') or ''}".strip()
    return f"{a:,.0f} {v.get('currency') or ''}".strip()


def build_summary(profile):
    facts = profile["facts"]
    val = lambda field: (_first(facts, field) or {}).get("value")
    name = profile.get("name") or profile["organization_number"]
    status = profile["status"]
    if status == "deleted":
        return (f"{name} (org no. {profile['organization_number']}) was deleted from the register"
                f"{' on ' + val('deleted_date') if val('deleted_date') else ''}. Only the facts the register still holds are listed.")
    parts = []
    form = val("organization_form")
    lead = f"{name} is {'an' if form and form[0] in 'AEIOU' else 'a'} {form}" if form else f"{name} is a registered unit"
    if status == "sub_unit":
        lead = f"{name} is a sub-unit (establishment) of organisation {val('parent_organization_number')}"
    if val("registered_date"):
        lead += f" registered in {val('registered_date')[:4]}"
    if val("municipality"):
        lead += f", based in {val('municipality').split(' (')[0].title()}"
    parts.append(lead + ".")
    flags = [t for k, t in (("bankrupt", "bankrupt"), ("under_liquidation", "in liquidation"),
                            ("under_forced_dissolution", "under forced dissolution")) if val(k) is True]
    if flags:
        parts.append("The register marks it as " + " and ".join(flags) + ".")
    if val("industry_code"):
        parts.append(f"Main industry: {val('industry_code')}.")
    if val("employees") is not None:
        parts.append(f"It has {val('employees'):,} registered employees.")
    for kind in ("selskap", "konsern"):
        rev, np_, info = val(f"financials:{kind}:revenue"), val(f"financials:{kind}:net_profit"), val(f"accounts_info:{kind}")
        if rev or np_:
            end = (info or {}).get("period_end") or ""
            bits = [f"revenue {_money(rev)}" if rev else None, f"net profit {_money(np_)}" if np_ else None]
            parts.append(f"Latest {kind} accounts (period ending {end}): " + ", ".join(b for b in bits if b) + ".")
            break
    ceo = val("role:DAGL")
    chair = val("role:LEDE")
    people = [f"{v['name']} ({v['role'].lower()})" for v in (ceo, chair) if isinstance(v, dict)]
    if people:
        parts.append("Key people: " + ", ".join(people) + ".")
    if val("establishment_count"):
        parts.append(f"It operates {val('establishment_count')} registered establishment(s).")
    site = val("website")
    if site:
        parts.append(f"Website: {urlparse(site if '://' in site else 'https://' + site).netloc or site}.")
    return " ".join(parts)


def identity_check(profile, unit_org, tie=None):
    facts = profile["facts"]
    out = ["Organisation number passed the 9-digit mod-11 check.",
           f"The register returned a record whose organisation number equals the requested {profile['organization_number']}."]
    if any(f["field"] == "establishment" for f in facts):
        out.append("Sub-units are listed only when the register names this organisation number as their parent.")
    if any(f["field"].startswith("role:") for f in facts):
        out.append("People and roles come from this organisation number's own role record.")
    ver = _first(facts, "website_verified")
    if ver:
        out.append(f"Website content was used because: {ver['evidence']}.")
    if _first(facts, "geo_location"):
        out.append("Coordinates were kept only because the street, postal code and municipality match the register.")
    return out


def coverage_notes(profile):
    facts = profile["facts"]
    have = lambda field: any(f["field"] == field or f["field"].startswith(field) for f in facts)
    notes = []
    if profile["status"] in ("found", "active") or profile["status"] == "sub_unit":
        if not have("website"):
            notes.append("No website: none is registered, and no name-based domain showed this organisation number.")
        if not have("financials:"):
            notes.append("No annual accounts found in Regnskapsregisteret for this organisation number.")
        if not have("employees"):
            notes.append("Employee count is not registered.")
        if not have("role:"):
            notes.append("No active roles are registered.")
        if not have("email") and not have("website_email"):
            notes.append("No e-mail address found in the register or on a verified website.")
        if not have("geo_location"):
            notes.append("No coordinates: the registered address has no verifiable street address.")
    return notes
