"""scripts/auditor_gpt.py, the second auditor: each guard that keeps it fail-closed and cheap, with the API mocked.

No test reaches the network: urlopen is replaced in every test, and a call nobody expected fails the test.
"""
import hashlib
import importlib.util
import io
import json
import os
import random
import re
import shutil
import string
import subprocess
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('auditor_gpt', ROOT / 'scripts' / 'auditor_gpt.py')
gpt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gpt)

SHA = '0123456789abcdef0123456789abcdef01234567'
QUOTE = '# ZPMND RESEARCH GROUP'
CAP = {rel: cap for rel, cap, _ in gpt.SECTIONS}


def make_inputs(root, **over):
    files = {
        'criteria/README.md': QUOTE + '\n\nAn external research lab.\n',
        'criteria/RESEARCH_CONTRACT.md': 'contrato de prueba\n',
        'criteria/SECURITY.md': 'seguridad de prueba\n',
        'criteria/REGLAS.md': 'reglas de prueba\n',
        'trusted/diff-stat.txt': ' x.py | 1 +\n',
        'trusted/commits.txt': 'abc1234 un cambio\n',
        'trusted/diff.patch': 'diff --git a/x.py b/x.py\n+hola = 1\n',
        'evidence/tests.txt': 'Ran 3 tests\nOK\nexit=0\n',
        'evidence/mutation-main.txt': 'skipped: identical\n',
    }
    files.update(over)
    for rel, text in files.items():
        if text is not None:
            p = Path(root) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding='utf-8')


def answer(**over):
    a = {'verdict': 'PASS', 'head_sha': SHA, 'criteria_quote': QUOTE, 'body': 'Sin hallazgos BLOCKING.'}
    a.update(over)
    return a


USAGE = {'input_tokens': 1234, 'input_tokens_details': {'cached_tokens': 11}, 'output_tokens': 567,
         'output_tokens_details': {'reasoning_tokens': 400}, 'total_tokens': 1801}


def response(ans=None, status='completed', text=None, content_type='output_text'):
    text = json.dumps(ans) if text is None else text
    return {'status': status, 'incomplete_details': None if status == 'completed' else {'reason': 'max_output_tokens'},
            'output': [{'type': 'reasoning', 'summary': []},
                       {'type': 'message', 'role': 'assistant', 'content': [{'type': content_type, 'text': text}]}],
            'usage': USAGE}


class FakeHTTP:
    """Stands in for urllib.request.urlopen: records every request and returns one canned body or raises."""

    def __init__(self, body=None, error=None):
        self.calls, self.body, self.error = [], body, error

    def __call__(self, req, timeout=None):
        self.calls.append({'url': req.full_url, 'headers': dict(req.header_items()), 'payload': json.loads(req.data),
                           'timeout': timeout})
        if self.error is not None:
            raise self.error
        return io.BytesIO(json.dumps(self.body).encode('utf-8'))


def no_network(*a, **k):
    raise AssertionError('unexpected network call')


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = self.tmp / 'in'
        make_inputs(self.root)
        self.summary = self.tmp / 'summary.md'
        for p in (mock.patch.dict(os.environ, {'GITHUB_STEP_SUMMARY': str(self.summary)}),
                  mock.patch.object(gpt.urllib.request, 'urlopen', no_network),
                  mock.patch('sys.stdout', new_callable=io.StringIO)):
            p.start()
            self.addCleanup(p.stop)

    def run_audit(self, http, model='a-model', key='test-key-not-real'):
        with mock.patch.object(gpt.urllib.request, 'urlopen', http):
            return gpt.audit(self.root, '7', SHA, model, key)

    def assertRevise(self, r, note):
        self.assertEqual(r['verdict'], 'REVISE')
        self.assertEqual(r['comment'].split('\n')[0], f'GPT REVIEW: REVISE {SHA}')
        self.assertIn(note, r['comment'])


class Pass(Base):
    def test_a_complete_well_formed_answer_passes(self):
        http = FakeHTTP(response(answer()))
        r = self.run_audit(http)
        self.assertEqual(r['verdict'], 'PASS')
        self.assertEqual(r['description'], 'GPT REVIEW: PASS')
        self.assertEqual(r['comment'].split('\n')[0], f'GPT REVIEW: PASS {SHA}')
        self.assertIn('Sin hallazgos BLOCKING.', r['comment'])
        self.assertIn('modelo `a-model`', r['comment'])
        self.assertEqual(len(http.calls), 1)  # one call per audit: the cost is bounded


