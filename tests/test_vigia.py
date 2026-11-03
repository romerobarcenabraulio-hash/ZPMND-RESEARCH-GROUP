"""Vigía de producción (scripts/vigia.py, vigia.yml, SECURITY.md T26): one state per watched workflow from its runs and
the time alone, an issue text with nothing the API wrote, and the workflow's own steps run against a stub gh. Built here
(CONSTRUIDO): run lists shaped like GET /repos/{repo}/actions/workflows/{file}/runs and states like GET
/repos/{repo}/actions/workflows/{file}. No network."""
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
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
ACTIVO = {'state': 'active'}


def run(i, conclusion='success', hace=H, status='completed', ahora=AHORA, **kw):
    t = (ahora - hace).strftime('%Y-%m-%dT%H:%M:%SZ')
    return {'id': i, 'run_number': i, 'status': status, 'conclusion': conclusion if status == 'completed' else None,
            'created_at': t, 'run_started_at': t, 'head_branch': 'main', 'event': 'schedule', **kw}


def issue(n, login=vigia.AUTOR, title=vigia.TITULO, **kw):
    return {'number': n, 'title': title, 'state': 'open', 'user': {'login': login}, **kw}


def estado(*runs, tope=2, gh='active', nombre='catalog-mx.yml'):
    return vigia.decidir(nombre, {'workflow_runs': list(runs)}, tope, AHORA, {'state': gh})['estado']


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
        self.assertEqual(vigia.decidir('texto-mx.yml', {'workflow_runs': []}, 8, AHORA, ACTIVO), {'estado': 'sin_correr', 'corrida': None, 'exito': None})
        self.assertEqual(estado(run(1, head_branch='otra')), 'sin_correr')
        self.assertEqual(estado(run(1, event='pull_request')), 'sin_correr')  # a fork's branch can be called main
        self.assertEqual(estado(run(1, event='workflow_dispatch')), 'ok')
        self.assertEqual(estado(run(1, status='misterio')), 'sin_correr')     # an unknown status is never success

    def test_a_run_going_on_within_the_cap_is_en_curso_and_one_stuck_past_it_is_not(self):
        for s in ('queued', 'in_progress'):
            self.assertEqual(estado(run(1, status=s)), 'en_curso')
        d = vigia.decidir('catalog-mx.yml', {'workflow_runs': [run(1, hace=5 * D), run(2, status='in_progress')]}, 2, AHORA, ACTIVO)
        self.assertEqual((d['estado'], d['corrida']['id'], d['exito']['id']), ('en_curso', 2, 1))
        self.assertEqual(estado(run(1, status='queued', hace=2 * D)), 'en_curso')  # the cap's edge
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
            self.assertRaises(ValueError, vigia.decidir, 'catalog-mx.yml', b, 2, AHORA, ACTIVO)

    def test_only_a_listed_workflow_disabled_by_hand_is_pausado_and_any_other_off_one_is_apagado_whatever_the_runs(self):
        for runs in ([run(1, 'failure')], [run(1)], [], [run(1, status='in_progress')], [run(1, hace=9 * D)]):
            self.assertEqual(estado(*runs, gh='disabled_manually', nombre='descubrir.yml'), 'pausado', runs)
            for n, s in [(n, s) for n, _ in vigia.VIGILADOS for s in ('disabled_inactivity', 'disabled_fork', 'deleted')] + [
                    (n, 'disabled_manually') for n, _ in vigia.VIGILADOS if n != 'descubrir.yml']:  # a token can disable one
                self.assertEqual(estado(*runs, gh=s, nombre=n), 'apagado', (n, s, runs))
        self.assertEqual(estado(run(1, 'failure'), nombre='descubrir.yml'), 'rojo')  # listed but active: as always
        d = vigia.decidir('descubrir.yml', {'workflow_runs': [run(1, 'failure', D), run(2, status='queued')]}, 2, AHORA,
                          {'state': 'disabled_manually'})
        self.assertEqual((d['corrida']['id'], d['exito']), (1, None))  # the row shows its last finished run

    def test_an_unknown_or_malformed_workflow_state_stops_the_decision(self):
        for f in (None, [], 'active', {}, {'state': None}, {'state': ['active']}, {'state': 'Active'}, {'state': 'disabled'},
                  {'state': '@evil <b>'}, {'estado': 'active'}):
            self.assertRaises(ValueError, vigia.decidir, 'descubrir.yml', {'workflow_runs': [run(1)]}, 2, AHORA, f)


