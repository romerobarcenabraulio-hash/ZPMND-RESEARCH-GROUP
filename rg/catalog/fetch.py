"""Polite, fail-closed HTTP fetcher for deterministic acquisition (no agent, no model).

Guards, each with a test in tests/test_catalog.py (FetchGuards), tests/test_run_guards.py or tests/test_hf_tesis.py:
- only https URLs whose host is in the source's allowlist; redirects are re-checked the same way;
- robots.txt is honored for every URL (other 4xx = allowed; 401/403/429, 3xx, 5xx or unreachable = everything
  disallowed; only a rule read from a 200 robots.txt is recorded as 'disallowed');
- at least `min_interval` seconds between requests to one host (or the site's Crawl-delay if larger);
- TLS is always verified; responses larger than `max_bytes` are refused; a per-run request budget and an optional
  deadline stop the run (BudgetExhausted); network errors, including a non-ASCII URL, are status 0, never a crash;
- a credential (`auth`) goes only to the host of the URL asked for: never to a host reached by redirect (a CDN with a
  signed URL) and never to robots.txt;
- a large body can be streamed to disk (`sink`, a FileSink) with its own size cap; every attempt starts it empty.
"""
import hashlib
import http.client
import time
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlsplit

USER_AGENT = 'ZPMND-RESEARCH-GROUP-catalog/0.1 (deterministic catalog; honors robots.txt)'
_LATIN1_LABELS = {'iso-8859-1', 'iso8859-1', 'latin1', 'latin-1', 'l1', 'us-ascii', 'ascii', 'windows-1252', 'cp1252'}


def decode_html(body, charset):
    """WHATWG Encoding Standard: the label 'iso-8859-1' (and ascii) means windows-1252. Official Mexican sites declare
    ISO-8859-1 and send 0x93/0x94 curly quotes; decoding them as Latin-1 yields invisible C1 control characters."""
    label = (charset or 'utf-8').strip().lower()
    if label in _LATIN1_LABELS:
        return body.decode('cp1252', errors='replace')
    try:
        return body.decode(label, errors='replace')
    except LookupError:
        return body.decode('utf-8', errors='replace')


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
        return decode_html(self.body, self.charset)