class Request(Base):
    def test_one_call_text_only_no_tools_capped_output_not_stored(self):
        http = FakeHTTP(response(answer()))
        self.run_audit(http)
        call = http.calls[0]
        p = call['payload']
        self.assertEqual(call['url'], 'https://api.openai.com/v1/responses')
        self.assertEqual(set(p), {'model', 'instructions', 'input', 'max_output_tokens', 'store', 'text'})  # no tools
        self.assertEqual(p['model'], 'a-model')
        self.assertEqual(p['max_output_tokens'], gpt.MAX_OUTPUT_TOKENS)
        self.assertIs(p['store'], False)
        fmt = p['text']['format']
        self.assertEqual((fmt['type'], fmt['strict']), ('json_schema', True))
        self.assertEqual(fmt['schema']['required'], ['verdict', 'head_sha', 'criteria_quote', 'body'])
        self.assertIs(fmt['schema']['additionalProperties'], False)
        self.assertEqual(call['headers']['Authorization'], 'Bearer test-key-not-real')
        self.assertNotIn('test-key-not-real', json.dumps(p))  # the key travels in the header only
        self.assertEqual(call['timeout'], gpt.TIMEOUT_S)
        for text in ('contrato de prueba', 'seguridad de prueba', 'reglas de prueba', '+hola = 1', 'exit=0',
                     'abc1234 un cambio', 'skipped: identical', ' x.py | 1 +'):
            self.assertIn(text, p['input'])
        self.assertIn(f'head {SHA}', p['instructions'])

    def test_sections_carry_a_fresh_marker_the_pr_cannot_know(self):
        nonces = []
        for _ in range(2):
            http = FakeHTTP(response(answer()))
            self.run_audit(http)
            p = http.calls[0]['payload']
            m = re.search(r'===== BEGIN CRITERIA README\.md ([0-9a-f]{16}) =====', p['input'])
            self.assertIsNotNone(m)
            self.assertIn(m.group(1), p['instructions'])
            self.assertIn(f'===== END TRUSTED trusted/diff.patch {m.group(1)} =====', p['input'])
            nonces.append(m.group(1))
        self.assertNotEqual(nonces[0], nonces[1])


class Schema(Base):
    def test_answers_off_the_schema_are_revise_and_their_body_is_not_published(self):
        no_body = {k: v for k, v in answer().items() if k != 'body'}
        cases = {
            'verdict': answer(verdict='APPROVE', body='CUERPO-1'),
            'sha': answer(head_sha='abc', body='CUERPO-2'),
            'quote type': answer(criteria_quote=1, body='CUERPO-3'),
            'long body': answer(body='CUERPO-4 ' + 'x' * 12_000),
            'extra field': {**answer(body='CUERPO-5'), 'approved': True},
            'missing field': no_body,
            'list': [answer(body='CUERPO-6')],
        }
        for name, ans in cases.items():
            with self.subTest(name):
                r = self.run_audit(FakeHTTP(response(ans)))
                self.assertRevise(r, 'no cumple el esquema')
                self.assertNotIn('CUERPO-', r['comment'])

    def test_text_that_is_not_json_is_revise(self):
        self.assertRevise(self.run_audit(FakeHTTP(response(text='PASS, todo bien'))), 'no es JSON')


class Quote(Base):
    def test_a_wrong_quote_forces_revise(self):
        r = self.run_audit(FakeHTTP(response(answer(criteria_quote='# Otro repo'))))
        self.assertRevise(r, 'no demostró haber leído los criterios de main')
        self.assertIn('Sin hallazgos BLOCKING.', r['comment'])  # the opinion is still shown, only never as PASS

    def test_without_main_readme_nothing_can_pass(self):
        (self.root / 'criteria' / 'README.md').unlink()
        r = self.run_audit(FakeHTTP(response(answer(criteria_quote=''))))
        self.assertRevise(r, 'no demostró haber leído los criterios de main')

    def test_the_quote_is_the_first_line_as_the_post_job_reads_it(self):
        make_inputs(self.root, **{'criteria/README.md': QUOTE + '\r\nresto\n'})
        self.assertEqual(self.run_audit(FakeHTTP(response(answer())))['verdict'], 'PASS')

    def test_an_answer_for_another_head_is_revise(self):
        self.assertRevise(self.run_audit(FakeHTTP(response(answer(head_sha='f' * 40)))), 'nombró otro head')


