"""Cost guards in the workflows: minutes are spent only where they buy certainty (docs/COSTOS.md)."""
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import yaml

WF = Path(__file__).resolve().parents[1] / '.github' / 'workflows'


def load(name):
    return yaml.safe_load((WF / name).read_text(encoding='utf-8'))


def on(doc):
    return doc.get('on', doc.get(True))  # YAML 1.1 reads the key `on` as True


class Mutation(unittest.TestCase):
    def test_mutation_runs_only_on_pull_requests(self):
        self.assertEqual(load('ci.yml')['jobs']['mutation']['if'], "github.event_name == 'pull_request'")


class CatalogChain(unittest.TestCase):
    def setUp(self):
        self.doc = load('catalog-mx.yml')
        self.chain = self.doc['jobs']['chain']

    def test_the_chain_can_only_dispatch_this_workflow_from_main(self):
        self.assertEqual(self.chain['permissions'], {'actions': 'write'})
        self.assertEqual(self.chain['needs'], 'run')
        run = self.chain['steps'][0]['run']
        self.assertIn('gh workflow run catalog-mx.yml -R "$GITHUB_REPOSITORY" --ref main', run)
        self.assertIn('-f chain="$(( CHAIN - 1 ))"', run)  # one less each time: it ends by construction

    def test_the_chain_is_bounded_and_opt_in(self):
        self.assertEqual(self.chain['if'], "needs.run.outputs.more == 'true' && inputs.chain != '' && inputs.chain != '0'"
                                           " && !cancelled() && needs.run.outputs.published == 'true'"
                                           " && contains(fromJSON('[\"0\", \"3\", \"4\"]'), needs.run.outputs.rc)")
        self.assertIn('(( CHAIN >= 1 && CHAIN <= 30 ))', self.chain['steps'][0]['run'])
        self.assertEqual(set(on(self.doc)), {'schedule', 'workflow_dispatch'})  # never code from a pull request

    def test_a_data_finding_does_not_stop_the_catch_up_but_a_broken_run_does(self):
        # 2026-10-27: one unparsed NOM title (exit 3) stopped the DOF catch-up for six days. A finding still fails the
        # run; only a run whose data was scanned for tokens, uploaded and pushed hands on, and never after a crash.
        run = self.doc['jobs']['run']
        self.assertEqual(run['outputs'], {'more': '${{ steps.catalog.outputs.more }}', 'rc': '${{ steps.catalog.outputs.rc }}',
                                          'published': '${{ steps.commit.outputs.published }}'})
        names = [s.get('name') or s.get('uses', '') for s in run['steps']]
        commit = next(s for s in run['steps'] if s.get('id') == 'commit')
        self.assertEqual(commit['run'].strip().splitlines()[-1], 'echo "published=true" >> "$GITHUB_OUTPUT"')  # after the push
        scan, upload = names.index('No token in anything that is committed or uploaded'), names.index(next(n for n in names if n.startswith('Upload raw bundle')))
        self.assertLess(scan, upload)
        self.assertLess(upload, run['steps'].index(commit))
        self.assertLess(run['steps'].index(commit), names.index('Fail on coverage or schema problems'))
        catalog = next(s for s in run['steps'] if s.get('id') == 'catalog')
        self.assertIn('echo "rc=$?" >> "$GITHUB_OUTPUT"', catalog['run'])

    def test_only_main_writes_the_data_branch(self):
        self.assertEqual(self.doc['jobs']['run']['if'], "github.ref == 'refs/heads/main'")


class ChainInputs(unittest.TestCase):
    """The chain step's own script, run against a stub gh: only plain numbers in range dispatch, and an input is never
    evaluated as an expression (GPT review of #19, c671ad3)."""

    def dispatch(self, chain, budget='12000', index_days='1500'):
        step = load('catalog-mx.yml')['jobs']['chain']['steps'][0]['run']
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'gh').write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$GH_ARGS"\n', encoding='utf-8')
            (Path(d) / 'gh').chmod(0o755)
            env = {**os.environ, 'PATH': d + os.pathsep + os.environ['PATH'], 'GH_ARGS': str(Path(d) / 'args'),
                   'GITHUB_REPOSITORY': 'o/r', 'CHAIN': chain, 'BUDGET': budget, 'INDEX_DAYS': index_days}
            r = subprocess.run(['bash', '-c', step], cwd=d, env=env, capture_output=True, text=True, timeout=30)
            args = (Path(d) / 'args').read_text(encoding='utf-8').split('\n') if (Path(d) / 'args').exists() else None
            return r.returncode, args, (Path(d) / 'pwned').exists()

    def test_a_number_in_range_dispatches_one_less(self):
        rc, args, _ = self.dispatch('3')
        self.assertEqual(rc, 0)
        self.assertEqual(args[:9], ['workflow', 'run', 'catalog-mx.yml', '-R', 'o/r', '--ref', 'main', '-f', 'budget=12000'])
        self.assertIn('chain=2', args)

    def test_anything_but_a_plain_number_in_range_dispatches_nothing(self):
        for chain in ('0', '31', '1+1', '2*3', 'a[$(touch pwned)]', ' 3', ''):
            rc, args, pwned = self.dispatch(chain)
            self.assertEqual((rc, args, pwned), (2, None, False), repr(chain))
        for budget, days in (('12x', '1'), ('1', '$(touch pwned)'), ('1-1', '1')):
            rc, args, pwned = self.dispatch('3', budget, days)
            self.assertEqual((rc, args, pwned), (2, None, False), (budget, days))


class ThisRunsManifest(unittest.TestCase):
    """`more` must come from the manifest this run wrote, never from an older one already on the data branch."""

    def more(self, old_text, new_text):
        step = next(s for s in load('catalog-mx.yml')['jobs']['run']['steps'] if s.get('id') == 'catalog')['run']
        lines = [l.strip() for l in step.splitlines()]
        pick = next(l for l in lines if l.startswith('manifest=$(find data/mx/runs'))
        decide = next(l for l in lines if l.startswith('more=$('))
        with tempfile.TemporaryDirectory() as d:
            runs = Path(d) / 'data' / 'mx' / 'runs'
            runs.mkdir(parents=True)
            if old_text is not None:
                (runs / '2026-10-01T000000Z.json').write_text(old_text, encoding='utf-8')
                past = time.time() - 3600
                os.utime(runs / '2026-10-01T000000Z.json', (past, past))
            script = f'marker=$(mktemp)\n'
            if new_text is not None:
                script += f"sleep 0.01; printf '%s' {new_text!r} > data/mx/runs/2026-10-22T000000Z.json\n"
            script += f'{pick}\n{decide}\necho "$more"\n'
            out = subprocess.run(['bash', '-c', script], cwd=d, capture_output=True, text=True, check=True, timeout=30)
            return out.stdout.strip()

    def test_more_reads_only_this_runs_manifest(self):
        old = '{"errors": ["mx.dof: request budget reached (continues next run)"]}'
        self.assertEqual(self.more(old, None), 'false')  # this run wrote nothing: not the old run's answer
        self.assertEqual(self.more(old, '{"errors": []}'), 'false')
        self.assertEqual(self.more(None, '{"errors": ["mx.dof: request budget reached (continues next run)"]}'), 'true')


if __name__ == '__main__':
    unittest.main()
