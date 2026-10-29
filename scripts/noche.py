"""The night: pick the pending ResearchRequests and start their investigar runs; in the morning, say what happened.

    GH_TOKEN=... REPO=<owner>/<name> python3 scripts/noche.py despachar [--max 4] [--dry-run]
    GH_TOKEN=... REPO=<owner>/<name> python3 scripts/noche.py resumen --since <ISO time> --out <dir>

Git and GitHub's own state are the queue (docs/NOCHE.md): no database, no service. A request on main is pending unless
a packet on main answers it (its packet.json's request_id, whatever the folder is called), a branch investigar/<RP>
exists, a PR from that branch is open, an investigar run for it is queued or running (run-name "investigar <RR>"), a
run for it ended without success in the last 3 days (it waits for a person), or requests/terminal/<RR>.json marks it
done by hand. Pending ones go by priority (P0 first), then oldest issued_at, then
id; at most --max start, each with discover unless the request has a reviewed plan. Each started run is waited for until GitHub lists it, so a later dispatcher finds it and starts
nothing twice; investigar.yml's own concurrency group and its create-only branch push keep any duplicate from
publishing twice. Only PUBLIC and ABSTRACTED requests are ever started.
"""
import argparse
import base64
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = 'https://api.github.com'
RID = re.compile(r'^RR-[A-Za-z0-9._-]{3,64}$')
REPO = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')
WORKFLOW = 'investigar.yml'
CORRIDA = re.compile(r'\(investigar\.yml, corrida (\d+)\)')  # the commit publish makes: "Paquete <RP> (investigar.yml, corrida <run>)"
MAIN = '&branch=main&event=workflow_dispatch'  # GitHub's own filter; ours() checks each run again
PRIORITY = {'P0': 0, 'P1': 1, 'P2': 2, 'P3': 3}
PRIVACY = ('PUBLIC', 'ABSTRACTED')  # RESEARCH_CONTRACT: nothing else ever leaves for research
ACTIVE = ('queued', 'in_progress', 'waiting', 'requested', 'pending')
MAX = 4  # HIPÓTESIS: four at once until a measured night says otherwise
RUN_LIFE = timedelta(days=35)  # GitHub ends a run held longer than 30 days: older ones cannot have ended recently
RETRY_AFTER = timedelta(days=3)  # a request whose run failed this recently waits for a person: no model call every night
SEEN_WAIT = 30  # seconds (wall clock) a dispatched run may take to appear in GitHub's list; then it is unconfirmed


def rp_of(rid):
    return 'RP-' + rid[3:]  # rg.investigar.assemble names the packet so


def iso(t):
    return t.strftime('%Y-%m-%dT%H:%M:%SZ')


def pending(requests, answered, branches, open_heads, active_titles, terminal, failed_titles=()):
    """[(request, why_not)] for every request, why_not None when it is to be started, in the order they start.
    answered: the request_ids the packets on main answer."""
    out = []
    for rq in requests:
        rid, rp = rq['request_id'], rp_of(rq['request_id'])
        why = ('not PUBLIC or ABSTRACTED' if rq.get('privacy_class') not in PRIVACY
               else 'its packet is on main' if rid in answered
               else 'marked terminal' if rid in terminal
               else 'a PR from its branch is open' if f'investigar/{rp}' in open_heads
               else 'its branch exists' if f'investigar/{rp}' in branches
               else 'a run for it is queued or running' if f'investigar {rid}' in active_titles
               else 'a run for it ended without success in the last 3 days' if f'investigar {rid}' in failed_titles
               else None)
        out.append((rq, why))
    key = lambda pair: (pair[1] is not None, PRIORITY.get(pair[0].get('priority'), 9), pair[0].get('issued_at', ''),
                        pair[0]['request_id'])
    return sorted(out, key=key)


class GitHub:
    def __init__(self, repo, token):
        self.repo, self.token = repo, token

    def call(self, path, method='GET', body=None):
        req = urllib.request.Request(f'{API}/repos/{self.repo}{path}', method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={'Accept': 'application/vnd.github+json', 'Authorization': f'Bearer {self.token}',
                                              'X-GitHub-Api-Version': '2022-11-28'})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        return json.loads(data) if data else None

    def pages(self, path, key=None):
        out, page = [], 1
        while True:
            got = self.call(f"{path}{'&' if '?' in path else '?'}per_page=100&page={page}")
            items = got[key] if key else got
            out += items
            if len(items) < 100:
                # GitHub's run search stops at 1,000 results and still says how many there are: fewer is a cut list
                if key and isinstance(got, dict) and len(out) < got.get('total_count', 0):
                    raise ValueError(f"{path}: {len(out)} of {got['total_count']} listed")
                return out
            if page >= 50:  # a full last page may hide more: no answer rather than a cut one
                raise ValueError(f'{path}: more than 50 pages')
            page += 1