class Texto(unittest.TestCase):
    def todos(self, **cambios):
        return {n: {'workflow_runs': cambios.get(n, [run(1)])} for n, _ in vigia.VIGILADOS}

    def revisar(self, datos, estados=(), repo='o/r', **extra):
        return vigia.revisar(datos, {n: {'state': dict(estados).get(n, 'active'), **extra} for n, _ in vigia.VIGILADOS}, AHORA, repo)

    def test_a_row_names_the_run_by_its_number_link_and_start_and_the_days_since_the_last_success(self):
        datos = self.todos(**{'catalog-mx.yml': [run(41329499070, 'failure', hace=6 * H, run_number=46), run(9, hace=2 * D)]})
        alerta, texto = self.revisar(datos)
        self.assertTrue(alerta)
        self.assertIn('| `catalog-mx.yml` | rojo | [#46](https://github.com/o/r/actions/runs/41329499070) '
                      '2026-11-02 17:37 UTC, failure | 2 | 2 |\n', texto)
        self.assertIn('| `texto-mx.yml` | ok | [#1](https://github.com/o/r/actions/runs/1) 2026-11-02 22:37 UTC, success | 0 | 8 |', texto)

    def test_nothing_the_api_wrote_reaches_the_text_and_only_red_or_not_running_alerts(self):
        hostil = {'display_title': '@braulio <img src=x> evil', 'name': 'evil', 'html_url': 'https://evil.example/',
                  'head_commit': {'message': '@evil'}, 'actor': {'login': 'evil'}, 'path': 'evil'}
        datos = self.todos(**{n: [run(7, '@evil <b>' if n == 'sondeo.yml' else 'success', **hostil)] for n, _ in vigia.VIGILADOS})
        alerta, texto = self.revisar(datos, {'descubrir.yml': 'disabled_manually', 'texto-mx.yml': 'deleted'}, **hostil)
        self.assertTrue(alerta)
        self.assertIn('| `sondeo.yml` | rojo | [#7](https://github.com/o/r/actions/runs/7) 2026-11-02 22:37 UTC, otra |', texto)
        for s in ('@', '<', 'evil'):
            self.assertNotIn(s, texto)
        self.assertEqual(set(re.findall(r'\]\(([^)]*)\)', texto)), {'https://github.com/o/r/actions/runs/7'})
        self.assertIn('| `descubrir.yml` | pausado |', texto)
        self.assertRegex(texto, r'^[\w\s|`#\[\]():/.,-]*$')
        self.assertFalse(self.revisar(self.todos(**{'texto-mx.yml': [run(1, status='queued')]}))[0])
        self.assertTrue(self.revisar(self.todos(**{'sondeo-inegi.yml': []}))[0])

    def test_pausado_never_alerts_even_after_a_failed_run_and_apagado_alerts_even_after_a_good_one(self):
        datos = self.todos(**{'descubrir.yml': [run(5, 'failure', hace=D)]})
        alerta, texto = self.revisar(datos, {'descubrir.yml': 'disabled_manually'})
        self.assertFalse(alerta)
        self.assertIn('| `descubrir.yml` | pausado | [#5](https://github.com/o/r/actions/runs/5) 2026-11-01 23:37 UTC, failure '
                      '| ninguno entre los últimos 20 | 2 |\n', texto)
        self.assertTrue(self.revisar(self.todos(**{'sondeo.yml': [run(1, 'failure')]}), {'descubrir.yml': 'disabled_manually'})[0])
        for s in ('disabled_manually', 'disabled_inactivity', 'disabled_fork', 'deleted'):  # sondeo is not in PAUSADOS
            alerta, texto = self.revisar(self.todos(), {'sondeo.yml': s})
            self.assertTrue(alerta, s)
            self.assertIn('| `sondeo.yml` | apagado | [#1](https://github.com/o/r/actions/runs/1) 2026-11-02 22:37 UTC, success |', texto)

    def test_a_listed_workflow_github_reports_active_is_decided_as_always_and_its_row_says_it_should_leave_the_list(self):
        alerta, texto = self.revisar(self.todos(**{'descubrir.yml': [run(5, 'failure')]}))
        self.assertTrue(alerta)
        self.assertIn('| `descubrir.yml` | rojo, sobra en PAUSADOS | [#5]', texto)
        alerta, texto = self.revisar(self.todos())
        self.assertFalse(alerta)
        self.assertIn('| `descubrir.yml` | ok, sobra en PAUSADOS | [#1]', texto)
        self.assertEqual(texto.count('sobra en PAUSADOS'), 2)  # that row and the legend only
        self.assertNotIn('sobra', self.revisar(self.todos(), {'descubrir.yml': 'disabled_manually'})[1].split('\n\n')[1])

    def test_a_missing_workflow_or_a_repo_that_is_not_owner_name_stops_it(self):
        for repo in ('o/r/../x', 'o/r\n@x', 'evil.example/o/r'):
            self.assertRaises(ValueError, self.revisar, self.todos(), repo=repo)
        self.assertRaises(KeyError, self.revisar, {k: v for k, v in self.todos().items() if k != 'sondeo.yml'})
        self.assertRaises(KeyError, vigia.revisar, self.todos(), {'sondeo.yml': ACTIVO}, AHORA, 'o/r')

    def test_a_state_file_missing_unreadable_or_unknown_stops_it_with_nothing_written(self):
        t = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, t)
        for n, _ in vigia.VIGILADOS:
            (t / f'{n}.json').write_text(json.dumps({'workflow_runs': [run(1, ahora=datetime.now(timezone.utc))]}))
            (t / f'{n}.estado.json').write_text(json.dumps(ACTIVO))
        salidas = ('vigia.md', 'nueva.json', 'cuerpo.json', 'cierre.json')
        for roto in ('{"state": "active"}', None, '{', '[]', '{"state": "disabled"}', '{"state": null}'):
            for x in salidas:
                (t / x).unlink(missing_ok=True)
            f = t / 'descubrir.yml.estado.json'
            f.unlink(missing_ok=True) if roto is None else f.write_text(roto)
            out = io.StringIO()
            with redirect_stdout(out):
                if roto == '{"state": "active"}':  # the same files whole: decided and written
                    vigia.main(['decidir', '--repo', 'o/r', '--dir', str(t)])
                else:
                    self.assertRaises((OSError, ValueError), vigia.main, ['decidir', '--repo', 'o/r', '--dir', str(t)])
            ok = roto == '{"state": "active"}'
            self.assertEqual((out.getvalue(), [x for x in salidas if (t / x).exists()]),
                             ('alerta=false\n', list(salidas)) if ok else ('', []), roto)


