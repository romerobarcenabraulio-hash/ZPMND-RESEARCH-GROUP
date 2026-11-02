"""Third reviewer, for measurement only: an open-weights model of another family through NVIDIA's hosted API, asked
only when the Claude auditor and the GPT review disagree on the same head (auditor.yml, `audit-tercero`).

    python3 -I scripts/auditor_tercero.py --inputs DIR --pr N --sha SHA --out result.json

Same input, guards and judgement as scripts/auditor_gpt.py (loaded from main's file next to this one): main's criteria,
the diff git computed from main, the untrusted evidence; no tools; fail closed to REVISE. It never gates a merge: its
line is "TERCER REVIEW", which no reader of the two verdicts takes for one, and pass-both never waits for it. What it
is for is the count in docs/REGLAS.md (rule 27 proposal): on how many disagreements it found something real that one
of the other two missed. Its key goes only to the host below; its model comes from the repo variable TERCER_AUDIT_MODEL
and without it nothing is called. Standard library only.
"""
import argparse
import http.client
import importlib.util
import json
import os
import re
import secrets
import sys
import urllib.error
import urllib.request
from pathlib import Path

_spec = importlib.util.spec_from_file_location('auditor_gpt', Path(__file__).with_name('auditor_gpt.py'))
g = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(g)

API_URL = 'https://integrate.api.nvidia.com/v1/chat/completions'  # fixed: the key never goes anywhere else
PREFIX = 'TERCER REVIEW: '
MODEL_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,63}(/[A-Za-z0-9][A-Za-z0-9._:-]{0,63})?')  # catalog names: org/model
INSTRUCTIONS = g.INSTRUCTIONS.replace(
    'You are the second, independent auditor', 'You are a third, independent auditor, asked because two others disagree,',
).replace('Another model audits the same PR separately', 'Two other models audit the same PR separately') + (
    '\nThe JSON object has exactly these keys and nothing around it (no code fence): '
    + json.dumps(g.SCHEMA).replace('{', '{{').replace('}', '}}') + '\n')  # literal braces: format() fills the rest


def call_model(model, key, instructions, text):
    """One POST to an OpenAI-compatible Chat Completions endpoint. No tools, temperature 0, capped output."""
    payload = {'model': model, 'temperature': 0, 'max_tokens': g.MAX_OUTPUT_TOKENS,
               'messages': [{'role': 'system', 'content': instructions}, {'role': 'user', 'content': text}]}
    req = urllib.request.Request(API_URL, data=json.dumps(payload).encode('utf-8'), method='POST',
                                 headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=g.TIMEOUT_S) as r:
        return json.loads(r.read().decode('utf-8'))


def parse_response(resp):
    """(answer dict or None, problem or None). Only one choice that stopped by itself counts; a cut one is a problem."""
    choices = resp.get('choices') if isinstance(resp, dict) else None
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        return None, 'la respuesta no trae exactamente una opción'
    if choices[0].get('finish_reason') != 'stop':
        return None, f'respuesta no completada ({g._word(choices[0].get("finish_reason"))})'
    content = (choices[0].get('message') or {}).get('content')
    if not isinstance(content, str):
        return None, 'la respuesta no trae texto'
    content = re.sub(r'^\s*```(?:json)?\s*|\s*```\s*$', '', content)  # a fence around the object, nothing else
    try:
        return json.loads(content), None
    except ValueError:
        return None, 'la respuesta no es JSON'


def render(verdict, sha, notes, body, model):
    """The PR comment: neither "AUDIT VERDICT" nor "GPT REVIEW" appears in it, so no reader of those lines takes it."""
    body = re.sub(r'(?i)gpt\s+review', 'GPT-REVIEW', re.sub(r'(?i)audit\s+verdict', 'AUDIT-VERDICT', body))
    notes = [n.replace('El auditor GPT', 'El tercer revisor') for n in notes]
    lines = [f'{PREFIX}{verdict} {sha}', ''] + [x for n in notes for x in (n, '')] + ([body, ''] if body else [])
    lines.append(f'_Tercera opinión, solo para medir (NVIDIA, modelo `{model}`, sin herramientas, solo texto; no ejecuta '
                 'código del PR y no decide merges): corre cuando el auditor de Claude y GPT discrepan._')
    return '\n'.join(lines) + '\n'


def audit(root, pr, sha, model, key):
    if not model:
        return g.skipped('TERCER_AUDIT_MODEL not set')
    if not MODEL_RE.fullmatch(model):
        return g.skipped('TERCER_AUDIT_MODEL is not a valid model name')
    if not key:
        return g.skipped('NVIDIA_API_KEY not set')
    nonce = secrets.token_hex(8)
    text, complete, quote = g.build_input(root, nonce, sha)
    answer, problem = None, None
    try:
        answer, problem = parse_response(call_model(model, key, INSTRUCTIONS.format(pr=pr, sha=sha, nonce=nonce), text))
    except urllib.error.HTTPError as e:  # its body is not read: it can echo part of the key
        e.close()
        problem = f'HTTP {e.code}'
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
        problem = f'sin respuesta de la API ({type(e).__name__})'
    verdict, notes, body = g.judge(answer, problem, sha, quote, complete)
    return {'verdict': verdict, 'description': f'{PREFIX}{verdict}', 'comment': render(verdict, sha, notes, body, model)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--inputs', required=True, type=Path)
    ap.add_argument('--pr', required=True)
    ap.add_argument('--sha', required=True)
    ap.add_argument('--out', required=True, type=Path)
    a = ap.parse_args(argv)
    if not g.SHA_RE.fullmatch(a.sha) or not re.fullmatch(r'[0-9]+', a.pr):
        sys.exit('bad --sha or --pr')
    result = audit(a.inputs, a.pr, a.sha, os.environ.get('TERCER_AUDIT_MODEL', '').strip(),
                   os.environ.get('NVIDIA_API_KEY', ''))
    a.out.write_text(json.dumps(result, ensure_ascii=True) + '\n', encoding='utf-8')
    print(f'{result["verdict"]}: {result["description"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
