"""scripts/noche.py: the night picks pending requests from Git's own state and reports.

Built here (CONSTRUIDO): request files in a temporary main checkout and a fake GitHub that records every call.
"""
import base64
import http.client
import importlib.util
import json
import os
import tempfile
import unittest
import unittest.mock
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('noche', ROOT / 'scripts' / 'noche.py')
noche = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(noche)


def rq(rid, priority='P2', issued='2026-10-21T00:00:00Z', privacy='PUBLIC', plan=False):
    return {'request_id': rid, 'priority': priority, 'issued_at': issued, 'privacy_class': privacy, 'has_plan': plan}


class Pending(unittest.TestCase):
    def test_only_what_nothing_covers_is_started_by_priority_then_age_then_id(self):
        requests = [rq('RR-2026-10-21-c', 'P2', '2026-10-21T00:00:00Z'), rq('RR-2026-10-21-a', 'P1', '2026-10-22T00:00:00Z'),
                    rq('RR-2026-10-21-b', 'P1', '2026-10-20T00:00:00Z'), rq('RR-2026-10-21-d', 'P0', '2026-10-25T00:00:00Z'),
                    rq('RR-2026-10-21-e'), rq('RR-2026-10-21-f'), rq('RR-2026-10-21-g'), rq('RR-2026-10-21-h'),
                    rq('RR-2026-10-21-i'), rq('RR-2026-10-21-j', privacy='INTERNAL'), rq('RR-2026-10-21-k', 'P0', privacy='ABSTRACTED')]
        got = noche.pending(requests, answered={'RR-2026-10-21-e'}, branches={'investigar/RP-2026-10-21-f', 'investigar/RP-2026-10-21-g'},
                            open_heads={'investigar/RP-2026-10-21-g'}, active_titles={'investigar RR-2026-10-21-h'},
                            terminal={'RR-2026-10-21-i'})
        self.assertEqual([(r['request_id'], why) for r, why in got], [
            ('RR-2026-10-21-k', None), ('RR-2026-10-21-d', None), ('RR-2026-10-21-b', None), ('RR-2026-10-21-a', None),
            ('RR-2026-10-21-c', None),
            ('RR-2026-10-21-e', 'its packet is on main'), ('RR-2026-10-21-f', 'its branch exists'),
            ('RR-2026-10-21-g', 'a PR from its branch is open'), ('RR-2026-10-21-h', 'a run for it is queued or running'),
            ('RR-2026-10-21-i', 'marked terminal'), ('RR-2026-10-21-j', 'not PUBLIC or ABSTRACTED')])

    def test_a_request_whose_run_failed_recently_waits_for_a_person(self):
        got = noche.pending([rq('RR-2026-10-21-a'), rq('RR-2026-10-21-b')], set(), set(), set(), set(), set(),
                            failed_titles={'investigar RR-2026-10-21-a'})
        self.assertEqual([(r['request_id'], why) for r, why in got],
                         [('RR-2026-10-21-b', None), ('RR-2026-10-21-a', 'a run for it ended without success in the last 3 days')])


class FakeGitHub:
    def __init__(self, repo='o/r', **routes):
        self.repo, self.routes, self.calls = repo, routes, []

    def pages(self, path, key=None):
        self.calls.append(('GET', path))
        got = self.routes.get(path.split('?')[0] + ('?' + path.split('?')[1] if '?' in path else ''), [])
        return got

    def call(self, path, method='GET', body=None):
        self.calls.append((method, path, body))
        got = self.routes.get(path)
        if isinstance(got, Exception):
            raise got
        if got is None and path.startswith('/contents/'):  # GitHub answers 404 for a file the commit does not have
            raise urllib.error.HTTPError(path, 404, 'Not Found', {}, None)
        if got is None and path.startswith('/git/matching-refs/'):  # and an empty list when no ref matches
            return []
        return got



class Titulo(unittest.TestCase):
    def test_the_title_the_dispatcher_looks_for_is_the_run_name_of_investigar(self):
        # the Claude auditor on 4a45cd8: GitHub titles a dispatch by its run-name, or by the workflow's name without one
        wf = yaml.safe_load((Path(__file__).resolve().parents[1] / '.github' / 'workflows' / 'investigar.yml').read_text())
        rid = 'RR-2026-11-01-ejemplo'
        self.assertEqual(wf['run-name'].replace('${{ inputs.request_id }}', rid), noche.titulo(rid))

