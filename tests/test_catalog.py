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
from rg.catalog.run import MAX_REREADS as MAX
from rg.catalog.store import Catalog, RawStore

FIX = Path(__file__).resolve().parent / 'fixtures'
BASE = 'https://www.diputados.gob.mx/LeyesBiblio/'
SAT = 'sidof_day_2026-10-17_saturday_mirror.html'
SIDOF = 'https://sidof.segob.gob.mx'


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

    def test_network_failure_is_retried_then_reported_not_raised(self):
        # Regression 2026-10-19: one IncompleteRead (cut chunked response) killed a whole run.
        import http.client

        class Flaky(FakeOpener):
            def open(self, req, timeout=None):
                if req.full_url.endswith('/x'):
                    self.calls.append((req.full_url, {}))
                    raise http.client.IncompleteRead(b'partial')
                return super().open(req, timeout)
        f = Fetcher(['a.gob.mx'], opener=Flaky({'https://a.gob.mx/robots.txt': ROBOTS_OK}), clock=lambda: 0.0, sleep=lambda s: None)
        r = f.get('https://a.gob.mx/x')
        self.assertEqual(r.status, 0)
        self.assertEqual(sum(1 for c in f._opener.calls if c[0].endswith('/x')), 3)  # 1 try + 2 retries

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


class Normalization(unittest.TestCase):
    def test_invisible_characters_removed_and_counted(self):
        # Regression 2026-10-19: an OJN title (CDMX) carries U+FEFF inside the text at the source.
        from rg.catalog.run import normalize_strings
        n = [0]
        out = normalize_strings({'title': 'de la \ufeffProcuraduría', 'x': ['a\u200bb', 'ok\n'], 'n': 3}, n)
        self.assertEqual(out, {'title': 'de la Procuraduría', 'x': ['ab', 'ok\n'], 'n': 3})
        self.assertEqual(n[0], 2)
        from rg.schemas import validate
        self.assertTrue(validate('research_request', {'question': 'a\ufeffb'}))  # the schema guard itself stays strict


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

    def test_dof_single_kind_sections_decide_the_type(self):
        # 2026-10-19: 3,233 procurement calls fell to OTRO because their titles start with the institution's name.
        from rg.catalog.categorize import dof_doc_type
        branch = 'CONVOCATORIAS PARA CONCURSOS DE ADQUISICIONES, ARRENDAMIENTOS, OBRAS Y SERVICIOS DEL SECTOR PUBLICO'
        self.assertEqual(dof_doc_type('INSTITUTO MEXICANO DEL SEGURO SOCIAL Convocatoria 12', branch), 'CONVOCATORIA DE ADQUISICIONES')
        self.assertEqual(dof_doc_type('Acuerdo por el que...', 'PODER EJECUTIVO'), 'ACUERDO')

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

    def test_publication_date_is_the_editions_own_date(self):
        # Regression 2026-10-20: the Saturday page shows Friday's edition; notes got Sunday's date in the catalog.
        sat = (FIX / 'sidof_day_2026-10-17_saturday_mirror.html').read_text(encoding='utf-8')
        self.assertEqual(sidof.edition_dates(sat).get('MATUTINA'), '2026-10-16')
        items = sidof.parse_day(sat)
        self.assertTrue(items and all(i['edition_date'] == '2026-10-16' for i in items))
        fri = (FIX / 'sidof_day_2026-10-16_two_editions.html').read_text(encoding='utf-8')
        self.assertEqual({i['edition_date'] for i in sidof.parse_day(fri)}, {'2026-10-16'})

    def test_unnamed_edition_falls_back_to_the_page_date_never_the_requested_day(self):
        # Audit of #6 finding 2: without the edition's PDF link the note took the requested day (a Saturday).
        sat = (FIX / SAT).read_text(encoding='utf-8')
        no_pdf = re.sub(r'(id="(pdfMat|pdfVes)"[^>]*value=")[^"]*"', r'\1"', sat)
        self.assertEqual(sidof.edition_dates(no_pdf), {})
        self.assertEqual({i['published'] for i in sidof.parse_day(no_pdf)}, {'2026-10-16'})
        self.assertEqual({i['edition_date'] for i in sidof.parse_day(no_pdf)}, {None})

    def test_edition_dates_ignore_attribute_order_and_quotes(self):
        page = "<input value='/welcome/showPDF/16-10-2026/MAT/1' type=hidden id='pdfMat'>"
        self.assertEqual(sidof.edition_dates(page), {'MATUTINA': '2026-10-16'})

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
            self.assertTrue(all(re.fullmatch(r'\d+', i['native_id']) for i in items))
            # no date exactly where the source prints 00-00-0000 ('no date'), never a fake 0000-00-00
            self.assertTrue(all((i['published'] is None) == (i['published_printed'] == '00-00-0000') for i in items))

    def test_source_repeated_rows_are_accounted(self):
        # Regression 2026-10-19: 21 of 128 listings 'missed' 1-10 rows; the source repeats rows (same idArchivo).
        from rg.catalog import ojn
        page = self._page('ojn_list_edo24_poder2.html')
        first_row = re.search(r'<tr>\s*<td bgcolor="[^"]*" align=left>.*?</tr>', page, re.S).group(0)
        doubled = page.replace(first_row, first_row + first_row, 1)
        self.assertEqual(ojn.count_rows(doubled), 203)
        self.assertEqual(len(ojn.parse_list(doubled)), 202)

    def test_row_values_are_verbatim(self):
        from rg.catalog import ojn
        first = ojn.parse_list(self._page('ojn_list_edo24_poder2.html'))[0]
        self.assertEqual(first, {'native_id': '95983', 'ambito': 'ESTATAL', 'title': 'Ley Sobre El Régimen De Propiedad En Condominio Para El Estado De San Luis Potosí',
                                 'published_printed': '09-04-2015', 'last_reform_printed': '27-06-2024', 'type_printed': 'Ley',
                                 'published': '2015-04-09', 'last_reform': '2024-06-27'})

    def test_municipal_listing_and_selector(self):
        from rg.catalog import ojn
        muns = ojn.parse_municipalities(self._page('ojn_state_page_edo24.html'))
        self.assertEqual(muns[0], ('2487', 'Todos los Municipios'))
        self.assertIn(('1847', 'Villa Hidalgo'), muns)
        self.assertEqual(len(muns), 59)
        page = self._page('ojn_mun_edo24_1847.html')
        items = ojn.parse_list(page)
        self.assertEqual(ojn.printed_total(page), 3)
        self.assertEqual(ojn.count_rows(page), 3)
        self.assertEqual(items[0]['title'], 'Reglamento Interior de la Administración Municipal del Municipio de Villa Hidalgo, S.L.P.')
        self.assertEqual((items[0]['type_printed'], items[0]['published'], items[0]['ambito']), ('Reglamento', None, ''))

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


