"""Catalog pipeline: fetch guards (T8/T10), parsers against real official pages, fixed categorization, store.

Each regression names the real failure it pins (found 2026-10-19 by the coverage reconciliation, not by review).
"""
import io
import json
import re
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path

from rg.catalog import leyesbiblio, sidof
from rg.catalog.categorize import doc_type, fold
from rg.catalog.fetch import BudgetExhausted, Fetcher, FetchRefused
from rg.catalog.store import Catalog, RawStore

FIX = Path(__file__).resolve().parent / 'fixtures'
BASE = 'https://www.diputados.gob.mx/LeyesBiblio/'


class FakeResp(io.BytesIO):
    def __init__(self, status, body=b'', headers=None):
        super().__init__(body)
        self.status = status
        self.headers = Message()
        for k, v in (headers or {}).items():
            self.headers[k] = v

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    """Maps URL -> (status, body, headers). Records requests."""
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def open(self, req, timeout=None):
        self.calls.append((req.full_url, dict(req.header_items())))
        status, body, headers = self.routes.get(req.full_url, (404, b'', {}))
        if status >= 400 or status in (301, 302, 303, 307, 308):
            hdrs = Message()
            for k, v in headers.items():
                hdrs[k] = v
            raise urllib.error.HTTPError(req.full_url, status, 'x', hdrs, io.BytesIO(body))
        return FakeResp(status, body, headers)


def fetcher(routes, **kw):
    sleeps = []
    clock = [0.0]
    f = Fetcher(['a.gob.mx', 'b.gob.mx'], opener=FakeOpener(routes), clock=lambda: clock[0],
                sleep=lambda s: (sleeps.append(s), clock.__setitem__(0, clock[0] + s)), **kw)
    return f, sleeps


ROBOTS_OK = (200, b'User-agent: *\nDisallow: /private/\n', {})


class FetchGuards(unittest.TestCase):
    def test_host_not_in_allowlist_refused_before_any_request(self):
        f, _ = fetcher({})
        with self.assertRaises(FetchRefused):
            f.get('https://evil.example/x')
        self.assertEqual(f._opener.calls, [])

    def test_scheme_and_credentials_refused(self):
        f, _ = fetcher({})
        for url in ('ftp://a.gob.mx/x', 'file:///etc/passwd', 'https://user:pw@a.gob.mx/x'):
            with self.assertRaises(FetchRefused):
                f.get(url)

    def test_robots_disallow_honored(self):
        f, _ = fetcher({'https://a.gob.mx/robots.txt': ROBOTS_OK, 'https://a.gob.mx/private/1': (200, b'x', {})})
        with self.assertRaises(FetchRefused):
            f.get('https://a.gob.mx/private/1')
        self.assertNotIn('https://a.gob.mx/private/1', [c[0] for c in f._opener.calls])

    def test_robots_missing_allows_and_robots_error_disallows_all(self):
        f, _ = fetcher({'https://a.gob.mx/robots.txt': (404, b'', {}), 'https://a.gob.mx/x': (200, b'ok', {}),
                        'https://b.gob.mx/robots.txt': (503, b'', {}), 'https://b.gob.mx/x': (200, b'ok', {})})
        self.assertEqual(f.get('https://a.gob.mx/x').body, b'ok')
        with self.assertRaises(FetchRefused):
            f.get('https://b.gob.mx/x')

    def test_redirect_outside_allowlist_refused_inside_followed(self):
        f, _ = fetcher({'https://a.gob.mx/robots.txt': ROBOTS_OK, 'https://b.gob.mx/robots.txt': ROBOTS_OK,
                        'https://a.gob.mx/out': (302, b'', {'Location': 'https://evil.example/'}),
                        'https://a.gob.mx/in': (302, b'', {'Location': 'https://b.gob.mx/doc'}),
                        'https://b.gob.mx/doc': (200, b'doc', {})})
        with self.assertRaises(FetchRefused):
            f.get('https://a.gob.mx/out')
        self.assertEqual(f.get('https://a.gob.mx/in').body, b'doc')

    def test_size_cap(self):
        f, _ = fetcher({'https://a.gob.mx/robots.txt': ROBOTS_OK, 'https://a.gob.mx/big': (200, b'x' * 101, {})}, max_bytes=100)
        with self.assertRaises(FetchRefused):
            f.get('https://a.gob.mx/big')

    def test_budget_counts_every_request_including_robots(self):
        f, _ = fetcher({'https://a.gob.mx/robots.txt': ROBOTS_OK, 'https://a.gob.mx/x': (200, b'ok', {})}, budget=2)
        f.get('https://a.gob.mx/x')
        with self.assertRaises(BudgetExhausted):
            f.get('https://a.gob.mx/x')

    def test_pacing_and_crawl_delay(self):
        f, sleeps = fetcher({'https://a.gob.mx/robots.txt': (200, b'User-agent: *\nCrawl-delay: 5\n', {}),
                             'https://a.gob.mx/x': (200, b'ok', {})}, min_interval=1.0)
        f.get('https://a.gob.mx/x')
        f.get('https://a.gob.mx/x')
        self.assertTrue(sleeps and max(sleeps) >= 5 - 1e-9, sleeps)

    def test_conditional_headers_sent(self):
        f, _ = fetcher({'https://a.gob.mx/robots.txt': ROBOTS_OK, 'https://a.gob.mx/x': (304, b'', {})})
        r = f.get('https://a.gob.mx/x', etag='"abc"', last_modified='Fri, 09 Oct 2026 01:47:49 GMT')
        self.assertEqual(r.status, 304)
        headers = f._opener.calls[-1][1]
        self.assertEqual(headers.get('If-none-match'), '"abc"')


