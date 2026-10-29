"""Data-only PRs merge by themselves (automerge.yml; Braulio, 2026-10-27: "sí, fusión automática para PRs de datos").

    GH_TOKEN=... REPO=<owner>/<name> SHA=<40 hex> python3 scripts/automerge.py

Runs from main (workflow_run) each time ci or auditor finishes for a commit. Each open PR into main whose head is that
commit is merged, pinned to it, only when all of this holds; anything else leaves the PR to the owner:
- it comes from a branch of this repository (a fork never qualifies), is not a draft and still has that head;
- every file it touches is data: added (never modified, removed or renamed) under research-packets/<RP>/ for an <RP>
  main does not have yet, since a packet on main never changes, not even by a file added beside it (docs/OUTBOX.md), or
  added or modified as a source plan requests/plans/<RR>.json. Never code, workflows, docs, tests or mutants;
- the trusted runs on that commit for that PR passed (TRUSTED): the newest run of .github/workflows/auditor.yml for
  pull_request_target (whose file always comes from main) and of .github/workflows/ci.yml for pull_request (the PR's
  copy, which a data-only PR cannot change) both finished success, and every job in them succeeded, none skipped, among
  them the ones each must have; in the auditor's, pass-both, which runs only when the Claude verdict and the GPT review
  it posted for that head are both PASS.
Statuses and comments are never read: any workflow of a branch here runs with this repository's token and could imitate
them (GPT, REVISE of #48). A run's file path and event are GitHub's, not the branch's. SECURITY.md T15.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

API = 'https://api.github.com'
SHA = re.compile(r'^[0-9a-f]{40}$')
REPO = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')
DATA = re.compile(r'^(?:research-packets/RP-[A-Za-z0-9._-]{3,64}/[A-Za-z0-9._/-]+|requests/plans/RR-[A-Za-z0-9._-]{3,64}\.json)$')
TRUSTED = {  # workflow file -> (the event of its trusted run, jobs that run must have)
    '.github/workflows/auditor.yml': ('pull_request_target', {'gate', 'evidence', 'packet-gate', 'audit', 'audit-gpt',
                                                              'post', 'post-gpt', 'pass-both'}),
    '.github/workflows/ci.yml': ('pull_request', {'checks'}),
}
MAX_FILES = 3000  # the files API lists at most 3,000 per PR: a longer list could hide one
PACKET = re.compile(r'^research-packets/(RP-[A-Za-z0-9._-]{3,64})/')


def data_only(files):
    """None when every file is data, added or modified; else why not."""
    if not files:
        return 'it touches no file'
    if len(files) >= MAX_FILES:
        return f'{len(files)} files: the list may be cut'
    for f in files:
        name = f.get('filename', '')
        if f.get('status') not in ('added', 'modified'):
            return f"{name}: {f.get('status')} (only added or modified data merges by itself)"
        if not DATA.match(name) or any(part in ('.', '..') for part in name.split('/')):
            return f'{name}: not data'
        if name.startswith('research-packets/') and f.get('status') != 'added':
            return f'{name}: {f.get("status")} (a packet on main never changes; only a new one merges by itself)'
    return None


def newest(runs, path, event, sha, n):
    """The newest run of that workflow file, for that event, on that commit and that PR; None if there is none."""
    mine = [r for r in runs if r.get('path') == path and r.get('event') == event and r.get('head_sha') == sha
            and n in [p.get('number') for p in r.get('pull_requests') or []]]
    return max(mine, key=lambda r: r.get('id', 0), default=None)


def verified(runs, jobs_of, sha, n):
    """None when each TRUSTED workflow's newest run on the commit for PR n finished success with every job succeeded
    (none skipped) and its required jobs among them; else why not. jobs_of(run id) lists that run's jobs."""
    for path, (event, required) in TRUSTED.items():
        run = newest(runs, path, event, sha, n)
        if run is None:
            return f'no {event} run of {path} on {sha[:7]}'
        if run.get('status') != 'completed' or run.get('conclusion') != 'success':
            return f"{path}: {run.get('status')}/{run.get('conclusion')}"
        jobs = jobs_of(run['id'])
        missing = required - {j.get('name') for j in jobs}
        if missing:
            return f'{path}: did not run {", ".join(sorted(missing))}'
        for j in jobs:
            if j.get('conclusion') != 'success':
                return f"{path}: {j.get('name')} {j.get('conclusion')}"
    return None


