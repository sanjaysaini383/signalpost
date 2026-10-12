"""Company website facts. A site is only used if it is declared in the register for the org number
AND the page itself ties back to the company (org number, or the company name on the page)."""
import json
import os
import re
import urllib.robotparser
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from .brreg import fact
from .budget import BudgetExceeded

MAX_PAGE_CHARS = 400_000
CONTACT_HINTS = re.compile(r"kontakt|contact|om-oss|om_oss|omoss|about|om-|tjenest|service|produkt|product", re.I)
SOCIAL = {
    "linkedin": re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/company/[\w\-%.]+", re.I),
    "facebook": re.compile(r"https?://(?:www\.)?facebook\.com/(?!sharer|share|plugins|tr\b)[\w\-.]+", re.I),
    "instagram": re.compile(r"https?://(?:www\.)?instagram\.com/[\w\-.]+", re.I),
    "x": re.compile(r"https?://(?:www\.)?(?:twitter|x)\.com/(?!share|intent)[\w\-]+", re.I),
    "youtube": re.compile(r"https?://(?:www\.)?youtube\.com/(?:c/|channel/|@|user/)[\w\-%.]+", re.I),
}
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
LEGAL_SUFFIX = re.compile(r"\b(as|asa|ans|da|enk|nuf|sa|ba|ks|fli|sti|se|v/.*)\b", re.I)


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.meta, self.links, self._text, self._skip, self._in_title = "", {}, [], [], 0, False
        self.ldjson, self._ld = [], False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and "ld+json" in (a.get("type") or "").lower():
            self._ld = True
            self.ldjson.append("")
        if tag in ("script", "style", "noscript", "svg"):
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            k = (a.get("name") or a.get("property") or "").lower()
            if k and a.get("content"):
                self.meta[k] = a["content"].strip()
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"].strip())

    def handle_endtag(self, tag):
        if tag == "script":
            self._ld = False
        if tag in ("script", "style", "noscript", "svg") and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._ld and self.ldjson:
            self.ldjson[-1] += data
        if self._in_title:
            self.title += data
        elif not self._skip and data.strip():
            self._text.append(data.strip())

    @property
    def text(self):
        return re.sub(r"\s+", " ", " ".join(self._text))


def parse_page(html):
    p = _Page()
    try:
        p.feed(html[:MAX_PAGE_CHARS])
    except Exception:
        pass
    p.title = re.sub(r"\s+", " ", p.title).strip()
    return p


def normalize_url(raw):
    raw = (raw or "").strip().split()[0] if (raw or "").strip() else ""
    if not raw or "@" in raw:
        return None
    if not re.match(r"https?://", raw, re.I):
        raw = "https://" + raw
    u = urlparse(raw)
    if not u.netloc or "." not in u.netloc:
        return None
    return f"{u.scheme}://{u.netloc}{u.path or '/'}"


def _name_core(name):
    n = re.sub(r"[^\wæøåÆØÅ ]", " ", name or "")
    n = LEGAL_SUFFIX.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip().lower()


def _org_pattern(org):
    return re.compile(rf"(?<!\d){org[:3]}[\s.]?{org[3:6]}[\s.]?{org[6:]}(?!\d)")


def ties_to_company(org, name, texts, postcode=None, phones=(), strong_only=False, domain=None):
    """Return an evidence string if the pages tie to THIS company, else None.

    Strong: the organisation number appears on the page. Weaker (only for sites the register itself declares):
    the company name together with the registered postal code or telephone number. A name alone is never enough."""
    blob = " ".join(texts)
    if _org_pattern(org).search(blob):
        return f"page text contains organisation number {org}"
    if strong_only:
        return None
    core = _name_core(name)
    flat = re.sub(r"\s+", " ", blob.lower())
    if len(core) < 4 or core not in flat:
        return None
    if postcode and re.search(rf"(?<!\d){postcode}(?!\d)", blob):
        return f"page text contains company name '{core}' and the registered postal code {postcode}"
    if domain and _domain_matches_name(domain, core):
        return f"the registered website domain '{domain}' matches the company name '{core}' and the page shows the name"
    digits = re.sub(r"\D", "", blob)
    for ph in phones:
        d = re.sub(r"\D", "", ph or "")[-8:]
        if len(d) == 8 and d in digits:
            return f"page text contains company name '{core}' and the registered telephone number {ph}"
    return None


