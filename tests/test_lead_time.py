"""scripts/lead_time.py with fixed timestamps; the rules it enforces are listed in docs/medicion/README.md."""
import io
import json
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts import lead_time as lt

ROOT = Path(__file__).resolve().parents[1]
HEAD, VIEJO = 'a' * 40, 'b' * 40
BOT = {'login': 'github-actions'}


def c(body, t, author=BOT):
    return {'author': author, 'body': body, 'createdAt': t}


def job(name, end, status='completed'):
    return {'name': name, 'status': status, 'completed_at': end}


def intento(start, jobs, status='completed', total=None, run_id=1, attempt=1):
    return {'run_id': run_id, 'run_attempt': attempt, 'status': status, 'run_started_at': start,
            'jobs_total': len(jobs) if total is None else total, 'jobs': jobs}


def pr(n=1, comments=(), head=HEAD, commits=None, created='2026-11-01T00:00:00Z', merged='2026-11-01T10:00:00Z'):
    return {'number': n, 'createdAt': created, 'mergedAt': merged, 'headRefOid': head,
            'additions': 30, 'deletions': 5, 'comments': list(comments),
            'commits': commits if commits is not None else [{'oid': VIEJO, 'committedDate': '2026-11-01T00:10:00Z'},
                                                            {'oid': HEAD, 'committedDate': '2026-11-01T04:00:00Z'}]}


DOS_PASS = [c(f'AUDIT VERDICT: REVISE {VIEJO}\nbody', '2026-11-01T02:00:00Z'),
            c(f'GPT REVIEW: REVISE {VIEJO}', '2026-11-01T02:30:00Z'),
            c(f'AUDIT VERDICT: PASS {HEAD}\nbody', '2026-11-01T05:00:00Z'),
            c(f'GPT REVIEW: PASS {HEAD}', '2026-11-01T06:00:00Z')]
# ci.yml attempt started 04:01; checks and two shards, the later finishing 05:01: CI ends before both PASS (06:00)
JOBS = [job('checks', '2026-11-01T04:04:00Z'), job('mutation (0)', '2026-11-01T04:40:00Z'), job('mutation (1)', '2026-11-01T05:01:00Z')]
CI_OK = [intento('2026-11-01T04:01:00Z', JOBS)]


