"""Vigía de producción (scripts/vigia.py, vigia.yml, SECURITY.md T26): one state per watched workflow from its runs and
the time alone, an issue text with nothing the API wrote, and the workflow's own steps run against a stub gh. Built here
(CONSTRUIDO): run lists shaped like GET /repos/{repo}/actions/workflows/{file}/runs. No network."""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('vigia', ROOT / 'scripts' / 'vigia.py')
vigia = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vigia)
TEXT = (ROOT / '.github' / 'workflows' / 'vigia.yml').read_text(encoding='utf-8')
WF = yaml.safe_load(TEXT)
JOB = WF['jobs']['vigia']
AHORA = datetime(2026, 11, 2, 23, 37, tzinfo=timezone.utc)
H, D = timedelta(hours=1), timedelta(days=1)


def run(i, conclusion='success', hace=H, status='completed', ahora=AHORA, **kw):
    t = (ahora - hace).strftime('%Y-%m-%dT%H:%M:%SZ')
    return {'id': i, 'run_number': i, 'status': status, 'conclusion': conclusion if status == 'completed' else None,
            'created_at': t, 'run_started_at': t, 'head_branch': 'main', 'event': 'schedule', **kw}


def issue(n, login=vigia.AUTOR, title=vigia.TITULO, **kw):
    return {'number': n, 'title': title, 'state': 'open', 'user': {'login': login}, **kw}


def estado(*runs, tope=2):
    return vigia.decidir({'workflow_runs': list(runs)}, tope, AHORA)['estado']


class Decision(unittest.TestCase):
    def test_a_last_finished_run_that_did_not_succeed_is_red(self):
        for c in ('failure', 'cancelled', 'timed_out', 'startup_failure', 'skipped', None, 'algo nuevo'):
            self.assertEqual(estado(run(1, hace=D), run(2, c)), 'rojo', c)
        self.assertEqual(estado(run(1, 'failure', 2 * H), run(2, status='in_progress')), 'rojo')

    def test_the_cap_counts_whole_days_and_its_edge_is_still_ok(self):
        self.assertEqual(estado(run(1, hace=2 * D)), 'ok')                          # exactly the cap
        self.assertEqual(estado(run(1, hace=3 * D - timedelta(seconds=1))), 'ok')  # 2 whole days
        self.assertEqual(estado(run(1, hace=3 * D)), 'sin_correr')                 # the third whole day

    def test_no_run_or_only_runs_not_of_main_by_schedule_or_dispatch_is_sin_correr(self):
        self.assertEqual(vigia.decidir({'workflow_runs': []}, 8, AHORA), {'estado': 'sin_correr', 'corrida': None, 'exito': None})
        self.assertEqual(estado(run(1, head_branch='otra')), 'sin_correr')
        self.assertEqual(estado(run(1, event='pull_request')), 'sin_correr')  # a fork's branch can be called main
        self.assertEqual(estado(run(1, event='workflow_dispatch')), 'ok')
        self.assertEqual(estado(run(1, status='misterio')), 'sin_correr')     # an unknown status is never success

    def test_a_run_going_on_within_the_cap_is_en_curso_and_one_stuck_past_it_is_not(self):
        for s in ('queued', 'in_progress'):
            self.assertEqual(estado(run(1, status=s)), 'en_curso')
        d = vigia.decidir({'workflow_runs': [run(1, hace=5 * D), run(2, status='in_progress')]}, 2, AHORA)
        self.assertEqual((d['estado'], d['corrida']['id'], d['exito']['id']), ('en_curso', 2, 1))
        self.assertEqual(estado(run(1, status='in_progress', hace=3 * D)), 'sin_correr')

    def test_the_newest_run_decides_whatever_the_order_of_the_answer_and_a_rerun_counts_from_its_start(self):
        self.assertEqual(estado(run(1, 'failure', 2 * H), run(2, hace=H)), 'ok')
        self.assertEqual(estado(run(2, hace=2 * H), run(1, 'failure', H)), 'rojo')
        r = run(1, hace=10 * D)  # a re-run counts from when it started again
        r['run_started_at'] = run(1)['created_at']
        self.assertEqual(estado(r), 'ok')

    def test_malformed_data_stops_the_decision(self):
        bad = [None, {}, {'workflow_runs': None}, {'workflow_runs': [[]]}]
        for k, v in (('id', '5'), ('id', True), ('id', 0), ('run_number', None), ('status', None), ('created_at', None),
                     ('created_at', '2026-11-02 10:00:00'), ('run_started_at', '')):
            bad.append({'workflow_runs': [{**run(1), k: v}]})
        for b in bad:
            self.assertRaises(ValueError, vigia.decidir, b, 2, AHORA)