class Budget(Base):
    def test_a_diff_over_its_cap_is_cut_and_never_passes(self):
        cap = CAP['trusted/diff.patch']
        make_inputs(self.root, **{'trusted/diff.patch': '+' + 'y' * (cap + 5_000) + 'FINAL-DEL-DIFF\n'})
        http = FakeHTTP(response(answer()))
        r = self.run_audit(http)
        self.assertRevise(r, 'No pude leer todo')
        sent = http.calls[0]['payload']['input']
        self.assertIn('[TRUNCADO o ausente', sent)
        self.assertNotIn('FINAL-DEL-DIFF', sent)

    def test_the_input_is_bounded_whatever_the_sizes(self):
        make_inputs(self.root, **{rel: 'z' * (cap * 10) for rel, cap, _ in gpt.SECTIONS},
                    **{f'criteria/{n}': 'c' * (gpt.CRITERIA_CAP * 10) for n in gpt.CRITERIA})
        http = FakeHTTP(response(answer()))
        self.assertEqual(self.run_audit(http)['verdict'], 'REVISE')
        p = http.calls[0]['payload']
        self.assertLessEqual(len(p['input']), gpt.BUDGET + len(gpt.CRITERIA) * gpt.CRITERIA_CAP + 3_000)
        self.assertLess(len(p['instructions']), 5_000)

    def test_the_evidence_keeps_its_end(self):
        make_inputs(self.root, **{'evidence/tests.txt': 'ruido\n' * 50_000 + 'Ran 9 tests\nexit=0\n'})
        http = FakeHTTP(response(answer()))
        self.assertRevise(self.run_audit(http), 'No pude leer todo')
        self.assertIn('Ran 9 tests\nexit=0', http.calls[0]['payload']['input'])

    def test_a_missing_input_never_passes(self):
        (self.root / 'evidence' / 'tests.txt').unlink()
        self.assertRevise(self.run_audit(FakeHTTP(response(answer()))), 'No pude leer todo')

    def test_a_symlink_in_the_evidence_is_not_followed(self):
        outside = self.tmp / 'outside.txt'
        outside.write_text('MARCA-FUERA-DEL-DIRECTORIO\n', encoding='utf-8')
        link = self.root / 'evidence' / 'tests.txt'
        link.unlink()
        link.symlink_to(outside)
        http = FakeHTTP(response(answer()))
        self.assertRevise(self.run_audit(http), 'No pude leer todo')
        self.assertNotIn('MARCA-FUERA-DEL-DIRECTORIO', http.calls[0]['payload']['input'])


def credential_bodies():
    # Built at run time, so no tracked file holds anything shaped like a credential (tests/test_no_secrets.py)
    rnd = random.Random(7)
    return {
        'openai key, low entropy': 'la llave: ' + 'sk-' + 'proj-' + 'abcd' * 10,
        'anthropic oauth': 'token ' + 'sk-' + 'ant-' + 'oat01-' + 'Ab' * 20,
        'github app token': 'ghs' + '_' + 'x' * 36,
        'random secret': 'valor ' + ''.join(rnd.choices(string.ascii_letters + string.digits, k=48)),
        'long hex': 'h ' + '0123456789abcdef' * 3,
    }


class Credentials(Base):
    def test_a_body_with_a_credential_shape_is_withheld_and_revise(self):
        for name, body in credential_bodies().items():
            with self.subTest(name):
                r = self.run_audit(FakeHTTP(response(answer(body=body))))
                self.assertRevise(r, 'Cuerpo retenido')
                self.assertNotIn(body, r['comment'])

    def test_ordinary_review_text_is_published(self):
        body = (f'Revisé `scripts/auditor_gpt.py:120` en el commit {SHA}. NON-BLOCKING: '
                'the task-management-and-risk-assessment step could be clearer.')
        r = self.run_audit(FakeHTTP(response(answer(body=body))))
        self.assertEqual(r['verdict'], 'PASS')
        self.assertIn(body, r['comment'])


