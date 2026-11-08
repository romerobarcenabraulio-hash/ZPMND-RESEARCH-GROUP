"""scripts/mutar_pr.py: a PR runs the mutants of the files it changes, all when it touches tests/, the runner or the
dependencies, none for docs or data; without a base (the nightly run, mutacion-noche.yml) everything runs."""
import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('mutar_pr', ROOT / 'scripts' / 'mutar_pr.py')
mp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mp)
MUT = [('rg/a.py', 'x', 'y'), ('rg/b.py', 'x', 'y'), ('.github/workflows/c.yml', 'x', 'y')]


class Elegir(unittest.TestCase):
    def test_only_the_mutants_of_changed_files_and_none_for_docs_or_data(self):
        self.assertEqual(mp.elegir(['rg/a.py', 'docs/X.md'], MUT), [MUT[0]])
        self.assertEqual(mp.elegir(['.github/workflows/c.yml'], MUT), [MUT[2]])
        self.assertEqual(mp.elegir(['docs/ESTADO.md', 'requests/RR-x.json', 'docs/medicion/a.json'], MUT), [])

    def test_all_when_tests_the_runner_or_the_dependencies_change(self):
        for f in ('tests/test_a.py', 'tests/helpers.py', 'scripts/mutar.py', 'scripts/mutar_pr.py', 'requirements-dev.txt'):
            self.assertEqual(mp.elegir([f], MUT), MUT, f)


class Main(unittest.TestCase):
    def correr(self, base, files):
        with mock.patch.object(mp.mutar, 'main', return_value=0) as run, mock.patch.dict(os.environ, {'RG_MUT_BASE': base}), \
                mock.patch.object(mp, 'cambiados', return_value=files), mock.patch.object(mp.mutar, 'MUT', list(MUT)):
            self.assertEqual(mp.main(), 0)
            return list(mp.mutar.MUT), run.call_count

    def test_without_a_base_everything_runs_with_one_only_the_selection_and_nothing_at_all_if_empty(self):
        self.assertEqual(self.correr('', ['docs/a.md']), (MUT, 1))
        self.assertEqual(self.correr('origin/main', ['rg/b.py']), ([MUT[1]], 1))
        self.assertEqual(self.correr('origin/main', ['docs/a.md']), ([], 0))  # not even the baseline suite

    def test_the_changed_files_come_from_git_against_the_base(self):
        with tempfile.TemporaryDirectory() as d:
            def g(*a):
                subprocess.run(['git', '-c', 'user.email=t@invalid', '-c', 'user.name=t', *a], cwd=d, check=True, capture_output=True)
            g('init', '-q')
            Path(d, 'a.txt').write_text('1', encoding='utf-8')
            g('add', '-A'), g('commit', '-qm', 'base'), g('branch', 'base')
            Path(d, 'b.txt').write_text('2', encoding='utf-8')
            g('add', '-A'), g('commit', '-qm', 'pr')
            cwd = os.getcwd()
            os.chdir(d)
            try:
                self.assertEqual(mp.cambiados('base'), ['b.txt'])
            finally:
                os.chdir(cwd)


class Workflows(unittest.TestCase):
    def test_a_pr_selects_and_the_night_runs_everything_with_the_same_shards(self):
        wf = lambda n: yaml.safe_load((ROOT / '.github' / 'workflows' / n).read_text(encoding='utf-8'))
        pr = wf('ci.yml')['jobs']['mutation']
        step = next(s for s in pr['steps'] if 'scripts/mutar' in s.get('run', ''))
        self.assertEqual((step['run'], step['env']['RG_MUT_BASE']), ('python scripts/mutar_pr.py', 'origin/${{ github.base_ref }}'))
        self.assertEqual(next(s for s in pr['steps'] if 'checkout' in s.get('uses', ''))['with']['fetch-depth'], 0)
        noche = wf('mutacion-noche.yml')
        self.assertEqual(set(noche.get('on') or noche[True]), {'schedule', 'workflow_dispatch'})
        run = next(s for s in noche['jobs']['mutation']['steps'] if 'scripts/mutar' in s.get('run', ''))
        self.assertEqual((run['run'], 'RG_MUT_BASE' in run.get('env', {})), ('python scripts/mutar.py', False))
        self.assertEqual(noche['jobs']['mutation']['strategy']['matrix'], pr['strategy']['matrix'])


if __name__ == '__main__':
    unittest.main()