class Decoding(unittest.TestCase):
    def test_iso_8859_1_label_means_windows_1252(self):
        # Regression 2026-10-19: OJN titles carried 0x93/0x94 quotes that Latin-1 turned into invisible C1 controls;
        # the catalog_entry schema rejected them (exit 4) before anything was written.
        from rg.catalog.fetch import decode_html
        self.assertEqual(decode_html(b'\x93Gigante de los Arellano\x94', 'ISO-8859-1'), '\u201cGigante de los Arellano\u201d')
        self.assertEqual(decode_html('Régimen'.encode('latin-1'), 'iso-8859-1'), 'Régimen')
        self.assertEqual(decode_html('ñ'.encode('utf-8'), 'utf-8'), 'ñ')
        self.assertNotRegex(decode_html(bytes(range(0x80, 0xa0)), 'iso-8859-1'), '[\x80-\x9f]')


class Categorize(unittest.TestCase):
    def test_table_and_longest_prefix(self):
        cases = {
            'Acuerdo por el que se modifica...': 'ACUERDO',
            'DECRETO por el que se reforma': 'DECRETO',
            'NORMA Oficial Mexicana NOM-001-SSA-2023': 'NORMA OFICIAL MEXICANA',
            'PROYECTO de Norma Oficial Mexicana PROY-NOM-002': 'PROYECTO DE NORMA OFICIAL MEXICANA',
            'Índice nacional de precios al consumidor.': 'INDICADOR ECONOMICO',
            'Tipo de cambio para solventar obligaciones': 'INDICADOR ECONOMICO',
            'CONSTITUCIÓN Política de los Estados Unidos Mexicanos': 'CONSTITUCION',
            'CÓDIGO Penal Federal': 'CODIGO',
            'ORDENANZA General de la Armada': 'ORDENANZA',
            'PRESUPUESTO de Egresos de la Federación': 'PRESUPUESTO',
        }
        for title, want in cases.items():
            self.assertEqual(doc_type(title), want, title)

    def test_no_match_is_otro_never_a_guess(self):
        for title in ('Leyenda de un mapa', 'Segundo Convenio Modificatorio', 'IMPUESTO sobre Servicios', ''):
            self.assertEqual(doc_type(title), 'OTRO', title)

    def test_fold_is_comparison_only(self):
        self.assertEqual(fold('  Índice   Nacional '), 'INDICE NACIONAL')


class SidofParser(unittest.TestCase):
    def _check(self, name, notes, editions):
        page = (FIX / name).read_text(encoding='utf-8')
        items = sidof.parse_day(page)
        self.assertEqual(len(items), notes)
        self.assertEqual(sidof.count_listed(page), notes)  # reconciliation holds
        self.assertEqual({i['edition'] for i in items}, editions)
        self.assertTrue(all(i['branch'] and i['issuer'] and i['section'] for i in items))
        return items

    def test_single_edition_day_without_tab_navigation(self):
        # Regression 2026-10-15: no tab navigation -> parser extracted 0 of 107 notes; caught by reconciliation.
        self._check('sidof_day_2026-10-15_single_edition.html', 107, {'MATUTINA'})

    def test_two_editions_and_top_notes_excluded(self):
        items = self._check('sidof_day_2026-10-16_two_editions.html', 57, {'MATUTINA', 'VESPERTINA'})
        self.assertEqual(items[0]['issuer'], 'SECRETARIA DE HACIENDA Y CREDITO PUBLICO')
        self.assertNotIn('5801477', {i['native_id'] for i in items})  # 'top notes' carousel link from another day

    def test_reconciliation_detects_structure_drift(self):
        # The 2026-10-15 failure mode: the page structure changes, the parser silently extracts fewer notes,
        # and only the independent count (official class on the page) shows it.
        page = (FIX / 'sidof_day_2026-10-16_two_editions.html').read_text(encoding='utf-8')
        drifted = re.sub(r'class="tab-pane[^"]*"', 'class="pane-renamed"', page)
        self.assertEqual(sidof.count_listed(drifted), 57)
        self.assertLess(len(sidof.parse_day(drifted)), sidof.count_listed(drifted))