class FileSink:
    """Destination for a body too large to keep in memory: written to `path` and hashed on the way, at most `limit`
    bytes. reset() empties it; the Fetcher calls it before every attempt, so a retry never appends to a cut body."""
    def __init__(self, path, limit):
        self.path, self.limit = Path(path), limit
        self.reset()

    def reset(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(b'')
        self._hash, self.bytes = hashlib.sha256(), 0

    def write(self, chunk):
        with open(self.path, 'ab') as fh:
            fh.write(chunk)
        self._hash.update(chunk)
        self.bytes += len(chunk)

    @property
    def sha256(self):
        return self._hash.hexdigest()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # redirects are followed by Fetcher.get after re-checking host and robots


class Fetcher:
    def __init__(self, allowed_hosts, budget=3000, min_interval=1.0, max_bytes=60_000_000, timeout=60,
                 opener=None, clock=time.monotonic, sleep=time.sleep, retries=2, deadline=None):
        self.allowed_hosts = {h.lower() for h in allowed_hosts}
        self.budget = budget
        self.used = 0
        self.min_interval = min_interval
        self.max_bytes = max_bytes
        self.timeout = timeout
        self.retries = retries  # network errors and 5xx are retried with growing pauses; 4xx is final
        self._opener = opener or urllib.request.build_opener(_NoRedirect)  # env proxies (HTTPS_PROXY) apply
        self._clock, self._sleep = clock, sleep
        self._last = {}
        self._robots = {}
        self._robots_status = {}
        self.deadline = deadline  # clock() value after which no request is sent (job time limit)

    def _check_url(self, url):
        parts = urlsplit(url)
        if parts.scheme != 'https' or not parts.hostname:  # https only: a redirect to http is refused, never followed
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

    def _send(self, url, headers, sink=None):
        if self.used >= self.budget:
            raise BudgetExhausted(f'request budget of {self.budget} used')
        if self.deadline is not None and self._clock() >= self.deadline:
            raise BudgetExhausted('run deadline reached')
        self.used += 1
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, **headers})
        try:
            with self._opener.open(req, timeout=self.timeout) as r:
                status, hdrs, stream = r.status, r.headers, r
                if sink is not None and status == 200:
                    sink.reset()  # a retry after a cut body starts from zero
                    while chunk := stream.read(1 << 20):
                        if sink.bytes + len(chunk) > sink.limit:
                            raise FetchRefused(f'response larger than {sink.limit} bytes: {url}')
                        sink.write(chunk)
                    body = b''
                else:
                    body = stream.read(self.max_bytes + 1)
        except urllib.error.HTTPError as e:
            with e:
                status, hdrs, body = e.code, e.headers, e.read(self.max_bytes + 1) if e.fp else b''
        except (http.client.HTTPException, urllib.error.URLError, OSError, ValueError) as e:  # ValueError: non-ASCII URL
            # Transient network failure (cut response, reset, timeout): status 0, the caller marks it failed and
            # the run goes on. Seen 2026-10-19: one IncompleteRead killed a 1.5 h run before this existed.
            return Response(0, b'', url, {'x-rg-network-error': type(e).__name__})
        if len(body) > self.max_bytes:
            raise FetchRefused(f'response larger than {self.max_bytes} bytes: {url}')
        return Response(status, body, url, {k.lower(): v for k, v in (hdrs or {}).items()})

    def _robots_for(self, parts):
        key = f'{parts.scheme}://{parts.netloc}'
        if key not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            for attempt in range(self.retries + 1):
                self._pace(parts.hostname, self.min_interval * (attempt + 1))
                r = self._send(key + '/robots.txt', {})
                if r.status != 0 and r.status < 500:
                    break
            self._robots_status[key] = r.status
            if r.status == 200:
                rp.parse(r.text().splitlines())
            elif r.status in (401, 403, 429):
                rp.disallow_all = True  # the site refuses robots: a block (rule 8), not an absent file
            elif 400 <= r.status < 500:
                rp.allow_all = True
            else:
                rp.disallow_all = True  # 3xx, 5xx: assume everything is disallowed (conservative reading of RFC 9309)
            self._robots[key] = rp
        return self._robots[key]

    def allowed(self, url):
        parts = self._check_url(url)
        return self._robots_for(parts).can_fetch(USER_AGENT, url)

    def disallowed_by_rule(self, url):
        """True only when a robots.txt that was read (200) disallows the URL. An unreachable robots.txt also blocks
        fetching, but it is a passing condition: the caller marks the item failed and retries, never 'disallowed'."""
        parts = self._check_url(url)
        rp = self._robots_for(parts)
        return self._robots_status.get(f'{parts.scheme}://{parts.netloc}') == 200 and not rp.can_fetch(USER_AGENT, url)

    def get(self, url, etag=None, last_modified=None, max_redirects=5, auth=None, sink=None):
        """GET with guards. Returns Response; status 304 means not modified. `auth` is an Authorization value sent only
        to the host of `url`; with `sink`, a 200 body goes to the FileSink and Response.body is empty."""
        origin = self._check_url(url).hostname
        for _ in range(max_redirects + 1):
            parts = self._check_url(url)
            robots = self._robots_for(parts)
            if not robots.can_fetch(USER_AGENT, url):
                raise FetchRefused(f'robots.txt disallows {url}')
            delay = max(self.min_interval, float(robots.crawl_delay(USER_AGENT) or 0))
            headers = {}
            if auth and parts.hostname == origin:  # a redirect to another host (a signed CDN URL) gets no credential
                headers['Authorization'] = auth
            if etag:
                headers['If-None-Match'] = etag
            if last_modified:
                headers['If-Modified-Since'] = last_modified
            for attempt in range(self.retries + 1):
                self._pace(parts.hostname, delay * (attempt + 1))
                r = self._send(url, headers, sink)
                if r.status != 0 and r.status < 500:
                    break
            if r.status in (301, 302, 303, 307, 308) and r.headers.get('location'):
                url = urljoin(url, r.headers['location'])
                continue
            return r
        raise FetchRefused(f'too many redirects: {url}')
