"""Every GitHub workflow must be valid YAML with the keys GitHub requires.

2026-10-20: a step name containing ': ' made catalog-mx.yml invalid; GitHub would reject the file and the scheduled
catalog would never run. Neither the tests nor three audits noticed, because nothing parsed the workflows.
"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

WORKFLOWS = sorted((Path(__file__).resolve().parents[1] / '.github' / 'workflows').glob('*.yml'))
AUDITOR = Path(__file__).resolve().parents[1] / '.github' / 'workflows' / 'auditor.yml'


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

    def test_every_action_is_pinned_by_full_commit_sha(self):
        for wf in WORKFLOWS:
            for name, job in yaml.safe_load(wf.read_text(encoding='utf-8'))['jobs'].items():
                for step in job.get('steps', []):
                    if 'uses' in step:
                        self.assertRegex(step['uses'], r'^[\w.-]+/[\w./-]+@[0-9a-f]{40}$', f'{wf.name}:{name}')

    def test_no_expression_is_interpolated_into_a_script(self):  # REGLAS 12: inputs go through env
        for wf in WORKFLOWS:
            for name, job in yaml.safe_load(wf.read_text(encoding='utf-8'))['jobs'].items():
                for step in job.get('steps', []):
                    self.assertNotIn('${{', step.get('run', ''), f'{wf.name}:{name}')


class AuditorGpt(unittest.TestCase):
    """The second auditor never has PR code next to its key, and never speaks with the Claude auditor's voice."""

    def setUp(self):
        self.raw = AUDITOR.read_text(encoding='utf-8')
        self.doc = yaml.safe_load(self.raw)
        self.jobs = self.doc['jobs']

    def test_it_runs_beside_the_claude_audit_under_the_same_gate(self):
        self.assertEqual(self.jobs['audit-gpt']['needs'], self.jobs['audit']['needs'] + ['packet-gate'])
        self.assertEqual(self.jobs['audit-gpt']['needs'], ['gate', 'evidence', 'packet-gate'])
        self.assertEqual(self.jobs['post-gpt']['needs'], ['gate', 'audit-gpt'])
        self.assertNotIn('if', self.jobs['audit-gpt'])  # skipped exactly when evidence is, as the audit job

    def test_it_checks_out_main_and_never_the_pr_head(self):
        job = self.jobs['audit-gpt']
        uses = [s['uses'].split('@')[0] for s in job['steps'] if 'uses' in s]
        self.assertEqual(uses, ['actions/checkout', 'actions/download-artifact', 'actions/download-artifact'])
        downloads = [s['with'] for s in job['steps'] if s.get('uses', '').startswith('actions/download-artifact@')]
        self.assertEqual([(d['name'], d['path']) for d in downloads],
                         [('evidence', '${{ runner.temp }}/gpt-audit/evidence'),
                          ('packet-gate', '${{ runner.temp }}/gpt-audit/trusted')])
        checkout = next(s for s in job['steps'] if s.get('uses', '').startswith('actions/checkout@'))
        self.assertEqual(checkout['with']['ref'], 'main')
        self.assertIs(checkout['with']['persist-credentials'], False)
        for step in job['steps']:
            run = step.get('run', '')
            self.assertNotRegex(run, r'\bgit\b[^\n;|&]*\b(checkout|switch|worktree|restore|reset|read-tree|'
                                     r'checkout-index|stash|merge|rebase|cherry-pick|pull|apply|am|archive)\b')
            self.assertNotRegex(run, r'\b(pip|unittest|pytest|make|npm|npx|bash|sh|source)\b')
            for line in run.splitlines():  # the only program run is main's script, isolated from env and cwd
                if 'python' in line:
                    self.assertRegex(line.strip(), r'^python3 -I scripts/auditor_gpt\.py ')

    def test_the_key_reaches_only_the_step_that_calls_the_api(self):
        self.assertEqual(self.raw.count('secrets.OPENAI_API_KEY'), 1)
        self.assertNotIn('env', self.doc)
        job = self.jobs['audit-gpt']
        self.assertNotIn('env', job)
        self.assertEqual(job['permissions'], {'contents': 'read'})
        holders = [s for s in job['steps'] if 'secrets.' in yaml.safe_dump(s)]
        self.assertEqual(len(holders), 1)
        step = holders[0]
        self.assertEqual(step['env']['OPENAI_API_KEY'], '${{ secrets.OPENAI_API_KEY }}')
        self.assertEqual([v for v in step['env'].values() if 'secrets.' in v], ['${{ secrets.OPENAI_API_KEY }}'])
        self.assertIn('python3 -I scripts/auditor_gpt.py', step['run'])
        self.assertEqual(step['env']['OPENAI_AUDIT_MODEL'], '${{ vars.OPENAI_AUDIT_MODEL }}')  # no model in code
        self.assertNotIn('secrets.', yaml.safe_dump(self.jobs['evidence']))  # where PR code runs, no secret at all

    def test_the_packet_gate_runs_mains_code_on_the_heads_packets_as_data(self):
        job = self.jobs['packet-gate']
        self.assertEqual((job['needs'], job['if'], job['permissions']),
                         ('gate', "needs.gate.outputs.run == 'true'", {'contents': 'read'}))
        self.assertNotIn('secrets.', yaml.safe_dump(job))  # hostile raws are parsed here
        checkout = next(s for s in job['steps'] if s.get('uses', '').startswith('actions/checkout@'))
        self.assertEqual((checkout['with']['ref'], checkout['with']['persist-credentials']), ('main', False))
        run = '\n'.join(s.get('run', '') for s in job['steps'])
        self.assertNotRegex(run, r'\bgit\b[^\n;|&]*\b(checkout|switch|worktree|restore|reset|read-tree|checkout-index|'
                                 r'stash|merge|rebase|cherry-pick|pull|apply|am)\b')
        self.assertIn('[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "bad head"; exit 1; }', run)
        self.assertIn('python scripts/packet_gate.py --base origin/main --sha "$SHA" --data "$d/data" --out "$d/packets.json"', run)
        with_token = [s for s in job['steps'] if 'github.token' in yaml.safe_dump(s)]
        self.assertEqual(len(with_token), 1)
        self.assertNotIn('python', with_token[0]['run'])  # the token fetches; it is never where raws are parsed
        gate_step = next(s for s in job['steps'] if 'packet_gate.py' in s.get('run', ''))
        self.assertEqual(gate_step['env'], {'SHA': '${{ needs.gate.outputs.sha }}'})
        upload = next(s['with'] for s in job['steps'] if s.get('uses', '').startswith('actions/upload-artifact@'))
        self.assertEqual(upload['name'], 'packet-gate')

    def test_post_gpt_speaks_only_as_gpt(self):
        job = self.jobs['post-gpt']
        self.assertEqual(job['permissions'], {'pull-requests': 'write', 'statuses': 'write'})
        self.assertNotIn('secrets.', yaml.safe_dump(job))
        self.assertFalse(any('uses' in s for s in job['steps']))
        run = '\n'.join(s.get('run', '') for s in job['steps'])
        self.assertIn('[ "$(head -n 1 verdict.md)" = "GPT REVIEW: $verdict $SHA" ]', run)
        self.assertIn('[ "$(grep -ci \'AUDIT VERDICT\' verdict.md)" = 0 ]', run)
        self.assertIn('-f state=pending -f context=auditor-gpt', run)
        self.assertIn('-f context=auditor-gpt -f description="GPT REVIEW: $verdict"', run)
        self.assertNotRegex(run, r'context=auditor(\s|$)')

    def test_the_evidence_has_time_for_all_of_mains_mutants(self):
        # #43 (run 40441783078): a PR that changes the mutation runner runs all of main's mutants with main's runner on
        # one runner; cancelled at 90 min, it left the PR with no audit at all.
        self.assertGreaterEqual(self.jobs['evidence']['timeout-minutes'], 300)

    def test_the_claude_auditor_keeps_its_format_and_status(self):
        run = self.jobs['post']['steps'][0]['run']
        self.assertIn('echo "AUDIT VERDICT: $verdict $SHA"; echo', run)
        self.assertIn('-f context=auditor -f description="AUDIT VERDICT: $verdict"', run)
        gate = self.jobs['gate']['steps'][0]['run']
        self.assertIn('. == "AUDIT VERDICT: PASS \\($s)" or . == "AUDIT VERDICT: REVISE \\($s)"', gate)
        self.assertIn('startswith("AUDIT VERDICT: REVISE")', gate)


