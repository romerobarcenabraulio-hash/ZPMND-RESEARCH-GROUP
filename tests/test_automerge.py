"""Data-only PRs merge by themselves (scripts/automerge.py, automerge.yml); everything else stays with the owner.

Built here (CONSTRUIDO): GitHub API answers as literals, shaped like the REST API's (pulls, files, statuses newest
first, check runs), and a fake caller that records what would be sent. No network.
"""
import copy
import importlib.util
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('automerge', ROOT / 'scripts' / 'automerge.py')
am = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(am)
REPO = 'romerobarcenabraulio-hash/ZPMND-RESEARCH-GROUP'
SHA = 'a' * 40
BOT = {'login': 'github-actions[bot]'}
FILES = [{'filename': 'research-packets/RP-2026-10-27-x/packet.json', 'status': 'added'},
         {'filename': 'research-packets/RP-2026-10-27-x/raw/sha256/ab/' + 'ab' * 32 + '.html', 'status': 'added'},
         {'filename': 'requests/plans/RR-2026-10-27-x.json', 'status': 'modified'}]
STATUSES = [{'context': 'auditor-gpt', 'state': 'success', 'description': 'GPT REVIEW: PASS', 'creator': BOT},
            {'context': 'auditor', 'state': 'success', 'description': 'AUDIT VERDICT: PASS', 'creator': BOT}]
RUNS = [{'name': n, 'status': 'completed', 'conclusion': c} for n, c in (
    ('checks', 'success'), ('mutation (0)', 'skipped'), ('gate', 'success'), ('packet-gate', 'success'),
    ('evidence', 'success'), ('audit', 'success'), ('audit-gpt', 'success'), ('post', 'success'), ('post-gpt', 'neutral'))]
PR = {'number': 7, 'state': 'open', 'draft': False, 'title': 'Paquete RP-2026-10-27-x', 'changed_files': 3,
      'base': {'ref': 'main'}, 'head': {'sha': SHA, 'ref': 'investigar/RP-2026-10-27-x', 'repo': {'full_name': REPO}}}


def decide(pr=PR, files=FILES, statuses=STATUSES, runs=RUNS):
    return am.decide(pr, files, statuses, runs, REPO, SHA)


def change(pr=None, **head):
    p = copy.deepcopy(PR)
    p.update(pr or {})
    p['head'].update(head)
    return p


