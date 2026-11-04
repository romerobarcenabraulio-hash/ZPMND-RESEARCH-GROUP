"""scripts/lead_time.py: each component from fixed timestamps; verdicts only from github-actions and naming the merged head."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts import lead_time as lt

HEAD, VIEJO = 'a' * 40, 'b' * 40
BOT = {'login': 'github-actions'}


def c(body, t, author=BOT):
    return {'author': author, 'body': body, 'createdAt': t}


def pr(n=1, comments=(), head=HEAD, commits=None):
    return {'number': n, 'createdAt': '2026-11-01T00:00:00Z', 'mergedAt': '2026-11-01T10:00:00Z', 'headRefOid': head,
            'additions': 30, 'deletions': 5, 'comments': list(comments),
            'commits': commits if commits is not None else [{'oid': VIEJO, 'committedDate': '2026-11-01T00:10:00Z'},
                                                            {'oid': HEAD, 'committedDate': '2026-11-01T04:00:00Z'}]}


DOS_PASS = [c(f'AUDIT VERDICT: REVISE {VIEJO}\nbody', '2026-11-01T02:00:00Z'),
            c(f'GPT REVIEW: REVISE {VIEJO}', '2026-11-01T02:30:00Z'),
            c(f'AUDIT VERDICT: PASS {HEAD}\nbody', '2026-11-01T05:00:00Z'),
            c(f'GPT REVIEW: PASS {HEAD}', '2026-11-01T06:00:00Z')]


class Medir(unittest.TestCase):
    def test_each_component_from_its_two_timestamps(self):
        f = lt.medir(pr(comments=DOS_PASS))
        self.assertEqual((f['total'], f['antes_head'], f['auditoria'], f['espera_dueno']), (10.0, 4.0, 2.0, 4.0))
        self.assertEqual(f['revise'], {'claude': 1, 'gpt': 1})
        self.assertEqual(f['lineas'], 35)

    def test_a_pass_on_an_older_head_is_not_a_pass_of_the_merged_one(self):
        old = [c(f'AUDIT VERDICT: PASS {VIEJO}', '2026-11-01T01:00:00Z'), c(f'GPT REVIEW: PASS {HEAD}', '2026-11-01T06:00:00Z')]
        f = lt.medir(pr(comments=old))
        self.assertIsNone(f['espera_dueno'])
        self.assertIsNone(f['auditoria'])

    def test_the_later_of_the_two_passes_starts_the_owner_wait(self):
        f = lt.medir(pr(comments=list(reversed(DOS_PASS))))
        self.assertEqual(f['espera_dueno'], 4.0)

    def test_a_verdict_not_posted_by_github_actions_is_ignored(self):
        fake = [c(f'AUDIT VERDICT: PASS {HEAD}', '2026-11-01T05:00:00Z', {'login': 'someone'}),
                c(f'GPT REVIEW: PASS {HEAD}', '2026-11-01T06:00:00Z')]
        self.assertIsNone(lt.medir(pr(comments=fake))['espera_dueno'])
        self.assertEqual(lt.medir(pr(comments=[c(f'AUDIT VERDICT: REVISE {HEAD}', '2026-11-01T05:00:00Z', None)]))['revise']['claude'], 0)

    def test_only_the_first_line_in_its_exact_form_is_a_verdict(self):
        loose = [c(f'note\nAUDIT VERDICT: PASS {HEAD}', '2026-11-01T05:00:00Z'), c(f'AUDIT VERDICT: PASS {HEAD} ok', '2026-11-01T05:00:00Z'),
                 c(f'GPT REVIEW: PASS {HEAD}', '2026-11-01T06:00:00Z')]
        self.assertIsNone(lt.medir(pr(comments=loose))['espera_dueno'])
        crlf = [c(f'AUDIT VERDICT: PASS {HEAD}\r\nbody', '2026-11-01T05:00:00Z'), c(f'GPT REVIEW: PASS {HEAD}', '2026-11-01T06:00:00Z')]
        self.assertEqual(lt.medir(pr(comments=crlf))['espera_dueno'], 4.0)

    def test_without_the_head_commit_there_is_no_before_head_nor_audit_time(self):
        f = lt.medir(pr(comments=DOS_PASS, commits=[]))
        self.assertIsNone(f['antes_head'])
        self.assertIsNone(f['auditoria'])
        self.assertEqual(f['espera_dueno'], 4.0)

    def test_a_head_that_is_not_a_sha_is_refused(self):
        with self.assertRaises(ValueError):
            lt.medir(pr(head='main'))

    def test_ci_spans_its_jobs_and_ignores_others_and_unfinished_ones(self):
        runs = [{'name': 'checks', 'started_at': '2026-11-01T04:01:00Z', 'completed_at': '2026-11-01T04:04:00Z'},
                {'name': 'mutation (3)', 'started_at': '2026-11-01T04:01:00Z', 'completed_at': '2026-11-01T05:01:00Z'},
                {'name': 'mutation (4)', 'started_at': '2026-11-01T04:01:00Z', 'completed_at': None},
                {'name': 'audit', 'started_at': '2026-11-01T04:00:00Z', 'completed_at': '2026-11-01T09:00:00Z'}]
        self.assertEqual(lt.medir(pr(comments=DOS_PASS), runs)['ci'], 1.0)
        self.assertIsNone(lt.medir(pr(), [runs[3]])['ci'])
        self.assertIsNone(lt.medir(pr())['ci'])

    def test_a_ci_that_ends_after_both_passes_is_its_own_wait_not_the_owners(self):
        late = [{'name': 'mutation (0)', 'started_at': '2026-11-01T04:01:00Z', 'completed_at': '2026-11-01T07:30:00Z'}]
        f = lt.medir(pr(comments=DOS_PASS), late)
        self.assertEqual((f['auditoria'], f['espera_ci'], f['espera_dueno']), (2.0, 1.5, 2.5))
        early = [{'name': 'checks', 'started_at': '2026-11-01T04:01:00Z', 'completed_at': '2026-11-01T04:04:00Z'}]
        f = lt.medir(pr(comments=DOS_PASS), early)
        self.assertEqual((f['espera_ci'], f['espera_dueno']), (0.0, 4.0))
        f = lt.medir(pr(comments=DOS_PASS))
        self.assertEqual((f['espera_ci'], f['espera_dueno']), (None, 4.0))


class Resumen(unittest.TestCase):
    def test_medians_p90_and_the_prs_merged_without_both_passes(self):
        filas = [lt.medir(pr(1, DOS_PASS)), lt.medir(pr(2)), lt.medir(pr(3, DOS_PASS + DOS_PASS[:1]))]
        r = lt.resumen(filas)
        self.assertEqual(r['prs'], 3)
        self.assertEqual(r['sin_dos_pass'], [2])
        self.assertEqual(r['espera_dueno'], {'n': 2, 'mediana': 4.0, 'p90': 4.0})
        self.assertEqual(r['revise'], {'total': 5, 'mediana': 2, 'prs_con_2_o_mas': 2})
        self.assertEqual(r['ci'], {'n': 0})

    def test_p90_is_the_nearest_rank(self):
        self.assertEqual(lt._p90(list(range(1, 11))), 9)
        self.assertEqual(lt._p90([5]), 5)
        self.assertEqual(lt._p90(list(range(1, 31))), 27)

    def test_the_estado_row(self):
        r = lt.resumen([lt.medir(pr(1, DOS_PASS))])
        self.assertEqual(lt.fila_estado(r, '2026-10-20', '2026-11-03'),
                         '| 2026-10-20 → 2026-11-03 | 1 | 10.0 (10.0) | 4.0 (4.0) | s/d | 2.0 (2.0) | s/d | 4.0 (4.0) | 2 (1 PR con 2+) |')


class Main(unittest.TestCase):
    def test_reads_the_gh_output_and_the_check_runs_folder(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'prs.json').write_text(json.dumps([pr(7, DOS_PASS)]), encoding='utf-8')
            Path(d, 'checks').mkdir()
            Path(d, 'checks', f'{HEAD}.json').write_text(json.dumps({'check_runs': [
                {'name': 'checks', 'started_at': '2026-11-01T04:00:00Z', 'completed_at': '2026-11-01T04:30:00Z'}]}), encoding='utf-8')
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(lt.main([str(Path(d, 'prs.json')), '--checks', str(Path(d, 'checks'))]), 0)
        got = json.loads(out.getvalue())
        self.assertEqual((got['prs'][0]['ci'], got['prs'][0]['espera_ci'], got['prs'][0]['espera_dueno']), (0.5, 0.0, 4.0))
        self.assertTrue(got['fila'].startswith('| 2026-11-01 → 2026-11-01 | 1 |'))


if __name__ == '__main__':
    unittest.main()