GH_STUB = """#!/bin/sh
case "$*" in
  *baseRefName*) echo main ;;
  *isCrossRepository*) printf '%s' "$STUB_CROSS" ;;
  *headRefOid*) echo 0123456789abcdef0123456789abcdef01234567 ;;
  *comments*) echo '{"comments": []}' ;;
  *) exit 9 ;;
esac
"""


@unittest.skipUnless(shutil.which('bash') and shutil.which('jq'), 'the gate needs bash and jq, as on the CI runner')
class AuditorGate(unittest.TestCase):
    """The repo is public since 2026-10-22: a fork's PR must never reach the jobs that hold the Claude and OpenAI
    secrets. The gate's own script runs here against a stub gh."""

    def gate(self, cross):
        script = yaml.safe_load(AUDITOR.read_text(encoding='utf-8'))['jobs']['gate']['steps'][0]['run']
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'gh').write_text(GH_STUB, encoding='utf-8')
            (Path(d) / 'gh').chmod(0o755)
            out = Path(d) / 'out'
            out.write_text('', encoding='utf-8')
            env = {**os.environ, 'PATH': d + os.pathsep + os.environ['PATH'], 'GITHUB_OUTPUT': str(out),
                   'STUB_CROSS': cross, 'EVENT': 'pull_request_target', 'PR_EVENT': '7', 'REPO': 'o/r', 'OWNER': 'o'}
            r = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            return dict(l.split('=', 1) for l in out.read_text(encoding='utf-8').split())

    def test_a_branch_of_this_repo_is_audited(self):
        self.assertEqual(self.gate('false'), {'run': 'true', 'pr': '7', 'sha': '0123456789abcdef0123456789abcdef01234567'})

    def test_a_fork_is_never_audited(self):
        self.assertEqual(self.gate('true'), {'run': 'false'})

    def test_an_unreadable_answer_counts_as_a_fork(self):
        for answer in ('', 'null', 'False'):
            self.assertEqual(self.gate(answer), {'run': 'false'}, answer)
