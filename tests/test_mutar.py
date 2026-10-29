"""scripts/mutar.py split in shards: the shards partition the mutant list, and CI ties them to its matrix."""
import importlib.util
import io
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('mutar', ROOT / 'scripts' / 'mutar.py')
mutar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mutar)


class Shards(unittest.TestCase):
    def test_shards_partition_the_list(self):
        items = list('abcdefghijk')
        for n in range(1, 6):
            parts = [mutar.shard(items, f'{k}/{n}') for k in range(n)]
            seen = [i for p in parts for i, _ in p]
            self.assertEqual(sorted(seen), list(range(1, len(items) + 1)), n)   # each mutant exactly once
            self.assertTrue(all(items[i - 1] == m for p in parts for i, m in p))

    def test_the_mutant_list_is_sorted_without_duplicates(self):
        # Each PR inserts its mutants in place; appending at the end made parallel PRs conflict on one line (2026-10-21).
        self.assertEqual(mutar.MUT, sorted(mutar.MUT))
        self.assertEqual(len(mutar.MUT), len(set(mutar.MUT)))

    def test_a_bad_shard_spec_stops_the_run(self):
        for spec in ('4/4', '-1/4', '1/0', 'x', '1'):
            with self.assertRaises(ValueError, msg=spec):
                mutar.shard(['a'], spec)

    def test_ci_derives_the_shard_from_the_matrix(self):
        job = yaml.safe_load((ROOT / '.github' / 'workflows' / 'ci.yml').read_text(encoding='utf-8'))['jobs']['mutation']
        env = next(s['env'] for s in job['steps'] if 'mutar.py' in s.get('run', ''))
        self.assertEqual(env['RG_SHARD'], '${{ strategy.job-index }}/${{ strategy.job-total }}')
        self.assertFalse(job['strategy']['fail-fast'])


