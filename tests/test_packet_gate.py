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
from tests.test_investigar import A_CLOSED, CLOSED, PAGE, PLAN, ROUTES, RR, answer

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('packet_gate', ROOT / 'scripts' / 'packet_gate.py')
pg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pg)
RP = 'RP-2026-10-23-prueba'


def statement(folder, rp=RP):
    """What investigar.yml's attest job signs for a packet folder: one statement, every file a subject by its path."""
    return {'_type': 'https://in-toto.io/Statement/v1', 'predicateType': 'https://slsa.dev/provenance/v1',
            'subject': [{'name': f'research-packets/{rp}/{f.relative_to(folder).as_posix()}',
                         'digest': {'sha256': hashlib.sha256(f.read_bytes()).hexdigest()}}
                        for f in sorted(Path(folder).rglob('*')) if f.is_file()]}


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
        self.assertEqual(packet['files'], {})  # a packet with its raws never waits for an attestation
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

    def test_the_clean_runner_holds_one_budget_for_the_head_across_folders(self):
        # GPT, third REVISE of #56: a forged packet-read result must not make the clean runner write past MAX_TOTAL
        sha, size = self.two_packets()
        second = 'RP-2026-10-23-segundo'
        signed = {rp: statement(self.repo / 'research-packets' / rp, rp) for rp in (RP, second)}
        forged = {'head_sha': sha, 'packets': [{'packet': rp, 'status': 'passed'} for rp in (RP, second)]}
        both = lambda f, r: list(signed.values())

        def run(verify):
            data = Path(tempfile.mkdtemp(dir=self.tmp))
            with mock.patch.object(pg, 'MAX_TOTAL', size + size // 2):
                packets = pg.attest(json.loads(json.dumps(forged)), 'main', sha, data, 'o/r', self.repo, verify=verify)['packets']
            return packets, sorted(d.name for d in (data / 'research-packets').iterdir())
        (first, over), written = run(both)
        self.assertEqual((first['packet'], first['status'], over['packet'], over['status']), (RP, 'passed', second, 'failed'))
        self.assertEqual(over, {'packet': second, 'status': 'failed', 'warnings': [], 'raws': {},
                                'problems': [f'{size} bytes: over the {size // 2} left for this head']})
        self.assertEqual(written, [RP])  # the second folder is never written
        calls = iter([OSError('gh'), None])

        def first_breaks(f, r):  # bytes written before an error still count
            err = next(calls)
            if err:
                raise err
            return both(f, r)
        (first, over), written = run(first_breaks)
        self.assertEqual((first['status'], first['problems'], over['status']), ('failed', ['the attestation check did not finish: OSError'], 'failed'))
        self.assertEqual(written, [RP])

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

    def settle(self, said, sha, verify):
        return pg.attest(json.loads(json.dumps(said)), 'main', sha, Path(tempfile.mkdtemp(dir=self.tmp)), 'o/r', self.repo,
                         verify=verify)['packets'][0]

    def test_a_folder_with_its_raws_passes_only_on_the_runs_statement_never_on_packet_reads_word(self):
        sha = self.commit('paquete')
        said = self.run_gate(sha)
        real = dict(said['packets'][0]['raws'])
        said['packets'][0]['raws'] = {k: '0' * 64 for k in real}  # a reader taken over lies about the digests
        signed = statement(self.repo / 'research-packets' / RP)
        attested = self.settle(said, sha, lambda f, r: [signed])
        self.assertEqual((attested['status'], attested['raws'], attested['attested']['files']), ('passed', real, 4))  # packet, receipt, two raws
        unattested = self.settle(said, sha, lambda f, r: [])  # every raw kept and packet-read passed it: still no pass
        self.assertEqual((unattested['status'], unattested['raws']), ('failed', {}))
        self.assertNotIn('attested', unattested)

    def test_an_invalid_packet_with_its_raws_and_a_forged_pass_fails(self):
        # GPT, second REVISE of #56: an invented quote, a filler raw under the expected name and a forged passed
        raw = next((self.repo / 'research-packets' / RP / 'raw').rglob('*.html'))
        raw.write_bytes(b'<html><body>relleno</body></html>')
        sha = self.commit('cita inventada, crudo de relleno')
        self.assertEqual(self.run_gate(sha)['packets'][0]['status'], 'failed')  # what an honest reader says
        forged = {'head_sha': sha, 'packets': [{'packet': RP, 'status': 'passed', 'problems': [], 'warnings': [],
                                                 'raws': {}, 'checked_by': 'packet-read'}]}
        packet = self.settle(forged, sha, lambda f, r: [])
        self.assertEqual((packet['status'], packet['raws']), ('failed', {}))

    def test_main_rejects_a_bad_sha_and_writes_one_result(self):
        with self.assertRaises(SystemExit):
            pg.main(['--base', 'main', '--sha', 'main', '--data', str(self.tmp), '--out', str(self.tmp / 'x.json')])
        sha = self.commit('paquete')
        out = self.tmp / 'packets.json'
        self.assertEqual(pg.main(['--base', 'main', '--sha', sha, '--data', str(Path(tempfile.mkdtemp(dir=self.tmp))),
                                  '--out', str(out), '--repo', str(self.repo)]), 0)
        self.assertEqual(json.loads(out.read_text(encoding='utf-8'))['packets'][0]['status'], 'passed')



@unittest.skipUnless(shutil.which('git'), 'needs git')
class Attested(unittest.TestCase):
    """A metadata_only packet keeps no raw, so this gate cannot check its quotes: the investigar run's gate did, and its
    attestation over every file is what vouches for them (GPT, REVISE of #52)."""
    REPO = 'romerobarcenabraulio-hash/ZPMND-RESEARCH-GROUP'

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.repo = self.tmp / 'repo'
        PacketGate.git(self, 'init', '-q', '-b', 'main', str(self.repo))
        (self.repo / 'README.md').write_text('main\n', encoding='utf-8')
        PacketGate.commit(self, 'main')
        work = self.tmp / 'work'
        rows = inv.fetch({**PLAN, 'sources': [{**CLOSED, 'role': 'primary'}]}, work, opener=FakeOpener(ROUTES), sleep=lambda s: None)
        ans = answer()
        ans['findings']['confirmed'] = [{'claim': 'El dataset trae una nota.', 'artifact_ids': [A_CLOSED],
                                         'quote': '"cerrado": true, "detalle": "solo citable"', 'locator': 'raíz'}]
        built = inv.assemble(RR, rows, ans, work, self.tmp / 'out', 'm', '2026-10-23T00:00:00Z')
        PacketGate.git(self, '-C', str(self.repo), 'checkout', '-q', '-b', 'pr')
        shutil.copytree(built, self.repo / 'research-packets' / RP)
        self.sha = PacketGate.commit(self, 'paquete de solo metadatos')
        self.data = Path(tempfile.mkdtemp(dir=self.tmp))
        self.result = pg.gate('main', self.sha, self.data, self.repo)

    def git(self, *args):
        return PacketGate.git(self, *args)

    def attest(self, verify, result=None):
        result = json.loads(json.dumps(self.result if result is None else result))
        return pg.attest(result, 'main', self.sha, Path(tempfile.mkdtemp(dir=self.tmp)), self.REPO, self.repo, verify=verify)

    def said(self, **packet):
        """packet-read's result for this head, as a runner a hostile raw took over could write it."""
        return {'head_sha': self.sha, 'packets': [{'packet': RP, **packet}]}

    def signed(self):
        """GitHub's answer for the head's packet: the one statement its investigar run signed."""
        st = statement(self.repo / 'research-packets' / RP)
        return lambda f, r: [st]

    def test_a_packet_whose_only_gap_is_its_unkept_raws_needs_the_runs_attestation(self):
        [packet] = self.result['packets']
        self.assertEqual((packet['status'], packet['problems'], packet['raws']), ('needs_attestation', [], {}))
        self.assertEqual(sorted(packet['files']), [f'research-packets/{RP}/packet.json', f'research-packets/{RP}/receipt.json'])

    def test_one_statement_naming_exactly_the_heads_folder_passes_it(self):
        st, seen = statement(self.repo / 'research-packets' / RP), []

        def verify(f, r):
            seen.append((f.name, r, f.read_bytes()))
            return [st]
        [packet] = self.attest(verify)['packets']
        self.assertEqual(packet, {'packet': RP, 'status': 'passed', 'problems': [], 'warnings': [], 'raws': {},
                                  'attested': {'signer_workflow': f'{self.REPO}/.github/workflows/investigar.yml',
                                               'ref': 'refs/heads/main', 'files': 2}})
        # asked once, for packet.json as the head holds it: written again from git objects, never from the reading job
        self.assertEqual(seen, [('packet.json', self.REPO, (self.repo / 'research-packets' / RP / 'packet.json').read_bytes())])
        other_run = {**st, 'subject': st['subject'][:1]}
        [packet] = self.attest(lambda f, r: [other_run, st])['packets']  # any one of GitHub's statements may be the one
        self.assertEqual(packet['status'], 'passed')

    def test_a_statement_that_does_not_name_exactly_the_folder_fails_it(self):
        # GPT, second REVISE of #56: each file attested on its own did not bind the folder; one statement must
        st = statement(self.repo / 'research-packets' / RP)
        first, second = st['subject']
        other = {**second, 'digest': {'sha256': '0' * 64}}
        cases = {'none': [], 'one file short': [{**st, 'subject': [first]}],
                 'one file more': [{**st, 'subject': [first, second, {'name': f'research-packets/{RP}/raw/x.html', 'digest': {'sha256': 'a' * 64}}]}],
                 'another digest': [{**st, 'subject': [first, other]}],
                 'moved': [{**st, 'subject': [first, {**second, 'name': f'research-packets/{RP}/sub/receipt.json'}]}],
                 'split across two runs': [{**st, 'subject': [first]}, {**st, 'subject': [second]}],
                 'a name twice': [{**st, 'subject': [first, second, second]}],
                 'not a statement': [{'subject': 'x'}, None, {'subject': [{'name': 'a'}]}]}
        for name, statements in cases.items():
            with self.subTest(name):
                [packet] = self.attest(lambda f, r, statements=statements: statements)['packets']
                self.assertEqual((packet['status'], packet['raws']), ('failed', {}))
                self.assertEqual(packet['problems'], [f'research-packets/{RP}: no statement from .github/workflows/investigar.yml on main names exactly its 2 files'])

    def test_files_of_two_attested_packets_never_pass_together(self):
        mine = statement(self.repo / 'research-packets' / RP)
        donor = self.tmp / 'donor'
        shutil.copytree(self.repo / 'research-packets' / RP, donor)
        (donor / 'raw').mkdir()
        (donor / 'raw' / 'otro.html').write_bytes(b'<html>otro paquete</html>')
        theirs = statement(donor)
        shutil.copy(donor / 'raw' / 'otro.html', self.repo / 'research-packets' / RP / 'raw.html')
        self.sha = PacketGate.commit(self, 'un crudo atestado de otro paquete')
        [packet] = self.attest(lambda f, r: [mine, theirs], self.said(status='needs_attestation'))['packets']
        self.assertEqual(packet['status'], 'failed')

    def test_a_pass_forged_by_packet_read_is_never_relayed(self):
        # GPT, REVISE of #56: a reader a hostile raw took over says passed, attested, with raws; nothing of it survives
        forged = self.said(status='passed', problems=[], warnings=[], files={},
                           raws={f'research-packets/{RP}/raw/sha256/aa/{"a" * 64}.html': 'b' * 64},
                           attested={'signer_workflow': f'{self.REPO}/.github/workflows/investigar.yml', 'ref': 'refs/heads/main', 'files': 2})
        [packet] = self.attest(lambda f, r: [], forged)['packets']
        self.assertEqual((packet['status'], packet['raws']), ('failed', {}))
        self.assertNotIn('attested', packet)
        self.assertNotIn('checked_by', packet)

    def test_packet_read_can_deny_a_pass_but_never_grant_one(self):
        for status in ('failed', 'removed', 'otro', None):
            with self.subTest(status):
                [packet] = self.attest(self.signed(), self.said(status=status, problems=['x' * 900, 7], raws={'a': 'b'}))['packets']
                self.assertEqual((packet['status'], packet['raws']), ('failed', {}))
                self.assertEqual(packet['problems'], ['x' * 500])  # its words, cut short; never anything but strings
                self.assertNotIn('attested', packet)
        [packet] = self.attest(self.signed(), self.said(status='failed', problems=['p'] * 60))['packets']
        self.assertEqual(len(packet['problems']), 50)
        for result in ({'head_sha': '0' * 40, 'packets': [{'packet': RP, 'status': 'passed'}]},  # another head
                       {'head_sha': self.sha, 'packets': []}, None, []):  # no result for the folder, or none at all
            with self.subTest(result=result):
                # even with the run's statement at hand: no pass of packet-read for this head, no pass
                [packet] = self.attest(self.signed(), result)['packets'] if result is not None else \
                    pg.attest(None, 'main', self.sha, Path(tempfile.mkdtemp(dir=self.tmp)), self.REPO, self.repo, verify=self.signed())['packets']
                self.assertEqual((packet['packet'], packet['status']), (RP, 'failed'))
        [packet] = self.attest(self.signed(), {'head_sha': self.sha, 'packets': []})['packets']
        self.assertEqual(packet['problems'], ['packet-read did not pass it'])

    def test_the_folders_are_listed_here_never_taken_from_packet_read(self):
        result = {'head_sha': self.sha, 'packets': [{'packet': '../../x', 'status': 'passed'},
                                                    {'packet': 'RP-2026-10-23-otro', 'status': 'passed'}]}
        packets = self.attest(self.signed(), result)['packets']
        self.assertEqual([p['packet'] for p in packets], [RP])  # only what the head changes
        self.assertEqual(packets[0]['status'], 'failed')  # and packet-read gave it no result

    def test_an_error_is_a_failed_result_never_a_missing_one(self):
        # GPT, #56: a gh that hangs or is missing must not leave the packet without a result
        for exc in (subprocess.TimeoutExpired(['gh'], 120), OSError('gh missing')):
            with self.subTest(exc=type(exc).__name__):
                def verify(f, r, exc=exc):
                    raise exc
                [packet] = self.attest(verify)['packets']
                self.assertEqual((packet['status'], packet['problems']),
                                 ('failed', [f'the attestation check did not finish: {type(exc).__name__}']))

    def test_a_folder_that_is_not_a_packet_or_holds_a_link_or_an_oversized_file_is_never_attested(self):
        other = self.repo / 'research-packets' / 'x-carpeta'
        other.mkdir(parents=True)
        (other / 'packet.json').write_text('{}', encoding='utf-8')
        (self.repo / 'research-packets' / RP / 'enlace').symlink_to('packet.json')
        self.sha = PacketGate.commit(self, 'una carpeta que no es paquete y un enlace')
        packets = self.attest(lambda f, r: [statement(self.repo / 'research-packets' / RP)], self.said(status='needs_attestation'))['packets']
        self.assertEqual([(p['packet'], p['status']) for p in packets], [(RP, 'failed')])  # x-carpeta is not a packet
        (self.repo / 'research-packets' / RP / 'enlace').unlink()
        self.sha = PacketGate.commit(self, 'sin enlace')
        with mock.patch.object(pg, 'MAX_BLOB', 10):
            [packet] = self.attest(self.signed(), self.said(status='needs_attestation'))['packets']
        self.assertEqual(packet['status'], 'failed')
        [packet] = self.attest(self.signed(), self.said(status='needs_attestation'))['packets']
        self.assertEqual(packet['status'], 'passed')

    def test_a_removed_folder_is_said_removed_here(self):
        self.git('-C', str(self.repo), 'checkout', '-q', 'main')
        self.git('-C', str(self.repo), 'merge', '-q', 'pr')
        self.git('-C', str(self.repo), 'checkout', '-q', '-b', 'quita', 'main')
        self.git('-C', str(self.repo), 'rm', '-q', '-r', f'research-packets/{RP}')
        (self.repo / 'otro.txt').write_text('x\n', encoding='utf-8')
        self.sha = PacketGate.commit(self, 'quita el paquete')
        self.assertEqual(self.attest(lambda f, r: [], self.said(status='passed'))['packets'], [{'packet': RP, 'status': 'removed'}])

    def test_any_other_warning_fails_the_packet_instead_of_waiting_for_an_attestation(self):
        p = self.repo / 'research-packets' / RP / 'packet.json'
        packet = json.loads(p.read_text(encoding='utf-8'))
        packet['findings']['confirmed'].append({'claim': 'Sin cita.', 'artifact_ids': [A_CLOSED], 'locator': 'raíz'})
        p.write_text(json.dumps(packet), encoding='utf-8')
        sha = PacketGate.commit(self, 'un hallazgo sin cita')
        [result] = pg.gate('main', sha, Path(tempfile.mkdtemp(dir=self.tmp)), self.repo)['packets']
        self.assertEqual((result['status'], result['files']), ('failed', {}))
        self.assertIn('confirmed[1]: no quote, so nothing to verify', result['warnings'])

    def test_a_real_problem_never_waits_for_an_attestation(self):
        p = self.repo / 'research-packets' / RP / 'packet.json'
        packet = json.loads(p.read_text(encoding='utf-8'))
        packet['status'] = 'ACTIVE'  # outside the schema
        p.write_text(json.dumps(packet), encoding='utf-8')
        sha = PacketGate.commit(self, 'estado inválido')
        [result] = pg.gate('main', sha, Path(tempfile.mkdtemp(dir=self.tmp)), self.repo)['packets']
        self.assertEqual((result['status'], result['files']), ('failed', {}))

    def test_the_attest_step_rewrites_packets_json_and_checks_its_input(self):
        out = self.tmp / 'packets.json'
        out.write_text(json.dumps(self.result), encoding='utf-8')
        data = str(Path(tempfile.mkdtemp(dir=self.tmp)))
        with mock.patch.object(pg, 'verify_gh', return_value=[statement(self.repo / 'research-packets' / RP)]):
            self.assertEqual(pg.main(['--attest', str(out), '--base', 'main', '--sha', self.sha, '--data', data,
                                      '--repo-name', self.REPO, '--repo', str(self.repo)]), 0)
        self.assertEqual(json.loads(out.read_text(encoding='utf-8'))['packets'][0]['status'], 'passed')
        out.write_text('no es json', encoding='utf-8')  # an unreadable packet-read result passes nothing
        with mock.patch.object(pg, 'verify_gh', return_value=[]):
            pg.main(['--attest', str(out), '--base', 'main', '--sha', self.sha, '--data', data, '--repo-name', self.REPO,
                     '--repo', str(self.repo)])
        self.assertEqual(json.loads(out.read_text(encoding='utf-8'))['packets'][0]['status'], 'failed')
        with mock.patch.object(pg, 'verify_gh', return_value=[statement(self.repo / 'research-packets' / RP)]):  # no folder list, no pass
            pg.main(['--attest', str(out), '--base', 'no-existe', '--sha', self.sha, '--data', data, '--repo-name', self.REPO,
                     '--repo', str(self.repo)])
        self.assertEqual(json.loads(out.read_text(encoding='utf-8')),
                         {'head_sha': self.sha, 'packets': [], 'error': 'the clean check did not run: CalledProcessError'})
        for bad in (['--repo-name', 'no/es/repo', '--sha', self.sha, '--base', 'main'],
                    ['--repo-name', self.REPO, '--sha', 'main', '--base', 'main'],
                    ['--repo-name', self.REPO, '--base', 'main'], ['--repo-name', self.REPO, '--sha', self.sha]):
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                pg.main(['--attest', str(out), '--data', data, *bad])
        with self.assertRaises(SystemExit):
            pg.main(['--data', str(self.data)])  # the gate itself still needs a base, a head and an output

    def test_verify_asks_github_for_the_signer_the_ref_and_a_hosted_runner(self):
        st = statement(self.repo / 'research-packets' / RP)
        answer = json.dumps([{'attestation': {'bundle': {}}, 'verificationResult': {'statement': st, 'signature': {}}}]).encode()
        with mock.patch.object(pg.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, answer, b'')) as run:
            self.assertEqual(pg.verify_gh(self.tmp / 'x', self.REPO), [st])
        argv = run.call_args.args[0]
        self.assertEqual(argv[:3], ['gh', 'attestation', 'verify'])
        for flag, value in (('--repo', self.REPO), ('--signer-workflow', f'{self.REPO}/.github/workflows/investigar.yml'),
                            ('--source-ref', 'refs/heads/main'), ('--format', 'json')):
            self.assertEqual(argv[argv.index(flag) + 1], value)
        self.assertIn('--deny-self-hosted-runners', argv)
        for code, out in ((1, answer), (0, b'no es json'), (0, b'[{"verificationResult": {}}]'), (0, b'{"x": 1}')):
            with self.subTest(code=code, out=out[:20]), \
                    mock.patch.object(pg.subprocess, 'run', return_value=subprocess.CompletedProcess([], code, out, b'')):
                self.assertEqual(pg.verify_gh(self.tmp / 'x', self.REPO), [])  # fail closed

    def test_subjects_are_distinct_names_with_a_sha256_each(self):
        self.assertEqual(pg.subjects({'subject': [{'name': 'a', 'digest': {'sha256': 'x'}}]}), {'a': 'x'})
        for bad in ({'subject': [{'name': 'a', 'digest': {'sha256': 'x'}}] * 2}, {'subject': [{'name': 'a', 'digest': {}}]},
                    {'subject': None}, {}, None):
            with self.subTest(bad=bad):
                self.assertIsNone(pg.subjects(bad))


if __name__ == '__main__':
    unittest.main()
