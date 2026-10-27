"""scripts/packet_gate.py: main's packet gate on the packet folders a PR head changes, read from git as data.

Built here (CONSTRUIDO): a local git repository with a main branch and a head that adds the packet the
tests/test_investigar.py fixtures build (two raws, two quotes), then variants of it.
"""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rg import investigar as inv
from tests.test_catalog import FakeOpener
from tests.test_investigar import PAGE, PLAN, ROUTES, RR, answer

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('packet_gate', ROOT / 'scripts' / 'packet_gate.py')
pg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pg)
RP = 'RP-2026-10-23-prueba'


@unittest.skipUnless(shutil.which('git'), 'needs git')
class PacketGate(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.repo = self.tmp / 'repo'
        self.git('init', '-q', '-b', 'main', str(self.repo))
        (self.repo / 'README.md').write_text('main\n', encoding='utf-8')
        self.commit('main')
        # The page carries an export-subst placeholder: git archive would rewrite it, git cat-file never does.
        self.page = PAGE.replace(b'</body>', b'<p>$Format:%s$</p></body>')
        routes = {**ROUTES, 'https://a.gob.mx/nota': (200, self.page, ROUTES['https://a.gob.mx/nota'][2])}
        work = self.tmp / 'work'
        rows = inv.fetch(PLAN, work, opener=FakeOpener(routes), sleep=lambda s: None)
        ans = answer()
        ans['findings']['confirmed'][0]['artifact_ids'] = ['SA-' + hashlib.sha256(self.page).hexdigest()[:24]]
        self.built = inv.assemble(RR, rows, ans, work, self.tmp / 'out', 'modelo de prueba', '2026-10-23T00:00:00Z')
        self.git('-C', str(self.repo), 'checkout', '-q', '-b', 'pr')
        shutil.copytree(self.built, self.repo / 'research-packets' / RP)

    def git(self, *args):
        return subprocess.run(['git', *args], check=True, capture_output=True, text=True, timeout=60).stdout.strip()

    def commit(self, msg):
        self.git('-C', str(self.repo), 'add', '-A')
        self.git('-C', str(self.repo), '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', msg)
        return self.git('-C', str(self.repo), 'rev-parse', 'HEAD')

    def run_gate(self, sha):
        data = Path(tempfile.mkdtemp(dir=self.tmp))
        return pg.gate('main', sha, data, self.repo)

    def test_a_packet_that_passes_lists_each_raw_with_its_sha256(self):
        sha = self.commit('paquete')
        result = self.run_gate(sha)
        self.assertEqual(result['head_sha'], sha)
        [packet] = result['packets']
        self.assertEqual((packet['packet'], packet['status'], packet['problems'], packet['warnings']), (RP, 'passed', [], []))
        on_disk = {f'research-packets/{RP}/{f.relative_to(self.built).as_posix()}': hashlib.sha256(f.read_bytes()).hexdigest()
                   for f in (self.built / 'raw').rglob('*') if f.is_file()}
        self.assertEqual(packet['raws'], on_disk)
        self.assertEqual(len(on_disk), 2)

    def test_the_heads_export_attributes_change_nothing_the_gate_reads(self):
        (self.repo / '.gitattributes').write_text('*.html export-subst\nresearch-packets/** export-ignore\n', encoding='utf-8')
        self.sha = self.commit('atributos de exportación')
        [packet] = self.run_gate(self.sha)['packets']
        self.assertEqual(packet['status'], 'passed', packet)
        self.assertIn(hashlib.sha256(self.page).hexdigest(), packet['raws'].values())  # the bytes as committed
        self.assertEqual(len(packet['raws']), 2)  # export-ignore drops nothing
        archived = subprocess.run(['git', '-C', str(self.repo), 'archive', '--format=tar', self.sha, '--',
                                   f'research-packets/{RP}'], capture_output=True, timeout=60).stdout
        self.assertNotIn(b'$Format:%s$', archived)  # what git archive would have handed the gate instead

    def test_a_path_outside_its_folder_is_never_written(self):
        oid = self.git('-C', str(self.repo), 'hash-object', '-w', str(self.repo / 'README.md'))
        data = Path(tempfile.mkdtemp(dir=self.tmp))
        for path in (f'research-packets/{RP}/../../fuera.txt', 'research-packets/RP-otro/x.txt'):
            with self.subTest(path), self.assertRaises(ValueError):
                pg.write_blobs([('100644', 'blob', oid, 5, path)], RP, data, self.repo)
        self.assertEqual(list(data.rglob('*.txt')), [])

    def test_a_blob_or_a_head_over_its_size_limit_is_never_written(self):
        sha = self.commit('paquete')
        for name, patch, said in (('blob', ('MAX_BLOB', 100), 'larger than 100 bytes'), ('head', ('MAX_TOTAL', 100), 'over the 100')):
            with self.subTest(name), mock.patch.object(pg, *patch):
                data = Path(tempfile.mkdtemp(dir=self.tmp))
                [packet] = pg.gate('main', sha, data, self.repo)['packets']
                self.assertEqual(packet['status'], 'failed')
                self.assertTrue(any(said in p for p in packet['problems']), packet['problems'])
                self.assertEqual(list(data.iterdir()), [])

    def test_an_error_is_a_failed_result_and_the_others_still_run(self):
        sha = self.commit('paquete')
        with mock.patch.object(pg, 'check', side_effect=RuntimeError('un analizador se rompió')):
            [packet] = self.run_gate(sha)['packets']
        self.assertEqual((packet['status'], packet['problems']), ('failed', ['the gate did not finish: RuntimeError']))

    def two_packets(self):
        shutil.copytree(self.repo / 'research-packets' / RP, self.repo / 'research-packets' / 'RP-2026-10-23-segundo')
        size = sum(f.stat().st_size for f in (self.repo / 'research-packets' / RP).rglob('*') if f.is_file())
        return self.commit('dos paquetes'), size

    def test_bytes_written_before_an_error_still_count_against_the_budget(self):
        sha, size = self.two_packets()
        real = pg.check
        calls = iter([RuntimeError('después de escribir'), None])

        def first_fails(folder):
            err = next(calls)
            if err:
                raise err
            return real(folder)
        with mock.patch.object(pg, 'MAX_TOTAL', size + size // 2), mock.patch.object(pg, 'check', first_fails):
            first, second = self.run_gate(sha)['packets']
        self.assertEqual(first['problems'], ['the gate did not finish: RuntimeError'])
        self.assertEqual(second['status'], 'failed')
        self.assertTrue(any('over the' in p for p in second['problems']), second['problems'])

    def test_an_error_while_hashing_fails_that_folder_and_keeps_the_others(self):
        sha, _ = self.two_packets()
        with mock.patch.object(pg.hashlib, 'sha256', side_effect=OSError('disco')):
            result = self.run_gate(sha)
        self.assertNotIn('error', result)
        self.assertEqual([(p['status'], p['problems']) for p in result['packets']],
                         [('failed', ['the gate did not finish: OSError'])] * 2)

    def test_a_tampered_raw_fails_and_lists_no_raw(self):
        raw = next((self.repo / 'research-packets' / RP / 'raw').rglob('*.html'))
        raw.write_bytes(raw.read_bytes().replace(b'escrito', b'ESCRITO'))
        [packet] = self.run_gate(self.commit('crudo alterado'))['packets']
        self.assertEqual((packet['status'], packet['raws']), ('failed', {}))
        self.assertTrue(any('does not match' in p for p in packet['problems']))

    def test_a_warning_fails_too_as_with_strict(self):
        p = self.repo / 'research-packets' / RP / 'packet.json'
        packet = json.loads(p.read_text(encoding='utf-8'))
        del packet['findings']['confirmed'][0]['quote']  # a finding with nothing to verify: a warning, not a problem
        p.write_text(json.dumps(packet), encoding='utf-8')
        [result] = self.run_gate(self.commit('sin cita'))['packets']
        self.assertEqual((result['status'], result['problems'], result['raws']), ('failed', [], {}))
        self.assertTrue(result['warnings'])

    def test_a_link_in_the_tree_is_never_extracted(self):
        (self.repo / 'research-packets' / RP / 'enlace.json').symlink_to('/etc/hostname')
        sha = self.commit('enlace')
        data = Path(tempfile.mkdtemp(dir=self.tmp))
        [packet] = pg.gate('main', sha, data, self.repo)['packets']
        self.assertEqual(packet['status'], 'failed')
        self.assertEqual(packet['problems'], [f'research-packets/{RP}/enlace.json: not a regular file'])
        self.assertEqual(list(data.iterdir()), [])  # nothing was extracted

    def test_only_changed_packets_are_gated_and_a_removed_one_says_so(self):
        main_sha = self.git('-C', str(self.repo), 'rev-parse', 'main')
        self.assertEqual(self.run_gate(main_sha)['packets'], [])
        self.commit('paquete')
        self.git('-C', str(self.repo), 'checkout', '-q', 'main')
        self.git('-C', str(self.repo), 'merge', '-q', 'pr')
        self.git('-C', str(self.repo), 'checkout', '-q', '-b', 'quita', 'main')
        self.git('-C', str(self.repo), 'rm', '-q', '-r', f'research-packets/{RP}')
        (self.repo / 'otro.txt').write_text('x\n', encoding='utf-8')
        sha = self.commit('quita el paquete')
        self.assertEqual(self.run_gate(sha)['packets'], [{'packet': RP, 'status': 'removed'}])

    def test_a_folder_name_outside_the_pattern_is_ignored(self):
        shutil.move(self.repo / 'research-packets' / RP, self.repo / 'research-packets' / 'nombre raro')
        self.assertEqual(self.run_gate(self.commit('otro nombre'))['packets'], [])

    def test_when_the_gate_cannot_run_its_result_still_says_so(self):
        sha = self.commit('paquete')
        out = self.tmp / 'packets.json'
        self.assertEqual(pg.main(['--base', 'no-existe', '--sha', sha, '--data', str(self.tmp / 'd'), '--out', str(out),
                                  '--repo', str(self.repo)]), 0)
        self.assertEqual(json.loads(out.read_text(encoding='utf-8')),
                         {'head_sha': sha, 'packets': [], 'error': 'the gate did not run: CalledProcessError'})

    def test_main_rejects_a_bad_sha_and_writes_one_result(self):
        with self.assertRaises(SystemExit):
            pg.main(['--base', 'main', '--sha', 'main', '--data', str(self.tmp), '--out', str(self.tmp / 'x.json')])
        sha = self.commit('paquete')
        out = self.tmp / 'packets.json'
        self.assertEqual(pg.main(['--base', 'main', '--sha', sha, '--data', str(Path(tempfile.mkdtemp(dir=self.tmp))),
                                  '--out', str(out), '--repo', str(self.repo)]), 0)
        self.assertEqual(json.loads(out.read_text(encoding='utf-8'))['packets'][0]['status'], 'passed')


if __name__ == '__main__':
    unittest.main()