class LeyesBiblioParser(unittest.TestCase):
    def _rows(self, name):
        page = (FIX / name).read_bytes().decode('iso-8859-1')
        return page, leyesbiblio.parse_listing(page, BASE)

    def test_every_pdf_on_the_page_is_accounted_for(self):
        for name in ('leyesbiblio_index_2026-10-19.htm', 'leyesbiblio_regla_2026-10-19.htm'):
            page, rows = self._rows(name)
            self.assertEqual(len(leyesbiblio.accounted_pdfs(rows, BASE)), leyesbiblio.count_text_pdfs(page), name)

    def test_laws_include_non_ley_titles_and_abrogated(self):
        # Regression: an instrument-word filter dropped ORDENANZA, PRESUPUESTO and 'IMPUESTO sobre...' rows.
        _, rows = self._rows('leyesbiblio_index_2026-10-19.htm')
        ids = {r['native_id']: r for r in rows}
        self.assertEqual(len(rows), 318)
        for nid in ('218', 'PEF_2026', '79', 'CPEUM'):
            self.assertIn(nid, ids)
        self.assertEqual(ids['218']['title'], 'ORDENANZA General de la Armada')
        self.assertEqual(sum(r['status_printed'] == 'ABROGADO' for r in rows), 3)

    def test_regulations_take_text_column_not_history(self):
        # Regression: taking the first PDF of the row picked a HISTORICAL version as the current text.
        _, rows = self._rows('leyesbiblio_regla_2026-10-19.htm')
        ids = {r['native_id']: r for r in rows}
        self.assertTrue(ids['Reg_LGS_MCSOTCSH']['raw_url'].endswith('regley/Reg_LGS_MCSOTCSH.pdf'))
        self.assertEqual(len(ids['Reg_LGS_MCSOTCSH']['history_urls']), 5)
        self.assertTrue(ids['Reg_LSM_060647']['raw_url'].endswith('Reg_LSM_060647.pdf'))
        self.assertEqual(len(rows), 150)

    def test_malformed_number_cell_is_kept(self):
        # Regression: the ISR regulation row has 'nos' in its number cell on the official page.
        _, rows = self._rows('leyesbiblio_regla_2026-10-19.htm')
        isr = [r for r in rows if r['list_marker'] == 'nos']
        self.assertEqual(len(isr), 1)
        self.assertIn('Impuesto sobre la Renta', isr[0]['title'])


class Store(unittest.TestCase):
    def test_raw_store_is_content_addressed(self):
        with tempfile.TemporaryDirectory() as d:
            raw = RawStore(d)
            a = raw.put(b'same', 'html')
            b = raw.put(b'same', 'html')
            self.assertEqual(a, b)
            self.assertEqual(len(raw.new_files), 1)
            self.assertTrue(re.fullmatch(r'sha256/[0-9a-f]{2}/[0-9a-f]{64}\.html', a[1]))

    def _entry(self, nid, published, versions=None):
        e = {'entry_id': f'mx.dof:{nid}', 'country': 'MX', 'source_id': 'mx.dof', 'native_id': nid, 'title': 'Acuerdo x',
             'url': f'https://sidof.segob.gob.mx/notas/{nid}', 'raw_status': 'pending', 'first_seen': f'2026-10-{nid[-2:]}T00:00:00Z',
             'category': {'jurisdiction': 'federal', 'collection': 'DOF', 'doc_type': 'ACUERDO'}, 'dates': {'published': published}}
        if versions is not None:
            e['versions'] = versions
        return e

    def test_upsert_keeps_first_seen_and_appends_versions(self):
        with tempfile.TemporaryDirectory() as d:
            c = Catalog(d, 'MX')
            v1 = {'sha256': 'a' * 64, 'retrieved_at': '2026-10-01T00:00:00Z', 'raw_path': 'x'}
            v2 = {'sha256': 'b' * 64, 'retrieved_at': '2026-10-02T00:00:00Z', 'raw_path': 'y'}
            self.assertTrue(c.upsert(self._entry('5801401', '2026-10-01', [v1])))
            later = self._entry('5801401', '2026-10-01', [v2])
            later['first_seen'] = '2030-01-01T00:00:00Z'
            self.assertFalse(c.upsert(later))
            stored = c.entries['mx.dof:5801401']
            self.assertEqual(stored['first_seen'], '2026-10-01T00:00:00Z')
            self.assertEqual([v['sha256'] for v in stored['versions']], ['a' * 64, 'b' * 64])

    def test_write_is_ordered_and_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            c = Catalog(d, 'MX')
            for nid, day in (('5801402', '2026-10-02'), ('5801401', '2026-10-01'), ('5801403', '2026-10-01')):
                c.upsert(self._entry(nid, day))
            c.write()
            first = {p: p.read_bytes() for p in Path(d).rglob('*') if p.is_file()}
            rows = [json.loads(l) for l in (Path(d) / 'mx' / 'dof' / '2026.jsonl').read_text().splitlines()]
            self.assertEqual([r['native_id'] for r in rows], ['5801401', '5801403', '5801402'])
            Catalog(d, 'MX').write()
            self.assertEqual(first, {p: p.read_bytes() for p in Path(d).rglob('*') if p.is_file()})
            self.assertEqual(json.loads((Path(d) / 'mx' / 'index.json').read_text())['total'], 3)


