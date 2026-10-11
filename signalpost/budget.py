"""Shared HTTP client with a hard outbound-request budget, retries and a disk cache."""
import hashlib
import json
import time
from pathlib import Path

import httpx

DEFAULT_MAX_REQUESTS = 1800  # competition limit is 2,000; keep headroom


class BudgetExceeded(RuntimeError):
    pass


class Fetcher:
    def __init__(self, max_requests=DEFAULT_MAX_REQUESTS, cache_dir=None, deadline=None, user_agent="signalpost/0.1"):
        self.max_requests = max_requests
        self.requests_made = 0
        self.deadline = deadline  # absolute time.monotonic() value
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": user_agent})

    def _cache_path(self, url, params):
        key = hashlib.sha1(f"{url}|{sorted((params or {}).items())}".encode()).hexdigest()
        return self.cache_dir / f"{key}.json"

    def get(self, url, params=None, accept="application/json", use_cache=True):
        """Return (status_code, text). 404 is returned, not raised. Counts every real request."""
        path = self._cache_path(url, params) if self.cache_dir and use_cache else None
        if path and path.exists():
            d = json.loads(path.read_text("utf-8"))
            return d["status"], d["text"]
        if self.deadline and time.monotonic() > self.deadline:
            raise BudgetExceeded("time budget exhausted")
        last = None
        for attempt in range(3):
            if self.requests_made >= self.max_requests:
                raise BudgetExceeded(f"request budget {self.max_requests} exhausted")
            self.requests_made += 1
            try:
                r = self.client.get(url, params=params, headers={"Accept": accept})
            except httpx.HTTPError as e:
                last = e
                time.sleep(1 + attempt)
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                last = RuntimeError(f"HTTP {r.status_code}")
                time.sleep(1 + attempt * 2)
                continue
            if path and r.status_code in (200, 404):
                path.write_text(json.dumps({"status": r.status_code, "text": r.text}), "utf-8")
            return r.status_code, r.text
        raise RuntimeError(f"GET {url} failed: {last}")

    def get_json(self, url, params=None, **kw):
        status, text = self.get(url, params, **kw)
        return status, (json.loads(text) if status == 200 else None)
