"""Run wiring against a fake site (no network). Each test pins a finding of the audit of PR #5 (REVISE 78ed195)."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from rg.catalog import leyesbiblio, sidof
from rg.catalog.fetch import BudgetExhausted, Fetcher, FetchRefused
from rg.catalog.run import Run
from tests.test_catalog import BASE, FIX, FakeOpener

SIDOF = 'https://sidof.segob.gob.mx'
DAY = 'sidof_day_2026-10-16_two_editions.html'
ROBOTS_ALL = (200, b'User-agent: *\nAllow: /\n', {})


class Site(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.routes = {}

    def make_run(self, today, forward_days=0):
        self.opener = FakeOpener(self.routes)
        return Run('MX', self.tmp.name + '/out', self.tmp.name + '/raw', None, today, forward_days, 0)

    def go(self, run, source_id, method, hosts, **src_overrides):
        src = {**next(s for s in run.registry['sources'] if s['source_id'] == source_id), **src_overrides}
        f = Fetcher(hosts, opener=self.opener, clock=lambda: 0.0, sleep=lambda s: None, retries=0)
        run._fetcher = lambda s: f
        return getattr(run, method)(src)

    def fetched(self, url):
        return sum(1 for c in self.opener.calls if c[0] == url)


class RobotsOutage(Site):
    def note(self, run, native_id, status):
        run.catalog.entries['mx.dof:' + native_id] = {
            'entry_id': 'mx.dof:' + native_id, 'source_id': 'mx.dof', 'native_id': native_id,
            'dates': {'published': '2026-10-01'}, 'raw_status': status}

    def test_unreachable_robots_leaves_notes_failed_not_disallowed(self):
        # Finding 1: a robots.txt 503 turned every pending note into robots_disallowed, never retried again.
        self.routes[SIDOF + '/robots.txt'] = (503, b'', {})
        run = self.make_run(date(2026, 10, 22))
        self.note(run, '1', 'pending')
        self.note(run, '2', 'robots_disallowed')  # mislabelled by an earlier outage: re-checked
        self.go(run, 'mx.dof', 'run_sidof', ['sidof.segob.gob.mx'])
        self.assertEqual(run.catalog.entries['mx.dof:1']['raw_status'], 'failed')
        self.assertEqual(run.catalog.entries['mx.dof:2']['raw_status'], 'failed')

    def test_a_rule_that_disallows_is_recorded_as_disallowed(self):
        self.routes[SIDOF + '/robots.txt'] = (200, b'User-agent: *\nDisallow: /notas/docFuente/\n', {})
        run = self.make_run(date(2026, 10, 22))
        self.note(run, '1', 'pending')
        self.go(run, 'mx.dof', 'run_sidof', ['sidof.segob.gob.mx'])
        self.assertEqual(run.catalog.entries['mx.dof:1']['raw_status'], 'robots_disallowed')


class DofGaps(Site):
    def test_failed_day_fails_the_run_and_is_read_next_time(self):
        # Finding 2: a day that failed was never added to the state, never retried, and the run exited 0.
        self.routes[SIDOF + '/robots.txt'] = ROBOTS_ALL
        gap = date(2026, 10, 15)
        self.routes[sidof.day_url(SIDOF, gap)] = (503, b'', {})
        run = self.make_run(date(2026, 10, 22))
        run.catalog.state['mx.dof'] = {'days': {'2026-10-14': {'notes': 0}, '2026-10-16': {'notes': 0}, '2026-10-20': {'notes': 0}}}
        self.go(run, 'mx.dof', 'run_sidof', ['sidof.segob.gob.mx'])
        self.assertIn('2026-10-15', [c['scope'] for c in run.manifest['coverage'] if not c['ok']])
        self.go(run, 'mx.dof', 'run_sidof', ['sidof.segob.gob.mx'])
        self.assertEqual(self.fetched(sidof.day_url(SIDOF, gap)), 2)

    def test_page_with_no_notes_is_not_a_closed_day(self):
        # Finding 10: a 200 page listing 0 notes passed 0 == 0 and closed the day for good.
        self.routes[SIDOF + '/robots.txt'] = ROBOTS_ALL
        d = date(2026, 10, 16)
        self.routes[sidof.day_url(SIDOF, d)] = (200, b'<html><body>Alta demanda</body></html>', {})
        run = self.make_run(d)
        self.go(run, 'mx.dof', 'run_sidof', ['sidof.segob.gob.mx'])
        self.assertIn('2026-10-16', [c['scope'] for c in run.manifest['coverage'] if not c['ok']])
        self.assertNotIn('2026-10-16', run.catalog.state['mx.dof']['days'])

    def test_judicial_notices_stay_metadata_only_whatever_the_case(self):
        # Finding 10: an exact, unfolded match fetched the raw of judicial notices if the label changed case/accents.
        self.routes[SIDOF + '/robots.txt'] = ROBOTS_ALL
        day = date(2026, 10, 16)
        self.routes[sidof.day_url(SIDOF, day)] = (200, (FIX / DAY).read_bytes(), {})
        run = self.make_run(day)
        branches = {i['branch'] for i in sidof.parse_day((FIX / DAY).read_text(encoding='utf-8'))}
        target = sorted(branches)[0]
        self.go(run, 'mx.dof', 'run_sidof', ['sidof.segob.gob.mx'], metadata_only_branches=[target.lower()])
        notes = [e for e in run.catalog.snapshot('mx.dof') if e['category']['branch'] == target]
        self.assertTrue(notes and all(e['raw_status'] == 'metadata_only' for e in notes))
        self.assertFalse(any('/notas/docFuente/' + e['native_id'] in c[0] for e in notes for c in self.opener.calls))


class LeyesBiblio(unittest.TestCase):
    def test_abrogated_laws_keep_their_original_publication(self):
        # Finding 3: rows marked 'A' were read as regulations and took the abrogation date as the original one.
        page = (FIX / 'leyesbiblio_index_2026-10-19.htm').read_bytes().decode('cp1252')
        rows = {r['native_id']: r for r in leyesbiblio.parse_listing(page, BASE)}
        self.assertEqual(rows['LFC']['original_publication'], '1992-12-29')
        self.assertEqual(rows['LEVCT_abro']['original_publication'], '1972-05-25')
        self.assertEqual(rows['LFC']['last_reform_printed'], '2026-05-22')

    def test_registry_never_fills_a_level_the_source_does_not_print(self):
        # Finding 4 (rule 3): LeyesBiblio prints no issuer per row; 'CONGRESO DE LA UNION' was wrong for PEF_2026.
        reg = json.loads((Path(__file__).resolve().parents[1] / 'sources' / 'mx.json').read_text(encoding='utf-8'))
        for s in reg['sources']:
            if s.get('adapter') == 'leyesbiblio':
                self.assertFalse({'issuer', 'branch'} & set(s['category']), s['source_id'])


class Cached304(Site):
    def test_304_without_kept_bytes_fetches_the_text_again(self):
        # Finding 9: a quarantined row lost its raw_path but kept its ETag; every later 304 left it pending forever.
        self.routes[BASE.rstrip('/').rsplit('/', 1)[0] + '/robots.txt'] = ROBOTS_ALL
        self.routes[BASE + 'index.htm'] = (200, (FIX / 'leyesbiblio_index_2026-10-19.htm').read_bytes(), {'content-type': 'text/html; charset=iso-8859-1'})
        page = (FIX / 'leyesbiblio_index_2026-10-19.htm').read_bytes().decode('cp1252')
        row = leyesbiblio.parse_listing(page, BASE)[0]

        class Conditional(FakeOpener):
            def open(self, req, timeout=None):
                if req.full_url == row['raw_url']:
                    self.calls.append((req.full_url, dict(req.header_items())))
                    from tests.test_catalog import FakeResp
                    if req.get_header('If-none-match'):
                        import io, urllib.error
                        raise urllib.error.HTTPError(req.full_url, 304, 'x', {}, io.BytesIO(b''))
                    return FakeResp(200, b'%PDF-1.4 texto', {})
                return super().open(req, timeout)

        run = self.make_run(date(2026, 10, 22))
        self.opener = Conditional(self.routes)
        run.catalog.state['mx.leyes-federales'] = {'etags': {row['raw_url']: {'etag': '"v1"', 'last_modified': None}}}
        self.go(run, 'mx.leyes-federales', 'run_leyesbiblio', ['www.diputados.gob.mx'])
        e = run.catalog.entries['mx.leyes-federales:' + row['native_id']]
        self.assertTrue(e.get('raw_path'))
        self.assertEqual(self.fetched(row['raw_url']), 2)


class FetchGuards(unittest.TestCase):
    def f(self, routes, **kw):
        return Fetcher(['a.gob.mx'], opener=FakeOpener(routes), clock=kw.pop('clock', lambda: 0.0), sleep=lambda s: None, retries=0, **kw)

    def test_https_only(self):
        # Finding 6: an http URL (or a redirect to one) on an allowed host was followed without TLS.
        with self.assertRaises(FetchRefused):
            self.f({}).get('http://a.gob.mx/x')
        f = self.f({'https://a.gob.mx/robots.txt': ROBOTS_ALL, 'https://a.gob.mx/x': (302, b'', {'Location': 'http://a.gob.mx/y'})})
        with self.assertRaises(FetchRefused):
            f.get('https://a.gob.mx/x')

    def test_robots_refused_by_the_site_is_a_block(self):
        for status in (401, 403, 429):
            f = self.f({'https://a.gob.mx/robots.txt': (status, b'', {})})
            self.assertFalse(f.allowed('https://a.gob.mx/x'), status)
            self.assertFalse(f.disallowed_by_rule('https://a.gob.mx/x'), status)
        self.assertTrue(self.f({'https://a.gob.mx/robots.txt': (404, b'', {})}).allowed('https://a.gob.mx/x'))

    def test_non_ascii_url_is_a_failed_request_not_a_crash(self):
        # Finding 7: UnicodeEncodeError (a ValueError) escaped and stopped the whole host group.
        class Bad(FakeOpener):
            def open(self, req, timeout=None):
                if 'robots' in req.full_url:
                    return super().open(req, timeout)
                raise UnicodeEncodeError('ascii', 'ñ', 0, 1, 'ordinal not in range')
        f = Fetcher(['a.gob.mx'], opener=Bad({'https://a.gob.mx/robots.txt': ROBOTS_ALL}), clock=lambda: 0.0, sleep=lambda s: None, retries=0)
        self.assertEqual(f.get('https://a.gob.mx/año').status, 0)

    def test_deadline_ends_the_run_like_the_budget(self):
        # Finding 8: a run longer than the job limit was killed before writing anything.
        f = self.f({'https://a.gob.mx/robots.txt': ROBOTS_ALL}, clock=lambda: 100.0, deadline=50.0)
        with self.assertRaises(BudgetExhausted):
            f.get('https://a.gob.mx/x')


OJN = 'https://compilacion.ordenjuridico.gob.mx/'


class OjnRuns(Site):
    def test_304_without_kept_bytes_fetches_the_document_again(self):
        # Finding 9 (OJN side): the row kept its ETag but not its bytes; a 304 marked it failed forever.
        from rg.catalog import ojn
        run = self.make_run(date(2026, 10, 22))
        src = next(s for s in run.registry['sources'] if s['source_id'] == 'mx.ojn-estatal')
        ficha = ojn.ficha_url(src['base_url'], '95983')
        sheet = ojn.parse_ficha((FIX / 'ojn_ficha_95983.html').read_bytes().decode('cp1252'), src['base_url'])
        robots = src['base_url'].split('/', 3)[0] + '//' + src['base_url'].split('/', 3)[2] + '/robots.txt'
        self.routes.update({robots: ROBOTS_ALL, ficha: (200, (FIX / 'ojn_ficha_95983.html').read_bytes(), {})})
        doc = sheet['doc_url']

        class Conditional(FakeOpener):
            def open(self, req, timeout=None):
                if req.full_url == doc:
                    self.calls.append((req.full_url, dict(req.header_items())))
                    import io, urllib.error
                    from tests.test_catalog import FakeResp
                    if req.get_header('If-none-match'):
                        raise urllib.error.HTTPError(req.full_url, 304, 'x', {}, io.BytesIO(b''))
                    return FakeResp(200, b'documento', {})
                return super().open(req, timeout)

        self.opener = Conditional(self.routes)
        st = {'etags': {doc: {'etag': '"v1"', 'last_modified': None}}, 'listed_at': {}}
        run.catalog.entries['mx.ojn-estatal:95983'] = {
            'entry_id': 'mx.ojn-estatal:95983', 'source_id': 'mx.ojn-estatal', 'native_id': '95983', 'url': ficha,
            'category': {'doc_type': 'LEY', 'jurisdiction': 'estatal'}, 'listing': {'state_code': 24}, 'versions': [], 'raw_status': 'failed'}
        f = Fetcher(src['allowed_hosts'], opener=self.opener, clock=lambda: 0.0, sleep=lambda s: None, retries=0)
        stats = {'raw_stored': 0, 'raw_unchanged': 0, 'raw_failed': 0, 'no_document_link': 0}
        run._ojn_fetch_pending(src, f, st, stats)
        e = run.catalog.entries['mx.ojn-estatal:95983']
        self.assertEqual((e['raw_status'], self.fetched(doc)), ('stored', 2))

    def test_state_listing_is_reconciled_against_distinct_sheets(self):
        from rg.catalog import ojn
        run = self.make_run(date(2026, 10, 22))
        src = next(s for s in run.registry['sources'] if s['source_id'] == 'mx.ojn-estatal')
        robots = src['base_url'].split('/', 3)[0] + '//' + src['base_url'].split('/', 3)[2] + '/robots.txt'
        page = (FIX / 'ojn_list_edo24_poder2.html').read_bytes().replace(b'align=left>', b'align="left">', 1)  # one row drifts
        self.routes.update({robots: ROBOTS_ALL, ojn.list_url(src['base_url'], 24, 2, src['liberado']): (200, page, {})})
        self.go(run, 'mx.ojn-estatal', 'run_ojn', src['allowed_hosts'], states=[24], powers=[2], max_requests=3)
        checks = [c for c in run.manifest['coverage'] if 'fichas distintas' in c['scope']]
        self.assertEqual([(c['expected'], c['extracted'], c['ok']) for c in checks], [(202, 201, False)])

    def test_state_with_a_failed_municipality_is_listed_again_next_run(self):
        # Finding 11: listed_at was set even when some municipality pages failed, hiding them for 30 days.
        from rg.catalog import ojn
        run = self.make_run(date(2026, 10, 22))
        src = next(s for s in run.registry['sources'] if s['source_id'] == 'mx.ojn-municipal')
        robots = src['base_url'].split('/', 3)[0] + '//' + src['base_url'].split('/', 3)[2] + '/robots.txt'
        page = (FIX / 'ojn_state_page_edo24.html').read_bytes()
        self.routes.update({robots: ROBOTS_ALL, ojn.state_page_url(src['base_url'], 24, src['liberado']): (200, page, {})})
        self.go(run, 'mx.ojn-municipal', 'run_ojn_municipal', src['allowed_hosts'], states=[24])
        self.assertTrue(any('mun' in e and 'HTTP' in e for e in run.manifest['errors']))
        self.assertNotIn('24', run.catalog.state['mx.ojn-municipal']['listed_at'])


class Quarantine(unittest.TestCase):
    def test_invalid_entry_keeps_its_last_valid_row(self):
        # Finding 9: quarantine deleted a previously valid row, and its versions history with it.
        from rg.catalog.run import quarantine
        from rg.catalog.store import Catalog
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / 'mx'
            d.mkdir()
            cat = Catalog(tmp, 'MX')
            self.assertEqual(cat.previous({'x'}), {})
            good = json.loads((FIX / 'catalog_row_ley.json').read_text(encoding='utf-8'))
            (d / 'leyes-federales.jsonl').write_text(json.dumps(good) + '\n', encoding='utf-8')
            cat = Catalog(tmp, 'MX')
            bad = {**good, 'title': None}
            cat.entries[good['entry_id']] = bad
            cat.entries['mx.leyes-federales:NUEVA'] = {**bad, 'entry_id': 'mx.leyes-federales:NUEVA'}
            quarantine(cat, {good['entry_id']: ['title'], 'mx.leyes-federales:NUEVA': ['title']})
            self.assertEqual(cat.entries[good['entry_id']], good)
            self.assertNotIn('mx.leyes-federales:NUEVA', cat.entries)


class NoDate(unittest.TestCase):
    def test_printed_zero_date_is_no_data_never_a_date(self):
        # 3,897 OJN rows carried '0000-00-00' (printed 00-00-0000 = no date) as if it were a date.
        from rg.catalog import ojn
        from rg.catalog.run import recategorize
        from rg.schemas import validate
        self.assertIsNone(ojn._iso('00-00-0000'))
        self.assertEqual(ojn._iso('29-02-2024'), '2024-02-29')
        row = json.loads((FIX / 'catalog_row_ley.json').read_text(encoding='utf-8'))
        bad = {**row, 'dates': {**row['dates'], 'published': '0000-00-00'}}
        self.assertTrue(validate('catalog_entry', bad))
        recategorize([bad])
        self.assertNotIn('published', bad['dates'])
        self.assertEqual(bad['dates']['original_publication'], row['dates']['original_publication'])
        self.assertFalse(validate('catalog_entry', bad))


class PrintedEdition(unittest.TestCase):
    def test_single_pane_takes_the_edition_the_page_prints(self):
        # Finding 5: the edition was guessed from the pane id (resp-tab3 = matutina, seen on two days only).
        page = (FIX / 'sidof_day_2026-10-15_single_edition.html').read_text(encoding='utf-8')
        self.assertIn('Edici&oacute;n Matutina del', page)
        ext = page.replace('Edici&oacute;n Matutina del', 'Edici&oacute;n Extraordinaria del')
        self.assertEqual({i['edition'] for i in sidof.parse_day(ext)}, {'EXTRAORDINARIA'})
        unnamed = page.replace('Edici&oacute;n Matutina del', 'Edici&oacute;n del')
        self.assertEqual({i['edition'] for i in sidof.parse_day(unnamed)}, {None})


class OjnCount(unittest.TestCase):
    def test_distinct_sheets_are_counted_independently_of_the_row_parser(self):
        # Finding 10: printed total vs rows used the same row regex as the parser; dropped items read as 'repeated'.
        from rg.catalog import ojn
        from rg.catalog.fetch import decode_html
        page = decode_html((FIX / 'ojn_list_edo24_poder2.html').read_bytes(), 'iso-8859-1')
        self.assertEqual(ojn.count_ids(page), len({i['native_id'] for i in ojn.parse_list(page)}))
        broken = page.replace('align=left>', 'align="left">', 1)  # one row's markup drifts: the row parser loses it
        self.assertEqual(ojn.count_ids(broken), ojn.count_ids(page))
        self.assertLess(len({i['native_id'] for i in ojn.parse_list(broken)}), ojn.count_ids(broken))


if __name__ == '__main__':
    unittest.main()
