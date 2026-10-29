"""scripts/consumidor.py: what a consumer that knows nothing of RG reads from Git alone (docs/OUTBOX.md).

Built here (CONSTRUIDO): a fake GitHub holding main as a list of commits, each with the files it changed, answering
what the consumer asks the way GitHub does (compare pages commits and counts them; a commit lists its files 100 a
page; a path's history is every commit that touched it, newest first).
"""
import contextlib
import hashlib
import http.client
import importlib.util
import io
import json
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('consumidor', ROOT / 'scripts' / 'consumidor.py')
cons = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cons)
REPO = 'o/r'
RP = 'RP-2026-10-23-prueba'
RAW = b'<html>la norma</html>'
SHA_RAW = hashlib.sha256(RAW).hexdigest()
RAW_PATH = f'research-packets/{RP}/raw/sha256/{SHA_RAW[:2]}/{SHA_RAW}.html'
RP_SCHEMA, SA_SCHEMA = b'{"rp": 1}', b'{"sa": 1}'
PAIR = (hashlib.sha256(RP_SCHEMA).hexdigest(), hashlib.sha256(SA_SCHEMA).hexdigest())


def sha(i):
    return f'{i:040x}'


def packet(**over):
    return json.dumps({'research_id': RP, 'request_id': 'RR-2026-10-23-prueba', 'status': 'CANDIDATE',
                       'artifacts': [{'artifact_id': 'SA-a', 'sha256': SHA_RAW, 'redistribution': 'allowed', 'url': 'https://a.gob.mx/n'},
                                     {'artifact_id': 'SA-b', 'sha256': 'd' * 64, 'redistribution': 'metadata_only', 'url': 'https://b.org/x'}],
                       **over}).encode()


def publish(rp=RP, receipt=True):
    files = [{'filename': f'research-packets/{rp}/packet.json', 'status': 'added'},
             {'filename': f'research-packets/{rp}/raw/sha256/{SHA_RAW[:2]}/{SHA_RAW}.html', 'status': 'added'}]
    return files + ([{'filename': f'research-packets/{rp}/receipt.json', 'status': 'added'}] if receipt else [])


class FakeGitHub:
    """main = [(sha, [file changes])], oldest first; since = the first commit's sha."""

    def __init__(self):
        self.main, self.blobs, self.asked, self.fail = [(sha(1), [{'filename': 'README.md', 'status': 'added'}])], {}, [], {}
        self.truncated = False

    def commit(self, files, blobs=None):
        c = sha(len(self.main) + 1)
        self.main.append((c, files))
        for path, body in (blobs or {}).items():
            self.blobs[(path, c)] = body
        return c

    def at(self, path, ref):
        """The bytes of path at ref: the last version written at or before it, None if removed or never there."""
        order = [c for c, _ in self.main]
        for c, files in reversed(self.main[:order.index(ref) + 1]):
            for f in files:
                if f['filename'] == path:
                    return None if f['status'] == 'removed' else self.blobs.get((path, c), b'x')
        return None

    def get(self, path):
        self.asked.append(path)
        for key, err in self.fail.items():
            if key in path:
                raise err
        head = self.main[-1][0]
        base, _, query = path.partition('?')
        q = dict(p.split('=', 1) for p in query.split('&')) if query else {}
        if base == f'/repos/{REPO}/commits/main':
            return {'sha': head}
        if base.startswith(f'/repos/{REPO}/compare/'):
            since = base.rsplit('/', 1)[1].split('...')[0]
            order = [c for c, _ in self.main]
            after = order[order.index(since) + 1:]
            page, per = int(q['page']), int(q['per_page'])
            return {'status': 'ahead' if after else 'identical', 'total_commits': len(after),
                    'commits': [{'sha': c} for c in after[(page - 1) * per:page * per]]}
        if base == f'/repos/{REPO}/commits':
            prefix, page = q['path'], int(q['page'])
            hits = [c for c, files in reversed(self.main)
                    if any(n == prefix or n.startswith(prefix + '/') for f in files for n in (f['filename'], f.get('previous_filename') or ''))]
            return [{'sha': c} for c in hits[(page - 1) * 100:page * 100]]
        if base.startswith(f'/repos/{REPO}/commits/'):
            c, page = base.rsplit('/', 1)[1], int(q['page'])
            files = dict(self.main)[c]
            return {'sha': c, 'files': files[(page - 1) * 100:page * 100]}
        if base.startswith(f'/repos/{REPO}/contents/research-packets/'):  # a packet folder's own listing
            where = base.split('/contents/')[1]
            present = {f['filename'] for _, files in self.main for f in files
                       if f['filename'].startswith(where + '/') and self.at(f['filename'], q['ref']) is not None}
            if not present:
                raise urllib.error.HTTPError(path, 404, 'Not Found', None, None)
            tops = sorted({p[len(where) + 1:].split('/')[0] for p in present})
            return [{'name': n, 'type': 'dir' if f'{where}/{n}' not in present else 'file', 'sha': f"tree|{where}/{n}|{q['ref']}"} for n in tops]
        if base.startswith(f'/repos/{REPO}/git/trees/tree|'):
            _, where, ref = base.split('/git/trees/')[1].split('|')
            blobs = sorted(f['filename'] for _, files in self.main for f in files
                           if f['filename'].startswith(where + '/') and self.at(f['filename'], ref) is not None)
            return {'truncated': self.truncated, 'tree': [{'path': p[len(where) + 1:], 'type': 'blob'} for p in blobs]}
        raise AssertionError(path)

    def get_raw(self, path):
        self.asked.append(path)
        for key, err in self.fail.items():
            if key in path:
                raise err
        rel, ref = path.split('/contents/')[1].split('?ref=')
        body = self.at(rel, ref)
        if body is None:
            raise urllib.error.HTTPError(path, 404, 'Not Found', None, None)
        return body