def state(gh, root):
    """Everything pending() reads, from main's checkout at `root` and GitHub's API."""
    requests = []
    for f in sorted(Path(root, 'requests').glob('RR-*.json')):
        rq = json.loads(f.read_text(encoding='utf-8'))
        if RID.match(rq.get('request_id', '')) and rq['request_id'] == f.stem:
            requests.append({**rq, 'has_plan': Path(root, 'requests', 'plans', f.name).is_file()})
    answered = set()
    for f in Path(root, 'research-packets').glob('RP-*/packet.json'):
        try:
            answered.add(json.loads(f.read_text(encoding='utf-8')).get('request_id'))
        except (ValueError, AttributeError):  # a packet main holds is the gate's to judge; it answers nothing here
            pass
    terminal = {f.stem for f in Path(root, 'requests', 'terminal').glob('RR-*.json')}
    branches = {b['name'] for b in gh.pages('/branches')}
    open_heads = {p['head']['ref'] for p in gh.pages('/pulls?state=open') if p['head']['repo'] and
                  p['head']['repo']['full_name'] == gh.repo}  # into any base: holding a request back is the safe side
    active = active_titles(gh)
    now = datetime.now(timezone.utc)
    after, created = iso(now - RETRY_AFTER), iso(now - RUN_LIFE)
    # by when it ended (updated_at), not when it was created: a run held days waiting and cancelled today still counts
    failed = {r['display_title'] for r in gh.pages(f'/actions/workflows/{WORKFLOW}/runs?status=completed&created=%3E%3D{created}{MAIN}', 'workflow_runs')
              if ours(r) and r.get('conclusion') != 'success' and (r.get('updated_at') or '') >= after}  # failure, cancelled, timed_out: none retried by itself
    return requests, answered, branches, open_heads, active, terminal, failed


def from_here(gh, p):
    """A PR the morning receipt counts: its branch lives in this repository and it merges into main. A fork's branch of
    the same name, a deleted fork's (repo None) or a PR into another base is not the night's work."""
    return ((p.get('head') or {}).get('repo') or {}).get('full_name') == gh.repo and (p.get('base') or {}).get('ref') == 'main'


def ours(r):
    """A run the night itself could have started: dispatched on main. A branch can change its own investigar.yml and
    title a run "investigar RR-...", and that must neither hold a request back nor confirm a dispatch."""
    return r.get('head_branch') == 'main' and r.get('event') == 'workflow_dispatch'


def active_titles(gh):
    return {r['display_title'] for s in ACTIVE for r in gh.pages(f'/actions/workflows/{WORKFLOW}/runs?status={s}{MAIN}', 'workflow_runs')
            if ours(r)}


def despachar(gh, root, most, dry, wait=SEEN_WAIT, sleep=lambda s: time.sleep(s), save=lambda record: None):
    """The night's record: taken before the first dispatch (at, a minute early, so the morning counts every run this
    started), saved after each dispatch (save), an error kept beside the ones that worked, and each started run waited
    for until GitHub lists it, so a dispatcher after this one sees it and starts nothing twice."""
    at = iso(datetime.now(timezone.utc) - timedelta(minutes=1))
    order = pending(*state(gh, root))
    record = {'at': at, 'dry_run': dry, 'max': most, 'pending_at_start': [rq['request_id'] for rq, why in order if why is None],
              'sending': None, 'started': [], 'failed_to_start': [], 'unconfirmed': [],
              'skipped': [{'request_id': rq['request_id'], 'why': why} for rq, why in order if why is not None]}
    save(record)
    for rq in [rq for rq, why in order if why is None][:most]:
        entry = {'request_id': rq['request_id'], 'discover': not rq['has_plan']}
        if dry:
            record['started'].append(entry)
            continue
        record['sending'] = entry  # saved before the call: a step killed mid-send still says which request was in flight
        save(record)
        try:
            gh.call(f'/actions/workflows/{WORKFLOW}/dispatches', 'POST',
                    {'ref': 'main', 'inputs': {'request_id': rq['request_id'], 'discover': 'false' if rq['has_plan'] else 'true'}})
        except (urllib.error.URLError, OSError) as e:  # one that fails never loses the record of the others
            if seen(gh, at, f"investigar {rq['request_id']}", wait, sleep):  # the answer was lost, the run was not
                record['started'].append({**entry, 'error': type(e).__name__})
            else:
                record['failed_to_start'].append({**entry, 'error': type(e).__name__})
            record['sending'] = None
            continue  # saved with the next send, or the last save
        record['started'].append(entry)
        record['sending'] = None
        save(record)  # started, before the wait: a step killed while waiting still says so
        if not seen(gh, at, f"investigar {rq['request_id']}", wait, sleep):
            record['unconfirmed'].append(rq['request_id'])  # saved with the next send, or the last save
    save(record)  # the last one: also a dry run's would-start list
    return record


