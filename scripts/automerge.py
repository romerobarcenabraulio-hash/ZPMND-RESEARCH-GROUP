"""Data-only PRs merge by themselves (automerge.yml; Braulio, 2026-10-27: "sí, fusión automática para PRs de datos").

    GH_TOKEN=... REPO=<owner>/<name> SHA=<40 hex> python3 scripts/automerge.py

Runs from main (workflow_run) each time ci or auditor finishes for a commit. Each open PR into main whose head is that
commit is merged, pinned to it, only when all of this holds; anything else leaves the PR to the owner:
- it comes from a branch of this repository (a fork never qualifies), is not a draft and still has that head;
- every file it touches is data: added or modified (never removed or renamed) under research-packets/<RP>/, or a
  source plan requests/plans/<RR>.json. Never code, workflows, docs, tests or mutants;
- both auditors passed this exact commit: the latest statuses `auditor` ("AUDIT VERDICT: PASS") and `auditor-gpt`
  ("GPT REVIEW: PASS") are success and were set by github-actions[bot], the auditor workflow's token;
- every check run on the commit finished as success, skipped or neutral, and the jobs of ci and of the auditor are
  among them (REQUIRED), so a workflow that has not started yet holds the merge back.
Trust boundary (SECURITY.md T15): a workflow of a same-repo PR runs with this repository's token too, so whoever can
push a branch here could set a status as github-actions[bot]; that actor can already push to main. A fork's workflows
get a read-only token, and the auditor never audits a fork.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request

API = 'https://api.github.com'
SHA = re.compile(r'^[0-9a-f]{40}$')
REPO = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')
DATA = re.compile(r'^(?:research-packets/RP-[A-Za-z0-9._-]{3,64}/[A-Za-z0-9._/-]+|requests/plans/RR-[A-Za-z0-9._-]{3,64}\.json)$')
BOT = 'github-actions[bot]'
VERDICTS = {'auditor': 'AUDIT VERDICT: PASS', 'auditor-gpt': 'GPT REVIEW: PASS'}
REQUIRED = {'checks', 'audit', 'audit-gpt', 'packet-gate'}  # ci's job and the auditor's
GREEN = {'success', 'skipped', 'neutral'}
MAX_FILES = 3000  # the files API lists at most 3,000 per PR: a longer list could hide one


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
    return None


def audited(statuses, sha):
    """None when both auditors passed the commit; statuses newest first (the API's order), the latest per context."""
    latest = {}
    for s in statuses:
        latest.setdefault(s.get('context'), s)
    for context, line in VERDICTS.items():
        s = latest.get(context) or {}
        if s.get('state') != 'success' or s.get('description') != line or (s.get('creator') or {}).get('login') != BOT:
            return f'{context}: no PASS from the auditor on {sha[:7]}'
    return None


def green(runs):
    """None when ci and the auditor ran and every check run finished green; else why not."""
    missing = REQUIRED - {r.get('name') for r in runs}
    if missing:
        return f'not run yet: {", ".join(sorted(missing))}'
    for r in runs:
        if r.get('conclusion') not in GREEN:  # a run still going has no conclusion
            return f"{r.get('name')}: {r.get('status')}/{r.get('conclusion')}"
    return None


def decide(pr, files, statuses, runs, repo, sha):
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
    return data_only(files) or audited(statuses, sha) or green(runs)


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
    for listed in call('GET', f'/repos/{repo}/commits/{sha}/pulls'):
        n = listed.get('number')
        if listed.get('state') != 'open' or not isinstance(n, int):
            continue
        pr = call('GET', f'/repos/{repo}/pulls/{n}')
        why = decide(pr, pages(call, f'/repos/{repo}/pulls/{n}/files'), pages(call, f'/repos/{repo}/commits/{sha}/statuses'),
                     pages(call, f'/repos/{repo}/commits/{sha}/check-runs?filter=latest', 'check_runs'), repo, sha)
        if why:
            print(f'#{n} stays with the owner: {why}')
            continue
        call('PUT', f'/repos/{repo}/pulls/{n}/merge', {'sha': sha, 'merge_method': 'squash', 'commit_title': f"{pr['title']} (#{n})"})
        print(f'#{n} merged, pinned to {sha}')
        try:
            call('DELETE', f"/repos/{repo}/git/refs/heads/{urllib.parse.quote(pr['head']['ref'], safe='/')}")
        except Exception as exc:  # the merge stands; a branch left behind is only clutter
            print(f"#{n}: branch {pr['head']['ref']} not deleted: {exc}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
