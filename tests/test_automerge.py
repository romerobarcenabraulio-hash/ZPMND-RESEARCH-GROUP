"""Data-only PRs merge by themselves (scripts/automerge.py, automerge.yml); everything else stays with the owner.

Built here (CONSTRUIDO): GitHub API answers as literals, shaped like the REST API's (pulls, files, workflow runs and
their jobs), and a fake caller that records what would be sent. No network.
"""
import copy
import importlib.util
import unittest
import urllib.error
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('automerge', ROOT / 'scripts' / 'automerge.py')
am = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(am)

REPO = 'romerobarcenabraulio-hash/ZPMND-RESEARCH-GROUP'
SHA = 'a' * 40
AUDITOR, CI = '.github/workflows/auditor.yml', '.github/workflows/ci.yml'
FILES = [{'filename': 'research-packets/RP-2026-10-27-x/packet.json', 'status': 'added'},
         {'filename': 'research-packets/RP-2026-10-27-x/raw/sha256/ab/' + 'ab' * 32 + '.html', 'status': 'added'},
         {'filename': 'requests/plans/RR-2026-10-27-x.json', 'status': 'modified'}]
RUNS = [{'id': 20, 'path': AUDITOR, 'event': 'pull_request_target', 'head_sha': SHA, 'status': 'completed',
         'conclusion': 'success', 'pull_requests': [{'number': 7}]},
        {'id': 21, 'path': CI, 'event': 'pull_request', 'head_sha': SHA, 'status': 'completed', 'conclusion': 'success',
         'pull_requests': [{'number': 7}]}]
JOBS = {20: [{'name': n, 'conclusion': 'success'} for n in ('gate', 'evidence', 'packet-gate', 'audit', 'audit-gpt', 'post',
                                                            'post-gpt', 'pass-both')],
        21: [{'name': n, 'conclusion': 'success'} for n in ('checks', 'mutation (0)', 'mutation (1)')]}
PR = {'number': 7, 'state': 'open', 'draft': False, 'title': 'Paquete RP-2026-10-27-x', 'changed_files': 3,
      'base': {'ref': 'main'}, 'head': {'sha': SHA, 'ref': 'investigar/RP-2026-10-27-x', 'repo': {'full_name': REPO}}}


def decide(pr=PR, files=FILES, runs=RUNS, jobs=JOBS, on_main=()):
    return am.decide(pr, files, runs, lambda rid: jobs.get(rid, []), REPO, SHA, exists=lambda rp: rp in on_main)


def change(pr=None, **head):
    p = copy.deepcopy(PR)
    p.update(pr or {})
    p['head'].update(head)
    return p


def run(i, **over):
    return dict(copy.deepcopy(RUNS[i]), **over)


def jobs(rid, name, conclusion='success', drop=False):
    j = copy.deepcopy(JOBS)
    j[rid] = [x for x in j[rid] if x['name'] != name] + ([] if drop else [{'name': name, 'conclusion': conclusion}])
    return j