class Despachar(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / 'requests' / 'plans').mkdir(parents=True)
        (self.root / 'requests' / 'terminal').mkdir()
        # a packet named for another day still answers its request: what counts is its request_id
        (self.root / 'research-packets' / 'RP-2026-10-22-hecho').mkdir(parents=True)
        (self.root / 'research-packets' / 'RP-2026-10-22-hecho' / 'packet.json').write_text(json.dumps({'request_id': 'RR-2026-10-21-hecho'}))
        (self.root / 'research-packets' / 'RP-2026-10-21-roto').mkdir()
        (self.root / 'research-packets' / 'RP-2026-10-21-roto' / 'packet.json').write_text('[')
        for rid, extra in (('RR-2026-10-21-con-plan', {'priority': 'P1'}), ('RR-2026-10-21-sin-plan', {'priority': 'P0'}),
                           ('RR-2026-10-21-hecho', {}), ('RR-2026-10-21-cerrado', {}), ('RR-2026-10-21-privado', {'privacy_class': 'INTERNAL'})):
            (self.root / 'requests' / f'{rid}.json').write_text(json.dumps({'request_id': rid, 'issued_at': '2026-10-21T00:00:00Z',
                                                                           'privacy_class': 'PUBLIC', 'priority': 'P2', **extra}))
        (self.root / 'requests' / 'RR-2026-10-21-otro-nombre.json').write_text(json.dumps({'request_id': 'RR-2026-10-21-x'}))
        (self.root / 'requests' / 'plans' / 'RR-2026-10-21-con-plan.json').write_text('{}')
        (self.root / 'requests' / 'terminal' / 'RR-2026-10-21-cerrado.json').write_text('{}')
        self.gh = FakeGitHub(**{'/branches': [{'name': 'main'}], '/pulls?state=open': [],
                                **{f'/actions/workflows/investigar.yml/runs?status={s}{noche.MAIN}': {'workflow_runs': []} for s in noche.ACTIVE}})
        self.gh.pages, self.gh.call = self.pages, self.call
        self.created, self.failed, self.dispatched_at, self.refuse, self.hide, self.lost = [], [], [], set(), False, set()
        self.saved, self.at_send = [], []
        self.clock = [0.0]
        tick = unittest.mock.patch.object(noche.time, 'monotonic', lambda: self.clock[0])
        tick.start()
        self.addCleanup(tick.stop)
        self.sleep = lambda s: self.clock.__setitem__(0, self.clock[0] + s)
        nap = unittest.mock.patch.object(noche.time, 'sleep', self.sleep)  # no test waits for real
        nap.start()
        self.addCleanup(nap.stop)

    def pages(self, path, key=None):
        self.gh.calls.append(('GET', path))
        runs = '/actions/workflows/investigar.yml/runs?'
        if path.startswith(runs + 'status=completed&created=%3E%3D'):
            self.created_since = path.rsplit('%3E%3D', 1)[1]
            return [{'display_title': t, 'conclusion': c, 'updated_at': e, 'head_branch': 'main', 'event': 'workflow_dispatch', **o}
                    for t, c, e, *rest in self.failed for o in [rest[0] if rest else {}]]
        if path.startswith(runs + 'created=%3E%3D'):  # what GitHub lists right after a dispatch, unless hidden
            return [] if self.hide else [{'display_title': t, 'head_branch': 'main', 'event': 'workflow_dispatch'} for t in self.created]
        got = self.gh.routes.get(path, [])
        return got[key] if key else got

    def call(self, path, method='GET', body=None):
        self.gh.calls.append((method, path, body))
        if method == 'POST':
            rid = body['inputs']['request_id']
            self.at_send.append((rid, json.loads(self.saved[-1]) if self.saved else None))
            if rid in self.refuse:
                raise urllib.error.HTTPError(path, 500, 'Server Error', None, None)
            if rid in getattr(self, 'cut', ()):  # the answer came back cut short and nothing started
                raise http.client.IncompleteRead(b'{"')
            if rid in self.lost:  # GitHub started it but the answer never came back
                self.created.append(f'investigar {rid}')
                raise getattr(self, 'lost_error', None) or urllib.error.URLError('timed out')
            self.dispatched_at.append(noche.iso(datetime.now(timezone.utc)))
            self.created.append(f'investigar {rid}')

    def test_it_starts_the_pending_ones_with_discover_only_without_a_plan(self):
        record = noche.despachar(self.gh, self.root, 4, False)
        self.assertEqual(record['pending_at_start'], ['RR-2026-10-21-sin-plan', 'RR-2026-10-21-con-plan'])
        self.assertEqual(record['started'], [{'request_id': 'RR-2026-10-21-sin-plan', 'discover': True},
                                             {'request_id': 'RR-2026-10-21-con-plan', 'discover': False}])
        posts = [c for c in self.gh.calls if c[0] == 'POST']
        self.assertEqual(posts, [('POST', '/actions/workflows/investigar.yml/dispatches',
                                  {'ref': 'main', 'inputs': {'request_id': 'RR-2026-10-21-sin-plan', 'discover': 'true'}}),
                                 ('POST', '/actions/workflows/investigar.yml/dispatches',
                                  {'ref': 'main', 'inputs': {'request_id': 'RR-2026-10-21-con-plan', 'discover': 'false'}})])
        self.assertEqual({s['request_id']: s['why'] for s in record['skipped']},
                         {'RR-2026-10-21-hecho': 'its packet is on main', 'RR-2026-10-21-cerrado': 'marked terminal',
                          'RR-2026-10-21-privado': 'not PUBLIC or ABSTRACTED'})  # a file named for another id is no request

    def test_at_most_max_start_and_a_dry_run_starts_nothing(self):
        self.assertEqual(len(noche.despachar(self.gh, self.root, 1, False)['started']), 1)
        self.gh.calls.clear()
        saved = []
        record = noche.despachar(self.gh, self.root, 4, True, save=lambda r: saved.append(json.dumps(r)))
        self.assertEqual(len(record['started']), 2)
        self.assertEqual(json.loads(saved[-1]), record)  # the file holds what a dry run would start
        self.assertEqual([c for c in self.gh.calls if c[0] == 'POST'], [])

    def test_the_record_is_taken_a_minute_before_the_first_dispatch(self):
        record = noche.despachar(self.gh, self.root, 4, False)
        at = datetime.fromisoformat(record['at'].replace('Z', '+00:00'))
        first = datetime.fromisoformat(self.dispatched_at[0].replace('Z', '+00:00'))
        self.assertGreaterEqual((first - at).total_seconds(), 60)  # the morning, reading runs created since `at`, sees them all

    def test_a_branch_or_an_open_pr_of_this_repo_holds_a_request_back_and_a_fork_does_not(self):
        (self.root / 'requests' / 'RR-2026-10-21-tercero.json').write_text(json.dumps({'request_id': 'RR-2026-10-21-tercero',
            'issued_at': '2026-10-21T00:00:00Z', 'privacy_class': 'PUBLIC', 'priority': 'P2'}))
        self.gh.routes['/branches'] = [{'name': 'main'}, {'name': 'investigar/RP-2026-10-21-con-plan'}]
        self.gh.routes['/pulls?state=open'] = [
            {'head': {'ref': 'investigar/RP-2026-10-21-sin-plan', 'repo': {'full_name': 'o/r'}}},
            {'head': {'ref': 'investigar/RP-2026-10-21-tercero', 'repo': {'full_name': 'otro/r'}}},  # a fork's branch of that name
            {'head': {'ref': 'investigar/RP-2026-10-21-tercero', 'repo': None}}]  # its repository deleted
        record = noche.despachar(self.gh, self.root, 4, False, wait=0, sleep=self.sleep)
        why = {s['request_id']: s['why'] for s in record['skipped']}
        self.assertEqual((why['RR-2026-10-21-con-plan'], why['RR-2026-10-21-sin-plan']), ('its branch exists', 'a PR from its branch is open'))
        self.assertEqual([s['request_id'] for s in record['started']], ['RR-2026-10-21-tercero'])

    def test_a_run_from_another_branch_or_event_neither_holds_back_nor_confirms(self):
        other = {'head_branch': 'rama', 'event': 'push'}
        self.gh.routes[f'/actions/workflows/investigar.yml/runs?status=queued{noche.MAIN}'] = {
            'workflow_runs': [{'display_title': 'investigar RR-2026-10-21-sin-plan', **other}]}
        now = noche.iso(datetime.now(timezone.utc))
        self.failed = [('investigar RR-2026-10-21-con-plan', 'failure', now, other)]
        record = noche.despachar(self.gh, self.root, 4, False, wait=0, sleep=self.sleep)
        self.assertEqual([s['request_id'] for s in record['started']], ['RR-2026-10-21-sin-plan', 'RR-2026-10-21-con-plan'])
        self.assertTrue(all(c[1].endswith(noche.MAIN) for c in self.gh.calls if c[0] == 'GET' and '/runs?' in c[1]))
        self.assertFalse(noche.ours({'head_branch': 'main', 'event': 'push'}))

    def test_a_listing_longer_than_50_pages_is_no_answer(self):
        full = [{'name': 'x'}] * 100
        gh = noche.GitHub('o/r', 't')
        with unittest.mock.patch.object(gh, 'call', side_effect=lambda path: full):
            with self.assertRaises(ValueError):
                gh.pages('/branches')
        with unittest.mock.patch.object(gh, 'call', side_effect=lambda path: full if path.endswith('page=1') else []):
            self.assertEqual(len(gh.pages('/branches')), 100)
        runs = lambda path: {'total_count': 1500, 'workflow_runs': [{}] * 100 if not path.endswith('page=11') else []}
        with unittest.mock.patch.object(gh, 'call', side_effect=runs), self.assertRaises(ValueError):
            gh.pages('/actions/workflows/investigar.yml/runs?status=completed', 'workflow_runs')  # GitHub stopped at 1,000
        whole = lambda path: {'total_count': 120, 'workflow_runs': [{}] * (100 if path.endswith('page=1') else 20)}
        with unittest.mock.patch.object(gh, 'call', side_effect=whole):
            self.assertEqual(len(gh.pages('/actions/workflows/investigar.yml/runs', 'workflow_runs')), 120)

    def test_the_request_in_flight_and_each_unconfirmed_one_are_saved_before_the_next_send(self):
        self.hide = True  # GitHub lists nothing: the first is unconfirmed before the second is sent
        noche.despachar(self.gh, self.root, 4, False, wait=10, sleep=self.sleep, save=lambda r: self.saved.append(json.dumps(r)))
        (first, before_first), (second, before_second) = self.at_send
        self.assertEqual(before_first['sending'], {'request_id': first, 'discover': True})  # on disk while the call is out
        self.assertEqual(before_second['sending']['request_id'], second)
        self.assertEqual(before_second['unconfirmed'], [first])
        self.assertIsNone(json.loads(self.saved[-1])['sending'])

    def test_a_step_killed_while_waiting_has_saved_the_run_it_started(self):
        def killed(path, key=None):
            if 'created=' in path and 'status=' not in path:
                raise SystemExit('the step ran out of time')
            return self.pages(path, key)
        self.gh.pages = killed
        with self.assertRaises(SystemExit):
            noche.despachar(self.gh, self.root, 4, False, wait=10, sleep=self.sleep, save=lambda r: self.saved.append(json.dumps(r)))
        last = json.loads(self.saved[-1])
        self.assertEqual((last['started'], last['sending']), ([{'request_id': 'RR-2026-10-21-sin-plan', 'discover': True}], None))

    def test_one_failed_dispatch_keeps_the_others_and_every_step_is_saved(self):
        self.refuse = {'RR-2026-10-21-sin-plan'}
        saved, posts = [], lambda: sum(c[0] == 'POST' for c in self.gh.calls)
        record = noche.despachar(self.gh, self.root, 4, False, save=lambda r: saved.append((posts(), json.dumps(r))))
        self.assertEqual(record['failed_to_start'], [{'request_id': 'RR-2026-10-21-sin-plan', 'discover': True, 'error': 'HTTPError'}])
        self.assertEqual(record['started'], [{'request_id': 'RR-2026-10-21-con-plan', 'discover': False}])
        # saved before anything starts, after the failure and before the next dispatch, and at the end
        self.assertEqual(json.loads(saved[0][1])['started'], [])
        self.assertIn((1, ['RR-2026-10-21-sin-plan']), [(n, [f['request_id'] for f in json.loads(x)['failed_to_start']]) for n, x in saved])
        self.assertEqual(json.loads(saved[-1][1]), record)

    def test_a_run_github_never_lists_is_unconfirmed_after_a_bounded_wait(self):
        self.hide = True
        record = noche.despachar(self.gh, self.root, 1, False, wait=30, sleep=self.sleep)
        self.assertEqual((record['unconfirmed'], self.clock[0]), (['RR-2026-10-21-sin-plan'], 30))  # 30 s of clock, not of reads
        self.hide = False
        self.assertEqual(noche.despachar(self.gh, self.root, 4, False, wait=30, sleep=self.sleep)['unconfirmed'], [])

    def test_a_request_whose_run_ended_without_success_recently_is_not_started_again(self):
        now = datetime.now(timezone.utc)
        recent, old = noche.iso(now - noche.timedelta(hours=2)), noche.iso(now - noche.timedelta(days=4))
        # one created weeks ago, held, cancelled two hours ago: it ended recently, so it waits; one that failed four days
        # ago and one that succeeded do not
        self.failed = [('investigar RR-2026-10-21-sin-plan', 'cancelled', recent), ('investigar RR-2026-10-21-con-plan', 'success', recent),
                       ('investigar RR-2026-10-21-con-plan', 'failure', old)]
        record = noche.despachar(self.gh, self.root, 4, False, wait=0, sleep=self.sleep)
        self.assertEqual([s['request_id'] for s in record['started']], ['RR-2026-10-21-con-plan'])
        self.assertLessEqual(self.created_since, noche.iso(now - noche.timedelta(days=30)))  # the listing reaches back past a held run's life
        self.assertIn({'request_id': 'RR-2026-10-21-sin-plan', 'why': 'a run for it ended without success in the last 3 days'},
                      record['skipped'])

    def test_a_dispatch_whose_answer_was_lost_but_whose_run_exists_is_started(self):
        self.lost = {'RR-2026-10-21-sin-plan'}
        record = noche.despachar(self.gh, self.root, 4, False, wait=10, sleep=self.sleep)
        self.assertEqual(record['failed_to_start'], [])
        self.assertEqual(record['started'][0], {'request_id': 'RR-2026-10-21-sin-plan', 'discover': True, 'error': 'URLError'})

    def test_an_answer_cut_short_on_send_is_a_lost_answer_and_the_next_request_is_still_sent(self):
        # GPT on 8400549: http.client.IncompleteRead is an HTTPException, neither URLError nor OSError
        self.lost, self.lost_error = {'RR-2026-10-21-sin-plan'}, http.client.IncompleteRead(b'{"')
        record = noche.despachar(self.gh, self.root, 4, False, wait=10, sleep=self.sleep)
        self.assertEqual(record['started'], [{'request_id': 'RR-2026-10-21-sin-plan', 'discover': True, 'error': 'IncompleteRead'},
                                             {'request_id': 'RR-2026-10-21-con-plan', 'discover': False}])
        self.cut = {'RR-2026-10-21-con-plan'}
        self.lost, self.created = set(), []
        record = noche.despachar(self.gh, self.root, 4, False, wait=10, sleep=self.sleep)
        self.assertIn({'request_id': 'RR-2026-10-21-con-plan', 'discover': False, 'error': 'IncompleteRead'}, record['failed_to_start'])

    def test_a_listing_cut_short_while_waiting_is_unconfirmed_not_a_crash(self):
        def broken(path, key=None):
            if 'created=' in path and 'status=' not in path:
                raise http.client.IncompleteRead(b'[')
            return self.pages(path, key)
        self.gh.pages = broken
        record = noche.despachar(self.gh, self.root, 4, False, wait=10, sleep=self.sleep)
        self.assertEqual(record['unconfirmed'], ['RR-2026-10-21-sin-plan', 'RR-2026-10-21-con-plan'])

    def test_github_unreadable_while_waiting_is_unconfirmed_not_a_crash(self):
        def broken(path, key=None):
            if 'created=' in path and 'status=' not in path:
                raise urllib.error.URLError('down')
            return self.pages(path, key)
        self.gh.pages = broken
        record = noche.despachar(self.gh, self.root, 4, False, wait=10, sleep=self.sleep)
        self.assertEqual(record['unconfirmed'], ['RR-2026-10-21-sin-plan', 'RR-2026-10-21-con-plan'])

    def test_the_command_saves_the_record_and_ends_red_when_a_dispatch_failed(self):
        self.refuse = {'RR-2026-10-21-sin-plan'}
        here = os.getcwd()
        self.addCleanup(os.chdir, here)
        os.chdir(self.root)
        with unittest.mock.patch.object(noche, 'GitHub', lambda repo, token: self.gh), \
                unittest.mock.patch.dict('os.environ', {'REPO': 'o/r', 'GH_TOKEN': 't'}, clear=True), \
                unittest.mock.patch('sys.stdout'):
            self.assertEqual(noche.main(['despachar', '--root', str(self.root)]), 1)
            self.assertEqual(json.loads((self.root / 'despacho.json').read_text())['started'],
                             [{'request_id': 'RR-2026-10-21-con-plan', 'discover': False}])
            self.refuse = set()
            self.created.clear()
            (self.root / 'requests' / 'terminal' / 'RR-2026-10-21-con-plan.json').write_text('{}')
            self.assertEqual(noche.main(['despachar', '--root', str(self.root)]), 0)

    def test_a_second_dispatcher_starts_nothing_already_running(self):
        noche.despachar(self.gh, self.root, 4, False, wait=10, sleep=self.sleep)
        main = {'head_branch': 'main', 'event': 'workflow_dispatch'}
        self.gh.routes[f'/actions/workflows/investigar.yml/runs?status=queued{noche.MAIN}'] = {
            'workflow_runs': [{'display_title': 'investigar RR-2026-10-21-sin-plan', **main}, {'display_title': 'investigar RR-2026-10-21-con-plan', **main}]}
        self.gh.calls.clear()
        self.assertEqual(noche.despachar(self.gh, self.root, 4, False)['started'], [])
        self.assertEqual([c for c in self.gh.calls if c[0] == 'POST'], [])