class Issue(unittest.TestCase):
    def test_only_the_open_issue_this_workflow_opened_with_the_exact_title_is_chosen(self):
        self.assertEqual(vigia.elegir_issue([issue(3, 'alguien'), issue(9), issue(7)]), 7)
        for i in (issue(3, 'alguien'), issue(4, pull_request={}), issue(5, title='Vigia de produccion'),
                  issue(6, title=vigia.TITULO + ' '), issue(8, state='closed'), issue('7')):
            self.assertIsNone(vigia.elegir_issue([i]), i)
        self.assertRaises(ValueError, vigia.elegir_issue, {'items': []})

    def test_every_page_is_read_before_choosing_and_too_many_or_an_unreadable_one_stops_it(self):
        llena = [issue(1000 + k, title='otra') for k in range(vigia.POR_PAGINA)]
        self.assertEqual([vigia.issue_de(p) for p in ([llena], [llena, [issue(7)]], [llena, []], [llena] * (vigia.PAGINAS - 1))],
                         ['mas', '7', '', 'mas'])
        for malas in ([], [llena, {'message': 'Server Error'}], [llena] * vigia.PAGINAS):
            self.assertRaises(ValueError, vigia.issue_de, malas)


class Workflow(unittest.TestCase):
    def test_the_watched_workflows_and_their_caps_are_fixed_and_start_only_by_schedule_or_dispatch(self):
        self.assertEqual(dict(vigia.VIGILADOS), {'catalog-mx.yml': 2, 'texto-mx.yml': 8, 'indicadores-mx.yml': 8,
                                                 'sondeo.yml': 8, 'descubrir.yml': 2, 'sondeo-inegi.yml': 35})
        for n, _ in vigia.VIGILADOS:
            doc = yaml.safe_load((ROOT / '.github' / 'workflows' / n).read_text(encoding='utf-8'))
            self.assertLessEqual(set(doc.get('on') or doc[True]), set(vigia.EVENTOS), n)

    def test_only_the_owners_list_in_the_script_pauses_a_workflow_and_each_entry_says_when_and_why(self):
        self.assertEqual(vigia.PAUSADOS, {'descubrir.yml': ('2026-11-03', 'decisión del dueño; reabre cuando un pedido de requests/ lo necesite')})
        for n, (fecha, motivo) in vigia.PAUSADOS.items():
            self.assertIn(n, dict(vigia.VIGILADOS))
            self.assertEqual((datetime.strptime(fecha, '%Y-%m-%d').strftime('%Y-%m-%d'), bool(motivo.strip())), (fecha, True))

    def test_mains_code_only_daily_or_by_dispatch_reading_runs_and_writing_issues_and_nothing_else(self):
        on = WF.get('on') or WF[True]
        self.assertEqual(set(on), {'schedule', 'workflow_dispatch'})
        minuto, hora, *resto = on['schedule'][0]['cron'].split()
        self.assertEqual((resto, int(minuto) % 5 != 0), (['*', '*', '*'], True))  # daily, at a minute nobody else picks
        self.assertEqual(JOB['if'], "github.ref == 'refs/heads/main'")
        self.assertEqual(JOB['steps'][0]['with'], {'ref': 'main', 'persist-credentials': False})
        self.assertEqual(WF['concurrency'], {'group': 'vigia', 'cancel-in-progress': False})
        # with permissions set, any left out is none: contents read is what lets the checkout of main read the code
        self.assertEqual((WF['permissions'], JOB['permissions']), ({}, {'actions': 'read', 'contents': 'read', 'issues': 'write'}))
        self.assertNotIn('secrets.', TEXT)
        for s in JOB['steps']:
            self.assertNotIn('${{', s.get('run', ''))
            for line in s.get('run', '').splitlines():
                if 'python' in line:
                    self.assertIn('python3 -I scripts/vigia.py ', line)
        self.assertEqual((JOB['steps'][-1]['if'], JOB['steps'][-1]['run']), ("steps.decidir.outputs.alerta != 'false'", 'exit 1'))


