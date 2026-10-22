"""The auditor's evidence runs, on the PR's code, only main's mutants that the PR's list no longer has (docs/COSTOS.md).
The selection is computed by the workflow from main, over the parsed lists; a guard the PR drops still runs there."""
import ast
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def evidence_step():
    jobs = yaml.safe_load((ROOT / '.github' / 'workflows' / 'auditor.yml').read_text(encoding='utf-8'))['jobs']
    return next(s['run'] for s in jobs['evidence']['steps'] if 'mutar_main.py' in s.get('run', ''))


class MissingFromThePR(unittest.TestCase):
    def setUp(self):
        self.run_text = evidence_step()
        self.snippet = textwrap.dedent(re.search(r"<<'PY'\n(.*?)\nPY\n", self.run_text, re.S).group(1))

    def select(self, main_list, pr_src):
        with tempfile.TemporaryDirectory() as d:
            m, p, out = Path(d) / 'main.py', Path(d) / 'pr.py', Path(d) / 'out.py'
            m.write_text(f'import os\nMUT = [\n' + ''.join(f' {t!r},\n' for t in main_list) + ']\n\ndef main():\n    pass\n',
                         encoding='utf-8')
            p.write_text(pr_src, encoding='utf-8')
            r = subprocess.run([sys.executable, '-I', '-', str(m), str(p), str(out)], input=self.snippet, text=True,
                               capture_output=True)
            if r.returncode:
                return None, None
            tree = ast.parse(out.read_text(encoding='utf-8'))
            node = next(n for n in tree.body if isinstance(n, ast.Assign) and n.targets[0].id == 'MUT')
            self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'main' for n in tree.body))
            return r.stdout.strip(), [tuple(x) for x in ast.literal_eval(node.value)]

    def test_a_guard_the_pr_dropped_or_changed_still_runs(self):
        main_list = [('a', '1', 'x'), ('b', '2', 'y'), ('c', '3', 'z')]
        pr = f"MUT = {[('a', '1', 'x'), ('c', '3', 'CHANGED')]!r}\n"
        self.assertEqual(self.select(main_list, pr), ('2', [('b', '2', 'y'), ('c', '3', 'z')]))

    def test_nothing_dropped_runs_nothing(self):
        main_list = [('a', '1', 'x'), ('b', '2', 'y')]
        self.assertEqual(self.select(main_list, f"MUT = {main_list + [('d', '4', 'w')]!r}\n"), ('0', []))

    def test_an_unreadable_pr_list_runs_all_of_mains(self):
        self.assertEqual(self.select([('a', '1', 'x')], 'MUT = [broken\n'), (None, None))
        self.assertIn('if ! [[ "$n" =~ ^[0-9]+$ ]]; then', self.run_text)
        fallback = self.run_text.split('if ! [[ "$n" =~ ^[0-9]+$ ]]; then', 1)[1].split('elif', 1)[0]
        self.assertIn('cp "$RUNNER_TEMP/mutar_main.py" scripts/mutar_main.py', fallback)


if __name__ == '__main__':
    unittest.main()
