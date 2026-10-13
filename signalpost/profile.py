"""Build a company profile from permitted public sources and diff it against the previous run."""
import json

from . import brreg, orgno
from .budget import BudgetExceeded
from .geo import geo_facts
from .summary import build_summary, coverage_notes, identity_check

SCHEMA_VERSION = 2
_STATUS = {"found": "active", "deleted": "deleted", "sub_unit": "sub_unit"}


def build_profile(fetcher, org, include_website=None):
    org = orgno.normalize(org)
    retrieved_at = brreg.now_iso()
    profile = {"schema_version": SCHEMA_VERSION, "organization_number": org, "generated_at": retrieved_at,
               "status": None, "facts": [], "warnings": [], "checks": {}}
    if not orgno.is_valid(org):
        profile["status"] = "invalid_org_number"
        return profile

    state, unit = brreg.fetch_unit(fetcher, org)
    if state == "not_found":
        profile["status"] = "not_found"
        return profile
    if (unit or {}).get("organisasjonsnummer") not in (None, org):
        # Never publish a record the register did not return for exactly this number.
        profile["status"] = "mismatch"
        profile["warnings"].append("register returned a different organisation number; nothing published")
        return profile
    profile["status"] = _STATUS[state]
    facts = brreg.unit_facts(org, unit, retrieved_at, sub_unit=(state == "sub_unit"))

    def optional(label, produce):
        # Secondary sources may fail (e.g. HTTP 500). Skip them with a warning; never guess the missing facts.
        try:
            return produce()
        except BudgetExceeded:
            raise
        except Exception as e:
            profile["warnings"].append(f"{label} unavailable: {e}")
            profile.setdefault("failed_sources", []).append(label)
            return []

    if state == "found":
        facts += optional("roles", lambda: brreg.role_facts(org, brreg.fetch_roles(fetcher, org), retrieved_at))
        facts += optional("accounts", lambda: brreg.account_facts(org, brreg.fetch_accounts(fetcher, org), retrieved_at))
        facts += optional("sub-units", lambda: brreg.subunit_facts(org, brreg.fetch_subunits(fetcher, org), retrieved_at))
    if state in ("found", "sub_unit"):
        facts += optional("geocoding", lambda: geo_facts(fetcher, org, unit, retrieved_at))
    if state == "found" and include_website:
        facts += optional("website", lambda: include_website(fetcher, org, unit, retrieved_at, profile["warnings"],
                                                                     checks=profile["checks"]))
    profile["name"] = unit.get("navn")
    profile["facts"] = facts
    profile["sources_used"] = sorted({f["source_url"].split("/")[2] for f in facts if "://" in f["source_url"]})
    profile["summary"] = build_summary(profile)
    profile["identity_check"] = identity_check(profile, org)
    profile["coverage_notes"] = coverage_notes(profile)
    return profile


_MULTI = ("website_email", "website_phone", "website_address", "product_or_service", "location")


def _key(f):
    """Identity of a fact across runs. Multi-valued fields are keyed by their member, so a changed
    member shows up as removed + added, and single-valued fields as 'changed'."""
    field = f["field"]
    if field.startswith("role:"):
        return field + "|" + f["value"]["name"]
    if field == "establishment":
        return field + "|" + str(f["value"].get("organization_number"))
    if field in _MULTI:
        return field + "|" + str(f["value"])
    return field


def _canon(v):
    return json.dumps(v, sort_keys=True, ensure_ascii=False)


def diff_profiles(old, new):
    """Return a list of changes between two profiles' facts (ignores retrieval timestamps)."""
    old_f = {_key(f): f for f in old.get("facts", [])}
    new_f = {_key(f): f for f in new.get("facts", [])}
    changes = []
    for k, f in new_f.items():
        if k not in old_f:
            changes.append({"field": f["field"], "change": "added", "new": f["value"]})
        elif _canon(old_f[k]["value"]) != _canon(f["value"]):
            changes.append({"field": f["field"], "change": "changed", "old": old_f[k]["value"], "new": f["value"],
                            "source_url": f["source_url"]})
    for k, f in old_f.items():
        if k not in new_f:
            changes.append({"field": f["field"], "change": "removed", "old": f["value"]})
    if old.get("status") != new.get("status"):
        changes.append({"field": "status", "change": "changed", "old": old.get("status"), "new": new.get("status")})
    return changes


_SOURCE_FIELDS = {
    "roles": ("role:",),
    "accounts": ("financials", "accounts_info"),
    "sub-units": ("establishment",),
    "geocoding": ("geo_location",),
    "website": ("website_", "social:", "product_or_service", "location", "business_summary"),
}


def apply_history(profile, previous):
    """Carry first_seen forward and record what changed since the previous run.

    If a source failed this run, its earlier facts are kept and flagged stale (with their original retrieval
    time) instead of being dropped, so a temporary outage is not reported as 'the company lost these facts'."""
    now = profile["generated_at"]
    have = {_key(f) for f in profile["facts"]}
    for label in profile.get("failed_sources", []):
        for f in (previous or {}).get("facts", []):
            if f["field"].startswith(_SOURCE_FIELDS.get(label, ())) and _key(f) not in have:
                profile["facts"].append({**f, "stale": True})
    prev = {_key(f): f for f in (previous or {}).get("facts", [])}
    for f in profile["facts"]:
        p = prev.get(_key(f))
        f["first_seen"] = p.get("first_seen", p["retrieved_at"]) if p and _canon(p["value"]) == _canon(f["value"]) else now
    profile["previous_run"] = previous.get("generated_at") if previous else None
    profile["changes_since_previous_run"] = diff_profiles(previous, profile) if previous else []
    return profile
