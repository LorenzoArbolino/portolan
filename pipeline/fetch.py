"""Polite fetching: PortolanBot User-Agent, robots.txt, one request per
domain every 3 s, cache by URL. No logins, no paywalls, no CAPTCHAs: a walled page is unreachable.

The cache (`cache/`, gitignored) holds full documents for re-checks; never committed (methodology, rule 4)."""

from __future__ import annotations

import hashlib
import json
import time
import urllib.robotparser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from portolan.ids import canonical_url

REPO_URL = "https://github.com/LorenzoArbolino/portolan"
USER_AGENT = f"PortolanBot/1.0 (+{REPO_URL})"
DEFAULT_CACHE = Path("cache/fetch")
MIN_INTERVAL_S = 3.0
TIMEOUT_S = 30.0
MAX_BYTES = 150_000_000  # annual reports with photos run past 50 MB


@dataclass
class Fetched:
    url: str
    ok: bool
    status: int | None = None
    content: bytes = b""
    content_type: str = ""
    sha256: str | None = None
    reason: str | None = None
    from_cache: bool = False


class Fetcher:
    def __init__(
        self,
        cache_dir: Path | None = DEFAULT_CACHE,
        min_interval: float = MIN_INTERVAL_S,
        client: httpx.Client | None = None,
    ) -> None:
        self.cache_dir = cache_dir
        self.min_interval = min_interval
        self.client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_S, follow_redirects=True
        )
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def _wait(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            delay = self.min_interval - (time.monotonic() - last)
            if delay > 0:
                time.sleep(delay)
        self._last[host] = time.monotonic()

    def _request(self, url: str, attempts: int = 3) -> httpx.Response:
        """GET with retries on transient transport errors (connection resets are common through proxies)."""
        host = urlsplit(url).netloc
        for i in range(attempts):
            self._wait(host)
            try:
                return self.client.get(url)
            except httpx.TransportError:
                if i == attempts - 1:
                    raise
                time.sleep(self.min_interval * (i + 1))
        raise AssertionError("unreachable")

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        root = f"{parts.scheme}://{parts.netloc}"
        if root not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self._request(root + "/robots.txt")
                if r.status_code >= 500:
                    rp = None  # robots unreachable: be conservative
                elif r.status_code >= 400:
                    rp.parse([])  # no robots.txt: everything allowed
                else:
                    rp.parse(r.text.splitlines())
            except httpx.HTTPError:
                rp = None
            self._robots[root] = rp
        rp = self._robots[root]
        return rp is not None and rp.can_fetch(USER_AGENT, url)

    def _cache_paths(self, url: str) -> tuple[Path, Path] | None:
        if self.cache_dir is None:
            return None
        key = hashlib.sha1(canonical_url(url).encode()).hexdigest()
        return self.cache_dir / f"{key}.bin", self.cache_dir / f"{key}.json"

    def get(self, url: str) -> Fetched:
        paths = self._cache_paths(url)
        if paths and paths[0].exists() and paths[1].exists():
            meta = json.loads(paths[1].read_text(encoding="utf-8"))
            content = paths[0].read_bytes()
            return Fetched(
                url=url,
                ok=True,
                status=meta.get("status"),
                content=content,
                content_type=meta.get("content_type", ""),
                sha256=meta.get("sha256"),
                from_cache=True,
            )
        if not self.allowed(url):
            return Fetched(url=url, ok=False, reason="robots.txt disallows or robots unreachable")
        try:
            r = self._request(url)
        except httpx.HTTPError as e:
            return Fetched(url=url, ok=False, reason=f"{type(e).__name__}: {e}")
        if r.status_code >= 400:
            return Fetched(url=url, ok=False, status=r.status_code, reason=f"HTTP {r.status_code}")
        if len(r.content) > MAX_BYTES:  # a cut PDF is unreadable: refuse it rather than cache a broken file
            return Fetched(url=url, ok=False, status=r.status_code, reason=f"larger than {MAX_BYTES} bytes")
        content = r.content
        sha = hashlib.sha256(content).hexdigest()
        f = Fetched(
            url=url,
            ok=True,
            status=r.status_code,
            content=content,
            content_type=r.headers.get("content-type", ""),
            sha256=sha,
        )
        if paths:
            paths[0].parent.mkdir(parents=True, exist_ok=True)
            paths[0].write_bytes(content)
            paths[1].write_text(
                json.dumps(
                    {"url": url, "status": r.status_code, "sha256": sha, "content_type": f.content_type}
                )
            )
        return f