class Medir(unittest.TestCase):
    def test_each_component_from_its_two_timestamps(self):
        f = lt.medir(pr(comments=DOS_PASS), CI_OK)
        self.assertEqual((f['total'], f['antes_head'], f['ci'], f['auditoria'], f['espera_ci'], f['espera_dueno']),
                         (10.0, 4.0, 1.0, 2.0, 0.0, 4.0))
        self.assertEqual((f['revise'], f['lineas']), ({'claude': 1, 'gpt': 1}, 35))
        self.assertEqual(lt.medir(pr(comments=list(reversed(DOS_PASS))), CI_OK)['espera_dueno'], 4.0)  # the later PASS starts it
        f = lt.medir(pr(comments=DOS_PASS, created='2026-11-01T04:30:00Z'), CI_OK)
        self.assertEqual((f['antes_head'], f['auditoria'], f['total']), (0.0, 1.5, 5.5))

    def test_a_ci_that_ends_after_both_passes_is_its_own_wait_not_the_owners(self):
        late = [intento('2026-11-01T04:01:00Z', JOBS[:2] + [job('mutation (1)', '2026-11-01T07:30:00Z')])]
        f = lt.medir(pr(comments=DOS_PASS), late)
        self.assertEqual((f['auditoria'], f['espera_ci'], f['espera_dueno']), (2.0, 1.5, 2.5))
        # the attempt itself lists the shards it runs: a trailing one still queued is seen, whatever finished before it
        pending = [intento('2026-11-01T04:01:00Z', JOBS + [job('mutation (2)', None, 'queued')], status='in_progress')]
        f = lt.medir(pr(comments=DOS_PASS), pending)
        self.assertEqual((f['ci'], f['espera_ci'], f['espera_dueno'], f['ci_completo']), (None, None, None, False))
        self.assertEqual(f['auditoria'], 2.0)
        self.assertIsNone(lt.medir(pr(comments=DOS_PASS), [intento('2026-11-01T04:01:00Z', JOBS + [job('mutation (2)', None, 'queued')])])['ci'])

    def test_a_job_listing_shorter_than_its_total_is_incomplete(self):
        self.assertIsNone(lt.medir(pr(comments=DOS_PASS), [intento('2026-11-01T04:01:00Z', JOBS, total=9)])['ci'])  # a cut page
        self.assertIsNone(lt.medir(pr(comments=DOS_PASS), [intento('2026-11-01T04:01:00Z', [])])['ci'])
        self.assertIsNone(lt.medir(pr(comments=DOS_PASS), [intento('2026-11-01T04:01:00Z', JOBS, status='in_progress')])['ci'])  # run not done
        self.assertIsNone(lt.medir(pr(comments=DOS_PASS), [])['ci'])
        after = [intento('2026-11-01T04:01:00Z', JOBS[:2] + [job('mutation (1)', '2026-11-01T11:00:00Z')])]  # job ends after merge
        self.assertEqual((lt.medir(pr(comments=DOS_PASS), after)['ci'], lt.medir(pr(comments=DOS_PASS), after)['espera_dueno']), (None, None))

    def test_the_last_attempt_started_before_the_merge_is_the_one_measured(self):
        primero = intento('2026-11-01T04:01:00Z', JOBS[:2] + [job('mutation (1)', None, 'cancelled')], status='in_progress')
        rerun = intento('2026-11-01T05:30:00Z', [job(j['name'], '2026-11-01T05:50:00Z') for j in JOBS], attempt=2)
        self.assertEqual(lt.medir(pr(comments=DOS_PASS), [rerun, primero])['ci'], round(20 / 60, 2))
        tarde = intento('2026-11-02T08:00:00Z', [job(j['name'], '2026-11-02T09:00:00Z') for j in JOBS], attempt=3)
        self.assertEqual(lt.medir(pr(comments=DOS_PASS), [rerun, tarde, primero])['ci'], round(20 / 60, 2))

    def test_a_verdict_after_the_merge_does_not_count(self):
        late = DOS_PASS[:3] + [c(f'GPT REVIEW: PASS {HEAD}', '2026-11-01T12:00:00Z'), c(f'GPT REVIEW: REVISE {HEAD}', '2026-11-01T13:00:00Z')]
        f = lt.medir(pr(comments=late), CI_OK)
        self.assertEqual((f['dos_pass'], f['espera_dueno'], f['revise']['gpt']), (False, None, 1))
        old = [c(f'AUDIT VERDICT: PASS {VIEJO}', '2026-11-01T01:00:00Z'), c(f'GPT REVIEW: PASS {HEAD}', '2026-11-01T06:00:00Z')]
        self.assertEqual(lt.medir(pr(comments=old), CI_OK)['dos_pass'], False)  # a PASS on an older head is not one on the merged

    def test_a_later_revise_on_the_head_cancels_its_pass_and_a_repeated_pass_does_not_move_it(self):
        again = DOS_PASS + [c(f'GPT REVIEW: PASS {HEAD}', '2026-11-01T07:00:00Z')]
        self.assertEqual(lt.medir(pr(comments=again), CI_OK)['espera_dueno'], 4.0)
        self.assertFalse(lt.medir(pr(comments=again + [c(f'GPT REVIEW: REVISE {HEAD}', '2026-11-01T08:00:00Z')]), CI_OK)['dos_pass'])

    def test_a_verdict_not_posted_by_github_actions_is_ignored(self):
        fake = [c(f'AUDIT VERDICT: PASS {HEAD}', '2026-11-01T05:00:00Z', {'login': 'someone'}),
                c(f'GPT REVIEW: PASS {HEAD}', '2026-11-01T06:00:00Z')]
        self.assertIsNone(lt.medir(pr(comments=fake), CI_OK)['espera_dueno'])
        self.assertEqual(lt.medir(pr(comments=[c(f'AUDIT VERDICT: REVISE {HEAD}', '2026-11-01T05:00:00Z', None)]), CI_OK)['revise']['claude'], 0)
        loose = [c(f'note\nAUDIT VERDICT: PASS {HEAD}', '2026-11-01T05:00:00Z'), c(f'AUDIT VERDICT: PASS {HEAD} ok', '2026-11-01T05:00:00Z'),
                 c(f'GPT REVIEW: PASS {HEAD}', '2026-11-01T06:00:00Z')]
        self.assertIsNone(lt.medir(pr(comments=loose), CI_OK)['espera_dueno'])
        crlf = [c(f'AUDIT VERDICT: PASS {HEAD}\r\nbody', '2026-11-01T05:00:00Z'), c(f'GPT REVIEW: PASS {HEAD}', '2026-11-01T06:00:00Z')]
        self.assertEqual(lt.medir(pr(comments=crlf), CI_OK)['espera_dueno'], 4.0)

    def test_without_the_head_commit_there_is_no_before_head_nor_audit_time(self):
        f = lt.medir(pr(comments=DOS_PASS, commits=[]), CI_OK)
        self.assertEqual((f['antes_head'], f['auditoria'], f['espera_dueno']), (None, None, 4.0))
        with self.assertRaises(ValueError):
            lt.medir(pr(head='main'), CI_OK)


