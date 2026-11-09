"""make check runs what CI runs on a PR (owner's order 7): the suite and the offline policy check, then the mutants of
the changed files, split in shards. The plan is read from make itself (make -n), and compared with ci.yml."""
import importlib.util
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

R = Path(__file__).resolve().parents[1]
CI = (R / '.github' / 'workflows' / 'ci.yml').read_text(encoding='utf-8')
_spec = importlib.util.spec_from_file_location('mutar', R / 'scripts' / 'mutar.py')
mutar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mutar)


def plan(*args):
    # inside `make check` itself the child make inherits SHARDS and BASE, through MAKEFLAGS and as plain environment
    # variables that ?= does not override: only PATH goes in, so the plan is the Makefile's own
    env = {'PATH': os.environ['PATH']}
    out = subprocess.run(['make', '-s', '-n', '-C', str(R), 'check', *args], capture_output=True, text=True, check=True,
                         env=env)
    return out.stdout.splitlines()


def mutantes(lines):
    return [x for x in lines if x.endswith(' scripts/mutar_pr.py')]


@unittest.skipUnless(shutil.which('make'), 'make is not installed')
class MakeCheck(unittest.TestCase):
    def test_check_runs_the_steps_ci_runs_before_the_mutants(self):
        lines = plan()
        suite = [m.group(1) for m in re.finditer(r'- run: (python -m (?:unittest discover|rg\.openclaw_policy)[^\n]*)', CI)]
        self.assertEqual(len(suite), 2)
        self.assertTrue(lines[0].startswith('python -m unittest discover -s tests -t .'))
        self.assertIn(suite[0].removesuffix(' -v'), lines[0])
        self.assertEqual(lines[1], suite[1])
        self.assertEqual(lines[2:], ['RG_SHARD=0/1 RG_MUT_BASE=origin/main python scripts/mutar_pr.py'])
        self.assertIn('python scripts/mutar_pr.py', CI)

    def test_the_shards_cover_every_index_once_and_take_the_given_base(self):
        got = mutantes(plan('SHARDS=4', 'BASE=origin/x'))
        self.assertEqual(sorted(got), [f'RG_SHARD={k}/4 RG_MUT_BASE=origin/x python scripts/mutar_pr.py' for k in range(4)])

    def test_a_shard_count_that_is_not_a_whole_number_of_one_or_more_reaches_the_mutant_runner_which_refuses_it(self):
        # check cannot pass with no mutants planned: the one shard it always plans is one mutar.shard refuses
        for bad in ('0', 'abc', '-1', '2.5'):
            with self.subTest(shards=bad):
                self.assertEqual(mutantes(plan(f'SHARDS={bad}')),
                                 [f'RG_SHARD=0/{bad} RG_MUT_BASE=origin/main python scripts/mutar_pr.py'])
                with self.assertRaises(ValueError):
                    mutar.shard(['a'], f'0/{bad}')


if __name__ == '__main__':
    unittest.main()