if __name__ == '__main__':
    unittest.main()


class OjnParser(unittest.TestCase):
    """State legislation (Orden Jurídico Nacional): the page prints its own total; that is the reconciliation."""
    OJN = 'https://www.ordenjuridico.gob.mx/'

    def _page(self, name):
        from rg.catalog.fetch import decode_html
        return decode_html((FIX / name).read_bytes(), 'iso-8859-1')

    def test_listing_matches_printed_total(self):
        for name, total, state in (('ojn_list_edo24_poder2.html', 202, 'San Luis Potosí'),
                                   ('ojn_list_edo11_poder2.html', 310, 'Guanajuato')):
            page = self._page(name)
            from rg.catalog import ojn
            items = ojn.parse_list(page)
            self.assertEqual(ojn.printed_total(page), total)
            self.assertEqual(len(items), total)
            self.assertEqual(ojn.state_name(page), state)
            self.assertTrue(all(i['published'] and re.fullmatch(r'\d+', i['native_id']) for i in items))

    def test_row_values_are_verbatim(self):
        from rg.catalog import ojn
        first = ojn.parse_list(self._page('ojn_list_edo24_poder2.html'))[0]
        self.assertEqual(first, {'native_id': '95983', 'title': 'Ley Sobre El Régimen De Propiedad En Condominio Para El Estado De San Luis Potosí',
                                 'published_printed': '09-04-2015', 'last_reform_printed': '27-06-2024', 'type_printed': 'Ley',
                                 'published': '2015-04-09', 'last_reform': '2024-06-27'})

    def test_ficha_fields_and_document_link(self):
        from rg.catalog import ojn
        sheet = ojn.parse_ficha(self._page('ojn_ficha_95983.html'), self.OJN)
        self.assertEqual(sheet['status_printed'], 'Vigente')
        self.assertEqual(sheet['locality'], 'San Luis Potosí')
        self.assertEqual(sheet['type_printed'], 'Ley')
        self.assertEqual(sheet['doc_url'], 'https://www.ordenjuridico.gob.mx/Documentos/Estatal/San%20Luis%20Potosi/wo95983.doc')

    def test_document_link_to_another_host_is_dropped(self):
        from rg.catalog import ojn
        page = self._page('ojn_ficha_95983.html').replace('http://www.ordenjuridico.gob.mx/./Documentos', 'http://evil.example/./Documentos')
        self.assertIsNone(ojn.parse_ficha(page, self.OJN)['doc_url'])


class DofWindow(unittest.TestCase):
    def test_last_days_are_reread_for_late_notes(self):
        # Regression: the window started after the last indexed day, so the promised re-read never happened.
        from datetime import date
        from rg.catalog.run import dof_window_start
        today = date(2026, 10, 22)
        indexed = {'2026-10-19': {}, '2026-10-22': {}}
        self.assertEqual(dof_window_start(indexed, today, 30), date(2026, 10, 20))
        self.assertEqual(dof_window_start({'2026-10-10': {}}, today, 30), date(2026, 10, 11))
        self.assertEqual(dof_window_start({}, today, 30), date(2026, 9, 22))
