"""Verified geocoding of the registered business address (Kartverket open address API)."""
from urllib.parse import urlencode

from .brreg import fact

SEARCH = "https://ws.geonorge.no/adresser/v1/sok"


def geo_facts(fetcher, org, unit, retrieved_at):
    """Only publish coordinates when the returned address matches the register on street text,
    postal code and municipality number. Anything weaker is dropped."""
    addr = unit.get("forretningsadresse") or unit.get("beliggenhetsadresse") or {}
    lines = addr.get("adresse") or []
    if not lines or not addr.get("postnummer") or addr.get("landkode") not in (None, "NO"):
        return []
    street = lines[0].strip()
    if not any(ch.isdigit() for ch in street):
        return []  # e.g. "Postboks" or a named place without a house number
    params = {"sok": street, "postnummer": addr["postnummer"], "treffPerSide": 5, "utkoordsys": 4258}
    status, data = fetcher.get_json(SEARCH, params)
    if not data:
        return []
    want = " ".join(street.lower().split())
    for hit in data.get("adresser", []):
        text = " ".join((hit.get("adressetekst") or "").lower().split())
        pt = hit.get("representasjonspunkt") or {}
        if (text == want and hit.get("postnummer") == addr["postnummer"]
                and (not addr.get("kommunenummer") or hit.get("kommunenummer") == addr["kommunenummer"])
                and "lat" in pt and "lon" in pt):
            src = f"{SEARCH}?{urlencode(params)}"
            return [fact("geo_location", {"lat": pt["lat"], "lon": pt["lon"], "crs": pt.get("epsg", "EPSG:4258")}, src,
                         f"address '{hit['adressetekst']}', {hit['postnummer']} {hit.get('poststed')}, "
                         f"municipality {hit.get('kommunenummer')} matches the register address",
                         f"Coordinates of the business address registered for organisation number {org}, "
                         f"accepted because street, postal code and municipality number equal the register values",
                         retrieved_at)]
    return []