def seen(gh, since, title, wait, sleep):
    """True once GitHub lists a run of that name created since `since` (queued, running or already over); False when
    `wait` seconds of wall clock are over (one more read may be under way) or GitHub cannot be read."""
    end = time.monotonic() + wait
    while True:
        try:
            if title in listed(gh, since):
                return True
        except (urllib.error.URLError, OSError):  # unreadable now is not seen: recorded as unconfirmed
            pass
        if time.monotonic() >= end:
            return False
        sleep(min(10, max(0, end - time.monotonic())))


def listed(gh, since):
    """The run-names of every investigar run GitHub lists as created since `since`, whatever its status."""
    return {r['display_title'] for r in gh.pages(f'/actions/workflows/{WORKFLOW}/runs?created=%3E%3D{since}{MAIN}', 'workflow_runs') if ours(r)}


def _secs(a, b):
    f = lambda t: datetime.fromisoformat(t.replace('Z', '+00:00'))
    return round((f(b) - f(a)).total_seconds()) if a and b else None


UNREAD = 'UNREAD'  # the receipt could not be read: the night's count of packets with gaps is not complete


def _stop(gh, rp, sha):
    """The discovery's stop (ENOUGH_FOR_PACKET or STOPPED_WITH_GAPS) in the packet's receipt at that commit; None when
    that commit has no receipt (GitHub answers 404); UNREAD when it could not be read (any other answer, the network, a
    receipt that is not JSON), so a 429 or a 500 never reads as a packet without gaps."""
    try:
        got = gh.call(f'/contents/research-packets/{rp}/receipt.json?ref={sha}')
    except urllib.error.HTTPError as e:
        return None if e.code == 404 else UNREAD
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException):  # IncompleteRead: a body cut short
        return UNREAD
    try:
        receipt = json.loads(base64.b64decode(got["content"]))
        return (receipt.get('discovery') or {}).get('stop')
    except (TypeError, KeyError, ValueError, AttributeError):  # no content, not base64, not JSON, not an object
        return UNREAD


def packets_by_run(gh, prs):
    """Run id -> (packet, head sha), read from the commit publish makes on every investigar/ branch and every packet PR's
    head, so a packet published without a PR (no App, or the PR failed to open) is found too. A head whose commit
    cannot be read names no run: that run's packet then counts as unread."""
    heads = {(p['head']['ref'], p['head']['sha']) for p in prs}
    heads |= {(r['ref'].removeprefix('refs/heads/'), r['object']['sha']) for r in gh.pages('/git/matching-refs/heads/investigar/')}
    out = {}
    for ref, sha in sorted(heads):
        try:
            m = CORRIDA.search(gh.call(f'/git/commits/{sha}')['message'])
        except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException, TypeError, KeyError):
            continue
        if m:
            out[int(m.group(1))] = (ref.split('/', 1)[1], sha)
    return out


def audited(gh, sha, ref):
    """Both auditors passed this head: the newest run of auditor.yml for pull_request_target on that commit and branch
    (the trusted run automerge reads, SECURITY T15) has a pass-both job that succeeded. GitHub empties a run's
    pull_requests once its PR is merged, so the branch, which GitHub sets, names the PR. A check of that name posted by
    anything else, or an older pass followed by a REVISE, does not count."""
    runs = [r for r in gh.pages(f'/actions/workflows/auditor.yml/runs?head_sha={sha}&event=pull_request_target', 'workflow_runs')
            if r.get('path') == '.github/workflows/auditor.yml' and r.get('event') == 'pull_request_target'
            and r.get('head_sha') == sha and r.get('head_branch') == ref
            and (r.get('head_repository') or {}).get('full_name') == gh.repo]  # a fork's run of that branch and commit is not this PR's
    if not runs:
        return False
    newest = max(runs, key=lambda r: r.get('id', 0))
    return any(j.get('name') == 'pass-both' and j.get('conclusion') == 'success'
               for j in gh.pages(f"/actions/runs/{newest['id']}/jobs", 'jobs'))