def republished(files, exists, branch=''):
    """None when the PR writes no packet, or exactly one packet folder new on main from that packet's own branch
    investigar/<RP>; else why not. exists(rp) says whether main has research-packets/<rp>/. The branch rule closes the
    race between this check and the merge: investigar pushes each investigar/<RP> once (create-only), so no other PR
    that merges by itself can write that folder meanwhile; one the owner merges is the owner's to order."""
    rps = sorted({m.group(1) for f in files for m in [PACKET.match(f.get('filename', ''))] if m})
    if not rps:
        return None
    if len(rps) > 1 or branch != f'investigar/{rps[0]}':
        return f"{', '.join(rps)} from {branch or 'no branch'}: a packet merges by itself only alone, from investigar/<its RP>"
    if exists(rps[0]):
        return f'research-packets/{rps[0]}/ is already on main (a packet on main never changes)'
    return None


def decide(pr, files, runs, jobs_of, repo, sha, *, exists):
    """None to merge; else the reason the PR stays with the owner."""
    head = pr.get('head') or {}
    if pr.get('state') != 'open' or pr.get('draft'):
        return 'not an open PR ready for review'
    if (pr.get('base') or {}).get('ref') != 'main':
        return 'its base is not main'
    if head.get('sha') != sha:
        return 'its head moved'
    if (head.get('repo') or {}).get('full_name') != repo:
        return 'it comes from a fork'
    if pr.get('changed_files') != len(files):
        return f"{pr.get('changed_files')} changed files, {len(files)} listed"
    already = republished(files, exists, head.get('ref') or '')
    if already:
        return already
    return data_only(files) or verified(runs, jobs_of, sha, pr.get('number'))


def api(method, path, body=None, token=''):
    req = urllib.request.Request(API + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json',
                                          'X-GitHub-Api-Version': '2022-11-28'})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    return json.loads(data) if data else None


def pages(call, path, key=None, limit=30):
    """Every row of a listing, 100 per page; ValueError past limit pages instead of a cut list."""
    rows = []
    for page in range(1, limit + 1):
        got = call('GET', f'{path}{"&" if "?" in path else "?"}per_page=100&page={page}')
        got = got[key] if key else got
        rows += got
        if len(got) < 100:
            return rows
    raise ValueError(f'{path}: more than {limit} pages')


def main(env=None, call=None):
    env = os.environ if env is None else env
    repo, sha = env.get('REPO', ''), env.get('SHA', '')
    if not REPO.match(repo) or not SHA.match(sha):
        print('REPO and SHA are required')
        return 2
    call = call or (lambda method, path, body=None: api(method, path, body, env.get('GH_TOKEN', '')))
    runs = pages(call, f'/repos/{repo}/actions/runs?head_sha={sha}', 'workflow_runs')

    def jobs_of(run_id):
        return pages(call, f'/repos/{repo}/actions/runs/{int(run_id)}/jobs?filter=latest', 'jobs')

    def exists(rp):  # any answer but GitHub's 404 stops the run: the PR stays with the owner
        try:
            call('GET', f'/repos/{repo}/contents/research-packets/{rp}?ref=main')
            return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            raise

    for listed in call('GET', f'/repos/{repo}/commits/{sha}/pulls'):
        n = listed.get('number')
        if listed.get('state') != 'open' or not isinstance(n, int):
            continue
        pr = call('GET', f'/repos/{repo}/pulls/{n}')
        why = decide(pr, pages(call, f'/repos/{repo}/pulls/{n}/files'), runs, jobs_of, repo, sha, exists=exists)
        if why:
            print(f'#{n} stays with the owner: {why}')
            continue
        call('PUT', f'/repos/{repo}/pulls/{n}/merge', {'sha': sha, 'merge_method': 'squash', 'commit_title': f"{pr['title']} (#{n})"})
        print(f'#{n} merged, pinned to {sha}')  # its branch stays: deleting it could race a new push (GPT, #48)
    return 0


if __name__ == '__main__':
    sys.exit(main())