class Decide(unittest.TestCase):
    def test_a_data_pr_from_this_repo_passed_twice_and_green_merges(self):
        self.assertIsNone(decide())

    def test_only_an_open_ready_pr_into_main_with_this_head_from_this_repo(self):
        for name, pr in (('closed', change({'state': 'closed'})), ('draft', change({'draft': True})),
                         ('base', change({'base': {'ref': 'catalog'}})), ('moved', change(sha='b' * 40)),
                         ('fork', change(repo={'full_name': 'someone/ZPMND-RESEARCH-GROUP'})), ('no repo', change(repo=None)),
                         ('count', change({'changed_files': 4}))):
            with self.subTest(name):
                self.assertIsNotNone(decide(pr))

    def test_code_workflows_docs_tests_and_mutants_never_merge_by_themselves(self):
        for name in ('rg/investigar.py', '.github/workflows/automerge.yml', 'scripts/mutar.py', 'tests/test_x.py',
                     'docs/REGLAS.md', 'README.md', 'requests/RR-2026-10-27-x.json', 'requests/plans/RR-x/plan.json',
                     'requests/plans/RR-2026-10-27-x.py', 'requests/plans/RR-2026-10-27-x.jsonx', 'research-packets/README.md', 'research-packets/x/packet.json',
                     'research-packets/RP-2026-10-27-x/../../scripts/a.py', 'research-packets/RP-2026-10-27-x/./a',
                     'knowledge-demand/KNOWLEDGE_DEMAND_MAP.json'):
            with self.subTest(name):
                files = FILES + [{'filename': name, 'status': 'modified'}]
                self.assertIn('not data', decide(change({'changed_files': 4}), files))

    def test_a_removal_or_a_rename_stays_with_the_owner_even_inside_data(self):
        for status in ('removed', 'renamed', 'copied', 'changed', None):
            with self.subTest(status):
                files = [dict(FILES[0], status=status)] + FILES[1:]
                self.assertIsNotNone(decide(files=files))

    def test_an_empty_or_possibly_cut_file_list_stays_with_the_owner(self):
        self.assertIsNotNone(decide(change({'changed_files': 0}), []))
        many = [dict(FILES[0], filename=f'research-packets/RP-2026-10-27-x/f{i}') for i in range(am.MAX_FILES)]
        self.assertIsNotNone(decide(change({'changed_files': am.MAX_FILES}), many))
        self.assertIsNone(decide(change({'changed_files': am.MAX_FILES - 1}), many[1:]))

    def test_both_auditors_must_have_passed_this_commit_through_the_bot(self):
        claude, gpt = STATUSES[1], STATUSES[0]
        for name, statuses in (
                ('none', []), ('only claude', [claude]), ('only gpt', [gpt]),
                ('claude revise', [gpt, dict(claude, state='failure', description='AUDIT VERDICT: REVISE')]),
                ('gpt skipped', [dict(gpt, state='pending', description='skipped: OPENAI_AUDIT_MODEL not set'), claude]),
                ('success without PASS', [gpt, dict(claude, description='AUDIT VERDICT: REVISE')]),
                ('PASS line, failed state', [gpt, dict(claude, state='failure')]),
                ('PASS by someone else', [gpt, dict(claude, creator={'login': 'romerobarcenabraulio-hash'})]),
                ('no creator', [gpt, {k: v for k, v in claude.items() if k != 'creator'}]),
                ('a newer REVISE wins', [dict(gpt, state='failure', description='GPT REVIEW: REVISE'), gpt, claude])):
            with self.subTest(name):
                self.assertIsNotNone(decide(statuses=statuses))
        older_revise = [gpt, claude, dict(claude, state='failure', description='AUDIT VERDICT: REVISE')]
        self.assertIsNone(decide(statuses=older_revise))  # a later round passed: the newest status counts

    def test_every_check_must_have_finished_green_and_ci_and_the_auditor_must_have_run(self):
        for name in sorted(am.REQUIRED):
            with self.subTest(missing=name):
                self.assertIn(name, decide(runs=[r for r in RUNS if r['name'] != name]))
        for name, run in (('running', {'status': 'in_progress', 'conclusion': None}), ('failed', {'conclusion': 'failure'}),
                          ('cancelled', {'conclusion': 'cancelled'}), ('timed out', {'conclusion': 'timed_out'}),
                          ('action required', {'conclusion': 'action_required'})):
            with self.subTest(name):
                self.assertIsNotNone(decide(runs=RUNS + [dict(RUNS[1], name='mutation (1)', **run)]))