class HostGroups(unittest.TestCase):
    def test_sources_sharing_a_host_never_run_in_parallel(self):
        # Politeness is per host: leyes-federales and reglamentos-federales share www.diputados.gob.mx.
        from rg.catalog.run import host_groups
        reg = json.loads((Path(__file__).resolve().parent.parent / 'sources' / 'mx.json').read_text(encoding='utf-8'))
        active = [s for s in reg['sources'] if s['status'] == 'active']
        groups = host_groups(active)
        hosts = [set(h for s in g for h in s['allowed_hosts']) for g in groups]
        for i, a in enumerate(hosts):
            for b in hosts[i + 1:]:
                self.assertFalse(a & b)
        dip = [g for g in groups if any(s['source_id'] == 'mx.leyes-federales' for s in g)][0]
        self.assertIn('mx.reglamentos-federales', [s['source_id'] for s in dip])


class Tree(unittest.TestCase):
    def test_hierarchy_and_missing_levels(self):
        from rg.catalog.store import build_tree, NO_DATA
        fed = {'country': 'MX', 'category': {'jurisdiction': 'federal', 'branch': 'PODER EJECUTIVO',
                                             'issuer': 'SECRETARIA DE ECONOMIA', 'doc_type': 'ACUERDO'}}
        est = {'country': 'MX', 'category': {'jurisdiction': 'estatal', 'locality': 'San Luis Potosí',
                                             'branch': 'PODER LEGISLATIVO', 'doc_type': 'LEY'}}
        t = build_tree([fed, est, est])
        mx = t['children']['país: MX']
        self.assertEqual(mx['n'], 3)
        fed_node = mx['children']['ámbito: federal']['children']['poder: PODER EJECUTIVO']
        self.assertIn('dependencia: SECRETARIA DE ECONOMIA', fed_node['children'])
        slp = mx['children']['ámbito: estatal']['children']['estado: San Luis Potosí']['children']['poder: PODER LEGISLATIVO']
        self.assertEqual(slp['children'][f'dependencia: {NO_DATA}']['children']['tipo: LEY']['n'], 2)