class Consumer(unittest.TestCase):
    def setUp(self):
        self.gh = FakeGitHub()
        self.since = sha(1)
        self.gh.commit([{'filename': 'schemas/research_packet.schema.json', 'status': 'added'},
                        {'filename': 'schemas/source_artifact.schema.json', 'status': 'added'}],
                       {'schemas/research_packet.schema.json': RP_SCHEMA, 'schemas/source_artifact.schema.json': SA_SCHEMA})
        self.pub = self.gh.commit(publish(), {f'research-packets/{RP}/packet.json': packet(),
                                              f'research-packets/{RP}/receipt.json': b'{"r": 1}', RAW_PATH: RAW})

    def run_it(self, accepted=(PAIR,), since=None):
        return cons.run(self.gh.get, self.gh.get_raw, REPO, since or self.since, set(accepted))

    def test_a_new_packet_arrives_with_its_publication_commit_bytes_schema_and_artifacts(self):
        self.gh.commit([{'filename': 'README.md', 'status': 'modified'}])  # main moved on after the publication
        [got], head = self.run_it()
        self.assertEqual(head, self.gh.main[-1][0])
        self.assertEqual(got, {'research_id': RP, 'request_id': 'RR-2026-10-23-prueba', 'packet_status': 'CANDIDATE', 'commit': self.pub,
                               'packet_sha256': hashlib.sha256(packet()).hexdigest(), 'receipt_sha256': hashlib.sha256(b'{"r": 1}').hexdigest(),
                               'schema': {'research_packet': PAIR[0], 'source_artifact': PAIR[1]}, 'status': 'accepted',
                               'artifacts': [{'artifact_id': 'SA-a', 'sha256': SHA_RAW, 'redistribution': 'allowed', 'url': 'https://a.gob.mx/n',
                                              'path': RAW_PATH},
                                             {'artifact_id': 'SA-b', 'sha256': 'd' * 64, 'redistribution': 'metadata_only', 'url': 'https://b.org/x',
                                              'path': None}]})
        # every byte at the publication commit, never at main's tip or a branch
        self.assertTrue(all(p.endswith(f'?ref={self.pub}') for p in self.gh.asked if '/contents/' in p))

    def test_a_schema_pair_not_accepted_fails_closed_and_says_which(self):
        [got], _ = self.run_it(accepted=())
        self.assertEqual((got['status'], got['schema']), ('schema_not_accepted', {'research_packet': PAIR[0], 'source_artifact': PAIR[1]}))
        [got], _ = self.run_it(accepted=((PAIR[0], 'e' * 64),))
        self.assertEqual(got['status'], 'schema_not_accepted')

    def test_a_packet_made_by_hand_has_no_receipt_and_still_arrives(self):
        self.gh.main[-1] = (self.pub, publish(receipt=False))
        [got], _ = self.run_it()
        self.assertEqual((got['status'], got['receipt_sha256']), ('accepted', None))

    def test_any_later_change_to_its_folder_is_reported_and_never_taken(self):
        later = {'packet.json changed': {'filename': f'research-packets/{RP}/packet.json', 'status': 'modified'},
                 'packet.json removed': {'filename': f'research-packets/{RP}/packet.json', 'status': 'removed'},
                 'only the receipt': {'filename': f'research-packets/{RP}/receipt.json', 'status': 'modified'},
                 'only a raw': {'filename': RAW_PATH, 'status': 'removed'},
                 'a file added later': {'filename': f'research-packets/{RP}/nota.md', 'status': 'added'},
                 'renamed away': {'filename': 'otro/packet.json', 'previous_filename': f'research-packets/{RP}/packet.json', 'status': 'renamed'}}
        for name, change in later.items():
            for since in (self.since, self.pub):  # changed inside the same range as its publication, or in a later one
                with self.subTest(name, since=since):
                    self.setUp()
                    self.gh.commit([change])
                    [got], _ = self.run_it(since=since if since == self.since else self.pub)
                    self.assertEqual((got['research_id'], got['status'], got['why']),
                                     (RP, 'rejected', 'its folder changed after it was published (2 commits)'))

    def test_a_packet_json_that_arrives_by_rename_is_not_a_publication(self):
        self.gh.main[-1] = (self.pub, [{'filename': f'research-packets/{RP}/packet.json', 'previous_filename': 'x/packet.json', 'status': 'renamed'}])
        [got], _ = self.run_it()
        self.assertEqual((got['status'], got['why']), ('rejected', 'its only commit does not add its packet.json'))

    def test_only_files_under_a_packet_folder_count(self):
        self.gh.commit([{'filename': 'research-packets/x/packet.json', 'status': 'added'}, {'filename': f'otro/{RP}/packet.json', 'status': 'added'},
                        {'filename': 'research-packets/README.md', 'status': 'added'}])
        self.assertEqual([g['research_id'] for g in self.run_it(since=self.pub)[0]], [])

    def test_more_than_300_files_and_100_commits_are_read_to_the_last_one(self):
        # the cut GitHub's compare would make: 300 files, 250 commits; here every commit and every file is read
        for i in range(150):  # under research-packets/ but no packet: 150 more commits in its history
            self.gh.commit([{'filename': f'research-packets/notas/{i}-{k}.md', 'status': 'added'} for k in range(3)])
        big = [{'filename': f'research-packets/RP-2026-10-24-grande/raw/sha256/aa/{k:064x}.html', 'status': 'added'} for k in range(250)]
        big += publish('RP-2026-10-24-grande')  # its packet.json on the commit's third page of files
        c = self.gh.commit(big, {'research-packets/RP-2026-10-24-grande/packet.json': packet(research_id='RP-2026-10-24-grande')})
        got, _ = self.run_it()
        self.assertEqual([(g['research_id'], g['status']) for g in got], [(RP, 'accepted'), ('RP-2026-10-24-grande', 'accepted')])
        self.assertEqual(got[1]['commit'], c)
        self.assertEqual(sum('/compare/' in p for p in self.gh.asked), 2)  # 152 commits, 100 a page
        self.assertEqual(sum(p.startswith(f'/repos/{REPO}/commits/{c}?') for p in self.gh.asked), 3)  # 253 files, 100 a page

    def test_raws_come_from_the_whole_tree_past_1000_and_a_truncated_tree_stops_the_read(self):
        many = [{'filename': f'research-packets/RP-2026-10-24-mil/raw/sha256/00/{k:064x}.html', 'status': 'added'} for k in range(1200)]
        last = f'research-packets/RP-2026-10-24-mil/raw/sha256/00/{1199:064x}.html'
        body = json.loads(packet(research_id='RP-2026-10-24-mil'))
        body['artifacts'] = [{'artifact_id': 'SA-z', 'sha256': f'{1199:064x}', 'redistribution': 'allowed', 'url': 'https://a.gob.mx/z'}]
        self.gh.commit(many + publish('RP-2026-10-24-mil'), {'research-packets/RP-2026-10-24-mil/packet.json': json.dumps(body).encode()})
        got = {g['research_id']: g for g in self.run_it()[0]}
        self.assertEqual(got['RP-2026-10-24-mil']['artifacts'][0]['path'], last)  # the 1200th raw, past a directory listing's cap
        self.gh.truncated = True
        with self.assertRaises(cons.Cut):
            self.run_it()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cons.main(['--repo', REPO, '--since', self.since], get=self.gh.get, get_raw=self.gh.get_raw), 3)
        self.assertEqual(out.getvalue(), '')  # no line, no cursor

    def test_a_range_github_would_list_in_part_stops_with_no_answer(self):
        real = self.gh.get
        cases = {'a count that does not add up': lambda p: {**real(p), 'total_commits': 9} if '/compare/' in p else real(p),
                 'since is not behind main': lambda p: {**real(p), 'status': 'diverged'} if '/compare/' in p else real(p),
                 'a commit at the file cap': lambda p: ({'files': [{'filename': f'f{i}', 'status': 'added'} for i in range(100)]
                                                                   if int(p.rsplit('=', 1)[1]) <= 31 else []}
                                                        if p.startswith(f'/repos/{REPO}/commits/{self.pub}?') else real(p))}
        for name, get in cases.items():
            with self.subTest(name), self.assertRaises(cons.Cut):
                cons.run(get, self.gh.get_raw, REPO, self.since, {PAIR})

    def test_github_not_answering_now_stops_everything_and_the_next_call_gets_the_packet(self):
        for path, err in ((f'receipt.json?ref={self.pub}', urllib.error.HTTPError('u', 500, 'Server Error', None, None)),
                          ('/compare/', urllib.error.URLError('down')),
                          (f'/commits/{self.pub}?', urllib.error.HTTPError('u', 403, 'rate limit', None, None)),
                          ('packet.json?ref=', urllib.error.HTTPError('u', 429, 'Too Many', None, None)),
                          ('/commits?sha=', TimeoutError()),
                          (f'packet.json?ref={self.pub}', http.client.IncompleteRead(b'{"research_id"', 900))):
            with self.subTest(path):
                self.gh.fail = {path: err}
                with self.assertRaises(cons.Transient):
                    self.run_it()
                self.gh.fail = {}
                self.assertEqual([g['status'] for g in self.run_it()[0]], ['accepted'])  # same since, nothing lost

    def test_a_permanent_answer_about_one_packet_is_its_rejection_and_the_rest_go_on(self):
        other = 'RP-2026-10-24-roto'
        self.gh.commit(publish(other))  # its packet.json has no bytes at all: a 404
        self.gh.blobs[(f'research-packets/{other}/packet.json', self.gh.main[-1][0])] = None
        bad = 'RP-2026-10-24-otro'
        self.gh.commit(publish(bad), {f'research-packets/{bad}/packet.json': packet()})  # research_id names another folder
        got, _ = self.run_it()
        self.assertEqual([(g['research_id'], g['status'], g.get('why')) for g in got],
                         [(RP, 'accepted', None), (bad, 'rejected', 'its research_id is not its folder'), (other, 'rejected', 'HTTPError')])

    def test_the_token_is_never_sent_to_another_host(self):
        handler = cons.SameHostAuth()
        req = urllib.request.Request('https://api.github.com/repos/o/r/contents/x', headers={'Authorization': 'Bearer t'})
        moved = handler.redirect_request(req, None, 302, 'Found', {}, 'https://objects.githubusercontent.com/x')
        same = handler.redirect_request(req, None, 302, 'Found', {}, 'https://api.github.com/repositories/1/contents/x')
        self.assertEqual((moved.has_header('Authorization'), same.has_header('Authorization')), (False, True))

    def test_a_redirect_off_https_is_refused_whatever_the_host(self):
        handler = cons.SameHostAuth()
        req = urllib.request.Request('https://api.github.com/repos/o/r/contents/x', headers={'Authorization': 'Bearer t'})
        for to in ('http://api.github.com/repos/o/r/contents/x', 'ftp://api.github.com/x'):
            with self.subTest(to=to), self.assertRaises(urllib.error.HTTPError):
                handler.redirect_request(req, None, 302, 'Found', {}, to)

    def test_a_garbled_answer_from_github_is_transient_and_the_cursor_waits(self):
        class Answer:
            def __init__(self, body):
                self.body = body
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def read(self):
                return self.body
        opener = mock.Mock()
        opener.open.return_value = Answer(b'{"sha": "ab')  # a JSON body cut short
        with mock.patch.object(cons.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaises(cons.Transient):
                cons.http('/repos/o/r/commits/main')
            self.assertEqual(cons.http('/repos/o/r/contents/x', raw=True), b'{"sha": "ab')  # raw bytes are not parsed here
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(cons.urllib.request, 'build_opener', return_value=opener), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(cons.main(['--repo', REPO, '--since', self.since]), 75)
        self.assertEqual(out.getvalue(), '')

    def test_a_packet_json_cut_on_the_way_is_transient_and_the_next_call_takes_it(self):
        real = self.gh.get_raw
        self.gh.get_raw = lambda path: real(path)[:20] if path.endswith(f'packet.json?ref={self.pub}') else real(path)
        with self.assertRaises(cons.Transient):
            self.run_it()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cons.main(['--repo', REPO, '--since', self.since], get=self.gh.get, get_raw=self.gh.get_raw), 75)
        self.assertEqual(out.getvalue(), '')  # no rejection, no cursor
        self.gh.get_raw = real
        self.assertEqual([g['status'] for g in self.run_it()[0]], ['accepted'])

    def test_what_counts_as_github_not_answering_now(self):
        err = lambda code: urllib.error.HTTPError('u', code, 'x', None, None)
        self.assertEqual([cons.transient(e) for e in (err(500), err(502), err(403), err(429), urllib.error.URLError('x'), TimeoutError(),
                                                       ConnectionResetError(), http.client.IncompleteRead(b'x', 10),
                                                       http.client.RemoteDisconnected('x'))], [True] * 9)
        self.assertEqual([cons.transient(e) for e in (err(404), err(422), ValueError('x'), KeyError('x'))], [False] * 4)

    def test_the_command_line_checks_its_arguments_reads_the_token_from_the_environment_and_prints_the_cursor(self):
        for argv in (['--repo', 'no/es/repo', '--since', self.since], ['--repo', REPO, '--since', 'main'],
                     ['--repo', REPO, '--since', self.since, '--accept', 'x:y'], ['--repo', REPO, '--since', self.since, '--token', 't']):
            with self.subTest(argv), self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                cons.main(argv, get=self.fail, get_raw=self.fail)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cons.main(['--repo', REPO, '--since', self.since, '--accept', f'{PAIR[0]}:{PAIR[1]}'],
                                       get=self.gh.get, get_raw=self.gh.get_raw), 0)
        lines = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(lines[0]['status'], 'accepted')
        self.assertEqual(lines[-1], {'cursor': self.gh.main[-1][0], 'since': self.since, 'packets': 1})
        seen = []
        with mock.patch.dict('os.environ', {'GH_TOKEN': 'tok'}, clear=True), \
                mock.patch.object(cons, 'http', side_effect=lambda p, raw=False, token='': seen.append(token) or (self.gh.get_raw(p) if raw else self.gh.get(p))), \
                contextlib.redirect_stdout(io.StringIO()):
            cons.main(['--repo', REPO, '--since', self.since])
        self.assertEqual(set(seen), {'tok'})

    def test_no_answer_and_no_cursor_when_github_is_down_or_the_range_is_cut(self):
        for err, code in ((urllib.error.URLError('down'), 75), (cons.Cut('cut'), 3)):
            with self.subTest(code):
                out, errs = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(errs):
                    got = cons.main(['--repo', REPO, '--since', self.since], get=mock.Mock(side_effect=err), get_raw=self.gh.get_raw)
                self.assertEqual((got, out.getvalue()), (code, ''))  # not one line, not a cursor
                self.assertIn('no cursor', errs.getvalue())

    def fail(self, path):
        raise AssertionError(path)


if __name__ == '__main__':
    unittest.main()
