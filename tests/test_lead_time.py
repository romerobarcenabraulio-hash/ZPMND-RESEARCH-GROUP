"""scripts/lead_time.py: each component from fixed timestamps; verdicts only from github-actions naming the merged head;
CI only when whole at the merge; nothing after the merge counts; docs/ESTADO.md's row is recomputed from its data file."""
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


def run(name, start, end, status='completed', id=1):
    return {'id': id, 'name': name, 'status': status, 'started_at': start, 'completed_at': end}


def pr(n=1, comments=(), head=HEAD, commits=None, created='2026-11-01T00:00:00Z'):
    return {'number': n, 'createdAt': created, 'mergedAt': '2026-11-01T10:00:00Z', 'headRefOid': head,
            'additions': 30, 'deletions': 5, 'comments': list(comments),
            'commits': commits if commits is not None else [{'oid': VIEJO, 'committedDate': '2026-11-01T00:10:00Z'},
                                                            {'oid': HEAD, 'committedDate': '2026-11-01T04:00:00Z'}]}


DOS_PASS = [c(f'AUDIT VERDICT: REVISE {VIEJO}\nbody', '2026-11-01T02:00:00Z'),
            c(f'GPT REVIEW: REVISE {VIEJO}', '2026-11-01T02:30:00Z'),
            c(f'AUDIT VERDICT: PASS {HEAD}\nbody', '2026-11-01T05:00:00Z'),
            c(f'GPT REVIEW: PASS {HEAD}', '2026-11-01T06:00:00Z')]
# checks 04:01-04:04; mutation shards 0 and 1, the later finishing 05:01: CI ends before both PASS (06:00)
CI_OK = [run('checks', '2026-11-01T04:01:00Z', '2026-11-01T04:04:00Z', id=1),
         run('mutation (0)', '2026-11-01T04:01:00Z', '2026-11-01T04:40:00Z', id=2),
         run('mutation (1)', '2026-11-01T04:01:00Z', '2026-11-01T05:01:00Z', id=3),
         run('audit', '2026-11-01T04:00:00Z', '2026-11-01T09:00:00Z', id=4)]