GH = """import json, os, sys
from urllib.parse import parse_qs, urlsplit
a = sys.argv[1:]
metodo, url = (a[2], a[3]) if a[1] == '-X' else ('GET', a[1])
ruta, q = urlsplit(url).path.split('/'), parse_qs(urlsplit(url).query)
carga = json.load(open(a[a.index('--input') + 1])) if '--input' in a else {}
campos = dict(a[k + 1].split('=') for k in range(len(a)) if a[k] == '-f')
with open(os.environ['STUB_LOG'], 'a') as f:
    f.write(json.dumps([metodo, url, carga or campos]) + '\\n')
issues = json.load(open(os.environ['STUB_ISSUES']))
if ruta[3:5] == ['actions', 'workflows']:  # a workflow's runs, or the workflow itself with its state
    print(open(os.path.join(os.environ['STUB_RUNS'], ruta[5] + ('.json' if ruta[6:] == ['runs'] else '.estado.json'))).read())
elif metodo == 'GET':  # every open issue, newest first as the API answers; the page in STUB_FALLA fails as gh does
    if q['page'] == [os.environ['STUB_FALLA']]:
        print('{"message": "Server Error"}')
        sys.exit(1)
    k, n = int(q['page'][0]), int(q['per_page'][0])
    abiertas = [i for i in issues if i['state'] == 'open']  # the API's creator filter is not relied on
    print(json.dumps(sorted(abiertas, key=lambda i: -i['number'])[(k - 1) * n:k * n]))
elif metodo == 'POST' and len(ruta) == 4:
    issues.append({'number': max([i['number'] for i in issues], default=0) + 1, 'state': 'open',
                   'user': {'login': 'github-actions[bot]'}, **carga})
elif metodo == 'PATCH':
    next(i for i in issues if i['number'] == int(ruta[4])).update(carga or campos)
json.dump(issues, open(os.environ['STUB_ISSUES'], 'w'))
"""
RUNS = [u for n, _ in vigia.VIGILADOS
        for u in (f'repos/o/r/actions/workflows/{n}/runs?branch=main&per_page=20', f'repos/o/r/actions/workflows/{n}')]