class Concurrency(unittest.TestCase):
    def test_snapshot_is_safe_while_another_thread_upserts(self):
        # Regression 2026-10-19: iterating catalog.entries while another source thread upserted raised
        # 'dictionary changed size during iteration' and stopped the DOF thread.
        import threading
        with tempfile.TemporaryDirectory() as d:
            c = Catalog(d, 'MX')
            base = {'country': 'MX', 'source_id': 'mx.dof', 'title': 't', 'url': 'https://x.gob.mx/', 'raw_status': 'pending',
                    'first_seen': '2026-10-19T00:00:00Z', 'category': {'jurisdiction': 'federal', 'collection': 'DOF', 'doc_type': 'OTRO'},
                    'dates': {'published': '2026-10-01'}}
            def writer():
                for i in range(20000):
                    c.upsert({**base, 'entry_id': f'mx.dof:{i}', 'native_id': str(i)})
            t = threading.Thread(target=writer)
            t.start()
            reads = 0
            while t.is_alive() or reads == 0:
                sum(1 for e in c.snapshot('mx.dof') if e['raw_status'] == 'pending')
                reads += 1
            t.join()
            self.assertEqual(len(c.snapshot('mx.dof')), 20000)

    def test_empty_official_heading_becomes_none(self):
        page = (FIX / 'sidof_day_2026-10-16_two_editions.html').read_text(encoding='utf-8')
        page = page.replace('SECRETARIA DE HACIENDA Y CREDITO PUBLICO </span>', ' </span>', 1)
        self.assertIsNone(sidof.parse_day(page)[0]['issuer'])


class Requeue(unittest.TestCase):
    def test_short_days_never_modifies_state(self):
        # 2026-10-19: 3 DOF notes were quarantined; their days stayed 'indexed', so the notes would never come back.
        # Audit of #6 (2026-10-20): deleting the row before the re-read lost the day when the re-read failed.
        from rg.catalog.run import short_days
        days = {'2026-10-01': {'notes': 2}, '2026-10-02': {'notes': 1}, '2026-10-03': {'notes': 5, 'edition': '2026-10-02'},
                '2026-10-04': {'ids': ['1', '2'], 'notes': 2}, '2026-10-05': {'ids': ['1'], 'notes': 1},
                '2026-10-06': {'ids': ['1'], 'notes': 3}, '2026-10-07': {'ids': ['9'], 'notes': 1, 'rereads': 3},
                '2026-10-08': {'notes': 0}}  # a count-only row of 0: an old soft error page
        entries = [{'source_id': 'mx.dof', 'native_id': '1', 'dates': {'published': '2026-10-01'}},
                   {'source_id': 'mx.dof', 'native_id': '5', 'dates': {'published': '2026-10-02'}}]
        before = json.dumps(days, sort_keys=True)
        # 10-01 legacy count short; 10-03 legacy mirror never short; 10-04 id '2' missing; 10-06 fewer ids than its count
        self.assertEqual(short_days(days, entries, 'mx.dof'), (['2026-10-01', '2026-10-04', '2026-10-06', '2026-10-08'], ['2026-10-07']))
        self.assertEqual(json.dumps(days, sort_keys=True), before)


