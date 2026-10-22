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
        self.assertEqual(self.chain['needs'], 'run')  # a failed run (coverage, schema) stops the chain
        run = self.chain['steps'][0]['run']
        self.assertIn('gh workflow run catalog-mx.yml -R "$GITHUB_REPOSITORY" --ref main', run)
        self.assertIn('-f chain="$(( CHAIN - 1 ))"', run)  # one less each time: it ends by construction

    def test_the_chain_is_bounded_and_opt_in(self):
        self.assertEqual(self.chain['if'], "needs.run.outputs.more == 'true' && inputs.chain != '' && inputs.chain != '0'")
        self.assertIn('(( CHAIN >= 1 && CHAIN <= 30 ))', self.chain['steps'][0]['run'])
        self.assertEqual(set(on(self.doc)), {'schedule', 'workflow_dispatch'})  # never code from a pull request

    def test_only_main_writes_the_data_branch(self):
        self.assertEqual(self.doc['jobs']['run']['if'], "github.ref == 'refs/heads/main'")


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
            out = subprocess.run(['bash', '-c', script], cwd=d, capture_output=True, text=True, check=True)
            return out.stdout.strip()

    def test_more_reads_only_this_runs_manifest(self):
        old = '{"errors": ["mx.dof: request budget reached (continues next run)"]}'
        self.assertEqual(self.more(old, None), 'false')  # this run wrote nothing: not the old run's answer
        self.assertEqual(self.more(old, '{"errors": []}'), 'false')
        self.assertEqual(self.more(None, '{"errors": ["mx.dof: request budget reached (continues next run)"]}'), 'true')


if __name__ == '__main__':
    unittest.main()
