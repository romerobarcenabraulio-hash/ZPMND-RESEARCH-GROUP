"""Polite, fail-closed HTTP fetcher for deterministic acquisition (no agent, no model).

Guards, each with a test in tests/test_catalog_fetch.py:
- only http(s) URLs whose host is in the source's allowlist; redirects are re-checked the same way;
- robots.txt is honored for every URL (404 = allowed, unreachable/5xx = everything disallowed);
- at least `min_interval` seconds between requests to one host (or the site's Crawl-delay if larger);
- TLS is always verified; responses larger than `max_bytes` are refused; a per-run request budget stops the run.
"""
import time
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

USER_AGENT = 'ZPMND-RESEARCH-GROUP-catalog/0.1 (deterministic catalog; honors robots.txt)'


class FetchRefused(Exception):
    """The request was not sent because a guard said no."""


class BudgetExhausted(FetchRefused):
    pass


@dataclass
class Response:
    status: int
    body: bytes
    url: str
    headers: dict = field(default_factory=dict)

    @property
    def charset(self):
        ctype = self.headers.get('content-type', '')
        for part in ctype.split(';'):
            if part.strip().lower().startswith('charset='):
                return part.split('=', 1)[1].strip().strip('"') or 'utf-8'
        return 'utf-8'

    def text(self):
        return self.body.decode(self.charset, errors='replace')


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # redirects are followed by Fetcher.get after re-checking host and robots


class Fetcher:
    def __init__(self, allowed_hosts, budget=3000, min_interval=1.0, max_bytes=60_000_000, timeout=60,
                 opener=None, clock=time.monotonic, sleep=time.sleep):
        self.allowed_hosts = {h.lower() for h in allowed_hosts}
        self.budget = budget
        self.used = 0
        self.min_interval = min_interval
        self.max_bytes = max_bytes
        self.timeout = timeout
        self._opener = opener or urllib.request.build_opener(_NoRedirect)  # env proxies (HTTPS_PROXY) apply
        self._clock, self._sleep = clock, sleep
        self._last = {}
        self._robots = {}

    def _check_url(self, url):
        parts = urlsplit(url)
        if parts.scheme not in ('https', 'http') or not parts.hostname:
            raise FetchRefused(f'scheme or host not allowed: {url}')
        if parts.hostname.lower() not in self.allowed_hosts:
            raise FetchRefused(f'host not in allowlist: {parts.hostname}')
        if parts.username or parts.password:
            raise FetchRefused('credentials in URL')
        return parts

    def _pace(self, host, delay):
        wait = self._last.get(host, -1e9) + delay - self._clock()
        if wait > 0:
            self._sleep(wait)
        self._last[host] = self._clock()

    def _send(self, url, headers):
        if self.used >= self.budget:
            raise BudgetExhausted(f'request budget of {self.budget} used')
        self.used += 1
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, **headers})
        try:
            with self._opener.open(req, timeout=self.timeout) as r:
                status, hdrs, stream = r.status, r.headers, r
                body = stream.read(self.max_bytes + 1)
        except urllib.error.HTTPError as e:
            with e:
                status, hdrs, body = e.code, e.headers, e.read(self.max_bytes + 1) if e.fp else b''
        if len(body) > self.max_bytes:
            raise FetchRefused(f'response larger than {self.max_bytes} bytes: {url}')
        return Response(status, body, url, {k.lower(): v for k, v in (hdrs or {}).items()})

    def _robots_for(self, parts):
        key = f'{parts.scheme}://{parts.netloc}'
        if key not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            self._pace(parts.hostname, self.min_interval)
            r = self._send(key + '/robots.txt', {})
            if r.status == 200:
                rp.parse(r.text().splitlines())
            elif 400 <= r.status < 500:
                rp.allow_all = True
            else:
                rp.disallow_all = True  # 3xx, 5xx: assume everything is disallowed (conservative reading of RFC 9309)
            self._robots[key] = rp
        return self._robots[key]

    def allowed(self, url):
        parts = self._check_url(url)
        return self._robots_for(parts).can_fetch(USER_AGENT, url)

    def get(self, url, etag=None, last_modified=None, max_redirects=5):
        """GET with guards. Returns Response; status 304 means not modified."""
        for _ in range(max_redirects + 1):
            parts = self._check_url(url)
            robots = self._robots_for(parts)
            if not robots.can_fetch(USER_AGENT, url):
                raise FetchRefused(f'robots.txt disallows {url}')
            delay = max(self.min_interval, float(robots.crawl_delay(USER_AGENT) or 0))
            headers = {}
            if etag:
                headers['If-None-Match'] = etag
            if last_modified:
                headers['If-Modified-Since'] = last_modified
            self._pace(parts.hostname, delay)
            r = self._send(url, headers)
            if r.status in (301, 302, 303, 307, 308) and r.headers.get('location'):
                url = urljoin(url, r.headers['location'])
                continue
            return r
        raise FetchRefused(f'too many redirects: {url}')
