"""rg/text/run.py as_user and rg/text/isolated.py: hostile raws parsed by an OS user that owns nothing RG trusts.

Built here (CONSTRUIDO): the HTML fixture of tests/test_texto.py, and a hostile extractor that tries to overwrite
packet.json, receipt.json, the gate's result and the publishable folder. The Linux tests need passwordless sudo, as on
a GitHub-hosted runner (CI); elsewhere they are skipped and the rest runs with the launch mocked.
"""
import contextlib
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from rg.text import isolated, run
from rg.text.extract import FAILED, OK, extractor

PAGE = '<html><body><h1>Norma</h1><p>5.1 El patrón deberá establecer una política.</p></body></html>'.encode()
USER = 'rgparse'


def sudo_ok():
    if not sys.platform.startswith('linux') or not shutil.which('sudo'):
        return False
    return subprocess.run(['sudo', '-n', 'true'], capture_output=True).returncode == 0


class Answer(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.raw = Path(tmp.name) / 'a.html'
        self.raw.write_bytes(PAGE)

    def test_the_parent_names_the_extractor_and_hashes_the_raw_itself(self):
        said = {'format': 'html', 'status': OK, 'text': 'x', 'invisibles_removed': 0, 'charset': 'utf-8',
                'extractor': 'otro==9', 'raw_sha256': '0' * 64, 'bytes': 1}  # a child lying about what is not its to say
        got = run.answer(json.dumps(said), self.raw)
        self.assertEqual(got, {'format': 'html', 'status': OK, 'text': 'x', 'invisibles_removed': 0, 'charset': 'utf-8',
                               'extractor': extractor('html'), 'raw_sha256': hashlib.sha256(PAGE).hexdigest(),
                               'bytes': len(PAGE)})

    def test_anything_but_an_extraction_result_is_refused(self):
        good = {'format': 'html', 'status': OK, 'text': 'x', 'invisibles_removed': 0}
        failed_ok = {'format': 'html', 'status': FAILED, 'text': None, 'invisibles_removed': 0, 'error': 'x'}
        self.assertEqual(run.answer(json.dumps(failed_ok), self.raw)['status'], FAILED)
        for name, said in {'not json': 'x', 'a list': '[]', 'no status': json.dumps({'format': 'html'}),
                           'unknown status': json.dumps({**good, 'status': 'aprobado'}),
                           'no format': json.dumps({'status': OK}),
                           'an extra field': json.dumps({**good, 'veredicto': 'PASS'}),
                           'a field of another type': json.dumps({**good, 'text': 7}),
                           'an optional field of another type': json.dumps({**good, 'charset': 7}),
                           'a bool for a count': json.dumps({**good, 'invisibles_removed': True}),
                           'pages that are not offsets': json.dumps({**good, 'pages': [{'x': 1}]}),
                           'a page offset that is not a number': json.dumps({**good, 'pages': [[0, 'x']]}),
                           'a page that is not a number': json.dumps({**good, 'pages_without_text': [[1]]}),
                           'no text': json.dumps({k: v for k, v in good.items() if k != 'text'}),
                           'no count of invisibles': json.dumps({k: v for k, v in good.items() if k != 'invisibles_removed'}),
                           'ok without text': json.dumps({**good, 'text': None}),
                           'a fallo without its reason': json.dumps({**good, 'status': FAILED, 'text': None})}.items():
            with self.subTest(name), self.assertRaises(ValueError):
                run.answer(said, self.raw)

    def test_the_child_prints_one_result_from_its_own_process(self):
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.object(isolated, '_limit_memory') as cap:
            self.assertEqual(isolated.main([str(self.raw), '1000', '2000000000']), 0)
        cap.assert_called_once_with(2000000000)  # the cap comes first
        got = run.answer(out.getvalue(), self.raw)
        self.assertEqual((got['status'], got['raw_sha256']), (OK, hashlib.sha256(PAGE).hexdigest()))
        self.assertIn('5.1 El patrón deberá establecer una política.', got['text'])


class Launch(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.raw = self.tmp / 'a.html'
        self.raw.write_bytes(PAGE)
        self.base = run.scratch(self.tmp / 's')

    def test_the_scratch_holds_a_read_only_copy_of_the_code(self):
        self.assertTrue((self.base / 'code' / 'rg' / 'text' / 'isolated.py').is_file())
        for d, dirs, files in os.walk(self.base):
            self.assertEqual(stat.S_IMODE(os.stat(d).st_mode), 0o711 if Path(d) == self.base / 'in' else 0o755, d)
            for f in files:
                self.assertEqual(stat.S_IMODE(os.stat(Path(d) / f).st_mode), 0o444, f)

    def test_each_raw_runs_as_the_user_from_a_read_only_copy(self):
        seen = {}

        def fake(argv, cwd, seconds, limit):
            copy = Path(argv[12])
            seen.update(argv=argv, cwd=cwd, mode=stat.S_IMODE(copy.stat().st_mode), parent=copy.parent, timeout=seconds, limit=limit)
            res = {'format': 'html', 'status': OK, 'text': 't', 'invisibles_removed': 0}
            return json.dumps(res).encode(), 0, None
        with mock.patch.object(run, 'bounded', side_effect=fake):
            path, res = run.as_user(USER, self.raw, self.base, 120)
        self.assertEqual(path, self.raw)
        self.assertEqual(seen['argv'][:12], ['sudo', '-n', '-u', USER, '--', 'timeout', '-s', 'KILL', '120', sys.executable,
                                            '-m', 'rg.text.isolated'])
        self.assertEqual(seen["argv"][13:], [str(run.MAX_BYTES), str(run.MAX_MEMORY)])
        self.assertEqual((seen['cwd'], seen['parent'], seen['mode'], seen['timeout'], seen['limit']),
                         (self.base / 'code', self.base / 'in', 0o444, 150, run.MAX_ANSWER))
        self.assertEqual(list((self.base / 'in').iterdir()), [])  # the copy is gone
        self.assertEqual((res['status'], res['raw_sha256']), (OK, hashlib.sha256(PAGE).hexdigest()))

    def test_a_child_that_fails_hangs_or_answers_nothing_is_a_fallo(self):
        ok = json.dumps({'format': 'html', 'status': OK, 'text': 't', 'invisibles_removed': 0}).encode()
        cases = {'exit': (ok, 9, None), 'garbage': (b'{', 0, None), 'not utf-8': (b'\xff\xfe', 0, None),
                 'timeout': (None, None, 'timeout'), 'flood': (None, None, 'too much'),
                 'nested past the decoder': (b'[' * 200_000 + b']' * 200_000, 0, None),
                 'a field of many small lists': (b'{"format": "html", "status": "ok", "x": [' + b'[],' * 300_000 + b'[]]}', 0, None),
                 'out of memory while parsing': MemoryError(),
                 'the launch fails': OSError('no sudo')}
        for name, outcome in cases.items():
            with self.subTest(name), mock.patch.object(run, 'bounded', side_effect=outcome if isinstance(outcome, (OSError, MemoryError)) else [outcome]):
                _, res = run.as_user(USER, self.raw, self.base, 120)
                self.assertEqual((res['status'], res['raw_sha256']), (FAILED, hashlib.sha256(PAGE).hexdigest()))
                why = {'timeout': 'timeout (120 s)', 'flood': f'answer over {run.MAX_ANSWER} bytes', 'exit': 'isolated extractor exit 9'}
                if name in why:
                    self.assertEqual(res['error'], why[name])
                self.assertEqual(list((self.base / 'in').iterdir()), [])

    def test_a_child_is_read_only_up_to_its_limit_and_its_time_and_never_its_stderr(self):
        py = lambda code: [sys.executable, '-c', code]
        started = time.monotonic()
        self.assertEqual(run.bounded(py('import sys; sys.stdout.write("x" * 3_000_000)'), self.tmp, 30, 1_000_000), (None, None, 'too much'))
        self.assertEqual(run.bounded(py('import time; time.sleep(30)'), self.tmp, 1, 1_000), (None, None, 'timeout'))
        # a child that keeps the pipe open past its time is not waited for either
        self.assertEqual(run.bounded(py('import sys, time; sys.stdout.write("x"); sys.stdout.flush(); time.sleep(30)'), self.tmp, 1, 1_000),
                         (None, None, 'timeout'))
        # one that closes its output and stays is not waited for past its time
        self.assertEqual(run.bounded(py('import os, time; os.close(1); time.sleep(30)'), self.tmp, 1, 1_000), (None, None, 'timeout'))
        pid = self.tmp / 'pid'
        run.bounded(py(f'import os, time; open({str(pid)!r}, "w").write(str(os.getpid())); time.sleep(30)'), self.tmp, 1, 1_000)
        with self.assertRaises(ProcessLookupError):  # killed and reaped, not left running
            os.kill(int(pid.read_text()), 0)
        self.assertLess(time.monotonic() - started, 20)
        out, code, why = run.bounded(py('import sys; sys.stderr.write("e" * 50_000_000); sys.stdout.write("{}"); sys.exit(3)'),
                                     self.tmp, 60, 1_000)
        self.assertEqual((out, code, why), (b'{}', 3, None))  # 50 MB of stderr went nowhere; the answer and exit code arrive
        self.assertEqual(run.bounded(py('print("a" * 1000, end="")'), self.tmp, 30, 1_000), (b'a' * 1000, 0, None))  # the limit itself fits

    def test_one_hostile_answer_is_its_files_fallo_and_the_next_file_still_gets_its_result(self):
        other = self.tmp / 'b.html'
        other.write_bytes(PAGE)
        ok = json.dumps({'format': 'html', 'status': OK, 'text': 't', 'invisibles_removed': 0}).encode()
        answers = iter([(b'[' * 200_000 + b']' * 200_000, 0, None), (ok, 0, None)])
        with mock.patch.object(run, 'bounded', side_effect=lambda *a: next(answers)), mock.patch.object(run, 'reap', return_value=[]):
            got = dict(run.extract_all([self.raw, other], workers=1, user=USER))
        self.assertEqual((got[self.raw]['status'], got[other]['status']), (FAILED, OK))

    def test_every_process_of_the_user_is_killed_by_pid_until_none_runs_even_after_an_error(self):
        table = [' 101 S\n 102 Z\n 103 R\n', ' 103 R\n', '']  # what ps says each round: 102 a zombie, 103 slow to die
        sent = []

        def fake(argv, **kw):
            sent.append(argv)
            return subprocess.CompletedProcess(argv, 0, table.pop(0) if argv[0] == 'ps' and table else '', '')
        with mock.patch.object(run.subprocess, 'run', side_effect=fake), \
                mock.patch.object(run, 'as_user', side_effect=lambda user, path, *a: (path, {'status': OK})), \
                mock.patch.object(run.time, 'sleep'):
            self.assertEqual(len(list(run.extract_all([self.raw], user=USER))), 1)
        self.assertEqual([a for a in sent if a[0] == 'sudo'], [['sudo', '-n', '-u', USER, '--', 'kill', '-s', 'KILL', '--', '101', '103'],
                                                              ['sudo', '-n', '-u', USER, '--', 'kill', '-s', 'KILL', '--', '103']])
        self.assertEqual(sent[0], ['ps', '-u', USER, '-o', 'pid=,stat='])
        sent.clear()
        with mock.patch.object(run.subprocess, 'run', side_effect=lambda argv, **kw: sent.append(argv) or subprocess.CompletedProcess(argv, 0, '', '')), \
                mock.patch.object(run, 'as_user', side_effect=RuntimeError('boom')), self.assertRaises(RuntimeError):
            list(run.extract_all([self.raw], user=USER))
        self.assertEqual(sent, [['ps', '-u', USER, '-o', 'pid=,stat=']])  # reaped after the error too: nothing was left
        with mock.patch.object(run, 'running', return_value=['7']), mock.patch.object(run.subprocess, 'run', side_effect=OSError('no sudo')), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(run.reap(USER, tries=3, sleep=lambda s: None), ['7'])  # what outlives it is said, not hidden
        self.assertIn('still running as rgparse: 7', err.getvalue())
        for outcome in (OSError('no ps'), subprocess.CompletedProcess([], 2, '', 'ps: bad'), subprocess.CompletedProcess([], 1, ' 9 S\n', '')):
            with self.subTest(outcome=outcome), mock.patch.object(run.subprocess, 'run', side_effect=[outcome] if isinstance(outcome, OSError) else lambda a, **k: outcome):
                self.assertIsNone(run.running(USER))  # ps could not say: never taken for "none left"
        with mock.patch.object(run.subprocess, 'run', side_effect=lambda a, **k: subprocess.CompletedProcess(a, 1, '', '')):
            self.assertEqual(run.running(USER), [])  # ps's own "no such process" is a real "none"
        with mock.patch.object(run, 'running', return_value=None), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(run.reap(USER, sleep=lambda s: None), ['?'])

    def test_an_answer_with_too_many_containers_is_refused_before_it_is_parsed(self):
        many = b'{"format": "html", "status": "ok", "text": "t", "invisibles_removed": 0, "x": [' + b'[],' * run.MAX_CONTAINERS + b'[]]}'
        with mock.patch.object(run.json, 'loads', side_effect=AssertionError('parsed')), self.assertRaises(ValueError):
            run.answer(many, self.raw)
        pages = json.dumps({'format': 'pdf', 'status': OK, 'text': 't', 'invisibles_removed': 0,
                            'pages': [[n, n + 1] for n in range(50_000)]})  # a long PDF's offsets still parse
        self.assertEqual(len(run.answer(pages, self.raw)['pages']), 50_000)

    def test_a_process_left_running_stops_the_extraction(self):
        with mock.patch.object(run, 'reap', return_value=['7']), \
                mock.patch.object(run, 'as_user', side_effect=lambda user, path, *a: (path, {'status': OK})), self.assertRaises(RuntimeError):
            list(run.extract_all([self.raw], user=USER))

    def test_a_copy_that_cannot_be_made_is_that_files_fallo(self):
        with mock.patch.object(run.shutil, 'copyfile', side_effect=OSError('disk full')), mock.patch.object(run, 'bounded') as never:
            path, res = run.as_user(USER, self.raw, self.base, 120)
        never.assert_not_called()
        self.assertEqual((path, res['status'], res['raw_sha256']), (self.raw, FAILED, hashlib.sha256(PAGE).hexdigest()))
        self.assertEqual(res['error'], 'could not prepare the copy (OSError)')
        self.assertEqual(list((self.base / 'in').iterdir()), [])

    def test_the_environment_names_the_user_and_a_bad_name_stops_the_run(self):
        calls = []

        def fake(user, path, base, timeout, max_bytes, max_memory, child):
            calls.append((user, path, child))
            return path, {'status': OK}
        with mock.patch.dict(os.environ, {run.EXTRACT_AS: USER}), mock.patch.object(run, 'as_user', side_effect=fake):
            got = dict(run.extract_all([self.raw, self.tmp / 'b.html'], workers=2))
        self.assertEqual(sorted(p.name for p in got), ['a.html', 'b.html'])
        self.assertEqual({(u, c) for u, _, c in calls}, {(USER, 'rg.text.isolated')})
        for bad in ('root; rm -rf /', '-u', 'Ra', 'x' * 40):
            with self.subTest(bad), mock.patch.dict(os.environ, {run.EXTRACT_AS: bad}), self.assertRaises(ValueError):
                list(run.extract_all([self.raw]))
        with mock.patch.dict(os.environ, {run.EXTRACT_AS: USER}), mock.patch.object(run, 'as_user', side_effect=fake):
            self.assertEqual(list(run.extract_all([self.raw], deadline=0)), [])  # nothing starts after the deadline
        with mock.patch.dict(os.environ, {run.EXTRACT_AS: ''}), mock.patch.object(run, 'as_user') as never:
            self.assertEqual(dict(run.extract_all([self.raw]))[self.raw]['status'], OK)  # unset: as before, in-process
        never.assert_not_called()


HOSTILE = '''"""A taken-over extractor: it tries to change every trusted byte it can name, then reports what it got."""
import json, os, sys
tries = {}
def attempt(name, fn):
    try:
        fn()
        tries[name] = 'done'
    except OSError as e:
        tries[name] = type(e).__name__
t = sys.argv[2]  # the test hands it the trusted folder where a real child gets its byte limit
attempt('packet.json', lambda: open(os.path.join(t, 'packet.json'), 'w').write('{}'))
attempt('receipt.json', lambda: open(os.path.join(t, 'receipt.json'), 'a').write('x'))
attempt('gate result', lambda: open(os.path.join(t, 'packets.json'), 'w').write('{"status": "passed"}'))
attempt('new file in the publishable folder', lambda: open(os.path.join(t, 'publicar', 'nuevo.txt'), 'w').write('x'))
attempt('remove from the publishable folder', lambda: os.remove(os.path.join(t, 'publicar', 'raw.html')))
attempt('rename the publishable folder', lambda: os.rename(os.path.join(t, 'publicar'), os.path.join(t, 'otra')))
attempt('the code it runs', lambda: open(os.path.join(os.getcwd(), 'rg', 'text', 'run.py'), 'a').write('x'))
attempt('the raw copy', lambda: open(sys.argv[1], 'w').write('x'))
sys.stdout.write(json.dumps({'format': 'html', 'status': 'fallo', 'text': None, 'invisibles_removed': 0, 'error': json.dumps(tries)}))
'''


LEAVES_A_CHILD = '''# A taken-over extractor that leaves a detached child running, then answers in time.
import json, os, sys, time
if os.fork() == 0:
    os.setsid()
    if os.fork() == 0:
        for fd in (0, 1, 2):
            os.close(fd)
        time.sleep(120)
    os._exit(0)
sys.stdout.write(json.dumps({'format': 'html', 'status': 'fallo', 'text': None, 'invisibles_removed': 0, 'error': 'left a child'}))
'''


@unittest.skipUnless(sudo_ok(), 'needs Linux and passwordless sudo, as on a GitHub-hosted runner (CI)')
class AsAnotherUser(unittest.TestCase):
    """The falsifier the directive asks for: a malicious extractor gets permission denied and no trusted byte changes."""

    @classmethod
    def setUpClass(cls):
        if subprocess.run(['id', USER], capture_output=True).returncode != 0:
            subprocess.run(['sudo', '-n', 'useradd', '--system', '--no-create-home', '--shell', '/usr/sbin/nologin', USER],
                           check=True, capture_output=True)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        os.chmod(self.tmp, 0o755)
        self.raw = self.tmp / 'a.html'
        self.raw.write_bytes(PAGE)

    def test_a_real_raw_is_extracted_by_the_other_user(self):
        [(path, res)] = list(run.extract_all([self.raw], user=USER, timeout=120))
        self.assertEqual((path, res['status'], res['raw_sha256']), (self.raw, OK, hashlib.sha256(PAGE).hexdigest()))
        self.assertIn('5.1 El patrón deberá establecer una política.', res['text'])

    def test_a_hostile_extractor_cannot_change_any_trusted_byte(self):
        trusted = self.tmp / 'trusted'
        (trusted / 'publicar').mkdir(parents=True)
        for name, body in (('packet.json', b'{"ok": 1}'), ('receipt.json', b'{"r": 1}'), ('packets.json', b'{"status": "failed"}'),
                           ('publicar/raw.html', PAGE)):
            (trusted / name).write_bytes(body)
        os.chmod(trusted, 0o755)
        os.chmod(trusted / 'publicar', 0o755)
        before = {p: p.read_bytes() for p in trusted.rglob('*') if p.is_file()}
        base = run.scratch(self.tmp / 's')
        hostile = base / 'code' / 'hostil.py'  # the scratch is the parent's: it places the module before handing it over
        hostile.write_text(HOSTILE, encoding='utf-8')
        os.chmod(hostile, 0o444)
        _, res = run.as_user(USER, self.raw, base, 120, max_bytes=str(trusted), child='hostil')
        tries = json.loads(res['error'])
        self.assertEqual(set(tries), {'packet.json', 'receipt.json', 'gate result', 'new file in the publishable folder',
                                      'remove from the publishable folder', 'rename the publishable folder', 'the code it runs',
                                      'the raw copy'})
        self.assertEqual(set(tries.values()), {'PermissionError'}, tries)
        self.assertEqual({p: p.read_bytes() for p in trusted.rglob('*') if p.is_file()}, before)  # no trusted byte changed
        self.assertEqual(res['raw_sha256'], hashlib.sha256(PAGE).hexdigest())  # the parent's hash, not the child's word

    def test_a_child_left_behind_by_a_parser_is_killed_when_the_call_ends(self):
        base = run.scratch(self.tmp / 's')
        (base / 'code' / 'deja_hijo.py').write_text(LEAVES_A_CHILD, encoding='utf-8')
        os.chmod(base / 'code' / 'deja_hijo.py', 0o444)
        _, res = run.as_user(USER, self.raw, base, 120, child='deja_hijo')
        self.assertEqual((res['status'], res['error']), (FAILED, 'left a child'))  # its own answer, read as a whole result
        self.assertTrue(run.running(USER))  # the answer came back and its child is still running
        left = run.reap(USER)
        table = subprocess.run(['ps', '-u', USER, '-o', 'pid=,ppid=,stat=,args='], capture_output=True, text=True).stdout
        self.assertEqual(left, [], table)  # on failure, what still runs and who its parent is
        self.assertEqual(run.running(USER), [], table)


if __name__ == '__main__':
    unittest.main()