def _domain_matches_name(domain, core):
    label = re.sub(r"[^a-z0-9]", "", domain.lower().removeprefix("www.").split(".")[0].translate(_ASCII))
    joined = re.sub(r"[^a-z0-9]", "", core.translate(_ASCII))
    if len(label) < 6 or len(joined) < 6:
        return False
    if label == joined:
        return True
    short, long_ = sorted((label, joined), key=len)
    return short in long_ and len(short) / len(long_) >= 0.7


_ASCII = str.maketrans({"æ": "ae", "ø": "o", "å": "a", "ä": "a", "ö": "o", "ü": "u", "é": "e"})
DISCOVERY_FORMS = {"AS", "ASA", "ANS", "DA", "SA", "BA", "KS", "SE", "IKS", "NUF"}


def candidate_domains(name, limit=3):
    """Plausible domains for a company, derived from its registered name. They are only guesses and must be
    confirmed by the organisation number on the page before anything is published."""
    folded = re.sub(r"[^a-z0-9 ]", "", _name_core(name).translate(_ASCII))
    tokens = folded.split()
    joined = "".join(tokens)
    if len(joined) < 5 or len(tokens) > 5:
        return []
    out = [f"{joined}.no", f"{joined}.com"]
    if len(tokens) > 1:
        out.append("-".join(tokens) + ".no")
    return list(dict.fromkeys(out))[:limit]


def discover_site(fetcher, org, unit):
    """Try name-derived domains; accept one only if its home page shows this organisation number."""
    if (unit.get("organisasjonsform") or {}).get("kode") not in DISCOVERY_FORMS:
        return None
    for host in candidate_domains(unit.get("navn", "")):
        url = f"https://{host}/"
        try:
            status, html = fetcher.get(url, accept="text/html", retries=1, timeout=8)
        except BudgetExceeded:
            raise
        except Exception:
            continue
        if status == 200 and "<" in html:
            p = parse_page(html)
            if ties_to_company(org, unit.get("navn", ""), [p.title + " " + p.text], strong_only=True):
                return url
    return None


def parse_jsonld(blocks):
    """Flatten schema.org objects found in application/ld+json blocks."""
    objs = []

    def walk(x):
        if isinstance(x, list):
            for i in x:
                walk(i)
        elif isinstance(x, dict):
            objs.append(x)
            for k in ("@graph", "mainEntity", "publisher", "provider"):
                if k in x:
                    walk(x[k])
    for b in blocks:
        try:
            walk(json.loads(b))
        except ValueError:
            continue
    return objs


_ORG_TYPES = re.compile(r"organi[sz]ation|business|corporation|company|store|restaurant|service", re.I)


def _allowed(fetcher, base, url):
    host = urlparse(base)
    status, text = fetcher.get(f"{host.scheme}://{host.netloc}/robots.txt", accept="text/plain")
    if status != 200:
        return True
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(text.splitlines())
    return rp.can_fetch(fetcher.client.headers.get("User-Agent", "*"), url)


def _snippet(text, needle, width=80):
    i = text.find(needle)
    if i < 0:
        return needle
    return text[max(0, i - width): i + len(needle) + width].replace("\n", " ").strip()


def collect_pages(fetcher, site, max_pages=4):
    """Fetch the home page plus up to two contact/about pages. Returns [(url, html)]."""
    if not _allowed(fetcher, site, site):
        return []
    status, html = fetcher.get(site, accept="text/html")
    if status != 200 or "<" not in html:
        return []
    pages = [(site, html)]
    home = parse_page(html)
    seen = {site.rstrip("/")}
    host = urlparse(site).netloc.removeprefix("www.")
    for href in home.links:
        if len(pages) >= max_pages:
            break
        full = urljoin(site, href).split("#")[0]
        u = urlparse(full)
        if u.scheme not in ("http", "https") or u.netloc.removeprefix("www.") != host:
            continue
        if full.rstrip("/") in seen or not CONTACT_HINTS.search(u.path):
            continue
        seen.add(full.rstrip("/"))
        if not _allowed(fetcher, site, full):
            continue
        st, h = fetcher.get(full, accept="text/html")
        if st == 200 and "<" in h:
            pages.append((full, h))
    return pages