class Muestra(unittest.TestCase):
    def test_the_sample_is_the_last_merges_not_the_last_openings(self):
        viejo = pr(1, created='2026-10-01T00:00:00Z', merged='2026-11-05T00:00:00Z')
        nuevo = pr(2, created='2026-11-04T00:00:00Z', merged='2026-11-04T01:00:00Z')
        otro = pr(3, created='2026-11-03T00:00:00Z', merged='2026-11-03T01:00:00Z')
        self.assertEqual([p['number'] for p in lt.ultimos([nuevo, otro, viejo], 2)], [1, 2])
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'prs.json').write_text(json.dumps([pr(i, head=f'{i:040x}') for i in range(lt.LIMITE_LISTA)]), encoding='utf-8')
            with self.assertRaises(SystemExit) as e:
                lt.leer(Path(d, 'prs.json'), Path(d))
        self.assertIn('limit', str(e.exception.code))


class Resumen(unittest.TestCase):
    def test_medians_p90_and_the_prs_merged_without_both_passes_or_a_whole_ci(self):
        filas = [lt.medir(pr(1, DOS_PASS), CI_OK), lt.medir(pr(2), CI_OK), lt.medir(pr(3, DOS_PASS + DOS_PASS[:1]), [])]
        r = lt.resumen(filas)
        self.assertEqual((r['prs'], r['sin_dos_pass'], r['ci_incompleto']), (3, [2], [3]))
        self.assertEqual(r['espera_dueno'], {'n': 1, 'mediana': 4.0, 'p90': 4.0})
        self.assertEqual(r['revise'], {'total': 5, 'mediana': 2, 'prs_con_2_o_mas': 2})
        self.assertEqual(r['ci'], {'n': 2, 'mediana': 1.0, 'p90': 1.0})
        self.assertEqual((lt._p90(list(range(1, 11))), lt._p90([5]), lt._p90(list(range(1, 31)))), (9, 5, 27))
        self.assertEqual(lt.fila_estado(lt.resumen([lt.medir(pr(1, DOS_PASS), CI_OK)]), '2026-10-20', '2026-11-03'),
                         '| 2026-10-20 → 2026-11-03 | 1 | 10.0 (10.0) | 4.0 (4.0) | 1.0 (1.0) | 2.0 (2.0) | 0.0 (0.0) | 4.0 (4.0) | 2 (1 PR con 2+) |')


