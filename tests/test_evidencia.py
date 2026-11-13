"""The auditor's evidence runs, on the PR's code, main's mutants that the PR's list no longer has (docs/COSTOS.md) and
the ones the PR adds (at most 40). The selection is computed by the workflow from main, over the parsed lists; a guard
the PR drops still runs there, unless its line left the head, and then it is named retired."""
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
    steps = [s for s in jobs['evidence']['steps'] if s.get('id') == 'evidence-run']
    assert len(steps) == 1, 'the evidence step must exist exactly once'
    return steps[0]['run']


class MissingFromThePR(unittest.TestCase):
    def setUp(self):
        self.run_text = evidence_step()
        found = re.search(r"<<'PY'\n(.*?)\nPY\n", self.run_text, re.S)
        self.assertIsNotNone(found, 'the selection snippet is missing from the evidence step')
        self.snippet = textwrap.dedent(found.group(1))

    def select(self, main_list, pr_src, pr_runner='\ndef main():\n    pass\n', head=None):
        """(stdout, main's mutants it runs, the PR's new mutants it runs, the retired lines). head: {path: text} of the
        PR's checkout, where each main anchor is looked up; by default every anchor is still there."""
        with tempfile.TemporaryDirectory() as d:
            for name, text in (head if head is not None else {t[0]: t[1] for t in main_list}).items():
                (Path(d) / name).write_text(text, encoding='utf-8')
            m, p, out, new, ret = (Path(d) / x for x in ('main.py', 'pr.py', 'out.py', 'new.py', 'ret.txt'))
            m.write_text(f'import os\nMUT = [\n' + ''.join(f' {t!r},\n' for t in main_list) + ']\n\ndef main():\n    pass\n',
                         encoding='utf-8')
            p.write_text('import os\n' + pr_src + pr_runner, encoding='utf-8')
            r = subprocess.run([sys.executable, '-I', '-', str(m), str(p), str(out), str(new), str(ret)], input=self.snippet,
                               text=True, capture_output=True, cwd=d)
            if r.returncode:
                return None, None, None, None
            if r.stdout.strip() == 'all':
                return 'all', out.read_text(encoding='utf-8') == m.read_text(encoding='utf-8'), None, None

            def listed(path):
                tree = ast.parse(path.read_text(encoding='utf-8'))
                node = next(n for n in tree.body if isinstance(n, ast.Assign) and n.targets[0].id == 'MUT')
                self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'main' for n in tree.body))
                return [tuple(x) for x in ast.literal_eval(node.value)]
            return r.stdout.strip(), listed(out), listed(new), ret.read_text(encoding='utf-8')

    def test_a_guard_the_pr_dropped_or_changed_still_runs(self):
        main_list = [('a', '1', 'x'), ('b', '2', 'y'), ('c', '3', 'z')]
        pr = 'MUT = [\n' + ''.join(f' {t!r},\n' for t in [('a', '1', 'x'), ('c', '3', 'CHANGED')]) + ']\n'
        self.assertEqual(self.select(main_list, pr), ('2 1', [('b', '2', 'y'), ('c', '3', 'z')], [('c', '3', 'CHANGED')], ''))

    def test_nothing_dropped_runs_only_what_the_pr_adds(self):
        main_list = [('a', '1', 'x'), ('b', '2', 'y')]
        pr = 'MUT = [\n' + ''.join(f' {t!r},\n' for t in main_list + [('d', '4', 'w')]) + ']\n'
        self.assertEqual(self.select(main_list, pr), ('0 1', [], [('d', '4', 'w')], ''))

    def test_a_guard_whose_line_left_the_head_is_named_retired_and_its_replacement_runs(self):
        # GPT on #155: eight NOT FOUND in the evidence and no word on the mutants that replaced them
        main_list = [('a', '1', 'x'), ('b', 'old line', 'y')]
        pr = 'MUT = [\n' + ''.join(f' {t!r},\n' for t in [('a', '1', 'x'), ('b', 'new line', 'v')]) + ']\n'
        out, mains, nuevos, retired = self.select(main_list, pr, head={'a': '1', 'b': 'new line'})
        self.assertEqual((out, mains, nuevos), ('0 1', [], [('b', 'new line', 'v')]))
        self.assertEqual(retired, "retired: b: 'old line' (its line is no longer in this head; what replaces it runs in "
                                  "mutation-new)\n")

    def test_the_prs_new_mutants_run_as_literals_never_as_its_text_and_at_most_40(self):
        main_list = [('a', '1', 'x')]
        added = ''.join(f' ("n{i}" "s", "a{i}", "b"),\n' for i in range(45))  # its own spelling: concatenated literals
        out, _, nuevos, _ = self.select(main_list, 'MUT = [\n' + f' {main_list[0]!r},\n' + added + ']\n')
        self.assertEqual((out, len(nuevos), nuevos[0]), ('0 45', 40, ('n0s', 'a0', 'b')))
        fallback = self.run_text.split('python scripts/mutar_nuevos.py > evidence/mutation-new.txt', 1)[1]
        self.assertIn('[ "$a" -le 40 ] || echo "not run here: $((a - 40)) more of the PR\'s mutants', fallback)

    def test_a_pr_that_changes_the_runner_gets_all_of_mains_with_mains_runner(self):
        # GPT review of #20: keeping every tuple while weakening the script must not skip main's mutants.
        main_list = [('a', '1', 'x'), ('b', '2', 'y')]
        pr = 'MUT = [\n' + ''.join(f' {t!r},\n' for t in main_list) + ']\n'
        self.assertEqual(self.select(main_list, pr, pr_runner='\ndef main():\n    print("all killed")\n')[:2], ('all', True))

    def test_a_statement_hidden_on_the_list_line_is_a_runner_change(self):
        # GPT review of #20 (d3d8b82): '] ; raise SystemExit(0)' kept every tuple and hid an exit on the list's last line.
        main_list = [('a', '1', 'x'), ('b', '2', 'y')]
        pr = 'MUT = [\n' + ''.join(f' {t!r},\n' for t in main_list) + ']; raise SystemExit(0)\n'
        self.assertEqual(self.select(main_list, pr)[:2], ('all', True))

    def test_an_unreadable_pr_list_runs_all_of_mains(self):
        self.assertEqual(self.select([('a', '1', 'x')], 'MUT = [broken\n'), (None, None, None, None))
        cond = 'if [[ "$n" == all ]] || ! [[ "$m" =~ ^[0-9]+$ && "$a" =~ ^[0-9]+$ ]]; then'
        fallback = self.run_text.split(cond, 1)[1].split('else', 1)[0]
        self.assertIn('cp "$RUNNER_TEMP/mutar_main.py" scripts/mutar_main.py', fallback)
        self.assertIn('python scripts/mutar_main.py > evidence/mutation-main.txt', fallback)
        self.assertIn('echo "skipped: the PR\'s list is main\'s" > evidence/mutation-new.txt', self.run_text)  # always written


