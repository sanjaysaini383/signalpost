"""Company website facts: official website, company-owned profiles, contact data, hiring and dated activity.

A site is only used when the page ties back to the exact legal entity (see `tie_evidence`). Every fetch goes
through the public-URL policy, respects robots.txt and runs inside a per-company time allowance."""
import json
import os
import re
import time
import urllib.robotparser
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from .brreg import fact
from .budget import BudgetExceeded, UnresolvableHost, UnsafeURL

MAX_PAGE_CHARS = 400_000
SITE_SECONDS = 40  # wall-clock allowance for everything we do on one company's website
SITE_TIMEOUT = 10  # per request
MAX_FEED_ITEMS = 10
CONTACT_HINTS = re.compile(r"kontakt|contact|om-oss|om_oss|omoss|about|om-|tjenest|service|produkt|product", re.I)
CAREER_HINTS = re.compile(r"karriere|career|jobb|jobs\b|/jobs|ledige|stilling|vacanc|join-us|bli-med|rekrutter", re.I)
NEWS_HINTS = re.compile(r"nyhet|news|aktuelt|blogg|blog|presse|artikler|articles", re.I)
SOCIAL = {
    "linkedin": re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/(?:company|school|showcase)/[\w\-%.]+", re.I),
    "facebook": re.compile(r"https?://(?:www\.|m\.|nb-no\.)?facebook\.com/(?!sharer|share|plugins|tr\b|dialog|login)[\w\-.]+", re.I),
    "instagram": re.compile(r"https?://(?:www\.)?instagram\.com/(?!p/|reel/|explore)[\w\-.]+", re.I),
    "x": re.compile(r"https?://(?:www\.)?(?:twitter|x)\.com/(?!share|intent|home)[\w\-]+", re.I),
    "youtube": re.compile(r"https?://(?:www\.)?youtube\.com/(?:c/|channel/|@|user/)[\w\-%.]+", re.I),
    "tiktok": re.compile(r"https?://(?:www\.)?tiktok\.com/@[\w\-.]+", re.I),
}
# Recruiting platforms a company links to from its own site. The link itself is the evidence that the company
# uses the channel; the destination platform is not crawled.
JOB_BOARDS = {
    "webcruiter": r"webcruiter\.(?:no|com)", "jobbnorge": r"jobbnorge\.no", "finn": r"finn\.no/(?:job|jobb)",
    "recman": r"recman\.(?:no|page|io)", "teamtailor": r"teamtailor\.com", "varbi": r"varbi\.com",
    "hrmanager": r"(?:hrmanager|hr-manager)\.(?:no|net|com)", "easycruit": r"easycruit\.com",
    "jobylon": r"jobylon\.com", "reachmee": r"reachmee\.com", "workday": r"myworkdayjobs\.com",
    "smartrecruiters": r"smartrecruiters\.com", "jobindex": r"jobindex\.(?:no|dk)", "nav": r"arbeidsplassen\.nav\.no",
}
JOB_BOARD_RX = {k: re.compile(rf"https?://(?:[\w\-]+\.)*{v}", re.I) for k, v in JOB_BOARDS.items()}
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
LEGAL_SUFFIX = re.compile(r"\b(as|asa|ans|da|enk|nuf|sa|ba|ks|fli|sti|se|v/.*)\b", re.I)


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.meta, self.links, self._text, self._skip, self._in_title = "", {}, [], [], 0, False
        self.ldjson, self._ld = [], False
        self.anchors, self._a = [], None  # [(href, anchor text)]
        self.feeds = []

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
        elif tag == "link" and (a.get("rel") or "").lower() == "alternate" and a.get("href") and \
                re.search(r"rss|atom", a.get("type") or "", re.I):
            self.feeds.append(a["href"].strip())
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"].strip())
            self._a = [a["href"].strip(), ""]

    def handle_endtag(self, tag):
        if tag == "script":
            self._ld = False
        if tag in ("script", "style", "noscript", "svg") and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag == "a" and self._a:
            self.anchors.append((self._a[0], re.sub(r"\s+", " ", self._a[1]).strip()))
            self._a = None

    def handle_data(self, data):
        if self._ld and self.ldjson:
            self.ldjson[-1] += data
        if self._in_title:
            self.title += data
        elif not self._skip and data.strip():
            self._text.append(data.strip())
            if self._a is not None:
                self._a[1] += " " + data

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