class Decide(unittest.TestCase):
    def test_a_packet_merges_by_itself_only_alone_and_from_its_own_branch(self):
        two = FILES + [{'filename': 'research-packets/RP-2026-10-27-y/packet.json', 'status': 'added'}]
        self.assertIn('only alone, from investigar/<its RP>', decide(change({'changed_files': 4}), two))
        for ref in ('investigar/RP-2026-10-27-y', 'otra', ''):
            with self.subTest(ref=ref):
                self.assertIn('only alone, from investigar/<its RP>', decide(change(ref=ref)))
        plan = [{'filename': 'requests/plans/RR-2026-10-27-x.json', 'status': 'modified'}]
        self.assertIsNone(decide(change({'changed_files': 1}, ref='plan-x'), plan))  # a plan alone: any branch of this repo

    def test_a_file_added_to_a_packet_already_on_main_stays_with_the_owner(self):
        for files in (FILES, [{'filename': 'research-packets/RP-2026-10-27-x/receipt.json', 'status': 'added'}]):
            with self.subTest(files=files):
                self.assertEqual(decide(change({'changed_files': len(files)}), files, on_main={'RP-2026-10-27-x'}),
                                 'research-packets/RP-2026-10-27-x/ is already on main (a packet on main never changes)')
        self.assertIsNone(decide(on_main={'RP-2026-10-27-otro'}))  # another packet on main changes nothing

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
                     'requests/plans/RR-2026-10-27-x.py', 'requests/plans/RR-2026-10-27-x.jsonx', 'research-packets/README.md',
                     'research-packets/x/packet.json', 'research-packets/RP-2026-10-27-x/../../scripts/a.py',
                     'research-packets/RP-2026-10-27-x/./a', 'knowledge-demand/KNOWLEDGE_DEMAND_MAP.json'):
            with self.subTest(name):
                files = FILES + [{'filename': name, 'status': 'modified'}]
                self.assertIn('not data', decide(change({'changed_files': 4}), files))

    def test_a_packet_file_main_already_holds_never_changes_by_itself(self):
        # a packet on main never changes (docs/OUTBOX.md): a modified packet file stays with the owner; a plan may change
        for i in (0, 1):
            with self.subTest(FILES[i]['filename']):
                files = [dict(f, status='modified') if k == i else f for k, f in enumerate(FILES)]
                self.assertEqual(decide(files=files), f"{FILES[i]['filename']}: modified (a packet on main never changes; "
                                                      'only a new one merges by itself)')
        self.assertEqual(FILES[2]['status'], 'modified')
        self.assertIsNone(decide())

    def test_a_removal_or_a_rename_stays_with_the_owner_even_inside_data(self):
        for status in ('removed', 'renamed', 'copied', 'changed', None):
            with self.subTest(status):
                for i in (0, 2):  # a packet file and a plan alike
                    files = [dict(f, status=status) if k == i else f for k, f in enumerate(FILES)]
                    self.assertIsNotNone(decide(files=files))

    def test_an_empty_or_possibly_cut_file_list_stays_with_the_owner(self):
        self.assertIsNotNone(decide(change({'changed_files': 0}), []))
        many = [dict(FILES[0], filename=f'research-packets/RP-2026-10-27-x/f{i}') for i in range(am.MAX_FILES)]
        self.assertIsNotNone(decide(change({'changed_files': am.MAX_FILES}), many))
        self.assertIsNone(decide(change({'changed_files': am.MAX_FILES - 1}), many[1:]))

    def test_only_the_trusted_runs_count_never_one_another_workflow_could_imitate(self):
        # GPT, REVISE of #48: a branch's own workflow can post statuses, comments and check runs with this repo's token,
        # but it cannot make a run of main's auditor.yml for pull_request_target, nor of ci.yml for this PR's event.
        for name, runs in (
                ('no auditor run', [RUNS[1]]), ('no ci run', [RUNS[0]]),
                ('auditor run by another event', [run(0, event='pull_request'), RUNS[1]]),
                ('auditor run by push', [run(0, event='push'), RUNS[1]]),
                ('a look-alike workflow file', [run(0, path='.github/workflows/auditor2.yml'), RUNS[1]]),
                ('ci by workflow_dispatch', [RUNS[0], run(1, event='workflow_dispatch')]),
                ('another commit', [run(0, head_sha='b' * 40), RUNS[1]]),
                ('another PR', [run(0, pull_requests=[{'number': 8}]), RUNS[1]]),
                ('no PR', [run(0, pull_requests=[]), RUNS[1]]),
                ('auditor still running', [run(0, status='in_progress', conclusion=None), RUNS[1]]),
                ('ci failed', [RUNS[0], run(1, conclusion='failure')]),
                ('ci cancelled', [RUNS[0], run(1, conclusion='cancelled')])):
            with self.subTest(name):
                self.assertIsNotNone(decide(runs=runs))

    def test_the_newest_trusted_run_counts(self):
        self.assertIsNotNone(decide(runs=RUNS + [run(0, id=30, conclusion='failure')]))
        self.assertIsNone(decide(runs=[run(0, id=10, conclusion='failure')] + RUNS))

    def test_every_job_must_have_succeeded_none_skipped_and_the_required_ones_must_be_there(self):
        for rid, name in ((20, 'pass-both'), (20, 'audit-gpt'), (20, 'packet-gate'), (20, 'evidence'), (21, 'checks')):
            for conclusion in ('skipped', 'neutral', 'failure', None):
                with self.subTest(job=name, conclusion=conclusion):
                    self.assertIsNotNone(decide(jobs=jobs(rid, name, conclusion)))
        for path, (_, required) in am.TRUSTED.items():
            rid = 20 if path == AUDITOR else 21
            for name in sorted(required):
                with self.subTest(missing=name):
                    self.assertIn(name, decide(jobs=jobs(rid, name, drop=True)))
        self.assertIsNotNone(decide(jobs=jobs(21, 'mutation (2)', 'skipped')))  # an extra job counts too

    def test_a_skipped_second_opinion_or_a_revise_leaves_pass_both_skipped_so_nothing_merges(self):
        wf = yaml.safe_load((ROOT / '.github' / 'workflows' / 'auditor.yml').read_text(encoding='utf-8'))
        both = wf['jobs']['pass-both']
        self.assertEqual(both['needs'], ['gate', 'post', 'post-gpt'])
        self.assertEqual(both['if'], "needs.post.outputs.verdict == 'PASS' && needs.post-gpt.outputs.verdict == 'PASS'")
        self.assertEqual(both['permissions'], {})
        for job, context in (('post', 'auditor'), ('post-gpt', 'auditor-gpt')):
            with self.subTest(job):
                j = wf['jobs'][job]
                self.assertEqual(j['outputs'], {'verdict': '${{ steps.post.outputs.verdict }}'})
                step = j['steps'][0]
                self.assertEqual(step['id'], 'post')
                lines = step['run'].rstrip('\n').split('\n')
                # the verdict goes out last, after it was posted and its status set; the skipped path exits before it
                self.assertTrue(lines[-1].startswith('echo "verdict=$verdict" >> "$GITHUB_OUTPUT"'), lines[-1])
                self.assertIn(f'-f context={context} -f description=', lines[-2])
        skipped = wf['jobs']['post-gpt']['steps'][0]['run']
        self.assertLess(skipped.index('exit 0'), skipped.index('echo "verdict=$verdict"'))