def website_facts(fetcher, org, unit, retrieved_at, warnings):
    site = normalize_url(unit.get("hjemmeside"))
    declared = bool(site)
    try:
        if not site:
            site = discover_site(fetcher, org, unit)
        if not site:
            return []
        pages = collect_pages(fetcher, site)
    except BudgetExceeded:
        raise
    except Exception as e:
        warnings.append(f"website fetch failed: {e}")
        return []
    if not pages:
        warnings.append(f"website {site} unreachable or blocked")
        return []
    parsed = [(u, h, parse_page(h)) for u, h in pages]
    texts = [p.title + " " + p.text for _, _, p in parsed]
    addr = unit.get("forretningsadresse") or {}
    tie = ties_to_company(org, unit.get("navn", ""), texts, postcode=addr.get("postnummer"),
                          phones=[unit.get("telefon"), unit.get("mobil")], strong_only=not declared,
                          domain=urlparse(site).netloc if declared else None)
    if not tie:
        warnings.append(f"website {site} discarded: page does not tie to organisation number {org}")
        return []

    origin = ("the website declared in Enhetsregisteret" if declared
              else "a website found by name-based domain lookup (not in the register)")
    why_base = f"Page from {site}, {origin} for organisation number {org}; {tie}"
    out = [fact("website_verified", True, pages[0][0], tie, why_base, retrieved_at)]
    if not declared:
        out.append(fact("website", site, pages[0][0], tie,
                        f"Not listed in the register. Accepted only because the page itself shows organisation number {org}",
                        retrieved_at))
    home_url, _, home = parsed[0]
    desc = home.meta.get("description") or home.meta.get("og:description")
    if desc and len(desc) > 20:
        out.append(fact("website_description", desc, home_url, f"meta description: {desc[:200]}", why_base, retrieved_at))

    site_domain = urlparse(site).netloc.removeprefix("www.").lower()
    emails, phones, socials = {}, {}, {}
    for url, html, p in parsed:
        for href in p.links:
            h = href.strip()
            if h.lower().startswith("mailto:"):
                e = h[7:].split("?")[0].strip().lower()
                if EMAIL.fullmatch(e):
                    emails.setdefault(e, (url, f"mailto:{e}"))
            elif h.lower().startswith("tel:"):
                t = re.sub(r"[^\d+]", "", h[4:])
                if 8 <= len(t) <= 15:
                    phones.setdefault(t, (url, f"tel:{h[4:].strip()}"))
            else:
                for name, rx in SOCIAL.items():
                    m = rx.match(urljoin(url, h))
                    if m and name not in socials:
                        socials[name] = (url, m.group(0))
        for e in EMAIL.findall(p.text):
            e = e.lower().rstrip(".")
            emails.setdefault(e, (url, _snippet(p.text, e)))
    for e, (url, ev) in sorted(emails.items()):
        dom = e.split("@")[1]
        if dom == site_domain or dom.endswith("." + site_domain) or site_domain.endswith("." + dom):
            out.append(fact("website_email", e, url, ev, why_base, retrieved_at))
    for t, (url, ev) in sorted(phones.items())[:3]:
        out.append(fact("website_phone", t, url, ev, why_base, retrieved_at))
    for name, (url, link) in sorted(socials.items()):
        out.append(fact(f"social:{name}", link, url, f"link on page: {link}", why_base, retrieved_at))

    # schema.org data the company publishes about itself (JSON-LD)
    seen = {(f["field"], str(f["value"])) for f in out}
    reg_post = addr.get("postnummer")
    for url, _, p in parsed:
        for o in parse_jsonld(p.ldjson):
            types = o.get("@type")
            types = " ".join(types) if isinstance(types, list) else str(types or "")
            if not _ORG_TYPES.search(types):
                continue
            ev = f"JSON-LD {types}: "
            tel = re.sub(r"[^\d+]", "", str(o.get("telephone") or ""))
            if 8 <= len(tel) <= 15 and ("website_phone", tel) not in seen:
                seen.add(("website_phone", tel))
                out.append(fact("website_phone", tel, url, ev + f"telephone {o.get('telephone')}", why_base, retrieved_at))
            mail = str(o.get("email") or "").replace("mailto:", "").strip().lower()
            if EMAIL.fullmatch(mail) and ("website_email", mail) not in seen and (
                    mail.split("@")[1] == site_domain or mail.split("@")[1].endswith("." + site_domain)):
                seen.add(("website_email", mail))
                out.append(fact("website_email", mail, url, ev + f"email {mail}", why_base, retrieved_at))
            a = o.get("address")
            if isinstance(a, dict) and a.get("streetAddress") and str(a.get("postalCode", "")).strip() == reg_post:
                text = f"{a['streetAddress']}, {a.get('postalCode')} {a.get('addressLocality', '')}".strip()
                if ("website_address", text) not in seen:
                    seen.add(("website_address", text))
                    out.append(fact("website_address", text, url, ev + f"address {text} (postal code equals the register's)",
                                    why_base, retrieved_at))
            same = o.get("sameAs")
            for link in ([same] if isinstance(same, str) else same or []):
                for name, rx in SOCIAL.items():
                    m = rx.match(str(link))
                    if m and (f"social:{name}", m.group(0)) not in seen and not any(f["field"] == f"social:{name}" for f in out):
                        seen.add((f"social:{name}", m.group(0)))
                        out.append(fact(f"social:{name}", m.group(0), url, ev + f"sameAs {m.group(0)}", why_base, retrieved_at))

    if os.environ.get("ANTHROPIC_API_KEY"):
        out += llm_facts(fetcher, parsed, why_base, retrieved_at, warnings)
    return out