class Medir(unittest.TestCase):
    def test_each_component_from_its_two_timestamps(self):
        f = lt.medir(pr(comments=DOS_PASS), CI_OK)
        self.assertEqual((f['total'], f['antes_head'], f['ci'], f['auditoria'], f['espera_ci'], f['espera_dueno']),
                         (10.0, 4.0, 1.0, 2.0, 0.0, 4.0))
        self.assertEqual(f['revise'], {'claude': 1, 'gpt': 1})
        self.assertEqual(f['lineas'], 35)

    def test_a_ci_that_ends_after_both_passes_is_its_own_wait_not_the_owners(self):
        late = CI_OK[:2] + [run('mutation (1)', '2026-11-01T04:01:00Z', '2026-11-01T07:30:00Z', id=3)]
        f = lt.medir(pr(comments=DOS_PASS), late)
        self.assertEqual((f['auditoria'], f['espera_ci'], f['espera_dueno']), (2.0, 1.5, 2.5))

    def test_a_pending_shard_makes_the_ci_incomplete_never_a_shorter_one(self):
        pending = CI_OK[:2] + [run('mutation (1)', '2026-11-01T04:01:00Z', None, status='in_progress', id=3)]
        f = lt.medir(pr(comments=DOS_PASS), pending)
        self.assertEqual((f['ci'], f['espera_ci'], f['espera_dueno'], f['ci_completo']), (None, None, None, False))
        self.assertEqual(f['auditoria'], 2.0)

    def test_a_missing_shard_or_a_missing_checks_job_makes_the_ci_incomplete(self):
        self.assertIsNone(lt.medir(pr(comments=DOS_PASS), [CI_OK[0], CI_OK[2]])['ci'])  # shard 1 without shard 0
        self.assertIsNone(lt.medir(pr(comments=DOS_PASS), CI_OK[1:])['ci'])  # no checks
        self.assertIsNone(lt.medir(pr(comments=DOS_PASS), [CI_OK[0]])['ci'])  # no mutation at all
        self.assertIsNone(lt.medir(pr(comments=DOS_PASS), [])['ci'])

    def test_a_rerun_replaces_the_run_it_repeats(self):
        rerun = [run('mutation (1)', '2026-11-01T04:01:00Z', None, status='in_progress', id=3),
                 run('mutation (1)', '2026-11-01T05:30:00Z', '2026-11-01T05:50:00Z', id=9)] + CI_OK[:2]
        self.assertEqual(lt.medir(pr(comments=DOS_PASS), rerun)['ci'], round(109 / 60, 2))

    def test_a_ci_run_or_rerun_after_the_merge_does_not_count(self):
        after = CI_OK + [run('mutation (1)', '2026-11-02T08:00:00Z', '2026-11-02T09:00:00Z', id=20)]
        self.assertEqual(lt.medir(pr(comments=DOS_PASS), after)['espera_dueno'], 4.0)
        ends_after = CI_OK[:2] + [run('mutation (1)', '2026-11-01T04:01:00Z', '2026-11-01T11:00:00Z', id=3)]
        f = lt.medir(pr(comments=DOS_PASS), ends_after)
        self.assertEqual((f['ci'], f['espera_dueno']), (None, None))

    def test_a_verdict_after_the_merge_does_not_count(self):
        late = DOS_PASS[:3] + [c(f'GPT REVIEW: PASS {HEAD}', '2026-11-01T12:00:00Z'), c(f'GPT REVIEW: REVISE {HEAD}', '2026-11-01T13:00:00Z')]
        f = lt.medir(pr(comments=late), CI_OK)
        self.assertEqual((f['dos_pass'], f['espera_dueno'], f['revise']['gpt']), (False, None, 1))

    def test_a_head_older_than_the_pr_counts_from_the_opening(self):
        f = lt.medir(pr(comments=DOS_PASS, created='2026-11-01T04:30:00Z'), CI_OK)
        self.assertEqual((f['antes_head'], f['auditoria'], f['total']), (0.0, 1.5, 5.5))

    def test_a_pass_on_an_older_head_is_not_a_pass_of_the_merged_one(self):
        old = [c(f'AUDIT VERDICT: PASS {VIEJO}', '2026-11-01T01:00:00Z'), c(f'GPT REVIEW: PASS {HEAD}', '2026-11-01T06:00:00Z')]
        f = lt.medir(pr(comments=old), CI_OK)
        self.assertEqual((f['espera_dueno'], f['auditoria'], f['dos_pass']), (None, None, False))

    def test_the_later_of_the_two_passes_starts_the_owner_wait(self):
        self.assertEqual(lt.medir(pr(comments=list(reversed(DOS_PASS))), CI_OK)['espera_dueno'], 4.0)

    def test_a_verdict_not_posted_by_github_actions_is_ignored(self):
        fake = [c(f'AUDIT VERDICT: PASS {HEAD}', '2026-11-01T05:00:00Z', {'login': 'someone'}),
                c(f'GPT REVIEW: PASS {HEAD}', '2026-11-01T06:00:00Z')]
        self.assertIsNone(lt.medir(pr(comments=fake), CI_OK)['espera_dueno'])
        self.assertEqual(lt.medir(pr(comments=[c(f'AUDIT VERDICT: REVISE {HEAD}', '2026-11-01T05:00:00Z', None)]), CI_OK)['revise']['claude'], 0)

    def test_only_the_first_line_in_its_exact_form_is_a_verdict(self):
        loose = [c(f'note\nAUDIT VERDICT: PASS {HEAD}', '2026-11-01T05:00:00Z'), c(f'AUDIT VERDICT: PASS {HEAD} ok', '2026-11-01T05:00:00Z'),
                 c(f'GPT REVIEW: PASS {HEAD}', '2026-11-01T06:00:00Z')]
        self.assertIsNone(lt.medir(pr(comments=loose), CI_OK)['espera_dueno'])
        crlf = [c(f'AUDIT VERDICT: PASS {HEAD}\r\nbody', '2026-11-01T05:00:00Z'), c(f'GPT REVIEW: PASS {HEAD}', '2026-11-01T06:00:00Z')]
        self.assertEqual(lt.medir(pr(comments=crlf), CI_OK)['espera_dueno'], 4.0)

    def test_without_the_head_commit_there_is_no_before_head_nor_audit_time(self):
        f = lt.medir(pr(comments=DOS_PASS, commits=[]), CI_OK)
        self.assertEqual((f['antes_head'], f['auditoria'], f['espera_dueno']), (None, None, 4.0))

    def test_a_head_that_is_not_a_sha_is_refused(self):
        with self.assertRaises(ValueError):
            lt.medir(pr(head='main'), CI_OK)


class Resumen(unittest.TestCase):
    def test_medians_p90_and_the_prs_merged_without_both_passes_or_a_whole_ci(self):
        filas = [lt.medir(pr(1, DOS_PASS), CI_OK), lt.medir(pr(2), CI_OK), lt.medir(pr(3, DOS_PASS + DOS_PASS[:1]), [])]
        r = lt.resumen(filas)
        self.assertEqual((r['prs'], r['sin_dos_pass'], r['ci_incompleto']), (3, [2], [3]))
        self.assertEqual(r['espera_dueno'], {'n': 1, 'mediana': 4.0, 'p90': 4.0})
        self.assertEqual(r['revise'], {'total': 5, 'mediana': 2, 'prs_con_2_o_mas': 2})
        self.assertEqual(r['ci'], {'n': 2, 'mediana': 1.0, 'p90': 1.0})

    def test_p90_is_the_nearest_rank(self):
        self.assertEqual((lt._p90(list(range(1, 11))), lt._p90([5]), lt._p90(list(range(1, 31)))), (9, 5, 27))

    def test_the_estado_row(self):
        r = lt.resumen([lt.medir(pr(1, DOS_PASS), CI_OK)])
        self.assertEqual(lt.fila_estado(r, '2026-10-20', '2026-11-03'),
                         '| 2026-10-20 → 2026-11-03 | 1 | 10.0 (10.0) | 4.0 (4.0) | 1.0 (1.0) | 2.0 (2.0) | 0.0 (0.0) | 4.0 (4.0) | 2 (1 PR con 2+) |')