class Main(unittest.TestCase):
    def caller(self, pr=PR, pulls=None, fail_delete=False):
        sent = []
        listing = [{'number': pr['number'], 'state': pr['state']}] if pulls is None else pulls

        def call(method, path, body=None):
            sent.append((method, path, body))
            if method == 'GET' and path.endswith(f'/commits/{SHA}/pulls'):
                return listing
            if method == 'GET' and '/files?' in path:
                return FILES
            if method == 'GET' and '/statuses?' in path:
                return STATUSES
            if method == 'GET' and '/check-runs?' in path:
                return {'check_runs': RUNS}
            if method == 'GET' and path.endswith(f"/pulls/{pr['number']}"):
                return pr
            if method == 'DELETE' and fail_delete:
                raise OSError('422')
            return None
        return call, sent

    def run_main(self, call):
        return am.main({'REPO': REPO, 'SHA': SHA, 'GH_TOKEN': 'x'}, call)

    def test_it_merges_squashed_pinned_to_the_commit_and_deletes_the_branch(self):
        call, sent = self.caller()
        self.assertEqual(self.run_main(call), 0)
        writes = [s for s in sent if s[0] != 'GET']
        self.assertEqual(writes, [
            ('PUT', f'/repos/{REPO}/pulls/7/merge', {'sha': SHA, 'merge_method': 'squash', 'commit_title': 'Paquete RP-2026-10-27-x (#7)'}),
            ('DELETE', f'/repos/{REPO}/git/refs/heads/investigar/RP-2026-10-27-x', None)])
        self.assertIn(('GET', f'/repos/{REPO}/commits/{SHA}/check-runs?filter=latest&per_page=100&page=1', None), sent)

    def test_nothing_is_written_for_a_pr_that_does_not_qualify_or_is_not_open(self):
        for name, (pr, pulls) in (('code', (change({'changed_files': 3}, repo={'full_name': 'x/y'}), None)),
                                  ('closed in the listing', (PR, [{'number': 7, 'state': 'closed'}])),
                                  ('no number', (PR, [{'state': 'open'}])), ('no PR', (PR, []))):
            with self.subTest(name):
                call, sent = self.caller(pr, pulls)
                self.assertEqual(self.run_main(call), 0)
                self.assertEqual([s for s in sent if s[0] != 'GET'], [])

    def test_a_branch_that_cannot_be_deleted_does_not_undo_the_merge(self):
        call, sent = self.caller(fail_delete=True)
        self.assertEqual(self.run_main(call), 0)
        self.assertEqual([s[0] for s in sent if s[0] != 'GET'], ['PUT', 'DELETE'])

    def test_inputs_are_checked_before_any_call(self):
        for env in ({'REPO': REPO, 'SHA': 'main'}, {'REPO': 'x/y/../z', 'SHA': SHA}, {}):
            with self.subTest(env=env):
                call, sent = self.caller()
                self.assertEqual(am.main(env, call), 2)
                self.assertEqual(sent, [])

    def test_a_listing_longer_than_its_page_limit_raises_instead_of_being_cut(self):
        full = [{}] * 100
        self.assertEqual(len(am.pages(lambda m, p, b=None: full if p.endswith('&page=1') else [], '/x')), 100)
        with self.assertRaises(ValueError):
            am.pages(lambda m, p, b=None: full, '/x', limit=3)


class Workflow(unittest.TestCase):
    def setUp(self):
        self.wf = yaml.safe_load((ROOT / '.github' / 'workflows' / 'automerge.yml').read_text(encoding='utf-8'))

    def test_it_runs_from_main_when_ci_or_the_auditor_finishes_with_only_what_merging_needs(self):
        self.assertEqual(self.wf.get('on') or self.wf.get(True), {'workflow_run': {'workflows': ['ci', 'auditor'], 'types': ['completed']}})
        self.assertEqual(self.wf['permissions'], {})
        self.assertEqual(list(self.wf['jobs']), ['merge'])
        job = self.wf['jobs']['merge']
        self.assertEqual(job['permissions'], {'contents': 'write', 'pull-requests': 'write', 'checks': 'read', 'statuses': 'read'})
        checkout, step = job['steps']
        self.assertEqual(checkout['with'], {'persist-credentials': False})  # main's code: no ref of the PR, no token kept
        self.assertEqual(step['run'], 'python3 scripts/automerge.py')
        self.assertEqual(step['env'], {'GH_TOKEN': '${{ github.token }}', 'REPO': '${{ github.repository }}',
                                       'SHA': '${{ github.event.workflow_run.head_sha }}'})

    def test_the_merge_policy_is_written_where_the_rules_are(self):
        self.assertIn('| T15 |', (ROOT / 'SECURITY.md').read_text(encoding='utf-8'))
        self.assertIn('scripts/automerge.py', (ROOT / 'docs' / 'REGLAS.md').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