# ---------------------------------------------------------------- optional LLM extraction

LLM_MODEL = os.environ.get("SIGNALPOST_MODEL", "claude-haiku-5-5")
PROMPT = (
    "You extract facts about ONE company from its own website text. Return only JSON: "
    '{"business_summary": {"value": str, "quote": str} | null, '
    '"products_services": [{"value": str, "quote": str}], '
    '"locations": [{"value": str, "quote": str}]}. '
    "Each quote MUST be copied verbatim (max 200 chars) from the text and support the value. "
    "Do not infer, do not add anything not in the text, do not include financial figures. "
    "Use null / empty lists when the text does not say."
)


def _norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def verify_llm_items(data, source_texts):
    """Keep only items whose quote literally occurs in a fetched page. Returns [(field, value, quote, url)]."""
    kept = []

    def check(field, item):
        if not isinstance(item, dict) or not item.get("value") or not item.get("quote"):
            return
        q = _norm(str(item["quote"]))
        if len(q) < 12:
            return
        # Any figure the model states must be in its own quote: no invented numbers, least of all money.
        nums = re.findall(r"\d[\d .,]*\d|\d", str(item["value"]))
        if any(re.sub(r"\D", "", n) not in re.sub(r"\D", "", q) for n in nums):
            return
        for url, text in source_texts:
            if q in _norm(text):
                kept.append((field, str(item["value"]).strip(), str(item["quote"]).strip(), url))
                return

    if not isinstance(data, dict):
        return kept
    check("business_summary", data.get("business_summary"))
    for item in (data.get("products_services") or [])[:8]:
        check("product_or_service", item)
    for item in (data.get("locations") or [])[:5]:
        check("location", item)
    return kept


def llm_facts(fetcher, parsed, why_base, retrieved_at, warnings, client=None):
    source_texts = [(u, p.title + " " + p.text) for u, _, p in parsed]
    corpus = "\n\n".join(f"[{u}]\n{t[:4000]}" for u, t in source_texts)[:9000]
    fetcher.count_external()  # an LLM call counts against the outbound-request budget
    try:
        if client is None:
            import anthropic
            client = anthropic.Anthropic(max_retries=1, timeout=60)
        resp = client.messages.create(
            model=LLM_MODEL, max_tokens=2000, system=PROMPT,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": corpus}])
        fetcher.add_llm_usage({"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens})
        text = "".join(b.text for b in resp.content if b.type == "text")
        data = json.loads(text[text.index("{"): text.rindex("}") + 1])
    except BudgetExceeded:
        raise
    except Exception as e:
        warnings.append(f"llm extraction failed: {e}")
        return []
    out = []
    for field, value, quote, url in verify_llm_items(data, source_texts):
        out.append(fact(field, value, url, f"quote: \"{quote}\"", why_base + "; value extracted by model and quote verified verbatim on page", retrieved_at))
    return out
