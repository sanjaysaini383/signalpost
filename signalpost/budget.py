"""Shared HTTP client: request/time budget, retries, short-lived cache, source snapshots and safe URL handling."""
import hashlib
import ipaddress
import json
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

DEFAULT_MAX_REQUESTS = 20000  # no request cap is published; this is only a runaway guard. Counts are reported.
MAX_BODY_BYTES = 2_000_000
MAX_REQUEST_SECONDS = 20
MAX_REDIRECTS = 5
DEFAULT_CACHE_TTL = 3600     # seconds. Short on purpose: a profile must never be built from yesterday's data
USER_AGENT = "signalpost/0.3 (company research agent; +https://github.com/sanjaysaini383/signalpost)"


class BudgetExceeded(RuntimeError):
    pass


class UnsafeURL(ValueError):
    pass


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_public_url(url):
    """Refuse anything but http(s) on default ports to hosts that resolve only to public addresses.
    Website URLs come from third parties (the register, links on pages), so they are treated as untrusted."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise UnsafeURL(f"unsupported URL scheme or host: {url}")
    if u.port not in (None, 80, 443) or u.username or u.password:
        raise UnsafeURL(f"non-default port or credentials in URL: {url}")
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise UnsafeURL(f"host does not resolve: {u.hostname}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            raise UnsafeURL(f"host {u.hostname} resolves to a non-public address")


class Fetcher:
    def __init__(self, max_requests=DEFAULT_MAX_REQUESTS, cache_dir=None, deadline=None,
                 cache_ttl=DEFAULT_CACHE_TTL, user_agent=USER_AGENT):
        self.max_requests = max_requests
        self.requests_made = 0
        self._lock = threading.Lock()
        self._local = threading.local()
        self.llm_input_tokens = 0
        self.llm_output_tokens = 0
        self.deadline = deadline  # absolute time.monotonic() value
        self.cache_ttl = cache_ttl
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = httpx.Client(timeout=20, follow_redirects=False, headers={"User-Agent": user_agent},
                                   limits=httpx.Limits(max_connections=32, max_keepalive_connections=16))

    # ------------------------------------------------------------- per-company accounting (thread-local)
    def begin_company(self):
        self._local.requests = 0
        self._local.snapshots = {}

    def company_requests(self):
        return getattr(self._local, "requests", 0)

    def snapshots(self):
        """Every source response used for the current company: url -> {final_url, status, retrieved_at, sha256}."""
        return getattr(self._local, "snapshots", {})

    def count_external(self):
        with self._lock:
            if self.requests_made >= self.max_requests:
                raise BudgetExceeded(f"request budget {self.max_requests} exhausted")
            self.requests_made += 1
        self._local.requests = getattr(self._local, "requests", 0) + 1

    def add_llm_usage(self, usage):
        with self._lock:
            self.llm_input_tokens += usage.get("input_tokens", 0)
            self.llm_output_tokens += usage.get("output_tokens", 0)

    # ------------------------------------------------------------- cache
    def _cache_path(self, url, params):
        key = hashlib.sha1(f"{url}|{sorted((params or {}).items())}".encode()).hexdigest()
        return self.cache_dir / f"{key}.json"

    def _cached(self, path):
        try:
            if path.exists() and time.time() - path.stat().st_mtime < self.cache_ttl:
                d = json.loads(path.read_text("utf-8"))
                return d
        except (OSError, ValueError, KeyError):
            pass
        return None

    def _record(self, url, params, snap):
        full = str(httpx.URL(url, params=params)) if params else url
        snaps = getattr(self._local, "snapshots", None)
        if snaps is not None:
            snaps[full] = snap
            snaps.setdefault(url, snap)

    # ------------------------------------------------------------- fetching
    def _fetch(self, url, params, accept, timeout, safe):
        """One GET (following redirects by hand) with caps on body size and total time."""
        started = time.monotonic()
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            if safe:
                check_public_url(current)
            with self.client.stream("GET", current, params=params, headers={"Accept": accept},
                                    **({"timeout": timeout} if timeout else {})) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    current = urljoin(str(r.url), r.headers["location"])
                    params = None
                    continue
                chunks, size = [], 0
                for chunk in r.iter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > MAX_BODY_BYTES or time.monotonic() - started > MAX_REQUEST_SECONDS:
                        break
                raw = b"".join(chunks)
                return r.status_code, raw.decode(r.encoding or "utf-8", errors="replace"), str(r.url), raw
        raise httpx.TooManyRedirects(f"more than {MAX_REDIRECTS} redirects: {url}")

    def get(self, url, params=None, accept="application/json", use_cache=True, retries=3, timeout=None, safe=False):
        """Return (status_code, text). 404 is returned, not raised. Every real request is counted.
        `safe=True` applies the public-URL policy to the URL and every redirect hop."""
        path = self._cache_path(url, params) if self.cache_dir and use_cache else None
        if path:
            hit = self._cached(path)
            if hit and "status" in hit:
                self._record(url, params, {"final_url": hit.get("final_url", url), "status": hit["status"],
                                           "retrieved_at": hit.get("retrieved_at", _now()),
                                           "content_sha256": hit.get("sha256") or hashlib.sha256(hit["text"].encode()).hexdigest()})
                return hit["status"], hit["text"]
        if self.deadline and time.monotonic() > self.deadline:
            raise BudgetExceeded("time budget exhausted")
        last = None
        for attempt in range(retries):
            self.count_external()
            try:
                status_code, body, final_url, raw = self._fetch(url, params, accept, timeout, safe)
            except UnsafeURL:
                raise
            except httpx.HTTPError as e:
                last = e
                if retries > 1:
                    time.sleep(1 + attempt)
                continue
            if status_code in (429, 500, 502, 503, 504):
                last = RuntimeError(f"HTTP {status_code}")
                if attempt < retries - 1:
                    time.sleep(1 + attempt * 2)
                continue
            snap = {"final_url": final_url, "status": status_code, "retrieved_at": _now(),
                    "content_sha256": hashlib.sha256(raw).hexdigest()}
            self._record(url, params, snap)
            if path and status_code in (200, 404, 410):
                try:
                    path.write_text(json.dumps({"status": status_code, "text": body, "final_url": final_url,
                                                "retrieved_at": snap["retrieved_at"], "sha256": snap["content_sha256"]}), "utf-8")
                except OSError:
                    pass
            return status_code, body
        raise RuntimeError(f"GET {url} failed: {last}")

    def get_json(self, url, params=None, **kw):
        status, text = self.get(url, params, **kw)
        if status != 200:
            return status, None
        try:
            return status, json.loads(text)
        except ValueError:
            return status, None
