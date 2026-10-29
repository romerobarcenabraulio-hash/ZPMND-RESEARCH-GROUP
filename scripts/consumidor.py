"""A consumer of RG's packets that knows nothing of RG's internals: Git is the outbox (docs/OUTBOX.md).

    GH_TOKEN=<read token, optional> python3 scripts/consumidor.py --repo <owner>/<name> --since <40-hex commit>
                                    [--accept <rp sha256>:<sa sha256>]...

It reads main only, through GitHub's REST API. The packets it looks at are those whose folder research-packets/<RP>/
a commit after --since touched: it lists every such commit (main's history of research-packets/, kept to the commits
the comparison --since...main names, all of them or none) and each one's files, page by page. A packet is taken only if
its whole folder has exactly one commit on main, the one that added its packet.json (the publication commit): one
whose folder changed or was removed after that is reported, never taken. For each it gives, at the publication commit,
the packet's exact bytes and sha256, its receipt.json's (None for a packet made by hand, which has none), the sha256 of
the two schema files it was validated against (research_packet and source_artifact) and each artifact's declared
sha256, with the path of its raw when the repository keeps it (from the raw folder's whole git tree; the raw's bytes
are not hashed here). Compatibility
fails closed: a packet is accepted only when its pair of schema digests is one --accept names; otherwise it is reported
as schema_not_accepted, with the digests, for the consumer to review. It prints one JSON line per packet and a last line
with main's commit, the cursor for the next call.

A read GitHub could not answer now (5xx, 403/429 rate limit, network, a body cut mid-read) stops everything: exit 75 and no cursor, so the
next call reads the same range again. A range GitHub would only list in part stops too: exit 3, no cursor. Nothing but
the API; no RG module, no model, no write. The token comes from GH_TOKEN or GITHUB_TOKEN, never the command line, and is
dropped on a redirect to another host.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.client import HTTPException

API = 'https://api.github.com'
FOLDER = re.compile(r'^research-packets/(RP-[A-Za-z0-9._-]{3,64})/')
REPO = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')
SHA = re.compile(r'^[0-9a-f]{40}$')
DIGEST = re.compile(r'^[0-9a-f]{64}$')
SCHEMAS = ('schemas/research_packet.schema.json', 'schemas/source_artifact.schema.json')
MAX_FILES = 3000  # GitHub lists at most this many files of one commit; a commit at the cap stops the read


class Cut(Exception):
    """GitHub would list the range only in part: nothing is taken and no cursor is given."""


class Transient(Exception):
    """GitHub could not answer now: nothing is taken and no cursor is given, so the next call retries the range."""


def transient(e):
    """True for an error that says nothing about the packet: a server error, a rate limit, the network or a body cut
    while it was read (IncompleteRead and the rest of http.client's)."""
    if isinstance(e, urllib.error.HTTPError):
        return e.code >= 500 or e.code in (403, 429)
    return isinstance(e, (Transient, urllib.error.URLError, HTTPException, OSError))


class SameHostAuth(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to https, without the token when it leads to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != 'https':  # never off TLS, whatever the host
            raise urllib.error.HTTPError(newurl, code, f'a redirect away from https is refused ({msg})', headers, fp)
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc:
            new.remove_header('Authorization')
        return new


def http(path, raw=False, token=''):
    headers = {'Accept': 'application/vnd.github.raw' if raw else 'application/vnd.github+json',
               'X-GitHub-Api-Version': '2022-11-28'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    with urllib.request.build_opener(SameHostAuth).open(urllib.request.Request(API + path, headers=headers), timeout=60) as r:
        body = r.read()
    if raw:
        return body
    try:
        return json.loads(body)
    except ValueError as e:  # GitHub's own answer cut or garbled: nothing about a packet, read again later
        raise Transient(f'an unreadable answer from GitHub ({type(e).__name__})') from e


def sha256(body):
    return hashlib.sha256(body).hexdigest()


def optional(fetch, path):
    """What fetch returns for path, or None when GitHub says it is not there (404): a packet made by hand has no
    receipt.json, a packet without a stored raw has no raw folder."""
    try:
        return fetch(path)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def history(get, repo, head, path):
    """Every commit on main up to head that touched path (a file or a folder), newest first, page by page."""
    out, page = [], 1
    while True:
        got = get(f'/repos/{repo}/commits?sha={head}&path={path}&per_page=100&page={page}')
        out += [c['sha'] for c in got]
        if len(got) < 100:
            return out
        page += 1


def window(get, repo, since, head):
    """The commits after `since` up to head, all of them: since must be behind head and the count GitHub's total."""
    out, page = [], 1
    while True:
        got = get(f'/repos/{repo}/compare/{since}...{head}?per_page=100&page={page}')
        if got.get('status') not in ('ahead', 'identical'):
            raise Cut(f"{since[:7]} is not behind main ({got.get('status')})")
        commits = got.get('commits') or []
        out += [c['sha'] for c in commits]
        if len(out) >= got.get('total_commits', 0) or not commits:
            break
        page += 1
    if len(out) != got.get('total_commits', 0):
        raise Cut(f"GitHub listed {len(out)} of {got.get('total_commits')} commits after {since[:7]}")
    return out


def touched(get, repo, sha):
    """{rp: {path: status}} of every file under a packet folder the commit changed (a rename counts on both sides)."""
    found, page, seen = {}, 1, 0
    while True:
        files = get(f'/repos/{repo}/commits/{sha}?per_page=100&page={page}').get('files') or []
        seen += len(files)
        for f in files:
            for name in (f.get('filename') or '', f.get('previous_filename') or ''):
                m = FOLDER.match(name)
                if m:
                    found.setdefault(m.group(1), {})[name] = f.get('status')
        if len(files) < 100:
            return found
        if seen >= MAX_FILES:
            raise Cut(f'{sha[:7]} changes more files than GitHub lists ({MAX_FILES})')
        page += 1


def changes(get, repo, since):
    """(main's commit, {rp: {commit: {path: status}}}) for every packet folder a commit after `since` touched."""
    head = get(f'/repos/{repo}/commits/main')['sha']
    inside = set(window(get, repo, since, head))
    found = {}
    for sha in history(get, repo, head, 'research-packets'):
        if sha in inside:
            for rp, files in touched(get, repo, sha).items():
                found.setdefault(rp, {})[sha] = files
    return head, found


def raws(get, repo, rp, commit):
    """Every file path under research-packets/<rp>/raw/ at that commit: the folder's tree, read whole (git trees, not a
    directory listing GitHub cuts at 1000 entries); a tree GitHub says it truncated stops the read (Cut)."""
    top = optional(get, f'/repos/{repo}/contents/research-packets/{rp}?ref={commit}') or []
    raw = next((e for e in top if e.get('name') == 'raw' and e.get('type') == 'dir'), None)
    if raw is None:
        return set()
    tree = get(f"/repos/{repo}/git/trees/{raw['sha']}?recursive=1")
    if tree.get('truncated'):
        raise Cut(f'{rp}: GitHub listed its raws only in part')
    return {f"research-packets/{rp}/raw/{e['path']}" for e in tree.get('tree', []) if e.get('type') == 'blob'}


def take(get, get_raw, repo, rp, head, events, accepted):
    """One packet: its identity at its publication commit, accepted or rejected with why."""
    folder = history(get, repo, head, f'research-packets/{rp}')
    if len(folder) != 1:  # a packet on main never changes (docs/OUTBOX.md)
        why = 'no commit on main adds its packet.json' if not folder else f'its folder changed after it was published ({len(folder)} commits)'
        return {'research_id': rp, 'status': 'rejected', 'why': why}
    commit = folder[0]
    if (events.get(commit) or {}).get(f'research-packets/{rp}/packet.json') != 'added':
        return {'research_id': rp, 'status': 'rejected', 'why': 'its only commit does not add its packet.json', 'commit': commit}
    body = get_raw(f'/repos/{repo}/contents/research-packets/{rp}/packet.json?ref={commit}')
    try:
        packet = json.loads(body)
    except ValueError as e:  # a packet on main passed the gate, so bytes that do not parse were cut on the way: read again
        raise Transient(f'{rp}: its packet.json came back unreadable ({type(e).__name__})') from e
    if packet.get('research_id') != rp:
        return {'research_id': rp, 'status': 'rejected', 'why': 'its research_id is not its folder', 'commit': commit}
    receipt = optional(get_raw, f'/repos/{repo}/contents/research-packets/{rp}/receipt.json?ref={commit}')
    schema = {name.split('/')[1].split('.')[0]: sha256(get_raw(f'/repos/{repo}/contents/{name}?ref={commit}')) for name in SCHEMAS}
    stored = raws(get, repo, rp, commit)
    artifacts = []
    for a in packet.get('artifacts', []):
        prefix = f"research-packets/{rp}/raw/sha256/{a['sha256'][:2]}/{a['sha256']}."
        artifacts.append({'artifact_id': a['artifact_id'], 'sha256': a['sha256'], 'redistribution': a['redistribution'],
                          'url': a['url'], 'path': next((n for n in sorted(stored) if n.startswith(prefix)), None)})
    out = {'research_id': rp, 'request_id': packet.get('request_id'), 'packet_status': packet.get('status'),
           'commit': commit, 'packet_sha256': sha256(body), 'receipt_sha256': sha256(receipt) if receipt is not None else None,
           'schema': schema,
           'artifacts': artifacts}
    if (schema['research_packet'], schema['source_artifact']) not in accepted:
        return {**out, 'status': 'schema_not_accepted'}
    return {**out, 'status': 'accepted'}


def run(get, get_raw, repo, since, accepted):
    """[results] for the packet folders touched since `since`, then the cursor: main's commit. Raises Cut or Transient
    instead of answering in part."""
    try:
        head, found = changes(get, repo, since)
    except Exception as e:  # noqa: BLE001 - classified here: the network is retried, never taken for an answer
        if transient(e) and not isinstance(e, Transient):
            raise Transient(type(e).__name__) from e
        raise
    results = []
    for rp, events in sorted(found.items()):
        try:
            results.append(take(get, get_raw, repo, rp, head, events, accepted))
        except Cut:
            raise  # a packet GitHub would show only in part is no answer: the read stops, no cursor
        except Exception as e:  # noqa: BLE001 - one bad packet is one rejection, never the end of the read
            if transient(e):
                raise Transient(f'{rp}: {type(e).__name__}') from e
            results.append({'research_id': rp, 'status': 'rejected', 'why': type(e).__name__})
    return results, head


def main(argv=None, get=None, get_raw=None):
    a = argparse.ArgumentParser(description="the packets RG's main published or changed since a commit, with their identity")
    a.add_argument('--repo', required=True)
    a.add_argument('--since', required=True)
    a.add_argument('--accept', action='append', default=[], help='<research_packet sha256>:<source_artifact sha256>')
    x = a.parse_args(argv)
    if not REPO.match(x.repo) or not SHA.match(x.since):
        raise SystemExit('--repo owner/name and --since <40-hex commit>')
    accepted = set()
    for pair in x.accept:
        rp_sha, _, sa_sha = pair.partition(':')
        if not (DIGEST.match(rp_sha) and DIGEST.match(sa_sha)):
            raise SystemExit('--accept <64 hex>:<64 hex>')
        accepted.add((rp_sha, sa_sha))
    token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN') or ''  # a public repository needs none
    get = get or (lambda p: http(p, token=token))
    get_raw = get_raw or (lambda p: http(p, raw=True, token=token))
    try:
        results, head = run(get, get_raw, x.repo, x.since, accepted)
    except Transient as e:
        print(f'GitHub did not answer ({e}); nothing taken, no cursor: run again', file=sys.stderr)
        return 75
    except Cut as e:
        print(f'{e}; nothing taken, no cursor', file=sys.stderr)
        return 3
    for r in results:
        print(json.dumps(r, ensure_ascii=False, sort_keys=True))
    print(json.dumps({'cursor': head, 'since': x.since, 'packets': len(results)}, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