class Faster(unittest.TestCase):
    """Same verdicts in less time: a data-only PR skips; a mutant meets its own tests before the whole suite."""

    def test_only_data_skips(self):
        for paths in (['research-packets/RP-x/packet.json', 'research-packets/RP-x/raw/sha256/ab/ab.html'],
                      ['requests/RR-x.json', 'requests/plans/RR-x.json'], ['docs/NORTE.md'], ['README.md', 'SECURITY.md'],
                      ['knowledge-demand/x.json']):
            self.assertTrue(mutar.data_only(paths), paths)
        for paths in ([], ['rg/investigar.py'], ['README.md', 'tests/test_x.py'], ['sources/mx.json'],
                      ['.github/workflows/ci.yml'], ['rg/README.md'], ['scripts/mutar.py'], ['docsx/a']):
            self.assertFalse(mutar.data_only(paths), paths)

    def test_related_are_the_test_modules_that_name_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'tests').mkdir()
            (Path(d) / 'tests' / 'test_a.py').write_text('from rg import investigar\n', encoding='utf-8')
            (Path(d) / 'tests' / 'test_b.py').write_text('import os\n', encoding='utf-8')
            (Path(d) / 'tests' / 'helper.py').write_text('investigar\n', encoding='utf-8')
            self.assertEqual(mutar.related(d, 'rg/investigar.py'), ['tests.test_a'])
            self.assertEqual(mutar.related(d, '.github/workflows/investigar.yml'), ['tests.test_a'])
            self.assertEqual(mutar.related(d, 'rg/otro.py'), [])
            (Path(d) / 'tests' / 'test_c.py').write_text('decide = 1\n', encoding='utf-8')
            self.assertEqual(mutar.related(d, '.github/workflows/ci.yml'), [])  # a whole word, not 'decide'

    def verdict(self, near, related_rc, full_rc):
        calls = []

        def fake(d, failfast=False, modules=None):
            calls.append(modules)
            return subprocess.CompletedProcess([], related_rc if modules else full_rc, '', '')
        with mock.patch.object(mutar, 'suite', fake):
            return mutar.killed('d', near), calls

    def test_the_whole_suite_decides_whenever_the_related_tests_pass(self):
        self.assertEqual(self.verdict(['tests.test_a'], 1, 0), (True, [['tests.test_a']]))  # killed: no full run needed
        self.assertEqual(self.verdict(['tests.test_a'], 0, 1), (True, [['tests.test_a'], None]))
        self.assertEqual(self.verdict(['tests.test_a'], 0, 0), (False, [['tests.test_a'], None]))  # alive only if all pass
        self.assertEqual(self.verdict([], 0, 1), (True, [None]))

    @unittest.skipUnless(shutil.which('git'), 'needs git')
    def test_code_moved_to_docs_is_never_read_as_data_only(self):
        # Claude, REVISE of #43: with rename detection git lists only docs/x.md, and the mutation job would skip
        with tempfile.TemporaryDirectory() as d:
            g = lambda *a: subprocess.run(['git', '-C', d, '-c', 'user.name=t', '-c', 'user.email=t@t', *a],
                                          check=True, capture_output=True, text=True).stdout.strip()
            g('init', '-q', '-b', 'main')
            (Path(d) / 'rg').mkdir()
            (Path(d) / 'rg' / 'guarda.py').write_text('def guarda():\n    return 1\n' * 20, encoding='utf-8')
            g('add', '-A')
            g('commit', '-q', '-m', 'base')
            base = g('rev-parse', 'HEAD')
            (Path(d) / 'docs').mkdir()
            g('mv', 'rg/guarda.py', 'docs/guarda.md')
            g('commit', '-q', '-m', 'mueve el código a docs')
            paths = mutar.changed(base, d)
            self.assertEqual(sorted(paths), ['docs/guarda.md', 'rg/guarda.py'])
            self.assertFalse(mutar.data_only(paths))
            (Path(d) / 'docs' / 'otra.md').write_text('solo datos\n', encoding='utf-8')
            g('add', '-A')
            g('commit', '-q', '-m', 'datos')
            self.assertTrue(mutar.data_only(mutar.changed(g('rev-parse', 'HEAD~1'), d)))

    def test_a_selection_that_fails_on_the_unmutated_copy_never_calls_a_mutant_killed(self):
        # GPT, REVISE of #43: the related modules alone may fail with sound code; then the whole suite decides
        calls = []

        def fake(d, failfast=False, modules=None):
            calls.append(tuple(modules or ()))
            return subprocess.CompletedProcess([], 1 if modules == ['tests.test_a'] else 0, '', '')
        near = {'rg/a.py': ['tests.test_a'], 'rg/a2.py': ['tests.test_a'], 'rg/b.py': ['tests.test_b'], 'rg/c.py': []}
        with mock.patch.object(mutar, 'related', side_effect=lambda d, f: near[f]), mock.patch.object(mutar, 'suite', fake):
            got = mutar.baseline_related('base', ['rg/a.py', 'rg/a2.py', 'rg/b.py', 'rg/c.py'])
        self.assertEqual(got, {'rg/a.py': [], 'rg/a2.py': [], 'rg/b.py': ['tests.test_b'], 'rg/c.py': []})
        self.assertEqual(sorted(calls), [('tests.test_a',), ('tests.test_b',)])  # each selection runs once

    def test_a_data_only_pr_runs_no_mutant(self):
        with mock.patch.dict(os.environ, {'RG_BASE': 'abc'}), \
                mock.patch.object(mutar, 'changed', return_value=['requests/plans/RR-x.json']), \
                mock.patch.object(mutar, 'shard', side_effect=AssertionError('a mutant ran')), \
                mock.patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertIsNone(mutar.main())
        self.assertIn('skipped: the change touches only data', out.getvalue())

    def test_ci_tells_the_runner_what_the_pr_changed(self):
        job = yaml.safe_load((ROOT / '.github' / 'workflows' / 'ci.yml').read_text(encoding='utf-8'))['jobs']['mutation']
        env = next(s['env'] for s in job['steps'] if 'mutar.py' in s.get('run', ''))
        self.assertEqual(env['RG_BASE'], '${{ github.event.pull_request.base.sha }}')
        checkout = next(s for s in job['steps'] if s.get('uses', '').startswith('actions/checkout@'))
        self.assertEqual(checkout['with']['fetch-depth'], 0)
        self.assertEqual(len(job['strategy']['matrix']['shard']), 8)


if __name__ == '__main__':
    unittest.main()