_ASCII = str.maketrans({"æ": "ae", "ø": "o", "å": "a", "ä": "a", "ö": "o", "ü": "u", "é": "e"})


def _label(domain):
    return re.sub(r"[^a-z0-9]", "", domain.lower().removeprefix("www.").split(".")[0].translate(_ASCII))


def _joined(core):
    return re.sub(r"[^a-z0-9]", "", core.translate(_ASCII))


def _domain_matches_name(domain, core):
    """The domain is the company's own name: equal, or containing the full name (e.g. 'thequickstyle' for
    'Quick Style'). A domain that holds only part of the name ('amestoaccounthouse' for 'Amesto Accounthouse
    Sor') is a group or brand domain and does not match."""
    label, joined = _label(domain), _joined(core)
    if len(label) < 6 or len(joined) < 6:
        return False
    return label == joined or (joined in label and len(joined) / len(label) >= 0.7)


def _domain_related(domain, core):
    """At least one distinctive name token appears in the domain (or the domain is inside the name)."""
    label, joined = _label(domain), _joined(core)
    tokens = [t for t in re.sub(r"[^a-z0-9 ]", " ", core.translate(_ASCII)).split() if len(t) >= 4]
    return any(t in label for t in tokens) or (len(label) >= 5 and label in joined)


_ORG_LABELLED = re.compile(r"org(?:anisasjons)?[\s.\-]*(?:nr|nummer|no)?[\s.:]*((?:NO\s?)?\d{3}[\s.]?\d{3}[\s.]?\d{3})", re.I)


def _listed_org_numbers(blob):
    from .orgno import is_valid
    found = set()
    for m in _ORG_LABELLED.finditer(blob):
        d = re.sub(r"\D", "", m.group(1))
        if is_valid(d):
            found.add(d)
    return found


def tie_evidence(org, name, texts, postcode=None, phones=(), strong_only=False, domain=None):
    """Return (description, literal span from the page) if the pages tie to THIS company, else None.

    Strong: the organisation number appears on the page (on a page that lists several organisation numbers,
    e.g. a group's list of subsidiaries, only together with a domain related to the name). Weaker (only for
    register-backed candidates): the company name together with the registered postal code or telephone
    number on a domain related to the name, or a domain that is the company's own name. A name alone is
    never enough."""
    blob = " ".join(texts)
    core = _name_core(name)
    m = _org_pattern(org).search(blob)
    if m:
        others = _listed_org_numbers(blob) - {org}
        if not others or (domain and _domain_related(domain, core)):
            return f"page text contains organisation number {org}", m.group(0)
    if strong_only:
        return None
    flat = re.sub(r"\s+", " ", blob.lower())
    if len(core) < 4 or core not in flat:
        return None
    i = flat.find(core)
    name_span = blob[i:i + len(core)] if blob.lower()[i:i + len(core)] == core else core
    if domain and _domain_matches_name(domain, core):
        return f"the registered website domain '{domain}' matches the company name '{core}' and the page shows the name", name_span
    related = (not domain) or _domain_related(domain, core)
    if postcode and related:
        pm = re.search(rf"(?<!\d){postcode}(?!\d)", blob)
        if pm:
            return f"page text contains company name '{core}' and the registered postal code {postcode}", name_span
    digits = re.sub(r"\D", "", blob)
    for ph in phones if related else ():
        d = re.sub(r"\D", "", ph or "")[-8:]
        if len(d) == 8 and d in digits:
            return f"page text contains company name '{core}' and the registered telephone number {ph}", name_span
    return None


def ties_to_company(org, name, texts, postcode=None, phones=(), strong_only=False, domain=None):
    tie = tie_evidence(org, name, texts, postcode, phones, strong_only, domain)
    return tie[0] if tie else None


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


def _get_page(fetcher, url, accept="text/html"):
    return fetcher.get(url, accept=accept, retries=1, timeout=SITE_TIMEOUT, safe=True)


def discover_site(fetcher, org, unit, until=None):
    """Try name-derived domains; accept one only if its home page shows this organisation number."""
    if (unit.get("organisasjonsform") or {}).get("kode") not in DISCOVERY_FORMS:
        return None
    for host in candidate_domains(unit.get("navn", "")):
        if until and time.monotonic() > until:
            break
        url = f"https://{host}/"
        try:
            status, html = fetcher.get(url, accept="text/html", retries=1, timeout=8, safe=True)
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
            for k in ("@graph", "mainEntity", "publisher", "provider", "itemListElement", "item"):
                if k in x:
                    walk(x[k])
    for b in blocks:
        try:
            walk(json.loads(b))
        except ValueError:
            continue
    return objs


