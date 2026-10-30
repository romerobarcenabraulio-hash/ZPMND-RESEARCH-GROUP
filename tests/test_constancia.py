"""Constancia de origen (SECURITY.md T20): every packet file on main is attested by constancia.yml, and the check a
consumer runs passes on the published bytes and fails on a copy with one byte changed.

The script runs here against a stub `gh` that plays the attestation store: a file verifies when its sha256 is in the
store, or always when the stub is told to (a verifier that checks nothing, which the last step must catch).
"""
import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'constancia.sh'
WORKFLOW = ROOT / '.github' / 'workflows' / 'constancia.yml'
REPO = 'romerobarcenabraulio-hash/ZPMND-RESEARCH-GROUP'
STUB = """#!/bin/bash
printf '%s\\n' "$*" >> "$STUB_LOG"
[ "${STUB_ALL:-}" = 1 ] && exit 0
sum=$(sha256sum "$3" | cut -d' ' -f1)
grep -qx "$sum" "$STUB_STORE"
"""


class Script(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.work = self.tmp / 'work'
        (self.tmp / 'bin').mkdir()
        (self.tmp / 'bin' / 'gh').write_text(STUB)
        (self.tmp / 'bin' / 'gh').chmod(0o755)
        self.store = self.tmp / 'store'
        self.store.write_text('')
        self.log = self.tmp / 'log'

    def packet(self, files):
        for rel, data in files.items():
            p = self.work / 'research-packets' / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)

    def attest(self, *rels):
        with self.store.open('a') as s:
            for rel in rels:
                s.write(hashlib.sha256((self.work / 'research-packets' / rel).read_bytes()).hexdigest() + '\n')

    def run_script(self, *args, all_verify=False):
        self.work.mkdir(exist_ok=True)
        env = {'PATH': f'{self.tmp / "bin"}:{os.environ["PATH"]}', 'REPO': REPO, 'GH_TOKEN': 'x',
               'STUB_STORE': str(self.store), 'STUB_LOG': str(self.log), 'HOME': str(self.tmp)}
        if all_verify:
            env['STUB_ALL'] = '1'
        return subprocess.run(['bash', str(SCRIPT), *args], cwd=self.work, env=env, capture_output=True, text=True,
                              timeout=120)

    def test_faltan_lists_exactly_the_files_no_attestation_covers(self):
        self.packet({'RP-a/packet.json': b'{"a": 1}', 'RP-a/raw/x.pdf': b'%PDF-1', 'RP-b/packet.json': b'{"b": 2}'})
        self.attest('RP-a/packet.json')
        out = self.tmp / 'sujetos'
        r = self.run_script('faltan', str(out))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, 'n=2\n')
        want = ''.join(f'{hashlib.sha256((self.work / "research-packets" / p).read_bytes()).hexdigest()}  research-packets/{p}\n'
                       for p in ('RP-a/raw/x.pdf', 'RP-b/packet.json'))
        self.assertEqual(out.read_text(), want)

    def test_faltan_with_everything_attested_is_zero(self):
        self.packet({'RP-a/packet.json': b'{}'})
        self.attest('RP-a/packet.json')
        r = self.run_script('faltan', str(self.tmp / 'sujetos'))
        self.assertEqual((r.returncode, r.stdout), (0, 'n=0\n'))

    def test_every_check_pins_repo_workflow_main_and_github_runners(self):
        self.packet({'RP-a/packet.json': b'{}'})
        self.run_script('faltan', str(self.tmp / 'sujetos'))
        self.assertEqual(self.log.read_text().split('\n')[0],
                         f'attestation verify research-packets/RP-a/packet.json -R {REPO} --signer-workflow '
                         f'{REPO}/.github/workflows/constancia.yml --source-ref refs/heads/main --deny-self-hosted-runners')

    def test_a_path_a_checksums_line_could_misread_stops_before_any_check(self):
        for name in ('RP-a/raw/dos palabras.pdf', 'RP-a/raw/año.pdf', 'RP-a/raw/a\\b.pdf'):
            with self.subTest(name=name):
                self.setUp()
                self.packet({'RP-a/packet.json': b'{}', name: b'x'})
                out = self.tmp / 'sujetos'
                r = self.run_script('faltan', str(out))
                self.assertEqual(r.returncode, 1)
                self.assertIn('characters outside', r.stderr)
                self.assertFalse(self.log.exists())

    def test_more_than_one_attestation_holds_stops(self):
        self.packet({f'RP-a/raw/{i}.txt': str(i).encode() for i in range(1025)})
        r = self.run_script('faltan', str(self.tmp / 'sujetos'))
        self.assertEqual(r.returncode, 1)
        self.assertIn('over the 1024 subjects', r.stderr)

    def test_no_packet_files_stops(self):
        (self.work / 'research-packets').mkdir(parents=True)
        self.assertEqual(self.run_script('faltan', str(self.tmp / 'sujetos')).returncode, 1)
        self.assertEqual(self.run_script('comprobar').returncode, 1)

    def test_comprobar_passes_when_every_file_verifies_and_the_changed_copy_does_not(self):
        self.packet({'RP-a/packet.json': b'{"a": 1}', 'RP-a/raw/x.pdf': b'%PDF-1'})
        self.attest('RP-a/packet.json', 'RP-a/raw/x.pdf')
        r = self.run_script('comprobar')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('2 packet files verified', r.stdout)

    def test_comprobar_fails_on_a_file_without_attestation(self):
        self.packet({'RP-a/packet.json': b'{"a": 1}', 'RP-a/raw/x.pdf': b'%PDF-1'})
        self.attest('RP-a/packet.json')
        r = self.run_script('comprobar')
        self.assertEqual(r.returncode, 1)
        self.assertIn('not verified: research-packets/RP-a/raw/x.pdf', r.stderr)

    def test_comprobar_fails_when_a_changed_copy_verifies(self):  # a verifier that checks nothing is caught
        self.packet({'RP-a/packet.json': b'{"a": 1}'})
        r = self.run_script('comprobar', all_verify=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn('with one byte changed verified', r.stderr)

    def test_the_changed_copy_comes_from_a_file_with_bytes(self):
        self.packet({'RP-a/a-vacio.txt': b'', 'RP-a/packet.json': b'{"a": 1}'})
        self.attest('RP-a/a-vacio.txt', 'RP-a/packet.json')
        r = self.run_script('comprobar')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('a copy of research-packets/RP-a/packet.json', r.stdout)

    def test_a_wrong_mode_is_refused(self):
        self.assertEqual(self.run_script('otra').returncode, 2)


class Workflow(unittest.TestCase):
    def setUp(self):
        self.doc = yaml.safe_load(WORKFLOW.read_text(encoding='utf-8'))
        self.job = self.doc['jobs']['constancia']
        self.steps = self.job['steps']

    def test_it_runs_when_packets_can_reach_main_and_nowhere_else(self):
        on = self.doc.get('on') or self.doc[True]
        self.assertEqual(on['push'], {'branches': ['main'], 'paths': ['research-packets/**']})
        self.assertEqual(on['workflow_run'], {'workflows': ['automerge'], 'types': ['completed']})
        self.assertIn('schedule', on)
        self.assertIn('workflow_dispatch', on)
        self.assertEqual(set(on), {'push', 'workflow_run', 'schedule', 'workflow_dispatch'})
        self.assertEqual(self.job['if'], "github.ref == 'refs/heads/main'")

    def test_only_the_powers_an_attestation_needs(self):
        self.assertEqual(self.doc['permissions'], {})
        self.assertEqual(self.job['permissions'], {'contents': 'read', 'id-token': 'write', 'attestations': 'write'})
        self.assertEqual(list(self.doc['jobs']), ['constancia'])
        self.assertNotIn('secrets.', WORKFLOW.read_text(encoding='utf-8'))

    def test_on_githubs_runner_from_main_without_a_kept_token(self):
        self.assertEqual(self.job['runs-on'], 'ubuntu-24.04')
        self.assertEqual(self.steps[0]['with'], {'persist-credentials': False})  # no ref: the event's commit on main

    def test_attests_only_what_is_missing_then_checks_everything(self):
        names = [s.get('uses', s.get('run', '')) for s in self.steps]
        self.assertIn('constancia.sh faltan', names[1])
        self.assertTrue(names[2].startswith('actions/attest-build-provenance@'))
        self.assertEqual(self.steps[2]['if'], "steps.faltan.outputs.n != '0'")
        self.assertEqual(self.steps[2]['with'], {'subject-checksums': '${{ runner.temp }}/sujetos.sha256'})
        self.assertEqual(names[3], 'bash scripts/constancia.sh comprobar')
        self.assertNotIn('if', self.steps[3])
        self.assertEqual(len(self.steps), 4)


if __name__ == '__main__':
    unittest.main()
