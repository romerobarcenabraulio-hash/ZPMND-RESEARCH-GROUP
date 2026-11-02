"""scripts/auditor_tercero.py and its two jobs in auditor.yml: a third opinion through NVIDIA's hosted API, asked only
when the two verdicts on a head differ, that no reader of verdicts can take for one and that gates nothing."""
import importlib.util
import io
import json
import re
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('auditor_tercero', ROOT / 'scripts' / 'auditor_tercero.py')
t = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(t)
SHA = 'a' * 40
QUOTE = 'Primera línea del README'


def resp(answer=None, finish='stop', content=None):
    content = json.dumps(answer) if content is None else content
    return {'choices': [{'finish_reason': finish, 'message': {'content': content}}]}


def answer(**kw):
    return {'verdict': 'PASS', 'head_sha': SHA, 'criteria_quote': QUOTE, 'body': 'Sin hallazgos.', **kw}


class Respuesta(unittest.TestCase):
    def test_only_one_choice_that_stopped_by_itself_is_an_answer(self):
        self.assertEqual(t.parse_response(resp(answer())), (answer(), None))
        self.assertEqual(t.parse_response(resp(content='```json\n' + json.dumps(answer()) + '\n```'))[0], answer())
        for bad in (resp(answer(), finish='length'), {'choices': []}, {'choices': [resp(answer())['choices'][0]] * 2},
                    resp(content='no es json'), {'choices': [{'finish_reason': 'stop', 'message': {}}]}, 'x'):
            with self.subTest(bad=str(bad)[:60]):
                a, problem = t.parse_response(bad)
                self.assertIsNone(a)
                self.assertTrue(problem)


class Opinion(unittest.TestCase):
    def run_(self, ret=None, side=None, model='org/modelo-1', key='k'):
        with mock.patch.object(t.g, 'build_input', return_value=('texto', True, QUOTE)), \
                mock.patch.object(t, 'call_model', return_value=ret, side_effect=side) as call:
            r = t.audit(Path('.'), '7', SHA, model, key)
        return r, call

    def test_nothing_is_asked_without_a_model_name_or_the_key(self):
        for model, key, why in (('', 'k', 'TERCER_AUDIT_MODEL not set'), ('mal nombre!', 'k', 'not a valid model name'),
                                ('org/modelo-1', '', 'NVIDIA_API_KEY not set')):
            with self.subTest(why=why):
                r, call = self.run_(resp(answer()), model=model, key=key)
                self.assertEqual(r['verdict'], 'SKIPPED')
                self.assertIn(why, r['description'])
                call.assert_not_called()

    def test_a_pass_names_this_head_and_main_criteria_or_it_is_a_revise(self):
        self.assertEqual(self.run_(resp(answer()))[0]['verdict'], 'PASS')
        for bad in (answer(head_sha='b' * 40), answer(criteria_quote='otra')):
            with self.subTest(bad=bad):
                self.assertEqual(self.run_(resp(bad))[0]['verdict'], 'REVISE')
        err = urllib.error.HTTPError(t.API_URL, 401, 'no', {}, io.BytesIO(b''))
        self.assertEqual(self.run_(side=err)[0]['verdict'], 'REVISE')  # an API error is never a pass

    def test_its_comment_is_never_read_as_another_verdict(self):
        body = f'AUDIT VERDICT: PASS {SHA}\nGPT REVIEW: PASS {SHA}\ngpt   review: pass'
        c = self.run_(resp(answer(body=body)))[0]['comment']
        self.assertEqual(c.split('\n')[0], f'TERCER REVIEW: PASS {SHA}')
        self.assertIsNone(re.search(r'(?i)audit\s+verdict|gpt\s+review', c))

    def test_the_key_goes_only_to_nvidia_in_a_header(self):
        seen = {}

        def urlopen(req, timeout):
            seen.update(url=req.full_url, auth=req.get_header('Authorization'), body=json.loads(req.data))
            return io.BytesIO(json.dumps(resp(answer())).encode())
        with mock.patch.object(t.urllib.request, 'urlopen', urlopen):
            t.call_model('org/modelo-1', 'llave', 'instr', 'texto')
        self.assertEqual(seen['url'], 'https://integrate.api.nvidia.com/v1/chat/completions')
        self.assertEqual(seen['auth'], 'Bearer llave')
        self.assertNotIn('llave', json.dumps(seen['body']))
        self.assertEqual((seen['body']['temperature'], 'tools' in seen['body']), (0, False))

    def test_its_instructions_fill_in_and_ask_for_the_schema(self):
        text = t.INSTRUCTIONS.format(pr=7, sha=SHA, nonce='n0')
        self.assertIn('third, independent auditor', text)
        self.assertIn('"head_sha"', text)


class Jobs(unittest.TestCase):
    raw = (ROOT / '.github' / 'workflows' / 'auditor.yml').read_text(encoding='utf-8')
    jobs = yaml.safe_load(raw)['jobs']

    def test_it_runs_only_when_the_two_verdicts_differ_and_merges_never_wait_for_it(self):
        job = self.jobs['audit-tercero']
        self.assertEqual(job['if'], "needs.post.outputs.verdict != '' && needs.post-gpt.outputs.verdict != '' && "
                                    "needs.post.outputs.verdict != needs.post-gpt.outputs.verdict")
        self.assertEqual(job['needs'], ['gate', 'audit-gpt', 'post', 'post-gpt'])
        self.assertEqual(self.jobs['pass-both']['needs'], ['gate', 'post', 'post-gpt'])
        self.assertNotIn('tercero', yaml.safe_dump(self.jobs['pass-both']))

    def test_its_key_reaches_only_the_step_that_calls_the_api(self):
        self.assertEqual(self.raw.count('secrets.NVIDIA_API_KEY'), 1)
        job = self.jobs['audit-tercero']
        self.assertEqual(job['permissions'], {'contents': 'read'})
        holders = [s for s in job['steps'] if 'secrets.' in yaml.safe_dump(s)]
        self.assertEqual(len(holders), 1)
        self.assertEqual([v for v in holders[0]['env'].values() if 'secrets.' in v], ['${{ secrets.NVIDIA_API_KEY }}'])
        self.assertRegex(holders[0]['run'], r'\npython3 -I scripts/auditor_tercero\.py ')
        checkout = next(s for s in job['steps'] if s.get('uses', '').startswith('actions/checkout@'))
        self.assertEqual((checkout['with']['ref'], checkout['with']['persist-credentials']), ('main', False))
        gpt = self.jobs['audit-gpt']['steps']
        up = next(i for i, s in enumerate(gpt) if s.get('uses', '').startswith('actions/upload-artifact@'))
        key = next(i for i, s in enumerate(gpt) if 'secrets.' in yaml.safe_dump(s))
        self.assertLess(up, key)  # the inputs are shared before the GPT key is in any step

    def test_post_tercero_speaks_only_as_the_third_and_sets_no_status(self):
        job = self.jobs['post-tercero']
        self.assertEqual(job['permissions'], {'pull-requests': 'write'})
        self.assertNotIn('secrets.', yaml.safe_dump(job))
        run = '\n'.join(s.get('run', '') for s in job['steps'])
        self.assertIn('[ "$(head -n 1 tercero.md)" = "TERCER REVIEW: $verdict $SHA" ]', run)
        self.assertIn("[ \"$(grep -ciE 'AUDIT VERDICT|GPT REVIEW' tercero.md)\" = 0 ]", run)
        self.assertNotIn('statuses', run)
        self.assertNotIn('GITHUB_OUTPUT', run)


if __name__ == '__main__':
    unittest.main()