def _types(o):
    t = o.get("@type")
    return " ".join(t) if isinstance(t, list) else str(t or "")


_ORG_TYPES = re.compile(r"organi[sz]ation|business|corporation|company|store|restaurant|service", re.I)


class _Blocked(Exception):
    pass


def _allowed(fetcher, base, url):
    """robots.txt per RFC 9309: 2xx is parsed, 4xx means no rules, 5xx or unreachable means disallow."""
    host = urlparse(base)
    try:
        status, text = fetcher.get(f"{host.scheme}://{host.netloc}/robots.txt", accept="text/plain",
                                   retries=1, timeout=SITE_TIMEOUT, safe=True)
    except (BudgetExceeded, UnsafeURL):
        raise
    except Exception:
        return False
    if 400 <= status < 500:
        return True
    if status != 200:
        return False
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(text.splitlines())
    return rp.can_fetch(fetcher.client.headers.get("User-Agent", "*"), url)


def _variants(site):
    """The same site over https/http and with/without www, tried in order when one form fails."""
    u = urlparse(site)
    host = u.netloc
    other = host[4:] if host.startswith("www.") else "www." + host
    path = u.path or "/"
    out = [f"https://{host}{path}", f"https://{other}{path}", f"http://{host}{path}", f"http://{other}{path}"]
    if u.scheme == "http":
        out = out[2:] + out[:2]
    return list(dict.fromkeys(out))


def _snippet(text, needle, width=80):
    i = text.find(needle)
    if i < 0:
        return needle
    return text[max(0, i - width): i + len(needle) + width].replace("\n", " ").strip()


def _same_site(url, host):
    return urlparse(url).netloc.lower().removeprefix("www.") == host


def collect_pages(fetcher, site, max_pages=4, until=None):
    """Fetch the home page plus up to three contact/about/service pages. Returns [(url, html)].
    Tries https/http and www/non-www forms of the site until one answers."""
    home_html, base, blocked, last_err = None, None, False, None
    for variant in _variants(site):
        if until and time.monotonic() > until:
            break
        try:
            if not _allowed(fetcher, variant, variant):
                blocked = True
                continue
            status, html = _get_page(fetcher, variant)
        except UnresolvableHost as e:
            last_err = e
            continue
        except (BudgetExceeded, UnsafeURL):
            raise
        except Exception as e:
            last_err = e
            continue
        if status == 200 and "<" in html:
            home_html, base = html, variant
            break
    if home_html is None:
        if blocked:
            raise _Blocked(f"robots.txt disallows {site} or cannot be read")
        if last_err:
            raise last_err
        return []
    site = base
    pages = [(site, home_html)]
    home = parse_page(home_html)
    seen = {site.rstrip("/")}
    host = urlparse(site).netloc.lower().removeprefix("www.")
    for href in home.links:
        if len(pages) >= max_pages or (until and time.monotonic() > until):
            break
        full = urljoin(site, href).split("#")[0]
        if urlparse(full).scheme not in ("http", "https") or not _same_site(full, host):
            continue
        if full.rstrip("/") in seen or not CONTACT_HINTS.search(urlparse(full).path):
            continue
        seen.add(full.rstrip("/"))
        try:
            if not _allowed(fetcher, site, full):
                continue
            st, h = _get_page(fetcher, full)
        except BudgetExceeded:
            raise
        except Exception:
            continue
        if st == 200 and "<" in h:
            pages.append((full, h))
    return pages


def _first_link(parsed, host, rx, exclude=()):
    for url, _, p in parsed:
        for href, text in p.anchors:
            full = urljoin(url, href).split("#")[0]
            if _same_site(full, host) and full.rstrip("/") not in exclude and (
                    rx.search(urlparse(full).path) or rx.search(text or "")):
                return full
    return None


def _iso_date(value):
    v = str(value or "").strip()
    if not v:
        return None
    try:
        return parsedate_to_datetime(v).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, IndexError):
        pass
    m = re.match(r"(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}(?::\d{2})?))?", v)
    if m:
        return m.group(1) + ("T" + m.group(2) + ("" if len(m.group(2)) > 5 else ":00") + "Z" if m.group(2) else "")
    return None