class Texto(unittest.TestCase):
    def todos(self, **cambios):
        return {n: {'workflow_runs': cambios.get(n, [run(1)])} for n, _ in vigia.VIGILADOS}

    def test_a_row_names_the_run_by_its_number_link_and_start_and_the_days_since_the_last_success(self):
        datos = self.todos(**{'catalog-mx.yml': [run(41329499070, 'failure', hace=6 * H, run_number=46), run(9, hace=2 * D)]})
        alerta, texto = vigia.revisar(datos, AHORA, 'o/r')
        self.assertTrue(alerta)
        self.assertIn('| `catalog-mx.yml` | rojo | [#46](https://github.com/o/r/actions/runs/41329499070) '
                      '2026-11-02 17:37 UTC, failure | 2 | 2 |\n', texto)
        self.assertIn('| `texto-mx.yml` | ok | [#1](https://github.com/o/r/actions/runs/1) 2026-11-02 22:37 UTC, success | 0 | 8 |', texto)

    def test_nothing_the_api_wrote_reaches_the_text_and_only_red_or_not_running_alerts(self):
        hostil = {'display_title': '@braulio <img src=x> evil', 'name': 'evil', 'html_url': 'https://evil.example/',
                  'head_commit': {'message': '@evil'}, 'actor': {'login': 'evil'}, 'path': 'evil'}
        datos = self.todos(**{n: [run(7, '@evil <b>' if n == 'sondeo.yml' else 'success', **hostil)] for n, _ in vigia.VIGILADOS})
        alerta, texto = vigia.revisar(datos, AHORA, 'o/r')
        self.assertTrue(alerta)
        self.assertIn('| `sondeo.yml` | rojo | [#7](https://github.com/o/r/actions/runs/7) 2026-11-02 22:37 UTC, otra |', texto)
        for s in ('@', '<', 'evil'):
            self.assertNotIn(s, texto)
        self.assertEqual(set(re.findall(r'\]\(([^)]*)\)', texto)), {'https://github.com/o/r/actions/runs/7'})
        self.assertRegex(texto, r'^[\w\s|`#\[\]():/.,-]*$')
        self.assertFalse(vigia.revisar(self.todos(**{'texto-mx.yml': [run(1, status='queued')]}), AHORA, 'o/r')[0])
        self.assertTrue(vigia.revisar(self.todos(**{'sondeo-inegi.yml': []}), AHORA, 'o/r')[0])

    def test_a_missing_workflow_or_a_repo_that_is_not_owner_name_stops_it(self):
        for repo in ('o/r/../x', 'o/r\n@x', 'evil.example/o/r'):
            self.assertRaises(ValueError, vigia.revisar, self.todos(), AHORA, repo)
        self.assertRaises(KeyError, vigia.revisar, {k: v for k, v in self.todos().items() if k != 'sondeo.yml'}, AHORA, 'o/r')


class Issue(unittest.TestCase):
    def test_only_the_open_issue_this_workflow_opened_with_the_exact_title_is_chosen(self):
        self.assertEqual(vigia.elegir_issue([issue(3, 'alguien'), issue(9), issue(7)]), 7)
        for i in (issue(3, 'alguien'), issue(4, pull_request={}), issue(5, title='Vigia de produccion'),
                  issue(6, title=vigia.TITULO + ' '), issue(8, state='closed'), issue('7')):
            self.assertIsNone(vigia.elegir_issue([i]), i)
        self.assertRaises(ValueError, vigia.elegir_issue, {'items': []})


class Workflow(unittest.TestCase):
    def test_the_watched_workflows_and_their_caps_are_fixed_and_start_only_by_schedule_or_dispatch(self):
        self.assertEqual(dict(vigia.VIGILADOS), {'catalog-mx.yml': 2, 'texto-mx.yml': 8, 'indicadores-mx.yml': 8,
                                                 'sondeo.yml': 8, 'descubrir.yml': 2, 'sondeo-inegi.yml': 35})
        for n, _ in vigia.VIGILADOS:
            doc = yaml.safe_load((ROOT / '.github' / 'workflows' / n).read_text(encoding='utf-8'))
            self.assertLessEqual(set(doc.get('on') or doc[True]), set(vigia.EVENTOS), n)

    def test_mains_code_only_daily_or_by_dispatch_reading_runs_and_writing_issues_and_nothing_else(self):
        on = WF.get('on') or WF[True]
        self.assertEqual(set(on), {'schedule', 'workflow_dispatch'})
        minuto, hora, *resto = on['schedule'][0]['cron'].split()
        self.assertEqual((resto, int(minuto) % 5 != 0), (['*', '*', '*'], True))  # daily, at a minute nobody else picks
        self.assertEqual(JOB['if'], "github.ref == 'refs/heads/main'")
        self.assertEqual(JOB['steps'][0]['with'], {'ref': 'main', 'persist-credentials': False})
        self.assertEqual(WF['concurrency'], {'group': 'vigia', 'cancel-in-progress': False})
        self.assertEqual((WF['permissions'], JOB['permissions']), ({}, {'actions': 'read', 'issues': 'write'}))
        self.assertNotIn('secrets.', TEXT)
        for s in JOB['steps']:
            self.assertNotIn('${{', s.get('run', ''))
            for line in s.get('run', '').splitlines():
                if 'python' in line:
                    self.assertIn('python3 -I scripts/vigia.py ', line)
        self.assertEqual((JOB['steps'][-1]['if'], JOB['steps'][-1]['run']), ("steps.decidir.outputs.alerta != 'false'", 'exit 1'))


