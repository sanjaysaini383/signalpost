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
CONTACT_HINTS = re.compile(r"kontakt|contact|om-oss|om_oss|omoss|about|om-|about-us", re.I)
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

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
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
        if tag in ("script", "style", "noscript", "svg") and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
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


def ties_to_company(org, name, texts):
    """Return an evidence string if the pages mention the org number or the company's name, else None."""
    blob = " ".join(texts)
    digits = re.sub(r"\s", "", blob)
    if re.search(rf"(?<!\d){org}(?!\d)", digits):
        return f"page text contains organisation number {org}"
    core = _name_core(name)
    if len(core) >= 4 and core in re.sub(r"\s+", " ", blob.lower()):
        return f"page text contains company name '{core}'"
    return None


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


def collect_pages(fetcher, site, max_pages=3):
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
    if not site:
        return []
    try:
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
    tie = ties_to_company(org, unit.get("navn", ""), texts)
    if not tie:
        warnings.append(f"website {site} discarded: page does not mention org number or company name")
        return []

    why_base = f"Page from {site}, the website declared in Enhetsregisteret for organisation number {org}; {tie}"
    out = [fact("website_verified", True, pages[0][0], tie, why_base, retrieved_at)]
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


def llm_facts(fetcher, parsed, why_base, retrieved_at, warnings):
    import anthropic

    source_texts = [(u, p.title + " " + p.text) for u, _, p in parsed]
    corpus = "\n\n".join(f"[{u}]\n{t[:4000]}" for u, t in source_texts)[:9000]
    fetcher.count_external()  # an LLM call counts against the outbound-request budget
    try:
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