class Resumen(unittest.TestCase):
    def test_the_morning_receipt_counts_stages_packets_prs_audits_and_merges(self):
        receipt = base64.b64encode(json.dumps({'discovery': {'stop': 'STOPPED_WITH_GAPS'}}).encode()).decode()
        runs = [{'id': 3, 'display_title': 'investigar RR-2026-10-21-c', 'event': 'workflow_dispatch', 'conclusion': 'cancelled', 'status': 'completed'},
                {'id': 4, 'display_title': 'investigar RR-2026-10-21-d', 'event': 'workflow_dispatch', 'conclusion': None, 'status': 'in_progress'},
                {'id': 1, 'display_title': 'investigar RR-2026-10-21-a', 'event': 'workflow_dispatch', 'conclusion': 'success', 'status': 'completed'},
                {'id': 2, 'display_title': 'investigar RR-2026-10-21-b', 'event': 'workflow_dispatch', 'conclusion': 'failure', 'status': 'completed'}]
        job = lambda name, c: {'name': name, 'conclusion': c, 'started_at': '2026-10-27T05:30:00Z', 'completed_at': '2026-10-27T05:31:40Z'}
        runs = [{**r, 'head_branch': 'main', 'event': 'workflow_dispatch'} for r in runs] + [
            {'id': 9, 'display_title': 'investigar RR-2026-10-21-z', 'event': 'push', 'head_branch': 'rama', 'conclusion': 'failure', 'status': 'completed'}]
        routes = {f'/actions/workflows/investigar.yml/runs?created=%3E%3D2026-10-27T05:30:00Z{noche.MAIN}': {'workflow_runs': runs},
                  '/actions/runs/1/jobs': {'jobs': [job('fetch', 'success'), job('publish', 'success')]},
                  '/actions/runs/2/jobs': {'jobs': [job('fetch', 'failure')]},
                  '/pulls?state=all&sort=created&direction=desc': [
                      {'number': 70, 'head': {'ref': 'investigar/RP-2026-10-21-a', 'sha': 'a' * 40, 'repo': {'full_name': 'o/r'}}, 'base': {'ref': 'main'}, 'user': {'login': 'rg-app[bot]', 'type': 'Bot'},
                       'created_at': '2026-10-27T06:00:00Z', 'merged_at': '2026-10-27T07:00:00Z'},
                      {'number': 71, 'head': {'ref': 'investigar/RP-2026-10-21-b', 'sha': 'd' * 40, 'repo': {'full_name': 'o/r'}}, 'base': {'ref': 'main'}, 'user': {'login': 'braulio', 'type': 'User'},
                       'created_at': '2026-10-27T06:30:00Z', 'merged_at': None},
                      {'number': 69, 'head': {'ref': 'investigar/RP-2026-10-20-z', 'sha': 'b' * 40, 'repo': {'full_name': 'o/r'}}, 'base': {'ref': 'main'}, 'user': {'login': 'braulio', 'type': 'User'},
                       'created_at': '2026-10-20T06:00:00Z', 'merged_at': None},
                      {'number': 68, 'head': {'ref': 'calidad', 'sha': 'c' * 40, 'repo': {'full_name': 'o/r'}}, 'base': {'ref': 'main'}, 'user': {'login': 'x', 'type': 'User'},
                       'created_at': '2026-10-27T06:00:00Z', 'merged_at': None},
                      # a fork's branch of a packet's name, merged elsewhere, and a PR of this repo into another base: not the night's
                      {'number': 72, 'head': {'ref': 'investigar/RP-2026-10-21-a', 'sha': 'a' * 40, 'repo': {'full_name': 'otro/r'}}, 'base': {'ref': 'main'},
                       'user': {'login': 'ajeno', 'type': 'User'}, 'created_at': '2026-10-27T06:10:00Z', 'merged_at': '2026-10-27T07:10:00Z'},
                      {'number': 73, 'head': {'ref': 'investigar/RP-2026-10-21-e', 'sha': 'a' * 40, 'repo': None}, 'base': {'ref': 'main'},
                       'user': {'login': 'ajeno', 'type': 'User'}, 'created_at': '2026-10-27T06:20:00Z', 'merged_at': None},
                      {'number': 74, 'head': {'ref': 'investigar/RP-2026-10-21-f', 'sha': 'a' * 40, 'repo': {'full_name': 'o/r'}}, 'base': {'ref': 'otra'},
                       'user': {'login': 'braulio', 'type': 'User'}, 'created_at': '2026-10-27T06:40:00Z', 'merged_at': '2026-10-27T07:20:00Z'}],
                  f"/actions/workflows/auditor.yml/runs?head_sha={'a' * 40}&event=pull_request_target": {'workflow_runs': [
                      {'id': 9, 'path': '.github/workflows/auditor.yml', 'event': 'pull_request_target', 'head_sha': 'a' * 40,
                       'head_branch': 'investigar/RP-2026-10-21-a', 'head_repository': {'full_name': 'o/r'}, 'pull_requests': []}]},  # merged: GitHub empties it
                  '/actions/runs/9/jobs': {'jobs': [{'name': 'pass-both', 'conclusion': 'success'}]},
                  f"/contents/research-packets/RP-2026-10-21-a/receipt.json?ref={'a' * 40}": {'content': receipt},
                  f"/git/commits/{'a' * 40}": {'message': 'Paquete RP-2026-10-21-a (investigar.yml, corrida 1)'}}
        gh = FakeGitHub(**routes)
        gh.pages = lambda path, key=None: routes.get(path, {key: []})[key] if key else routes.get(path, [])
        night = noche.resumen(gh, '2026-10-27T05:30:00Z', {'pending_at_start': ['RR-2026-10-21-a', 'RR-2026-10-21-b'],
                                                           'started': [{'request_id': 'RR-2026-10-21-a'}, {'request_id': 'RR-2026-10-21-b'}]})
        self.assertEqual({k: night[k] for k in ('started', 'completed', 'failed', 'packets_produced', 'stopped_with_gaps',
                                                'audits_passed', 'packets_merged', 'manual_interventions')},
                         {'started': 4, 'completed': 3, 'failed': ['investigar RR-2026-10-21-c', 'investigar RR-2026-10-21-b'], 'packets_produced': 1,
                          'stopped_with_gaps': ['RP-2026-10-21-a'], 'audits_passed': 1, 'packets_merged': 1,
                          'manual_interventions': {'pr_openings': 1}})
        self.assertEqual(night['prs_opened'], [{'number': 70, 'packet': 'RP-2026-10-21-a', 'by': 'rg-app[bot]', 'bot': True,
                                                'audits_passed': True, 'merged': True, 'stop': 'STOPPED_WITH_GAPS'},
                                               {'number': 71, 'packet': 'RP-2026-10-21-b', 'by': 'braulio', 'bot': False,
                                                'audits_passed': False, 'merged': False, 'stop': None}])
        self.assertEqual(next(r for r in night['runs'] if r['run'] == 1)['stages'], {'fetch': {'conclusion': 'success', 's': 100}, 'publish': {'conclusion': 'success', 's': 100}})
        self.assertEqual(len(night['pending_at_start']), 2)
        self.assertIn('paquetes producidos: 1; con huecos (STOPPED_WITH_GAPS): 1', noche.markdown(night))

    def test_a_receipt_that_cannot_be_read_never_counts_as_a_packet_without_gaps(self):
        path = f"/contents/research-packets/RP-x/receipt.json?ref={'a' * 40}"
        good = json.dumps({'discovery': {'stop': 'STOPPED_WITH_GAPS'}}).encode()
        wrapped = '\n'.join(base64.b64encode(good).decode()[i:i + 60] for i in range(0, len(base64.b64encode(good)), 60))
        cases = {'served as GitHub serves it, wrapped every 60 characters': ({'content': wrapped + '\n'}, 'STOPPED_WITH_GAPS'),
                 'the commit has no receipt (404)': (None, None),
                 'rate limited (429)': (urllib.error.HTTPError(path, 429, 'Too Many Requests', {}, None), noche.UNREAD),
                 'GitHub failing (500)': (urllib.error.HTTPError(path, 500, 'Server Error', {}, None), noche.UNREAD),
                 'the network': (urllib.error.URLError('down'), noche.UNREAD),
                 'a receipt that is not JSON': ({'content': base64.b64encode(b'{not json').decode()}, noche.UNREAD),
                 'an answer without content': ({'message': 'x'}, noche.UNREAD),
                 'a body cut short (IncompleteRead)': (http.client.IncompleteRead(b'{"con'), noche.UNREAD)}
        for name, (answer, want) in cases.items():
            with self.subTest(name):
                self.assertEqual(noche._stop(FakeGitHub(**({path: answer} if answer is not None else {})), 'RP-x', 'a' * 40), want)

    def test_an_unread_receipt_is_listed_said_in_the_markdown_and_turns_the_step_red(self):
        sha = 'a' * 40
        routes = {'/pulls?state=all&sort=created&direction=desc': [
                      {'number': 80, 'head': {'ref': 'investigar/RP-2026-10-21-a', 'sha': sha, 'repo': {'full_name': 'o/r'}}, 'base': {'ref': 'main'},
                       'user': {'login': 'rg-app[bot]', 'type': 'Bot'}, 'created_at': '2026-10-27T06:00:00Z', 'merged_at': None}],
                  f'/contents/research-packets/RP-2026-10-21-a/receipt.json?ref={sha}': urllib.error.HTTPError('x', 500, 'Server Error', {}, None)}
        gh = FakeGitHub(**routes)
        gh.pages = lambda path, key=None: routes.get(path, {key: []})[key] if key else routes.get(path, [])
        night = noche.resumen(gh, '2026-10-27T05:30:00Z')
        self.assertEqual((night['stopped_with_gaps'], night['stop_unread']), ([], ['RP-2026-10-21-a']))
        self.assertIn('recibos sin leer, la cuenta de huecos está incompleta: RP-2026-10-21-a', noche.markdown(night))
        with tempfile.TemporaryDirectory() as d:
            for answer, code in ((routes[f'/contents/research-packets/RP-2026-10-21-a/receipt.json?ref={sha}'], 1), (None, 0)):
                with self.subTest(code=code):
                    gh.routes[f'/contents/research-packets/RP-2026-10-21-a/receipt.json?ref={sha}'] = answer  # None: no receipt, 404
                    with unittest.mock.patch.object(noche, 'GitHub', lambda repo, token: gh), \
                            unittest.mock.patch.dict('os.environ', {'REPO': 'o/r', 'GH_TOKEN': 't'}, clear=True), \
                            unittest.mock.patch('sys.stdout'):
                        self.assertEqual(noche.main(['resumen', '--since', '2026-10-27T05:30:00Z', '--out', d]), code)
                    self.assertTrue(Path(d, 'noche.json').is_file())  # written before the exit code says red

    def test_every_published_packet_is_read_with_or_without_its_pr(self):
        # GPT on 9b3aec6: without the App, publish succeeds and no PR opens; that packet's gaps must still be counted
        gaps = base64.b64encode(json.dumps({'discovery': {'stop': 'STOPPED_WITH_GAPS'}}).encode()).decode()
        runs = [{'id': i, 'display_title': f'investigar RR-2026-10-21-{c}', 'event': 'workflow_dispatch', 'head_branch': 'main',
                 'conclusion': 'success', 'status': 'completed'} for i, c in ((5, 'sin-pr'), (6, 'perdido'))]
        publish = {'jobs': [{'name': 'publish', 'conclusion': 'success', 'started_at': None, 'completed_at': None}]}
        routes = {f'/actions/workflows/investigar.yml/runs?created=%3E%3D2026-10-27T05:30:00Z{noche.MAIN}': {'workflow_runs': runs},
                  '/actions/runs/5/jobs': publish, '/actions/runs/6/jobs': publish,
                  '/git/matching-refs/heads/investigar/': [{'ref': 'refs/heads/investigar/RP-sin-pr', 'object': {'sha': 'f' * 40}},
                                                           {'ref': 'refs/heads/investigar/RP-otro', 'object': {'sha': 'e' * 40}}],
                  f"/git/commits/{'f' * 40}": {'message': 'Paquete RP-sin-pr (investigar.yml, corrida 5)'},
                  f"/git/commits/{'e' * 40}": urllib.error.HTTPError('x', 502, 'Bad Gateway', {}, None),  # names no run
                  f"/contents/research-packets/RP-sin-pr/receipt.json?ref={'f' * 40}": {'content': gaps}}
        gh = FakeGitHub(**routes)
        gh.pages = lambda path, key=None: routes.get(path, {key: []})[key] if key else routes.get(path, [])
        night = noche.resumen(gh, '2026-10-27T05:30:00Z')
        self.assertEqual(night['prs_opened'], [])
        self.assertEqual((night['packets_produced'], night['stopped_with_gaps'], night['stop_unread']),
                         (2, ['RP-sin-pr'], ['corrida 6']))  # run 6's packet was not found: not counted as without gaps
        self.assertEqual(night['packets'], [{'run': 5, 'packet': 'RP-sin-pr', 'stop': 'STOPPED_WITH_GAPS'},
                                            {'run': 6, 'packet': None, 'stop': noche.UNREAD}])

    def test_matching_refs_is_read_once_because_github_ignores_its_pages(self):
        # GPT on 194b95a, checked against GitHub on 2026-11-01: matching-refs gives the whole list for any page
        listed = [{'ref': f'refs/heads/investigar/RP-{i}', 'object': {'sha': f'{i:040x}'}} for i in range(150)]

        class Like(noche.GitHub):  # the real pages(); a call() that answers as GitHub does
            def call(self, path, method='GET', body=None):
                self.asked.append(path)
                if path.startswith('/git/matching-refs/heads/investigar/'):
                    return listed  # page and per_page ignored
                return {'message': f"Paquete RP-x (investigar.yml, corrida {int(path.rsplit('/', 1)[1], 16)})"}
        gh = Like('o/r', 't')
        gh.asked = []
        self.assertEqual(len(noche.packets_by_run(gh, [])), 150)
        self.assertEqual(sum(p.startswith('/git/matching-refs/') for p in gh.asked), 1)
        for bad in ({'message': 'Not Found'}, [{'message': 'x'}], [{'object': {'sha': 'a' * 40}}], [{'ref': 'r', 'object': {}}]):
            listed[:] = [bad] if isinstance(bad, dict) else bad
            gh.call = lambda path, *a, bad=bad: bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                noche.refs(gh, 'heads/investigar/')

    def test_the_dispatch_record_is_read_or_what_kept_it_from_being_read_is_said(self):
        # GPT on b262a77: a listing, a download or a record that fails before the night is read is said, never skipped
        with tempfile.TemporaryDirectory() as d:
            good, bad, odd = Path(d, 'bueno.json'), Path(d, 'malo.json'), Path(d, 'raro.json')
            good.write_text(json.dumps({'at': '2026-10-28T05:30:00Z', 'started': []}))
            bad.write_text('{no es json')
            odd.write_text(json.dumps(['2026-10-28T05:30:00Z']))
            sin_hora = Path(d, 'sin_hora.json')
            sin_hora.write_text(json.dumps({'started': []}))
            cases = {'GitHub did not list the dispatch runs': ((str(good), '77', 'fallo'), (None, 'GitHub no listó las corridas del despacho')),
                     'no dispatch ran: nothing was sent': ((str(good), '', 'ok'), (None, None)),
                     'a record read': ((str(good), '77', 'ok'), ({'at': '2026-10-28T05:30:00Z', 'started': []}, None)),
                     'a run whose record never arrived': ((str(Path(d, 'nada.json')), '77', 'ok'), (None, 'el registro del despacho de la corrida 77 no se pudo leer')),
                     'a record that is not JSON': ((str(bad), '77', 'ok'), (None, 'el registro del despacho de la corrida 77 no se pudo leer')),
                     'JSON that is not a record': ((str(odd), '77', 'ok'), (None, 'el registro del despacho de la corrida 77 no es un registro')),
                     'a record with no time': ((str(sin_hora), '77', 'ok'), (None, 'el registro del despacho de la corrida 77 no es un registro')),
                     'no path given': ((None, '77', 'ok'), (None, 'el registro del despacho de la corrida 77 no se pudo leer')),
                     'a run id that is not a number': ((str(good), '77; rm', 'ok'), (None, 'el id de la corrida del despacho no es un número'))}
            for name, (args, want) in cases.items():
                with self.subTest(name):
                    self.assertEqual(noche.read_despacho(*args), want)

    def test_a_dispatch_record_that_cannot_be_read_turns_the_step_red_and_the_night_still_counts(self):
        gh = FakeGitHub()
        gh.pages = lambda path, key=None: [] if key is None else []
        for args, since_from, code in ((['--despacho-run', '91', '--despacho', '/no/existe.json'], None, 1),
                                       (['--despacho-listado', 'fallo'], None, 1), ([], None, 0)):
            with self.subTest(args=args), tempfile.TemporaryDirectory() as d, \
                    unittest.mock.patch.object(noche, 'GitHub', lambda repo, token: gh), \
                    unittest.mock.patch.dict('os.environ', {'REPO': 'o/r', 'GH_TOKEN': 't'}, clear=True), unittest.mock.patch('sys.stdout'):
                self.assertEqual(noche.main(['resumen', '--out', d] + args), code)
                night = json.loads(Path(d, 'noche.json').read_text())
                self.assertEqual(bool(night['despacho_problem']), code == 1)
                self.assertRegex(night['since'], noche.ISO)  # the last 24 hours, said in the record
                if code:
                    self.assertIn('registro del despacho:', Path(d, 'noche.md').read_text())
        with tempfile.TemporaryDirectory() as d:  # with a record, the night starts when the dispatch did
            Path(d, 'despacho.json').write_text(json.dumps({'at': '2026-10-28T05:30:00Z'}))
            with unittest.mock.patch.object(noche, 'GitHub', lambda repo, token: gh), \
                    unittest.mock.patch.dict('os.environ', {'REPO': 'o/r', 'GH_TOKEN': 't'}, clear=True), unittest.mock.patch('sys.stdout'):
                self.assertEqual(noche.main(['resumen', '--out', d, '--despacho', str(Path(d, 'despacho.json')), '--despacho-run', '91']), 0)
            self.assertEqual(json.loads(Path(d, 'noche.json').read_text())['since'], '2026-10-28T05:30:00Z')

    def test_github_failing_midway_still_leaves_a_record_and_a_red_step(self):
        gh = FakeGitHub()
        gh.pages = unittest.mock.Mock(side_effect=http.client.IncompleteRead(b'{"workflow_runs": ['))
        with tempfile.TemporaryDirectory() as d, unittest.mock.patch.object(noche, 'GitHub', lambda repo, token: gh), \
                unittest.mock.patch.dict('os.environ', {'REPO': 'o/r', 'GH_TOKEN': 't'}, clear=True), unittest.mock.patch('sys.stdout'):
            self.assertEqual(noche.main(['resumen', '--since', '2026-10-27T05:30:00Z', '--out', d]), 1)
            record = json.loads(Path(d, 'noche.json').read_text())
            self.assertEqual((record['since'], record['error'].split(':')[0]), ('2026-10-27T05:30:00Z', 'IncompleteRead'))
            self.assertIn('nada de esta noche está contado', Path(d, 'noche.md').read_text())

    def test_only_the_newest_trusted_audit_run_of_that_head_and_pr_counts(self):
        sha, url = 'e' * 40, f"/actions/workflows/auditor.yml/runs?head_sha={'e' * 40}&event=pull_request_target"
        run = lambda i, **over: {'id': i, 'path': '.github/workflows/auditor.yml', 'event': 'pull_request_target', 'head_sha': sha,
                                 'head_branch': 'investigar/RP-x', 'head_repository': {'full_name': 'o/r'}, 'pull_requests': [], **over}
        jobs = {1: [{'name': 'pass-both', 'conclusion': 'success'}], 2: [{'name': 'pass-both', 'conclusion': 'skipped'}],
                3: [{'name': 'otro', 'conclusion': 'success'}]}
        for runs, want in (([run(1)], True), ([run(1), run(2)], False), ([run(3)], False),
                           ([run(1, head_branch='otra')], False), ([run(1, head_sha='f' * 40)], False),
                           ([run(1, event='pull_request')], False), ([run(1, path='.github/workflows/otro.yml')], False), ([], False),
                           ([run(1, head_repository={'full_name': 'otro/r'})], False), ([run(1, head_repository=None)], False)):
            with self.subTest(runs=runs):
                gh = FakeGitHub()
                gh.pages = lambda path, key=None: (runs if path == url else jobs[int(path.split('/')[3])])
                self.assertEqual(noche.audited(gh, sha, 'investigar/RP-x'), want)

    def test_a_record_cut_mid_write_leaves_the_previous_one_whole(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'despacho.json'
            noche.keep(out, '{"started": []}\n')
            with unittest.mock.patch('os.replace', side_effect=OSError('cut')), self.assertRaises(OSError):
                noche.keep(out, '{"started": [1]}\n')
            self.assertEqual(json.loads(out.read_text()), {'started': []})
            noche.keep(out, '{"started": [2]}\n')
            self.assertEqual(json.loads(out.read_text()), {'started': [2]})

    def test_bad_arguments_stop_before_any_call(self):
        for argv, env in ((['despachar'], {}), (['despachar', '--max', '11'], {'REPO': 'o/r', 'GH_TOKEN': 't'}),
                          (['resumen', '--since', 'ayer', '--out', 'x'], {'REPO': 'o/r', 'GH_TOKEN': 't'})):
            with self.subTest(argv), unittest.mock.patch.dict('os.environ', env, clear=True), \
                    unittest.mock.patch('urllib.request.urlopen', side_effect=AssertionError('no call')), self.assertRaises(SystemExit):
                noche.main(argv)



if __name__ == '__main__':
    unittest.main()