GH = """#!/bin/bash
printf '%s\\n' "$*" >> "$STUB_LOG"
case "$2" in
  repos/o/r/actions/workflows/*) f=${2#repos/o/r/actions/workflows/}; cat "$STUB_RUNS/${f%%/*}.json" ;;
  'repos/o/r/issues?state=open'*) cat "$STUB_ISSUES" ;;
esac
prev=; for a in "$@"; do [ "$prev" = --input ] && printf 'INPUT %s\\n' "$(cat "$a")" >> "$STUB_LOG"; prev=$a; done; true
"""


class Pasos(unittest.TestCase):
    """The workflow's own steps, in order, against a stub gh that serves the runs and the open issues."""

    def correr(self, rojo, issues, alerta=None):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / 'bin').mkdir(); (t / 'runs').mkdir()
            for name, body in (('gh', GH), ('python3', f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')):
                (t / 'bin' / name).write_text(body); (t / 'bin' / name).chmod(0o755)
            ahora = datetime.now(timezone.utc)
            for n, _ in vigia.VIGILADOS:
                runs = [run(2, 'failure', ahora=ahora)] if n in rojo else [run(1, ahora=ahora)]
                (t / 'runs' / f'{n}.json').write_text(json.dumps({'workflow_runs': runs}))
            (t / 'issues.json').write_text(json.dumps(issues))
            env = {'PATH': f'{t / "bin"}:{os.environ["PATH"]}', 'HOME': str(t), 'RUNNER_TEMP': str(t), 'REPO': 'o/r',
                   'GH_TOKEN': 'x', 'GITHUB_OUTPUT': str(t / 'out'), 'GITHUB_STEP_SUMMARY': str(t / 'summary'),
                   'STUB_LOG': str(t / 'log'), 'STUB_RUNS': str(t / 'runs'), 'STUB_ISSUES': str(t / 'issues.json')}
            for s in JOB['steps'][1:-1]:
                if 'ALERTA' in s.get('env', {}):
                    env['ALERTA'] = (t / 'out').read_text().strip().split('=')[1] if alerta is None else alerta
                r = subprocess.run(['bash', '-e', '-c', s['run']], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
                self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('| `catalog-mx.yml` |', (t / 'summary').read_text())
            log = (t / 'log').read_text().replace(str(t / 'vigia'), '$d').splitlines()
        reads = [f'api repos/o/r/actions/workflows/{n}/runs?branch=main&per_page=20' for n, _ in vigia.VIGILADOS]
        self.assertEqual(log[:7], reads + ['api repos/o/r/issues?state=open&creator=github-actions%5Bbot%5D&per_page=100'])
        return [json.loads(x[6:]) if x.startswith('INPUT ') else x for x in log[7:]]

    def test_red_opens_the_issue_or_updates_ours_and_never_touches_an_outsiders(self):
        self.assertEqual(self.correr({'catalog-mx.yml'}, []), ['api -X POST repos/o/r/issues --input $d/nueva.json', {
            'title': vigia.TITULO, 'body': mock.ANY}])
        calls = self.correr({'texto-mx.yml'}, [issue(3, 'alguien'), issue(7)])
        self.assertEqual(calls, ['api -X PATCH repos/o/r/issues/7 --input $d/cuerpo.json', {'body': mock.ANY}])
        self.assertIn('| `texto-mx.yml` | rojo |', calls[1]['body'])

    def test_all_well_closes_ours_with_a_comment_and_an_undecided_run_writes_nothing(self):
        self.assertEqual(self.correr(set(), []), [])
        calls = self.correr(set(), [issue(7)])
        self.assertEqual(calls, ['api -X POST repos/o/r/issues/7/comments --input $d/cierre.json', {'body': mock.ANY},
                                 'api -X PATCH repos/o/r/issues/7 -f state=closed -f state_reason=completed'])
        self.assertTrue(calls[1]['body'].startswith('Todo en orden'))
        self.assertEqual(self.correr(set(), [issue(7)], alerta=''), [])


if __name__ == '__main__':
    unittest.main()