PAGINA = 'repos/o/r/issues?state=open&creator=github-actions%5Bbot%5D&per_page=100&page={}'


class Pasos(unittest.TestCase):
    """The workflow's own steps, in order, against a stub gh that serves the runs and keeps the repo's issues."""

    def setUp(self):
        t = self.t = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, t)
        (t / 'bin').mkdir(); (t / 'runs').mkdir(); (t / 'gh.py').write_text(GH)
        for name, cmd in (('gh', f'"{sys.executable}" "{t / "gh.py"}"'), ('python3', f'"{sys.executable}"')):
            (t / 'bin' / name).write_text(f'#!/bin/sh\nexec {cmd} "$@"\n'); (t / 'bin' / name).chmod(0o755)
        self.poner([])

    def poner(self, issues):
        (self.t / 'issues.json').write_text(json.dumps(issues))

    def abiertas(self):
        return [i['number'] for i in json.loads((self.t / 'issues.json').read_text()) if i['state'] == 'open']

    def correr(self, rojo, alerta=None, falla=0, estados=()):
        """One run on a fresh runner; the calls that write, (method, path, payload). Only an unreadable page fails a step."""
        t, ahora = self.t, datetime.now(timezone.utc)
        for n, _ in vigia.VIGILADOS:
            runs = [run(2, 'failure', ahora=ahora)] if n in rojo else [run(1, ahora=ahora)]
            (t / 'runs' / f'{n}.json').write_text(json.dumps({'workflow_runs': runs}))
            (t / 'runs' / f'{n}.estado.json').write_text(json.dumps({'id': 9, 'name': '@evil', 'state': dict(estados).get(n, 'active')}))
        shutil.rmtree(t / 'vigia', ignore_errors=True)
        for f in ('log', 'out', 'summary'):
            (t / f).write_text('')
        env = {'PATH': f'{t / "bin"}:{os.environ["PATH"]}', 'HOME': str(t), 'RUNNER_TEMP': str(t), 'REPO': 'o/r',
               'GH_TOKEN': 'x', 'GITHUB_OUTPUT': str(t / 'out'), 'GITHUB_STEP_SUMMARY': str(t / 'summary'),
               'STUB_LOG': str(t / 'log'), 'STUB_RUNS': str(t / 'runs'), 'STUB_ISSUES': str(t / 'issues.json'), 'STUB_FALLA': str(falla)}
        for s in JOB['steps'][1:-1]:
            if 'ALERTA' in s.get('env', {}):
                env['ALERTA'] = (t / 'out').read_text().strip().split('=')[1] if alerta is None else alerta
            r = subprocess.run(['bash', '-e', '-c', s['run']], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode != 0, falla > 0 and 'ALERTA' in s['env'], r.stderr)
        self.assertIn('| `catalog-mx.yml` |', (t / 'summary').read_text())
        log = [json.loads(x) for x in (t / 'log').read_text().splitlines()]
        self.lecturas = [u for m, u, _ in log if m == 'GET']
        return [(m, u, c) for m, u, c in log if m != 'GET']

    def test_red_opens_the_issue_or_updates_ours_and_never_touches_an_outsiders(self):
        self.assertEqual(self.correr({'catalog-mx.yml'}), [('POST', 'repos/o/r/issues', {'title': vigia.TITULO, 'body': mock.ANY})])
        self.assertEqual(self.lecturas, RUNS + [PAGINA.format(1)])
        self.poner([issue(3, 'alguien'), issue(7)])
        escritas = self.correr({'texto-mx.yml'})
        self.assertEqual(escritas, [('PATCH', 'repos/o/r/issues/7', {'body': mock.ANY})])
        self.assertIn('| `texto-mx.yml` | rojo |', escritas[0][2]['body'])

    def test_all_well_closes_ours_with_a_comment_and_an_undecided_run_writes_nothing(self):
        self.assertEqual(self.correr(set()), [])
        self.poner([issue(7)])
        self.assertEqual(self.correr(set(), alerta=''), [])
        escritas = self.correr(set())
        self.assertEqual(escritas, [('POST', 'repos/o/r/issues/7/comments', {'body': mock.ANY}),
                                    ('PATCH', 'repos/o/r/issues/7', {'state': 'closed', 'state_reason': 'completed'})])
        self.assertTrue(escritas[0][2]['body'].startswith('Todo en orden'))

    def test_one_open_issue_per_state_not_per_run(self):
        """The owner's order: red twice is one issue, all well closes it, red again opens one; never two open."""
        for rojo, metodos, abiertas in (({'catalog-mx.yml'}, ['POST'], [1]), ({'sondeo.yml'}, ['PATCH'], [1]),
                                        (set(), ['POST', 'PATCH'], []), ({'descubrir.yml'}, ['POST'], [2])):
            self.assertEqual(([m for m, _, _ in self.correr(rojo)], self.abiertas()), (metodos, abiertas), rojo)

    def test_a_listed_paused_workflow_with_the_rest_well_closes_ours_and_one_disabled_off_the_list_opens_one(self):
        pausa = {'descubrir.yml': 'disabled_manually'}
        self.assertEqual(self.correr({'descubrir.yml'}, estados=pausa), [])  # its last run failed: no issue opened
        self.assertEqual(self.lecturas, RUNS + [PAGINA.format(1)])
        self.poner([issue(7)])
        escritas = self.correr({'descubrir.yml'}, estados=pausa)
        self.assertEqual([(m, u) for m, u, _ in escritas], [('POST', 'repos/o/r/issues/7/comments'), ('PATCH', 'repos/o/r/issues/7')])
        self.assertIn('| `descubrir.yml` | pausado |', escritas[0][2]['body'])
        for s in ('disabled_manually', 'disabled_inactivity'):  # texto-mx failed and was disabled, by hand or by GitHub
            self.poner([])
            escritas = self.correr({'texto-mx.yml'}, estados={**pausa, 'texto-mx.yml': s})
            self.assertEqual(escritas, [('POST', 'repos/o/r/issues', {'title': vigia.TITULO, 'body': mock.ANY})], s)
            self.assertIn('| `texto-mx.yml` | apagado |', escritas[0][2]['body'])

    def test_every_page_of_open_issues_is_read_first_and_an_unreadable_page_writes_nothing(self):
        otras = [issue(n, title=f'otra {n}') for n in range(8, 160)]  # 152 newer issues of the bot: ours is on page 2
        self.poner([issue(7)] + otras)
        self.assertEqual(self.correr({'catalog-mx.yml'}), [('PATCH', 'repos/o/r/issues/7', {'body': mock.ANY})])
        self.assertEqual(self.lecturas, RUNS + [PAGINA.format(1), PAGINA.format(2)])
        self.assertEqual(self.correr({'catalog-mx.yml'}, falla=2), [])  # ours on the unreadable page: no second issue
        self.poner([issue(200)] + otras)
        self.assertEqual(self.correr(set(), falla=2), [])  # ours on page 1 and page 2 unreadable: not closed
        self.assertEqual(sorted(self.abiertas()), [*range(8, 160), 200])

if __name__ == '__main__':
    unittest.main()