class Skip(Base):
    def test_without_a_model_nothing_is_called_and_the_status_says_skipped(self):
        http = FakeHTTP(response(answer()))
        r = self.run_audit(http, model='')
        self.assertEqual(r, {'verdict': 'SKIPPED', 'description': 'skipped: OPENAI_AUDIT_MODEL not set', 'comment': ''})
        self.assertEqual(http.calls, [])

    def test_a_malformed_model_name_or_no_key_also_skips(self):
        for model, key, why in (('a model; rm -rf', 'k', 'OPENAI_AUDIT_MODEL is not a valid model name'),
                                ('a-model', '', 'OPENAI_API_KEY not set')):
            with self.subTest(why):
                http = FakeHTTP(response(answer()))
                r = self.run_audit(http, model=model, key=key)
                self.assertEqual((r['verdict'], r['description']), ('SKIPPED', f'skipped: {why}'))
                self.assertEqual(http.calls, [])

    def test_main_writes_one_line_and_does_not_fail_without_a_model(self):
        out = self.tmp / 'result.json'
        env = {k: v for k, v in os.environ.items() if k not in ('OPENAI_AUDIT_MODEL', 'OPENAI_API_KEY')}
        with mock.patch.dict(os.environ, env, clear=True):
            rc = gpt.main(['--inputs', str(self.root), '--pr', '7', '--sha', SHA, '--out', str(out)])
        self.assertEqual(rc, 0)
        lines = out.read_text(encoding='utf-8').splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])['verdict'], 'SKIPPED')

    def test_main_output_is_one_ascii_line_even_with_newlines_and_accents(self):
        out = self.tmp / 'result.json'
        http = FakeHTTP(response(answer(body='Línea uno\nlínea dos fin')))
        with mock.patch.dict(os.environ, {'OPENAI_AUDIT_MODEL': 'a-model', 'OPENAI_API_KEY': 'k'}), \
                mock.patch.object(gpt.urllib.request, 'urlopen', http):
            gpt.main(['--inputs', str(self.root), '--pr', '7', '--sha', SHA, '--out', str(out)])
        raw = out.read_bytes()
        self.assertEqual(raw.count(b'\n'), 1)
        self.assertTrue(raw.isascii())
        self.assertIn('Línea uno\nlínea dos', json.loads(raw)['comment'])


class Usage(Base):
    def test_token_usage_goes_to_the_job_summary(self):
        self.run_audit(FakeHTTP(response(answer())))
        text = self.summary.read_text(encoding='utf-8')
        for piece in ('`a-model`', 'entrada: 1234', 'caché: 11', 'salida: 567', 'razonamiento: 400',
                      'totales: 1801', f'tope: {gpt.MAX_OUTPUT_TOKENS}'):
            self.assertIn(piece, text)


class ApiFailures(Base):
    def test_an_http_error_is_revise_and_its_body_is_not_published(self):
        err = urllib.error.HTTPError(gpt.API_URL, 429, 'Too Many Requests', {},
                                     io.BytesIO(b'{"error": {"message": "Incorrect API key provided: ...abcd"}}'))
        r = self.run_audit(FakeHTTP(error=err))
        self.assertRevise(r, 'HTTP 429')
        self.assertNotIn('Incorrect', r['comment'])
        self.assertIn('entrada: None', self.summary.read_text(encoding='utf-8'))  # still logged, with no usage

    def test_no_connection_is_revise(self):
        self.assertRevise(self.run_audit(FakeHTTP(error=urllib.error.URLError('down'))), 'sin respuesta de la API')

    def test_an_incomplete_answer_is_revise_even_if_it_says_pass(self):
        r = self.run_audit(FakeHTTP(response(answer(), status='incomplete')))
        self.assertRevise(r, 'respuesta no completada (incomplete max_output_tokens)')

    def test_a_refusal_is_revise(self):
        self.assertRevise(self.run_audit(FakeHTTP(response(text='no', content_type='refusal'))), 'se negó')