def resumen(gh, since, despacho=None):
    """The morning receipt: what the night's dispatch started (despacho, its record), the investigar runs created since
    `since` with each stage's time, and the packet PRs: opened by whom, audited (pass-both), merged, and how each
    discovery ended."""
    runs = [r for r in gh.pages(f'/actions/workflows/{WORKFLOW}/runs?created=%3E%3D{since}{MAIN}', 'workflow_runs') if ours(r)]
    rows = []
    for r in runs:
        jobs = gh.pages(f"/actions/runs/{r['id']}/jobs", 'jobs')
        rows.append({'run': r['id'], 'title': r['display_title'], 'event': r['event'], 'conclusion': r['conclusion'],
                     'status': r['status'], 'stages': {j['name']: {'conclusion': j['conclusion'], 's': _secs(j['started_at'], j['completed_at'])}
                                                      for j in jobs}})
    prs = [p for p in gh.pages('/pulls?state=all&sort=created&direction=desc')
           if p['head']['ref'].startswith('investigar/') and p['created_at'] >= since and from_here(gh, p)]
    opened = []
    for p in prs:
        rp, sha = p['head']['ref'].split('/', 1)[1], p['head']['sha']
        opened.append({'number': p['number'], 'packet': rp, 'by': p['user']['login'], 'bot': p['user']['type'] == 'Bot',
                       'audits_passed': audited(gh, sha, p['head']['ref']),
                       'merged': bool(p.get('merged_at')), 'stop': _stop(gh, rp, sha)})
    found = packets_by_run(gh, prs)
    packets = []  # every packet the night published, whether or not its PR was opened
    for x in rows:
        if x['stages'].get('publish', {}).get('conclusion') == 'success':
            rp_sha = found.get(x['run'])
            packets.append({'run': x['run'], 'packet': rp_sha[0] if rp_sha else None,
                            'stop': _stop(gh, *rp_sha) if rp_sha else UNREAD})  # not found is not read
    gaps = {o['packet'] for o in packets + opened if o['stop'] == 'STOPPED_WITH_GAPS'}
    unread = {o['packet'] or f"corrida {o['run']}" for o in packets + opened if o['stop'] == UNREAD}
    despacho = despacho or {}
    return {'since': since, 'pending_at_start': despacho.get('pending_at_start'), 'dispatched': despacho.get('started'),
            'failed_to_start': despacho.get('failed_to_start'), 'unconfirmed': despacho.get('unconfirmed'),
            'in_flight_when_cut': despacho.get('sending'),
            'started': len(rows), 'completed': sum(1 for x in rows if x['status'] == 'completed'),
            'failed': [x['title'] for x in rows if x['status'] == 'completed' and x['conclusion'] != 'success'],  # cancelled and timed out too
            'packets_produced': sum(1 for x in rows if x['stages'].get('publish', {}).get('conclusion') == 'success'),
            'stopped_with_gaps': sorted(gaps),
            'stop_unread': sorted(unread), 'packets': packets,
            'prs_opened': opened, 'audits_passed': sum(o['audits_passed'] for o in opened),
            'packets_merged': sum(o['merged'] for o in opened),
            'manual_interventions': {'pr_openings': sum(not o['bot'] for o in opened)}, 'runs': rows}


def markdown(night):
    lines = [f"# Noche desde {night['since']}", '',
             f"- corridas iniciadas: {night['started']}; terminadas: {night['completed']}; fallidas: {len(night['failed'])}",
             f"- pendientes al empezar: {len(night['pending_at_start'] or [])}; despachadas: {len(night['dispatched'] or [])}; "
             f"envíos fallidos: {len(night['failed_to_start'] or [])}; sin confirmar: {len(night['unconfirmed'] or [])}",
             f"- envío en vuelo cuando se cortó el despacho: {(night.get('in_flight_when_cut') or {}).get('request_id', 'ninguno')}",
             f"- paquetes producidos: {night['packets_produced']}; con huecos (STOPPED_WITH_GAPS): {len(night['stopped_with_gaps'])}"
             + (f"; recibos sin leer, la cuenta de huecos está incompleta: {', '.join(night['stop_unread'])}" if night['stop_unread'] else ''),
             f"- PRs abiertos: {len(night['prs_opened'])}; auditorías pasadas: {night['audits_passed']}; fusionados: {night['packets_merged']}",
             f"- intervenciones manuales (PRs abiertos a mano): {night['manual_interventions']['pr_openings']}", '']
    if night.get('despacho_problem'):
        lines.insert(2, f"- registro del despacho: {night['despacho_problem']}; la noche se cuenta con lo que GitHub lista")
    for x in night['runs']:
        stages = ', '.join(f"{k} {v['conclusion']} {v['s']}s" for k, v in x['stages'].items())
        lines.append(f"- {x['title']} ({x['conclusion']}): {stages}")
    return '\n'.join(lines) + '\n'