class Main(unittest.TestCase):
    def caller(self, pr=PR, pulls=None, on_main=(), contents_error=404):
        sent = []
        listing = [{'number': pr['number'], 'state': pr['state']}] if pulls is None else pulls

        def call(method, path, body=None):
            sent.append((method, path, body))
            if method == 'GET' and path.endswith(f'/commits/{SHA}/pulls'):
                return listing
            if method == 'GET' and '/files?' in path:
                return FILES
            if method == 'GET' and f'/actions/runs?head_sha={SHA}&' in path:
                return {'workflow_runs': RUNS}
            for rid in JOBS:
                if method == 'GET' and f'/actions/runs/{rid}/jobs?filter=latest&' in path:
                    return {'jobs': JOBS[rid]}
            if method == 'GET' and path.endswith(f"/pulls/{pr['number']}"):
                return pr
            if method == 'GET' and '/contents/research-packets/' in path:
                rp = path.split('/contents/research-packets/')[1].split('?')[0]
                assert path.endswith('?ref=main'), path
                if rp in on_main:
                    return [{'name': 'packet.json'}]
                raise urllib.error.HTTPError(path, contents_error, 'x', None, None)
            return None
        return call, sent

    def run_main(self, call):
        return am.main({'REPO': REPO, 'SHA': SHA, 'GH_TOKEN': 'x'}, call)

    def test_it_merges_squashed_pinned_to_the_commit_and_leaves_the_branch(self):
        call, sent = self.caller()
        self.assertEqual(self.run_main(call), 0)
        # no DELETE: a branch deleted after the merge could take a newer push with it (GPT, #48)
        self.assertEqual([s for s in sent if s[0] != 'GET'], [
            ('PUT', f'/repos/{REPO}/pulls/7/merge', {'sha': SHA, 'merge_method': 'squash', 'commit_title': 'Paquete RP-2026-10-27-x (#7)'})])

    def test_nothing_is_written_for_a_pr_that_does_not_qualify_or_is_not_open(self):
        for name, (pr, pulls) in (('fork', (change(repo={'full_name': 'x/y'}), None)),
                                  ('closed in the listing', (PR, [{'number': 7, 'state': 'closed'}])),
                                  ('no number', (PR, [{'state': 'open'}])), ('no PR', (PR, []))):
            with self.subTest(name):
                call, sent = self.caller(pr, pulls)
                self.assertEqual(self.run_main(call), 0)
                self.assertEqual([s for s in sent if s[0] != 'GET'], [])

    def test_a_packet_folder_main_has_or_cannot_be_checked_is_not_merged(self):
        call, sent = self.caller(on_main={'RP-2026-10-27-x'})
        self.assertEqual(self.run_main(call), 0)
        self.assertEqual([s for s in sent if s[0] != 'GET'], [])
        call, sent = self.caller(contents_error=500)
        with self.assertRaises(urllib.error.HTTPError):
            self.run_main(call)
        self.assertEqual([s for s in sent if s[0] != 'GET'], [])

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
        self.assertEqual(job['permissions'], {'contents': 'write', 'pull-requests': 'write', 'actions': 'read'})
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
