"""Build a company profile from permitted public sources and diff it against the previous run."""
import json
from pathlib import Path

from . import brreg, orgno
from .budget import BudgetExceeded


def build_profile(fetcher, org, include_website=None):
    org = orgno.normalize(org)
    retrieved_at = brreg.now_iso()
    profile = {"organization_number": org, "generated_at": retrieved_at, "status": None, "facts": [], "warnings": []}
    if not orgno.is_valid(org):
        profile["status"] = "invalid_org_number"
        return profile

    state, unit = brreg.fetch_unit(fetcher, org)
    if state != "found":
        profile["status"] = state  # deleted | not_found
        return profile
    profile["status"] = "active"
    facts = brreg.unit_facts(org, unit, retrieved_at)
    # Secondary sources may fail (e.g. HTTP 500). Skip them with a warning; never guess the missing facts.
    for label, fetch, convert in (
            ("roles", brreg.fetch_roles, brreg.role_facts),
            ("accounts", brreg.fetch_accounts, brreg.account_facts),
            ("sub-units", brreg.fetch_subunits, brreg.subunit_facts)):
        try:
            facts += convert(org, fetch(fetcher, org), retrieved_at)
        except BudgetExceeded:
            raise
        except Exception as e:
            profile["warnings"].append(f"{label} unavailable: {e}")
    if include_website:
        facts += include_website(fetcher, org, unit, retrieved_at, profile["warnings"])
    profile["name"] = unit.get("navn")
    profile["facts"] = facts
    return profile


_MULTI = ("website_email", "website_phone", "product_or_service", "location")


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


def apply_history(profile, previous):
    """Carry first_seen forward and record what changed since the previous run."""
    now = profile["generated_at"]
    prev = {_key(f): f for f in (previous or {}).get("facts", [])}
    for f in profile["facts"]:
        p = prev.get(_key(f))
        f["first_seen"] = p.get("first_seen", p["retrieved_at"]) if p and _canon(p["value"]) == _canon(f["value"]) else now
    profile["previous_run"] = previous.get("generated_at") if previous else None
    profile["changes_since_previous_run"] = diff_profiles(previous, profile) if previous else []
    return profile


def load_previous(out_dir, org):
    p = Path(out_dir) / "profiles" / f"{org}.json"
    if p.exists():
        try:
            return json.loads(p.read_text("utf-8"))
        except ValueError:
            return None
    return None


def save_profile(out_dir, profile):
    d = Path(out_dir) / "profiles"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{profile['organization_number']}.json").write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), "utf-8")