_ITEM = re.compile(r"<(item|entry)\b.*?</\1>", re.S | re.I)


def _tag(block, *names):
    for n in names:
        m = re.search(rf"<{n}\b[^>]*>(.*?)</{n}>", block, re.S | re.I)
        if m:
            return unescape(re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", m.group(1), flags=re.S)).strip()
    return None


def parse_feed(xml):
    """RSS/Atom items as (title, link, published). Regex based on purpose: no XML entity expansion."""
    out = []
    for m in _ITEM.finditer(xml[:MAX_PAGE_CHARS]):
        b = m.group(0)
        title = _tag(b, "title")
        link = _tag(b, "link")
        if not link:
            lm = re.search(r"<link\b[^>]*href=[\"']([^\"']+)[\"']", b, re.I)
            link = lm.group(1) if lm else None
        published = _iso_date(_tag(b, "pubDate", "published", "updated", "dc:date"))
        if title and link and published:
            out.append((re.sub(r"<[^>]+>", "", title)[:300], link.strip(), published))
        if len(out) >= MAX_FEED_ITEMS:
            break
    return out


def _mark(checks, key, state, note=None):
    if checks is not None:
        checks[key] = {"availability": state, **({"note": note} if note else {})}


FREE_MAIL = {
    "gmail.com", "googlemail.com", "hotmail.com", "hotmail.no", "outlook.com", "outlook.no", "live.no", "live.com",
    "msn.com", "yahoo.com", "yahoo.no", "yahoo.co.uk", "icloud.com", "me.com", "mac.com", "aol.com", "mail.com",
    "gmx.com", "gmx.net", "protonmail.com", "proton.me", "online.no", "frisurf.no", "broadpark.no", "getmail.no",
    "start.no", "c2i.net", "lyse.net", "lyse.no", "altibox.no", "telenor.no", "tele2.no", "ebnett.no", "enivest.net",
    "haugnett.no", "combitel.no", "loqal.no", "sensewave.com", "vikenfiber.no", "tdcnet.no", "nextgentel.com",
    "bluezone.no", "powertech.no", "netcom.no", "chello.no", "oneco.no", "kpnmail.no", "eunet.no", "post.com",
    "yahoo.se", "hotmail.se", "frisurf.com", "tussa.com", "nordnet.no", "online.net", "ice.no", "barnehage.no",
}


def email_domain(unit):
    """Domain of the e-mail address the company registered, unless it is a mailbox provider."""
    mail = (unit.get("epostadresse") or "").strip().lower()
    if "@" not in mail:
        return None
    dom = mail.rsplit("@", 1)[1].strip(". ")
    if dom in FREE_MAIL or "." not in dom or len(dom) < 4:
        return None
    return dom


_SECTION_KEYS = ("official_website", "company_profiles", "hiring", "public_activity")


def _resolve_site(fetcher, org, unit, until, warnings):
    """Find the company's own website. Returns (site, origin, pages, tie) or (None, state, note, None).

    Candidates, in order: the website registered in Enhetsregisteret; the domain of the registered e-mail
    address; domains derived from the registered name. A candidate is used only when its pages tie to this
    exact entity: always by the organisation number for name-derived guesses, and for register-backed
    candidates by the organisation number or the name together with postal code, phone or a matching domain."""
    addr = unit.get("forretningsadresse") or {}
    registered = normalize_url(unit.get("hjemmeside"))
    candidates = []
    if registered:
        candidates.append((registered, "register_website"))
    dom = email_domain(unit)
    if dom and not (registered and urlparse(registered).netloc.lower().removeprefix("www.") == dom):
        candidates.append((f"https://{dom}/", "register_email_domain"))
    failure = None
    for site, origin in candidates:
        if until and time.monotonic() > until:
            break
        try:
            pages = collect_pages(fetcher, site, until=until)
        except BudgetExceeded:
            raise
        except _Blocked as e:
            warnings.append(str(e))
            failure = failure or ("blocked", str(e))
            continue
        except UnresolvableHost:
            warnings.append(f"{origin} {site} does not resolve")
            failure = failure or ("not_available", f"{'registered website' if origin == 'register_website' else 'e-mail domain'} {site} does not resolve")
            continue
        except UnsafeURL as e:
            warnings.append(f"website refused by URL policy: {e}")
            failure = failure or ("blocked", "refused by public-URL policy")
            continue
        except Exception as e:
            warnings.append(f"website fetch failed for {site}: {type(e).__name__}: {e}"[:300])
            failure = failure or ("failed", f"{site} could not be fetched")
            continue
        if not pages:
            failure = failure or ("failed", f"{site} unreachable or not HTML")
            continue
        texts = [parse_page(h).title + " " + parse_page(h).text for _, h in pages]
        # A parent or group site may list a subsidiary's name and address, so for an e-mail domain only the
        # organisation number or a domain that is the company's own name counts.
        strict = origin != "register_website"
        tie = tie_evidence(org, unit.get("navn", ""), texts,
                           postcode=None if strict else addr.get("postnummer"),
                           phones=() if strict else [unit.get("telefon"), unit.get("mobil")],
                           domain=urlparse(pages[0][0]).netloc)
        if tie:
            return pages[0][0], origin, pages, tie
        warnings.append(f"{origin} {pages[0][0]} discarded: pages do not tie to organisation number {org}")
        failure = failure or ("ambiguous", f"{pages[0][0]} does not tie to this exact entity")
    found = discover_site(fetcher, org, unit, until) if not registered or failure else None
    if found:
        try:
            pages = collect_pages(fetcher, found, until=until)
        except BudgetExceeded:
            raise
        except Exception:
            pages = []
        if pages:
            texts = [parse_page(h).title + " " + parse_page(h).text for _, h in pages]
            tie = tie_evidence(org, unit.get("navn", ""), texts, strong_only=True)
            if tie:
                return pages[0][0], "name_domain_discovery", pages, tie
    if not registered or failure:
        for cand in search_candidates(fetcher, unit):
            if until and time.monotonic() > until:
                break
            try:
                pages = collect_pages(fetcher, cand, until=until)
            except BudgetExceeded:
                raise
            except Exception:
                continue
            if not pages:
                continue
            texts = [parse_page(h).title + " " + parse_page(h).text for _, h in pages]
            tie = tie_evidence(org, unit.get("navn", ""), texts, strong_only=True)
            if not tie:
                # A search hit whose domain is the company's own name may also pass with the registered
                # postal code or telephone number on the page; the name alone never does.
                t2 = tie_evidence(org, unit.get("navn", ""), texts, postcode=addr.get("postnummer"),
                                  phones=[unit.get("telefon"), unit.get("mobil")])
                if t2 and _domain_matches_name(urlparse(pages[0][0]).netloc, _name_core(unit.get("navn", ""))):
                    tie = (t2[0] + f"; the domain {urlparse(pages[0][0]).netloc} matches the company name", t2[1])
            if tie:
                return pages[0][0], "search_discovery", pages, tie
    if failure:
        return None, failure[0], failure[1], None
    return None, "not_available", "none registered; no candidate domain showed this organisation number", None


# ------------------------------------------------------------------ optional search discovery (candidates only)

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
BRAVE_KEY_ENV = "BRAVE_SEARCH_API_KEY"
_NOT_COMPANY_SITES = re.compile(
    r"(^|\.)(proff|purehelp|gulesider|1881|finn|brreg|regnskapstall|bedriftsdatabasen|firmasok|kompass|allabolag|"
    r"enirodirectory|facebook|linkedin|instagram|youtube|twitter|x|tiktok|wikipedia|wikidata|google|bing|yelp|"
    r"tripadvisor|trustpilot|mittanbud|anbudstorget|nav|altinn|ssb|kartverket|norgeskart|hitta|eniro|krak|"
    r"118|180|firmanett|forhandlerkart|vg|dagbladet|nrk|e24|dn|aftenposten|tu|amazon|apple|"
    r"bygg|byggmakker|zoominfo|dnb|crunchbase|bloomberg|opencorporates|northdata|companyhouse|infobel|cylex|"
    r"hotfrog|bedrift|bizzdo|bisnode|dun|dnbbedrift|nettavisen|regjeringen|lovdata)\.[a-z.]+$", re.I)
_search_lock = __import__("threading").Lock()
_search_last = [0.0]


def search_candidates(fetcher, unit, limit=3):
    """Candidate company sites from Brave Search. Results are never evidence; each one is re-fetched and must
    tie to the entity. The API key comes only from the BRAVE_SEARCH_API_KEY environment variable."""
    key = os.environ.get(BRAVE_KEY_ENV, "").strip()
    name = (unit.get("navn") or "").strip()
    if not key or not name:
        return []
    place = ((unit.get("forretningsadresse") or {}).get("poststed") or "").title()
    query = f'"{name}" {place}'.strip()
    interval = float(os.environ.get("BRAVE_MIN_INTERVAL", "1.05"))
    with _search_lock:
        wait = _search_last[0] + interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _search_last[0] = time.monotonic()
    try:
        status, data = fetcher.get_json(BRAVE_ENDPOINT, {"q": query, "count": 10, "country": "no", "search_lang": "nb",
                                                         "safesearch": "moderate", "spellcheck": "0"},
                                        headers={"X-Subscription-Token": key}, use_cache=False, retries=1,
                                        timeout=SITE_TIMEOUT, record=False)
    except BudgetExceeded:
        raise
    except Exception:
        return []
    out = []
    for r in ((data or {}).get("web") or {}).get("results", []):
        url = r.get("url") or ""
        host = urlparse(url).netloc.lower().removeprefix("www.")
        if not host or _NOT_COMPANY_SITES.search(host) or any(urlparse(u).netloc.lower().removeprefix("www.") == host for u in out):
            continue
        out.append(f"{urlparse(url).scheme or 'https'}://{urlparse(url).netloc}/")
        if len(out) >= limit:
            break
    return out


_ORIGIN_TEXT = {
    "register_website": "the website declared in Enhetsregisteret",
    "register_email_domain": "the domain of the e-mail address registered in Enhetsregisteret",
    "name_domain_discovery": "a website found by name-based domain lookup (not in the register)",
    "search_discovery": "a website found through Brave Search (not in the register; search was used only to find the candidate)",
}


def website_facts(fetcher, org, unit, retrieved_at, warnings, checks=None):
    until = time.monotonic() + SITE_SECONDS
    for k in _SECTION_KEYS:
        _mark(checks, k, "not_available", "no verified website to research from")
    site, origin, pages, tie = _resolve_site(fetcher, org, unit, until, warnings)
    if not site:
        _mark(checks, "official_website", origin, pages)
        return []
    declared = origin == "register_website"
    parsed = [(u, h, parse_page(h)) for u, h in pages]
    addr = unit.get("forretningsadresse") or {}
    tie_text, tie_span = tie

    why_base = f"Page from {site}, {_ORIGIN_TEXT[origin]} for organisation number {org}; {tie_text}"

    def add(field, value, url, evidence, span=None, method="html", source_class="company_site"):
        f = fact(field, value, url, evidence, why_base, retrieved_at)
        f["span"] = span or evidence
        f["method"] = method
        f["source_class"] = source_class
        out.append(f)

    out = []
    add("website_verified", True, pages[0][0], tie_text, tie_span, "identity_tie")
    if not declared:
        add("website", site, pages[0][0], tie_text, tie_span, origin)
    _mark(checks, "official_website", "available")
    home_url, _, home = parsed[0]

    # A page on a group, chain or brand domain is the company's page, but the rest of that site (footer social
    # links, careers, news feed) belongs to the group. Publish only the page itself in that case.
    own_domain = _domain_matches_name(urlparse(site).netloc, _name_core(unit.get("navn", "")))
    org_tie = tie_text.startswith("page text contains organisation number")
    deep = urlparse(site).path not in ("", "/")
    if not own_domain and (deep or not org_tie):
        note = "the verified page sits on a shared or group domain; site-wide profiles, jobs and news are not attributed"
        for k in ("company_profiles", "hiring", "public_activity"):
            _mark(checks, k, "ambiguous", note)
        out[0]["shared_domain"] = True
        return out
    desc = home.meta.get("description") or home.meta.get("og:description")
    if desc and len(desc) > 20:
        add("website_description", desc, home_url, f"meta description: {desc[:200]}", desc, "meta")
    brand = home.meta.get("og:site_name")
    if brand and 2 <= len(brand) <= 80:
        add("public_brand", brand, home_url, f"og:site_name: {brand}", brand, "meta")

    host = urlparse(site).netloc.lower().removeprefix("www.")
    emails, phones, socials, boards = {}, {}, {}, {}
    for url, html, p in parsed:
        for href, text in p.anchors:
            h = href.strip()
            if h.lower().startswith("mailto:"):
                e = h[7:].split("?")[0].strip().lower()
                if EMAIL.fullmatch(e):
                    emails.setdefault(e, (url, h))
            elif h.lower().startswith("tel:"):
                t = re.sub(r"[^\d+]", "", h[4:])
                if 8 <= len(t) <= 15:
                    phones.setdefault(t, (url, h))
            else:
                full = urljoin(url, h)
                for name, rx in SOCIAL.items():
                    m = rx.match(full)
                    if m and name not in socials:
                        socials[name] = (url, m.group(0), h)
                for name, rx in JOB_BOARD_RX.items():
                    if rx.match(full) and full not in boards:
                        boards[full] = (url, name, h, text)
        for e in EMAIL.findall(p.text):
            e = e.lower().rstrip(".")
            emails.setdefault(e, (url, e))
    for e, (url, span) in sorted(emails.items()):
        dom = e.split("@")[1]
        if dom == host or dom.endswith("." + host) or host.endswith("." + dom):
            add("website_email", e, url, f"e-mail on page: {e}", span)
    for t, (url, span) in sorted(phones.items())[:3]:
        add("website_phone", t, url, f"telephone link on page: {span}", span)
    for name, (url, link, span) in sorted(socials.items()):
        add(f"social:{name}", link, url, f"link on the company's own page: {link}", span, "outbound_link", "company_social")

    # schema.org data the company publishes about itself (JSON-LD)
    seen = {(f["field"], str(f["value"])) for f in out}
    reg_post = addr.get("postnummer")
    jobs, news = [], []
    for url, _, p in parsed:
        for o in parse_jsonld(p.ldjson):
            types = _types(o)
            if re.search(r"JobPosting", types):
                jobs.append((url, o))
                continue
            if re.search(r"NewsArticle|BlogPosting|\bArticle\b|PressRelease", types):
                news.append((url, o))
                continue
            if not _ORG_TYPES.search(types):
                continue
            tel = re.sub(r"[^\d+]", "", str(o.get("telephone") or ""))
            if 8 <= len(tel) <= 15 and ("website_phone", tel) not in seen:
                seen.add(("website_phone", tel))
                add("website_phone", tel, url, f"JSON-LD {types} telephone {o.get('telephone')}", str(o.get("telephone")), "json_ld")
            mail = str(o.get("email") or "").replace("mailto:", "").strip().lower()
            if EMAIL.fullmatch(mail) and ("website_email", mail) not in seen and (
                    mail.split("@")[1] == host or mail.split("@")[1].endswith("." + host)):
                seen.add(("website_email", mail))
                add("website_email", mail, url, f"JSON-LD {types} email {mail}", mail, "json_ld")
            a = o.get("address")
            if isinstance(a, dict) and a.get("streetAddress") and str(a.get("postalCode", "")).strip() == reg_post:
                text = f"{a['streetAddress']}, {a.get('postalCode')} {a.get('addressLocality', '')}".strip()
                if ("website_address", text) not in seen:
                    seen.add(("website_address", text))
                    add("website_address", text, url, f"JSON-LD {types} address {text} (postal code equals the register's)",
                        str(a["streetAddress"]), "json_ld")
            same = o.get("sameAs")
            for link in ([same] if isinstance(same, str) else same or []):
                for name, rx in SOCIAL.items():
                    m = rx.match(str(link))
                    if m and not any(f["field"] == f"social:{name}" for f in out):
                        add(f"social:{name}", m.group(0), url, f"JSON-LD {types} sameAs {m.group(0)}", str(link),
                            "json_ld", "company_social")
    _mark(checks, "company_profiles", "available" if any(f["field"].startswith("social:") for f in out) else "not_available",
          None if any(f["field"].startswith("social:") for f in out) else "verified website links to no social profile")

    seen_urls = {u.rstrip("/") for u, _ in pages}

    # ---------------- hiring: careers page, structured job postings, recruiting channels linked by the company
    def fetch_extra(url):
        if not url or (until and time.monotonic() > until):
            return None
        try:
            if not _allowed(fetcher, site, url):
                return None
            st, h = _get_page(fetcher, url)
        except BudgetExceeded:
            raise
        except Exception:
            return None
        if st == 200 and "<" in h:
            seen_urls.add(url.rstrip("/"))
            return url, h, parse_page(h)
        return None

    careers = _first_link(parsed, host, CAREER_HINTS, seen_urls)
    extra = fetch_extra(careers)
    if extra:
        add("careers_page", extra[0], extra[0], f"careers page linked from the company's own site: {extra[0]}",
            urlparse(extra[0]).path or extra[0], "outbound_link")
        for o in parse_jsonld(extra[2].ldjson):
            if re.search(r"JobPosting", _types(o)):
                jobs.append((extra[0], o))
        for href, text in extra[2].anchors:
            full = urljoin(extra[0], href)
            for name, rx in JOB_BOARD_RX.items():
                if rx.match(full) and full not in boards:
                    boards[full] = (extra[0], name, href, text)
    job_keys = set()
    for url, o in jobs[:20]:
        title = str(o.get("title") or "").strip()
        if not title:
            continue
        posted = _iso_date(o.get("datePosted"))
        loc = o.get("jobLocation")
        loc = loc[0] if isinstance(loc, list) and loc else loc
        place = ((loc or {}).get("address") or {}).get("addressLocality") if isinstance(loc, dict) else None
        value = {k: v for k, v in {"title": title[:200], "date_posted": posted,
                                   "valid_through": _iso_date(o.get("validThrough")),
                                   "url": o.get("url") or url, "employment_type": o.get("employmentType"),
                                   "location": place}.items() if v}
        key = (title.lower(), value.get("url"))
        if key in job_keys:
            continue
        job_keys.add(key)
        add("job_posting", value, url, f"JSON-LD JobPosting: {title}", title, "json_ld")
    for full, (url, name, href, text) in sorted(boards.items())[:10]:
        add("hiring_channel", {"platform": name, "url": full, **({"label": text[:120]} if text else {})}, url,
            f"link to {name} on the company's own page", href, "outbound_link")
    hiring_found = any(f["field"] in ("job_posting", "hiring_channel", "careers_page") for f in out)
    _mark(checks, "hiring", "available" if hiring_found else "not_available",
          None if hiring_found else "no careers page, job posting or recruiting link on the verified website")

    # ---------------- dated public activity: company feeds, structured articles
    feed_urls = [urljoin(u, f) for u, _, p in parsed for f in p.feeds]
    if not feed_urls and "wordpress" in (home.meta.get("generator") or "").lower():
        feed_urls = [urljoin(site, "/feed/")]
    if not news and not feed_urls:
        news_page = fetch_extra(_first_link(parsed, host, NEWS_HINTS, seen_urls))
        if news_page:
            feed_urls = [urljoin(news_page[0], f) for f in news_page[2].feeds]
            news += [(news_page[0], o) for o in parse_jsonld(news_page[2].ldjson)
                     if re.search(r"NewsArticle|BlogPosting|\bArticle\b|PressRelease", _types(o))]
    items = []
    for feed in feed_urls[:1]:
        if not _same_site(feed, host) or (until and time.monotonic() > until):
            continue
        try:
            if not _allowed(fetcher, site, feed):
                continue
            st, xml = fetcher.get(feed, accept="application/rss+xml, application/atom+xml, application/xml, text/xml",
                                  retries=1, timeout=SITE_TIMEOUT, safe=True)
        except BudgetExceeded:
            raise
        except Exception:
            continue
        if st == 200:
            for title, link, published in parse_feed(xml):
                if _same_site(urljoin(feed, link), host):
                    items.append((feed, title, urljoin(feed, link), published, "feed"))
    for url, o in news[:20]:
        title = str(o.get("headline") or o.get("name") or "").strip()
        published = _iso_date(o.get("datePublished") or o.get("dateCreated"))
        if title and published:
            items.append((url, title[:300], o.get("url") or url, published, "json_ld"))
    seen_items = set()
    for src, title, link, published, method in sorted(items, key=lambda x: x[3], reverse=True):
        if link in seen_items:
            continue
        seen_items.add(link)
        add("news_item", {"title": title, "url": link, "published": published}, src,
            f"{'feed item' if method == 'feed' else 'JSON-LD article'}: {title}", title, method)
        out[-1]["as_of"] = published[:10]
        if len(seen_items) >= MAX_FEED_ITEMS:
            break
    _mark(checks, "public_activity", "available" if seen_items else "not_available",
          None if seen_items else "verified website publishes no dated news feed or dated articles")

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
        f = fact(field, value, url, f"quote: \"{quote}\"",
                 why_base + "; value extracted by model and quote verified verbatim on page", retrieved_at)
        f.update({"span": quote, "method": f"llm:{LLM_MODEL}", "source_class": "company_site"})
        out.append(f)
    return out