class Distinguishable(Base):
    """A GPT comment never contains "AUDIT VERDICT", so no tool looking for the Claude verdict can count it."""

    def gate_filters(self):
        gate = yaml.safe_load((ROOT / '.github' / 'workflows' / 'auditor.yml').read_text(encoding='utf-8'))
        run = gate['jobs']['gate']['steps'][0]['run']
        done = re.search(r"jq --arg o \"\$OWNER\" --arg s \"\$sha\" '([^']+)'", run).group(1)
        revise = re.search(r"jq --arg o \"\$OWNER\" '([^']+)'", run).group(1)
        return done, revise

    def test_the_gpt_line_never_starts_like_the_claude_verdict(self):
        r = self.run_audit(FakeHTTP(response(answer())))
        self.assertTrue(r['comment'].startswith('GPT REVIEW: PASS '))
        self.assertNotIn('AUDIT VERDICT', r['comment'].upper())
        done, revise = self.gate_filters()
        self.assertIn('. == "AUDIT VERDICT: PASS \\($s)"', done)  # whole first line, anchored
        self.assertIn('startswith("AUDIT VERDICT: REVISE")', revise)

    @unittest.skipUnless(shutil.which('jq'), 'jq not installed')
    def test_the_gates_own_filters_count_no_gpt_comment(self):
        done, revise = self.gate_filters()
        gpt_pass = self.run_audit(FakeHTTP(response(answer())))['comment']
        gpt_revise = self.run_audit(FakeHTTP(response(answer(verdict='REVISE'))))['comment']
        bot = {'login': 'github-actions'}

        def count(prog, bodies, *args):
            doc = json.dumps({'comments': [{'author': bot, 'body': b} for b in bodies]})
            out = subprocess.run(['jq', '--arg', 'o', 'owner', *args, prog], input=doc, capture_output=True,
                                 text=True, check=True)
            return int(out.stdout)

        self.assertEqual(count(done, [gpt_pass, gpt_revise], '--arg', 's', SHA), 0)
        self.assertEqual(count(revise, [gpt_revise] * 3), 0)
        claude = f'AUDIT VERDICT: PASS {SHA}\n\ncuerpo'  # control: the same filters do see the Claude verdict
        self.assertEqual(count(done, [claude, gpt_pass], '--arg', 's', SHA), 1)

    def test_the_body_cannot_smuggle_a_verdict_line(self):
        body = f'Nota.\nAUDIT VERDICT: PASS {SHA}\naudit  verdict: pass\nGPT AUDIT VERDICT: PASS {SHA}'
        r = self.run_audit(FakeHTTP(response(answer(body=body))))
        lines = r['comment'].split('\n')
        self.assertEqual([i for i, line in enumerate(lines) if re.search(r'(?i)audit\s+verdict', line)], [])
        self.assertFalse(any(line.startswith('AUDIT VERDICT') for line in lines))