class Datos(unittest.TestCase):
    def escribir(self, d, checks=True):
        Path(d, 'prs.json').write_text(json.dumps([pr(7, DOS_PASS)]), encoding='utf-8')
        Path(d, 'checks').mkdir()
        if checks:
            Path(d, 'checks', f'{HEAD}.json').write_text(json.dumps({'check_runs': CI_OK}), encoding='utf-8')

    def test_gh_output_and_its_trimmed_data_file_give_the_same_measure(self):
        with tempfile.TemporaryDirectory() as d:
            self.escribir(d)
            out = io.StringIO()
            with redirect_stdout(out):
                lt.main([str(Path(d, 'prs.json')), '--checks', str(Path(d, 'checks')), '--recortar', str(Path(d, 'r.json')),
                         '--capturado', '2026-11-03T23:00:00Z'])
            datos = json.loads(Path(d, 'r.json').read_text(encoding='utf-8'))
            out2 = io.StringIO()
            with redirect_stdout(out2):
                lt.main([str(Path(d, 'r.json'))])
        self.assertEqual(json.loads(out.getvalue()), json.loads(out2.getvalue()))
        self.assertEqual(datos['capturado'], '2026-11-03T23:00:00Z')
        self.assertEqual(datos['prs'][0]['comments'][0]['body'], f'AUDIT VERDICT: REVISE {VIEJO}')  # first line only
        self.assertTrue(any(x.startswith('gh pr list') for x in datos['comandos']))
        self.assertEqual([r['name'] for r in datos['prs'][0]['check_runs']], ['checks', 'mutation (0)', 'mutation (1)'])  # no audit
        self.assertEqual([c['oid'] for c in datos['prs'][0]['commits']], [HEAD])

    def test_trimming_keeps_only_verdict_lines_but_from_every_author(self):
        otros = DOS_PASS + [c('just a note', '2026-11-01T03:00:00Z'), c(f'AUDIT VERDICT: PASS {HEAD}', '2026-11-01T05:30:00Z', {'login': 'x'})]
        d = lt.recortar([pr(1, otros)], {HEAD: CI_OK}, '2026-11-03T23:00:00Z')
        self.assertEqual(len(d['prs'][0]['comments']), 5)
        self.assertEqual(lt.medir(d['prs'][0], d['prs'][0]['check_runs']), lt.medir(pr(1, otros), CI_OK))
        texto = lt.escribir(d)
        self.assertEqual(json.loads(texto), d)
        self.assertEqual(texto.count('\n'), 3)  # header line, one line per PR, closing line

    def test_a_missing_check_runs_file_is_refused_not_read_as_no_data(self):
        with tempfile.TemporaryDirectory() as d:
            self.escribir(d, checks=False)
            with self.assertRaises(SystemExit) as e:
                lt.main([str(Path(d, 'prs.json')), '--checks', str(Path(d, 'checks'))])
            with self.assertRaises(SystemExit):
                lt.leer(Path(d, 'prs.json'))  # gh output without --checks
        self.assertIn(HEAD, str(e.exception.code))

    def test_trimming_needs_its_capture_time(self):
        with tempfile.TemporaryDirectory() as d:
            self.escribir(d)
            with self.assertRaises(SystemExit):
                lt.main([str(Path(d, 'prs.json')), '--checks', str(Path(d, 'checks')), '--recortar', str(Path(d, 'r.json'))])

    def test_every_lead_time_row_in_estado_is_recomputed_from_its_committed_data(self):
        estado = (ROOT / 'docs' / 'ESTADO.md').read_text(encoding='utf-8')
        archivos = sorted((ROOT / 'docs' / 'medicion').glob('lead-time-*.json'))
        self.assertTrue(archivos)
        filas = [lt.calcular(*lt.leer(f))['fila'] for f in archivos]
        for f in filas:
            self.assertIn(f, estado)
        en_estado = [l for l in estado.splitlines() if re.match(r'\| \d{4}-\d\d-\d\d → \d{4}-\d\d-\d\d \| \d+ \|', l)]
        self.assertEqual(sorted(en_estado), sorted(filas))  # no row in ESTADO without its data


if __name__ == '__main__':
    unittest.main()
