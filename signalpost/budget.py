"""Shared HTTP client with a hard outbound-request budget, retries and a short-lived disk cache."""
import hashlib
import json
import threading
import time
from pathlib import Path

import httpx

DEFAULT_MAX_REQUESTS = 1800  # competition limit is 2,000; keep headroom
DEFAULT_CACHE_TTL = 3600     # seconds. Short on purpose: a profile must never be built from yesterday's data


class BudgetExceeded(RuntimeError):
    pass


class Fetcher:
    def __init__(self, max_requests=DEFAULT_MAX_REQUESTS, cache_dir=None, deadline=None,
                 cache_ttl=DEFAULT_CACHE_TTL, user_agent="signalpost/0.2 (company profile research agent)"):
        self.max_requests = max_requests
        self.requests_made = 0
        self._lock = threading.Lock()
        self.llm_input_tokens = 0
        self.llm_output_tokens = 0
        self.deadline = deadline  # absolute time.monotonic() value
        self.cache_ttl = cache_ttl
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": user_agent},
                                   limits=httpx.Limits(max_connections=32, max_keepalive_connections=16))

    def count_external(self):
        with self._lock:
            if self.requests_made >= self.max_requests:
                raise BudgetExceeded(f"request budget {self.max_requests} exhausted")
            self.requests_made += 1

    def add_llm_usage(self, usage):
        with self._lock:
            self.llm_input_tokens += usage.get("input_tokens", 0)
            self.llm_output_tokens += usage.get("output_tokens", 0)

    def _cache_path(self, url, params):
        key = hashlib.sha1(f"{url}|{sorted((params or {}).items())}".encode()).hexdigest()
        return self.cache_dir / f"{key}.json"

    def _cached(self, path):
        try:
            if path.exists() and time.time() - path.stat().st_mtime < self.cache_ttl:
                d = json.loads(path.read_text("utf-8"))
                return d["status"], d["text"]
        except (OSError, ValueError, KeyError):
            pass
        return None

    def get(self, url, params=None, accept="application/json", use_cache=True, retries=3, timeout=None):
        """Return (status_code, text). 404 is returned, not raised. Every real request is counted."""
        path = self._cache_path(url, params) if self.cache_dir and use_cache else None
        if path:
            hit = self._cached(path)
            if hit:
                return hit
        if self.deadline and time.monotonic() > self.deadline:
            raise BudgetExceeded("time budget exhausted")
        last = None
        for attempt in range(retries):
            self.count_external()
            try:
                r = self.client.get(url, params=params, headers={"Accept": accept},
                                    **({"timeout": timeout} if timeout else {}))
            except httpx.HTTPError as e:
                last = e
                if retries > 1:
                    time.sleep(1 + attempt)
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                last = RuntimeError(f"HTTP {r.status_code}")
                if attempt < retries - 1:
                    time.sleep(1 + attempt * 2)
                continue
            if path and r.status_code in (200, 404, 410):
                try:
                    path.write_text(json.dumps({"status": r.status_code, "text": r.text}), "utf-8")
                except OSError:
                    pass
            return r.status_code, r.text
        raise RuntimeError(f"GET {url} failed: {last}")

    def get_json(self, url, params=None, **kw):
        status, text = self.get(url, params, **kw)
        if status != 200:
            return status, None
        try:
            return status, json.loads(text)
        except ValueError:
            return status, None