class Datos(unittest.TestCase):
    def escribir(self, d, corridas=True):
        Path(d, 'prs.json').write_text(json.dumps([pr(7, DOS_PASS)]), encoding='utf-8')
        Path(d, 'corridas').mkdir()
        if corridas:
            Path(d, 'corridas', f'{HEAD}.json').write_text(json.dumps(CI_OK), encoding='utf-8')

    def test_gh_output_and_its_trimmed_data_file_give_the_same_measure(self):
        with tempfile.TemporaryDirectory() as d:
            self.escribir(d)
            out = io.StringIO()
            with redirect_stdout(out):
                lt.main([str(Path(d, 'prs.json')), '--corridas', str(Path(d, 'corridas')), '--recortar', str(Path(d, 'r.json')),
                         '--capturado', '2026-11-03T23:00:00Z'])
            datos = json.loads(Path(d, 'r.json').read_text(encoding='utf-8'))
            out2 = io.StringIO()
            with redirect_stdout(out2):
                lt.main([str(Path(d, 'r.json'))])
        self.assertEqual(json.loads(out.getvalue()), json.loads(out2.getvalue()))
        self.assertEqual((datos['capturado'], datos['listados']), ('2026-11-03T23:00:00Z', 1))
        self.assertEqual(datos['prs'][0]['comments'][0]['body'], f'AUDIT VERDICT: REVISE {VIEJO}')  # first line only
        self.assertTrue(any(x.startswith('gh pr list') for x in datos['comandos']))
        self.assertEqual([c['oid'] for c in datos['prs'][0]['commits']], [HEAD])

    def test_trimming_keeps_only_verdict_lines_but_from_every_author(self):
        otros = DOS_PASS + [c('just a note', '2026-11-01T03:00:00Z'), c(f'AUDIT VERDICT: PASS {HEAD}', '2026-11-01T05:30:00Z', {'login': 'x'})]
        d = lt.recortar([pr(1, otros)], {HEAD: CI_OK}, '2026-11-03T23:00:00Z', 1)
        self.assertEqual(len(d['prs'][0]['comments']), 5)
        self.assertEqual(lt.medir(d['prs'][0], d['prs'][0]['corridas']), lt.medir(pr(1, otros), CI_OK))
        texto = lt.escribir(d)
        self.assertEqual(json.loads(texto), d)
        self.assertEqual(texto.count('\n'), 3)  # header line, one line per PR, closing line

    def test_a_missing_attempts_file_is_refused_not_read_as_no_data(self):
        with tempfile.TemporaryDirectory() as d:
            self.escribir(d, corridas=False)
            with self.assertRaises(SystemExit) as e:
                lt.main([str(Path(d, 'prs.json')), '--corridas', str(Path(d, 'corridas'))])
            with self.assertRaises(SystemExit):
                lt.leer(Path(d, 'prs.json'))  # gh output without --corridas
            Path(d, 'corridas', f'{HEAD}.json').write_text(json.dumps(CI_OK), encoding='utf-8')
            with self.assertRaises(SystemExit):  # trimming needs its capture time
                lt.main([str(Path(d, 'prs.json')), '--corridas', str(Path(d, 'corridas')), '--recortar', str(Path(d, 'r.json'))])
        self.assertIn(HEAD, str(e.exception.code))

    def test_every_lead_time_row_in_estado_is_recomputed_from_its_committed_data(self):
        estado = (ROOT / 'docs' / 'ESTADO.md').read_text(encoding='utf-8')
        archivos = sorted((ROOT / 'docs' / 'medicion').glob('lead-time-*.json'))
        self.assertTrue(archivos)
        calculos = [lt.calcular(*lt.leer(f)[:2]) for f in archivos]
        for k in calculos:
            self.assertIn(k['fila'], estado)
            for f in k['prs']:  # an impossible chronology would show as a negative duration
                self.assertTrue(all(f[x] is None or f[x] >= 0 for x in lt.COMPONENTES), f['pr'])
        en_estado = [l for l in estado.splitlines() if re.match(r'\| \d{4}-\d\d-\d\d → \d{4}-\d\d-\d\d \| \d+ \|', l)]
        self.assertEqual(sorted(en_estado), sorted(k['fila'] for k in calculos))  # no row in ESTADO without its data


if __name__ == '__main__':
    unittest.main()