class SidofRun(unittest.TestCase):
    """run_sidof wiring with a fake site (no network): the audit of #6 showed four mutations of it passing the suite."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.routes = {SIDOF + '/robots.txt': (200, b'User-agent: *\nAllow: /\n', {})}

    def run_once(self, run, today=None):
        from rg.catalog.run import Run
        src = next(s for s in run.registry['sources'] if s['source_id'] == 'mx.dof')
        f = Fetcher(['sidof.segob.gob.mx'], opener=self.opener, clock=lambda: 0.0, sleep=lambda s: None, retries=0)
        run._fetcher = lambda s: f
        return run.run_sidof(src)

    def make_run(self, today, forward_days=0):
        from rg.catalog.run import Run
        self.opener = FakeOpener(self.routes)
        return Run('MX', self.tmp.name + '/out', self.tmp.name + '/raw', None, today, forward_days, 0)

    def day(self, d):
        return sidof.day_url(SIDOF, d)

    def fetched(self, d):
        return sum(1 for c in self.opener.calls if c[0] == self.day(d))

    def entry(self, native_id, published):
        return {'entry_id': 'mx.dof:' + native_id, 'source_id': 'mx.dof', 'native_id': native_id,
                'dates': {'published': published}, 'raw_status': 'metadata_only'}

    def test_weekend_mirror_notes_get_the_editions_date(self):
        from datetime import date
        sat = date(2026, 10, 17)
        self.routes[self.day(sat)] = (200, (FIX / SAT).read_bytes(), {})
        run = self.make_run(sat)
        self.run_once(run)
        published = {e['dates']['published'] for e in run.catalog.snapshot('mx.dof')}
        self.assertEqual(published, {'2026-10-16'})  # never the requested Saturday
        self.assertTrue(all(c['ok'] for c in run.manifest['coverage']))

    def test_failed_reread_keeps_the_day_owed(self):
        from datetime import date
        short = date(2026, 10, 14)
        self.routes[self.day(short)] = (500, b'', {})
        run = self.make_run(date(2026, 10, 22))
        run.catalog.state['mx.dof'] = {'days': {'2026-10-14': {'ids': ['1', '2'], 'notes': 2},
                                                '2026-10-20': {'ids': [], 'notes': 0}}}
        run.catalog.entries['mx.dof:1'] = self.entry('1', '2026-10-14')
        self.run_once(run)
        self.assertIn('2026-10-14', run.catalog.state['mx.dof']['days'])
        self.run_once(run)  # the next run asks again
        self.assertEqual(self.fetched(short), 2)

    def test_empty_reread_never_erases_the_debt(self):
        from datetime import date
        from rg.catalog.run import short_days
        self.routes[self.day(date(2026, 10, 14))] = (200, b'<html><body>mantenimiento</body></html>', {})
        run = self.make_run(date(2026, 10, 22))
        self.routes[self.day(date(2026, 10, 15))] = self.routes[self.day(date(2026, 10, 14))]
        days = {'2026-10-14': {'ids': ['1', '2'], 'notes': 2},
                '2026-10-15': {'notes': 3},  # a row from before 2026-10-20: only the count is known
                '2026-10-20': {'ids': [], 'notes': 0}}
        run.catalog.state['mx.dof'] = {'days': days}
        run.catalog.entries['mx.dof:1'] = self.entry('1', '2026-10-14')
        self.run_once(run)
        self.assertEqual(days['2026-10-14']['ids'], ['1', '2'])
        self.assertEqual(days['2026-10-15']['notes'], 3)
        self.assertEqual(short_days(days, run.catalog.snapshot('mx.dof'), 'mx.dof')[0], ['2026-10-14', '2026-10-15'])

    def test_reread_listing_fewer_notes_keeps_the_debt(self):
        # A re-read that lists fewer notes than before (not zero) never shrinks what the day owes.
        from datetime import date
        page = (FIX / SAT).read_bytes()
        for d in (date(2026, 10, 14), date(2026, 10, 15)):
            self.routes[self.day(d)] = (200, page, {})
        run = self.make_run(date(2026, 10, 22))
        days = {'2026-10-14': {'ids': ['X1'], 'notes': 1},  # X1 was listed before; today's page no longer lists it
                '2026-10-15': {'notes': 999},                # a count-only row from before 2026-10-20
                '2026-10-20': {'ids': [], 'notes': 0}}
        run.catalog.state['mx.dof'] = {'days': days}
        self.run_once(run)
        self.assertIn('X1', days['2026-10-14']['ids'])
        self.assertEqual(days['2026-10-15']['notes'], 999)

    def test_requeued_day_in_the_reread_window_is_fetched_once(self):
        from datetime import date
        d = date(2026, 10, 21)
        self.routes[self.day(d)] = (500, b'', {})
        run = self.make_run(date(2026, 10, 22))
        run.catalog.state['mx.dof'] = {'days': {'2026-10-21': {'ids': ['1'], 'notes': 1}}}
        self.run_once(run)
        self.assertEqual(self.fetched(d), 1)

    def test_a_day_that_stays_short_is_reported_not_reread_forever(self):
        from datetime import date
        sat = date(2026, 10, 17)
        self.routes[self.day(sat)] = (200, (FIX / SAT).read_bytes(), {})
        run = self.make_run(date(2026, 10, 25))
        lost = sidof.parse_day((FIX / SAT).read_text(encoding='utf-8'))[0]['native_id']
        run.catalog.state['mx.dof'] = {'days': {'2026-10-17': {'ids': [lost], 'notes': 1},
                                                '2026-10-23': {'ids': [], 'notes': 0}}}
        for _ in range(MAX + 2):  # the same note is quarantined after every run (deterministic schema failure)
            self.run_once(run)
            run.catalog.entries.pop('mx.dof:' + lost, None)
        self.assertEqual(self.fetched(sat), MAX)
        self.assertIn('2026-10-17 notas o fecha oficial pendientes al cerrar',
                      [c['scope'] for c in run.manifest['coverage'] if not c['ok']])

    def test_note_without_any_official_date_fails_coverage(self):
        from datetime import date
        sat = date(2026, 10, 17)
        page = (FIX / SAT).read_text(encoding='utf-8')
        page = re.sub(r'(id="(pdfMat|pdfVes|fechaPub)"[^>]*value=")[^"]*"', r'\1"', page)
        page = re.sub(r'(value=")[^"]*("[^>]*id="fechaPub")', r'\1\2', page)
        self.routes[self.day(sat)] = (200, page.encode('utf-8'), {})
        run = self.make_run(sat)
        self.run_once(run)
        self.assertIn('2026-10-17 fecha oficial', [c['scope'] for c in run.manifest['coverage'] if not c['ok']])
        self.assertTrue(all(e['dates']['published'] is None for e in run.catalog.snapshot('mx.dof')))