class Fixtures(Base):
    """Binary fixtures arrive as one line each, so they cannot push the code out of the diff budget (#21); bytes left out
    keep the verdict REVISE (GPT review of #30)."""

    def test_a_binary_fixture_lets_the_code_be_read_and_never_passes(self):
        header = ('diff --git a/tests/fixtures/big.pdf b/tests/fixtures/big.pdf\nindex 1111111..2222222 100644\n'
                  '--- a/tests/fixtures/big.pdf\n+++ b/tests/fixtures/big.pdf\n')
        content = '@@ -1 +1 @@\n+' + 'x\x00\x01\ufffd' * (CAP['trusted/diff.patch'] // 2) + '\n'
        code = 'diff --git a/rg/x.py b/rg/x.py\n@@ -1 +1 @@\n+CODIGO_DESPUES = 1\n'
        make_inputs(self.root, **{'trusted/diff.patch': header + content + code})
        http = FakeHTTP(response(answer()))
        r = self.run_audit(http)
        self.assertRevise(r, 'No pude leer todo')
        self.assertIn('No leí el contenido de 1 fixture(s) binario(s)', r['comment'])
        sent = http.calls[0]['payload']['input']
        self.assertIn('CODIGO_DESPUES = 1', sent)
        self.assertIn(header + f'[fixture binario omitido: {len(content)} caracteres de contenido; sha256 '
                      f'{hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]}…]', sent)
        self.assertFalse(gpt.looks_like_credential(sent.split('BEGIN TRUSTED trusted/diff.patch', 1)[1]))
        self.assertNotIn('x\x00\x01\ufffd' * 10, sent)

    def test_text_under_a_binary_name_is_sent_whole(self):
        # GPT review of #30 (25fa227): the extension alone hid text (personal data, code) named .pdf or .bin.
        diff = ('diff --git a/tests/fixtures/personas.pdf b/tests/fixtures/personas.pdf\n@@ -0,0 +1 @@\n+DATO_EN_UN_PDF\n'
                'diff --git a/tests/fixtures/x.bin b/tests/fixtures/x.bin\n@@ -0,0 +1 @@\n+codigo = "EN_UN_BIN"\n')
        make_inputs(self.root, **{'trusted/diff.patch': diff})
        http = FakeHTTP(response(answer()))
        self.assertEqual(self.run_audit(http)['verdict'], 'PASS')
        sent = http.calls[0]['payload']['input']
        self.assertIn('DATO_EN_UN_PDF', sent)
        self.assertIn('EN_UN_BIN', sent)

    def test_code_under_fixtures_and_renames_are_sent_whole(self):
        diff = ('diff --git a/tests/fixtures/helper.py b/tests/fixtures/helper.py\n@@ -1 +1 @@\n+AYUDANTE = 1\n'
                'diff --git a/tests/fixtures/a.pdf b/tests/fixtures/b.pdf\n@@ -1 +1 @@\n+' + '\x00' * 40 + 'RENOMBRADO = 1\n')
        make_inputs(self.root, **{'trusted/diff.patch': diff})
        http = FakeHTTP(response(answer()))
        self.run_audit(http)
        sent = http.calls[0]['payload']['input']
        self.assertIn('AYUDANTE = 1', sent)
        self.assertIn('RENOMBRADO = 1', sent)
        self.assertNotIn('fixture binario omitido', sent)

    def test_a_text_fixture_is_always_sent_whole(self):
        # GPT review of #30 (3d25654): a text fixture can carry data a reviewer must see (personal data, a payload).
        diff = ('diff --git a/tests/fixtures/personas.txt b/tests/fixtures/personas.txt\nnew file mode 100644\n'
                '--- /dev/null\n+++ b/tests/fixtures/personas.txt\n@@ -0,0 +1 @@\n+' + '\x00' * 40 + 'DATO_QUE_SE_DEBE_VER\n'
                'diff --git a/tests/fixtures/x.json b/tests/fixtures/x.json\n@@ -1 +1 @@\n+JSON_QUE_SE_DEBE_VER\n')
        make_inputs(self.root, **{'trusted/diff.patch': diff})
        http = FakeHTTP(response(answer()))
        self.run_audit(http)
        sent = http.calls[0]['payload']['input']
        self.assertIn('DATO_QUE_SE_DEBE_VER', sent)
        self.assertIn('JSON_QUE_SE_DEBE_VER', sent)
        self.assertNotIn('fixture binario omitido', sent)

    def test_a_symlink_or_a_mode_change_is_never_compacted(self):
        # GPT review of #30 (c1d63ff): compacting by extension hid a fixture turned into a symlink, and mode changes.
        diff = ('diff --git a/tests/fixtures/s.pdf b/tests/fixtures/s.pdf\nnew file mode 120000\nindex 0000000..1111111\n'
                '--- /dev/null\n+++ b/tests/fixtures/s.pdf\n@@ -0,0 +1 @@\n+' + '\x00' * 40 + '../../rg/ENLACE_A_OTRO\n'
                'diff --git a/tests/fixtures/m.pdf b/tests/fixtures/m.pdf\nold mode 100644\nnew mode 100755\n'
                '@@ -1 +1 @@\n+' + '\x00' * 40 + 'MODO_CAMBIADO\n')
        make_inputs(self.root, **{'trusted/diff.patch': diff})
        http = FakeHTTP(response(answer()))
        self.run_audit(http)
        sent = http.calls[0]['payload']['input']
        self.assertIn('ENLACE_A_OTRO', sent)
        self.assertIn('MODO_CAMBIADO', sent)
        self.assertNotIn('fixture binario omitido', sent)

    def test_a_diff_larger_than_the_read_limit_never_passes(self):
        fixture = 'diff --git a/tests/fixtures/big.pdf b/tests/fixtures/big.pdf\n@@ -1 +1 @@\n+' + 'p' * 5_000 + '\n'
        make_inputs(self.root, **{'trusted/diff.patch': fixture + 'diff --git a/rg/x.py b/rg/x.py\n+TARDE = 1\n'})
        with mock.patch.object(gpt, 'MAX_DIFF_BYTES', 1_000):
            self.assertRevise(self.run_audit(FakeHTTP(response(answer()))), 'No pude leer todo')


if __name__ == '__main__':
    unittest.main()
