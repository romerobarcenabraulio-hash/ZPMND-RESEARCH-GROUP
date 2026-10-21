"""Every GitHub workflow must be valid YAML with the keys GitHub requires.

2026-10-20: a step name containing ': ' made catalog-mx.yml invalid; GitHub would reject the file and the scheduled
catalog would never run. Neither the tests nor three audits noticed, because nothing parsed the workflows.
"""
import unittest
from pathlib import Path

import yaml

WORKFLOWS = sorted((Path(__file__).resolve().parents[1] / '.github' / 'workflows').glob('*.yml'))


class Workflows(unittest.TestCase):
    def test_every_workflow_parses_and_has_jobs(self):
        self.assertTrue(WORKFLOWS)
        for wf in WORKFLOWS:
            with self.subTest(workflow=wf.name):
                doc = yaml.safe_load(wf.read_text(encoding='utf-8'))
                self.assertIsInstance(doc, dict)
                self.assertTrue(doc.get('jobs'))
                self.assertTrue(doc.get('on') or doc.get(True))  # YAML 1.1 reads the bare key `on` as True
                for name, job in doc['jobs'].items():
                    self.assertTrue(job.get('runs-on'), f'{wf.name}:{name}')
                    for step in job.get('steps', []):
                        self.assertTrue('run' in step or 'uses' in step, f'{wf.name}:{name}: {step}')