class MainsListAtTheBranchPoint(unittest.TestCase):
    """GPT on 2de8c8d (#74): a PR one commit behind main got main's newer mutants as 'dropped', all NOT FOUND."""

    def test_the_list_is_mains_where_the_branch_left_it_not_todays(self):
        jobs = yaml.safe_load((ROOT / '.github' / 'workflows' / 'auditor.yml').read_text(encoding='utf-8'))['jobs']
        step = next(s for s in jobs['evidence']['steps'] if s.get('name') == "Take main's mutant list before any PR code runs")
        with tempfile.TemporaryDirectory() as d:
            g = lambda *a: subprocess.run(['git', '-C', d, *a], check=True, capture_output=True, text=True).stdout.strip()
            g('init', '-q', '-b', 'main'); g('config', 'user.email', 't@t'); g('config', 'user.name', 't')
            (Path(d) / 'scripts').mkdir()
            mut = Path(d) / 'scripts' / 'mutar.py'
            mut.write_text('MUT = [("a", "x", "y")]\n'); g('add', '-A'); g('commit', '-qm', 'base')
            g('checkout', '-qb', 'pr'); (Path(d) / 'f').write_text('pr'); g('add', '-A'); g('commit', '-qm', 'pr')
            g('checkout', '-q', 'main'); mut.write_text('MUT = [("a", "x", "y"), ("b", "later", "z")]\n')
            g('commit', '-qam', 'main adds a mutant'); g('update-ref', 'refs/remotes/origin/main', 'main'); g('checkout', '-q', 'pr')
            out = Path(d) / 'runner'; out.mkdir()
            subprocess.run(['bash', '-c', step['run']], cwd=d, check=True, env={'PATH': '/usr/bin:/bin', 'RUNNER_TEMP': str(out)})
            self.assertEqual((out / 'mutar_main.py').read_text(), 'MUT = [("a", "x", "y")]\n')


if __name__ == '__main__':
    unittest.main()