def keep(path, text):
    """Replaces path with text whole: a step cut mid-write leaves the previous record, never half of one."""
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    os.replace(tmp, path)


ISO = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')


def read_despacho(path, run, listing):
    """The dispatch record the morning reads, and what kept it from reading one (GPT on b262a77): GitHub not listing
    the dispatch runs, or a run found whose record is missing or is not a record. No dispatch run at all is no problem:
    nothing was sent."""
    if listing != 'ok':
        return None, 'GitHub no listó las corridas del despacho'
    if not run:
        return None, None
    if not run.isdigit():
        return None, 'el id de la corrida del despacho no es un número'
    try:
        record = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return None, f'el registro del despacho de la corrida {run} no se pudo leer'
    if not isinstance(record, dict) or not ISO.match(str(record.get('at', ''))):
        return None, f'el registro del despacho de la corrida {run} no es un registro'
    return record, None


def main(argv=None):
    a = argparse.ArgumentParser(description='start the pending investigations; report the night')
    sub = a.add_subparsers(dest='cmd', required=True)
    d = sub.add_parser('despachar')
    d.add_argument('--max', type=int, default=MAX)
    d.add_argument('--dry-run', action='store_true')
    d.add_argument('--root', default='.')
    r = sub.add_parser('resumen')
    r.add_argument('--since', help='YYYY-MM-DDTHH:MM:SSZ; by default the dispatch record\'s time, else 24 hours ago')
    r.add_argument('--despacho', help="the night's dispatch record (noche.py despachar's output)")
    r.add_argument('--despacho-run', default='', help='the run that record was downloaded from; empty when none was found')
    r.add_argument('--despacho-listado', choices=('ok', 'fallo'), default='ok', help='whether GitHub listed the dispatch runs')
    r.add_argument('--out', required=True)
    x = a.parse_args(argv)
    repo, token = os.environ.get('REPO', ''), os.environ.get('GH_TOKEN', '')
    if not REPO.match(repo) or not token:
        raise SystemExit('REPO and GH_TOKEN are required')
    gh = GitHub(repo, token)
    if x.cmd == 'despachar':
        if not 0 <= x.max <= 10:
            raise SystemExit('--max is 0-10')
        out = Path('despacho.json')
        record = despachar(gh, x.root, x.max, x.dry_run,
                           save=lambda r: keep(out, json.dumps(r, ensure_ascii=False, indent=1) + '\n'))
        print(json.dumps(record, ensure_ascii=False, indent=1))
        return 1 if record['failed_to_start'] or record['unconfirmed'] else 0  # red, the record uploaded anyway
    if x.since is not None and not ISO.match(x.since):
        raise SystemExit('--since YYYY-MM-DDTHH:MM:SSZ')
    Path(x.out).mkdir(parents=True, exist_ok=True)
    try:
        despacho, problem = read_despacho(x.despacho, x.despacho_run, x.despacho_listado)
        since = x.since or (despacho or {}).get('at') or iso(datetime.now(timezone.utc) - timedelta(hours=24))
        night = resumen(gh, since, despacho)
        night['despacho_problem'] = problem
    except Exception as e:  # noqa: BLE001 - GitHub failing midway still leaves a record that says the night is not known
        note = f'{type(e).__name__}: {str(e)[:200]}'
        keep(Path(x.out, 'noche.json'), json.dumps({'since': x.since, 'error': note}, ensure_ascii=False, indent=1) + '\n')
        keep(Path(x.out, 'noche.md'), f"# Noche desde {x.since}\n\nEl resumen no se pudo completar ({note}): nada de esta noche está contado.\n")
        print(f'resumen incompleto: {note}')
        return 1
    keep(Path(x.out, 'noche.json'), json.dumps(night, ensure_ascii=False, indent=1) + '\n')  # replaces the step's provisional one
    keep(Path(x.out, 'noche.md'), markdown(night))
    print(markdown(night))
    return 1 if night['stop_unread'] or night['despacho_problem'] else 0  # red, the receipt uploaded anyway


if __name__ == '__main__':
    sys.exit(main())
