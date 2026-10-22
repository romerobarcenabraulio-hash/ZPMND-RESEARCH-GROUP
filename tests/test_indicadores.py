"""Calculation indicators (Banxico SIE, INEGI BIE): parsers, verbatim entries, coverage, token handling, wiring.

FIXTURES CONSTRUIDOS DE LA DOCUMENTACIÓN OFICIAL (HIPÓTESIS hasta la primera corrida real, workflow indicadores-mx):
the tokens exist only in GitHub Actions, so no real API answer could be read from here. Each fixture has
CONSTRUIDO_DE_DOCS in its name and follows the documented format, read on 2026-10-21:
- banxico_sie_datos_SF43718_CONSTRUIDO_DE_DOCS.json: the SF43718 block of Banxico's own example resource
  https://www.banxico.org.mx/SieAPIRest/json/datosSeriesRango.json (shown at .../service/v1/doc/consultaDatosSerieRango).
- banxico_sie_metadatos_CONSTRUIDO_DE_DOCS.json: format of the example at .../service/v1/doc/consultaSeries; SF43718
  and SP68257 copied from it, SF331451 and SF43783 filled with what the SIE cuadro CF101 prints for them.
- inegi_bie_indicator_628194_CONSTRUIDO_DE_DOCS.json and inegi_bie_cl_indicator_628194_CONSTRUIDO_DE_DOCS.json: the
  fields of "Estructura de salida" and of the example code at https://www.inegi.org.mx/servicios/api_indicadores.html
  (Series[0].OBSERVATIONS[i].TIME_PERIOD / OBS_VALUE; CODE[0].value / Description). Values are placeholders.
banxico_robots_2026-10-21.txt is real (anterior.banxico.org.mx/robots.txt). No network: a fake opener plays both hosts.
"""
import contextlib
import io
import json
import os
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import yaml

from rg.catalog import indicadores
from rg.catalog.fetch import Fetcher, FetchRefused
from rg.catalog.run import Run, main
from rg.catalog.store import Catalog
from rg.schemas import validate
from tests.test_catalog import FIX, FakeOpener

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 21)
BTOK = '0123456789abcdef' * 4  # fake; Banxico's documented tokens are 64 hex characters
ITOK = '11111111-2222-3333-4444-555555555555'  # fake; INEGI's documented token is a UUID
BX, BX_OLD, IN = 'https://www.banxico.org.mx', 'https://anterior.banxico.org.mx', 'https://www.inegi.org.mx'
ROBOTS_BX = (FIX / 'banxico_robots_2026-10-21.txt').read_bytes()
DATOS = (FIX / 'banxico_sie_datos_SF43718_CONSTRUIDO_DE_DOCS.json').read_bytes()
META = (FIX / 'banxico_sie_metadatos_CONSTRUIDO_DE_DOCS.json').read_bytes()
IND = (FIX / 'inegi_bie_indicator_628194_CONSTRUIDO_DE_DOCS.json').read_bytes()
CL = (FIX / 'inegi_bie_cl_indicator_628194_CONSTRUIDO_DE_DOCS.json').read_bytes()
JSON_CT = {'content-type': 'application/json;charset=UTF-8'}


def registry():
    return json.loads((ROOT / 'sources' / 'mx.json').read_text(encoding='utf-8'))


def source(sid):
    return next(s for s in registry()['sources'] if s['source_id'] == sid)


def datos_for(series_id, body=DATOS):
    """The constructed SF43718 answer, re-labelled for another series (same documented shape)."""
    doc = json.loads(body)
    doc['bmx']['series'][0]['idSerie'] = series_id
    doc['bmx']['series'][0]['titulo'] = f'Serie {series_id}'
    return json.dumps(doc, ensure_ascii=False, indent=2).encode('utf-8') if series_id != 'SF43718' else body


def with_datos(edit, body=DATOS):
    doc = json.loads(body)
    edit(doc['bmx']['series'][0]['datos'])
    return json.dumps(doc, ensure_ascii=False, indent=2).encode('utf-8')


class Parsers(unittest.TestCase):
    def test_banxico_values_and_dates_are_the_served_text(self):
        title, obs = indicadores.parse_banxico_datos(DATOS, 'SF43718')
        self.assertTrue(title.startswith('Tipo de cambio Pesos por dólar E.U.A.') and title.endswith('(FIX)'))
        self.assertEqual(obs[:3], [('01/01/2015', 'N/E'), ('02/01/2015', '14.8290'), ('03/01/2015', 'N/E')])
        self.assertEqual(len(obs), indicadores.served_count(DATOS, 'fecha'))
        self.assertEqual(indicadores.parse_banxico_meta(META)['SF43718']['unidad'], 'Pesos por Dólar')

    def test_numbers_keep_their_literal_text(self):
        body = b'{"bmx":{"series":[{"idSerie":"SF43718","titulo":"t","datos":[{"fecha":"02/01/2015","dato":14.8290},' \
               b'{"fecha":"05/01/2015","dato":15}]}]}}'
        self.assertEqual(indicadores.parse_banxico_datos(body, 'SF43718')[1], [('02/01/2015', '14.8290'), ('05/01/2015', '15')])
        ind = IND.replace(b'"100.500000"', b'100.500000').replace(b'"INDICADOR": "628194"', b'"INDICADOR": 628194')
        self.assertEqual(indicadores.parse_inegi_indicator(ind, '628194')[1][1], ('2026/07', '100.500000'))

    def test_a_response_for_another_or_for_several_series_is_refused(self):
        example = json.loads(DATOS)
        example['bmx']['series'].append(dict(example['bmx']['series'][0], idSerie='SF61745'))
        for body, sid in ((DATOS, 'SP68257'), (json.dumps(example).encode(), 'SF43718'), (b'[]', 'SF43718'),
                          (b'{"bmx": {"series": [{"idSerie": "SF43718"}]}}', 'SF43718')):
            with self.subTest(sid=sid, body=body[:30]), self.assertRaises(ValueError):
                indicadores.parse_banxico_datos(body, sid)
        with self.assertRaises(ValueError):
            indicadores.parse_inegi_indicator(IND, '628195')
        with self.assertRaises(ValueError):
            indicadores.parse_inegi_catalog(CL, '628195')

    def test_inegi_unit_values_and_official_description(self):
        unit, obs = indicadores.parse_inegi_indicator(IND, '628194')
        self.assertEqual(unit, '96')
        self.assertEqual(obs, [('2026/06', '100.000000'), ('2026/07', '100.500000'), ('2026/08', None), ('2026/09', '101.250000')])
        self.assertEqual(indicadores.parse_inegi_catalog(CL, '628194'), 'Índice general')
        self.assertEqual(indicadores.served_count(IND, 'TIME_PERIOD'), 4)

    def test_the_served_count_reads_bytes_not_the_parser(self):
        body = b'{"bmx":{"series":[{"idSerie":"SF1","fechaInicio":"x","datos":[{"fecha" : "01/01/2015","dato":"1"},' \
               b'{"fecha":"02/01/2015","dato":"2"}]}]}}'
        self.assertEqual(indicadores.served_count(body, 'fecha'), 2)  # "fechaInicio" is not an observation

    def test_ids_are_identifiers_and_dates_stay_verbatim(self):
        self.assertEqual(indicadores.native_id('SF43718', '02/01/2015'), 'SF43718.02-01-2015')
        self.assertEqual(indicadores.native_id('628194', '2026/09'), '628194.2026-09')
        for bad in ('2015-01-02', '02/01/2015 ', '', None, '1/2/3/4'):
            self.assertIsNone(indicadores.native_id('SF1', bad), bad)

    def test_tokens_that_could_inject_are_never_valid(self):
        self.assertTrue(indicadores.valid_token(BTOK) and indicadores.valid_token(ITOK))
        for bad in ('', 'short', BTOK + '\r\nX: 1', ITOK + '/../x', ITOK + '?a=1', 'x' * 200):
            self.assertFalse(indicadores.valid_token(bad), bad)


class FetcherTokens(unittest.TestCase):
    """fetch refuses to send either token to any host but its own, in a header or in a URL, even after a redirect."""

    def fetcher(self, routes):
        self.opener = FakeOpener(routes)
        return Fetcher(['www.banxico.org.mx', 'anterior.banxico.org.mx', 'www.inegi.org.mx', 'a.gob.mx'],
                       opener=self.opener, clock=lambda: 0.0, sleep=lambda s: None, retries=0,
                       secrets={BTOK: 'www.banxico.org.mx', ITOK: 'www.inegi.org.mx'})

    def sent(self):
        return [(u, {k.lower(): v for k, v in h.items()}) for u, h in self.opener.calls]

    def test_fetch_refuses_either_token_to_any_other_host(self):
        ok = (200, b'User-agent: *\nAllow: /\n', {})
        f = self.fetcher({BX + '/robots.txt': ok, BX_OLD + '/robots.txt': ok, IN + '/robots.txt': ok,
                          'https://a.gob.mx/robots.txt': ok, BX + '/s': (200, b'ok', {}), IN + f'/x/{ITOK}': (200, b'ok', {}),
                          IN + f'/r/{ITOK}': (302, b'', {'Location': f'https://a.gob.mx/{ITOK}'}),
                          BX + '/r': (302, b'', {'Location': BX_OLD + '/s'}), BX_OLD + '/s': (200, b'moved', {})})
        attempts = [(IN + '/s', {'auth': ('Bmx-Token', BTOK)}), ('https://a.gob.mx/s', {'auth': ('Bmx-Token', BTOK)}),
                    (BX + f'/x/{ITOK}', {}), (f'https://a.gob.mx/{ITOK}', {}), (IN + f'/r/{ITOK}', {}),
                    (BX + '/s', {'auth': ITOK})]
        for url, kw in attempts:
            with self.subTest(url=url), self.assertRaises(FetchRefused) as ctx:
                f.get(url, **kw)
            self.assertNotIn(BTOK, str(ctx.exception))
            self.assertNotIn(ITOK, str(ctx.exception))
        for url, headers in self.sent():
            host = re.match(r'https://([^/]+)', url).group(1)
            self.assertTrue(ITOK not in url or host == 'www.inegi.org.mx', url)
            self.assertTrue(BTOK not in json.dumps(headers) or host == 'www.banxico.org.mx', url)
        # each one does reach its own host; a redirect to the other Banxico host goes without the header
        self.assertEqual(f.get(BX + '/s', auth=('Bmx-Token', BTOK)).body, b'ok')
        self.assertEqual(f.get(IN + f'/x/{ITOK}').body, b'ok')
        self.assertEqual(f.get(BX + '/r', auth=('Bmx-Token', BTOK)).body, b'moved')
        heads = dict(self.sent())
        self.assertEqual((heads[BX + '/s'].get('bmx-token'), heads[BX + '/r'].get('bmx-token'), heads[BX_OLD + '/s'].get('bmx-token')),
                         (BTOK, BTOK, None))


class _RunCase(unittest.TestCase):
    SID = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {'BANXICO_TOKEN': BTOK, 'INEGI_TOKEN': ITOK})
        env.start()
        self.addCleanup(env.stop)
        self.out, self.raw = Path(self.tmp.name) / 'out', Path(self.tmp.name) / 'raw'
        self.run_ = Run('MX', self.out, self.raw, None, TODAY, 0, 0)
        self.src = next(s for s in self.run_.registry['sources'] if s['source_id'] == self.SID)
        self.calls, self.secrets_seen = [], []
        self.routes = self.default_routes()

    def opener(self):
        opener = FakeOpener(self.routes)
        opener.calls = self.calls
        return opener

    def fake_fetcher(self, run):
        opener = self.opener()

        def make(src, secrets=None):
            self.secrets_seen.append(secrets)
            return Fetcher(src['allowed_hosts'], opener=opener, clock=lambda: 0.0, sleep=lambda s: None, retries=0,
                           robots_log=run.manifest['robots'], secrets=secrets)
        return make

    def go(self):
        self.run_.manifest['coverage'] = []
        self.run_._fetcher = self.fake_fetcher(self.run_)
        return self.run_.run_indicadores(self.src)

    def failed(self):
        return [c for c in self.run_.manifest['coverage'] if not c['ok']]

    def entries(self, series_id):
        return [e for e in self.run_.catalog.snapshot(self.SID) if e['observation']['series_id'] == series_id]

    def headers_of(self, url):
        return [{k.lower(): v for k, v in h.items()} for u, h in self.calls if u == url]


class BanxicoRun(_RunCase):
    SID = 'mx.banxico-sie'

    def default_routes(self):
        ids = [s['id'] for s in source(self.SID)['series']]
        routes = {BX + '/robots.txt': (302, b'', {'Location': BX_OLD + '/robots.txt'}), BX_OLD + '/robots.txt': (200, ROBOTS_BX, {}),
                  indicadores.BANXICO_META.format(series=','.join(ids)): (200, META, JSON_CT)}
        for s in source(self.SID)['series']:
            routes[self.datos_url(s['id'])] = (200, datos_for(s['id']), JSON_CT)
        return routes

    def datos_url(self, series_id):
        start = next(s['start'] for s in self.src['series'] if s['id'] == series_id) if hasattr(self, 'src') else \
            next(s['start'] for s in source(self.SID)['series'] if s['id'] == series_id)
        return indicadores.BANXICO_DATOS.format(series=series_id, start=start, end=TODAY.isoformat())

    def test_every_observation_is_catalogued_exactly_as_served(self):
        stats = self.go()
        self.assertEqual(self.failed(), [])
        es = self.entries('SF43718')
        self.assertEqual([e['observation']['value_printed'] for e in es],
                         ['N/E', '14.8290', 'N/E', 'N/E', '14.9469', '14.8479', '14.7936', '14.6274'])
        self.assertEqual({e['observation']['unit_printed'] for e in es}, {'Pesos por Dólar'})  # from the metadata
        e = next(x for x in es if x['observation']['date_printed'] == '02/01/2015')
        self.assertEqual((e['native_id'], e['url'], e['category']['doc_type'], e['category']['issuer']),
                         ('SF43718.02-01-2015', self.datos_url('SF43718'), 'INDICADOR ECONOMICO', 'Banco de México'))
        self.assertTrue(e['title'].endswith('Fecha de determinación (FIX)'))
        self.assertEqual((self.raw / e['raw_path']).read_bytes(), DATOS)  # the raw response, byte-exact
        self.assertEqual((stats['raw_stored'], stats['observations_served'], stats['entries_new']), (5, 32, 32))
        for x in self.run_.catalog.snapshot(self.SID):
            self.assertEqual(validate('catalog_entry', x), [], x['entry_id'])
        # the token went in Bmx-Token to the API, never to robots.txt; the robots redirect is in the manifest
        for url in [self.datos_url('SF43718'), indicadores.BANXICO_META.format(series='SF43718,SP68257,SF331451,SF43783')]:
            self.assertEqual([h.get('bmx-token') for h in self.headers_of(url)], [BTOK])
        self.assertEqual(self.headers_of(BX + '/robots.txt')[0].get('bmx-token'), None)
        self.assertEqual(self.run_.manifest['robots'][BX], {'url': BX_OLD + '/robots.txt', 'status': 200, 'redirects': 1})
        self.assertEqual(self.secrets_seen, [{BTOK: 'www.banxico.org.mx'}])  # the Fetcher refuses it anywhere else

    def test_the_requested_range_is_the_whole_history_to_today(self):
        self.go()
        asked = sorted(u for u, _ in self.calls if '/datos/' in u)
        self.assertEqual(asked, sorted(self.datos_url(s['id']) for s in self.src['series']))
        self.assertIn('/series/SF43718/datos/1991-11-12/2026-10-21', ' '.join(asked))

    def test_served_and_stored_must_match_or_the_run_fails(self):
        cases = {
            'a repeated date': with_datos(lambda d: d.append(dict(d[1]))),
            'a date the id cannot carry': with_datos(lambda d: d[0].update(fecha='2015-01-01')),
            'no observations': with_datos(lambda d: d.clear()),
            'a key repeated in the JSON (the parser keeps the last)': DATOS.replace(b'"datos": [', b'"datos": [], "datos": [', 1)
            .replace(b'"datos": [], "datos": [', b'"datos": [{"fecha": "31/12/2014", "dato": "N/E"}], "datos": [', 1),
        }
        for name, body in cases.items():
            with self.subTest(name):
                self.run_.catalog.entries.clear()
                self.routes[self.datos_url('SF43718')] = (200, body, JSON_CT)
                self.go()
                bad = [c for c in self.failed() if c['scope'].startswith('SF43718')]
                self.assertEqual(len(bad), 1, name)
                self.assertNotEqual(bad[0]['expected'], bad[0]['extracted'])
                self.assertEqual([c for c in self.failed() if not c['scope'].startswith('SF43718')], [])

    def test_without_the_served_unit_nothing_is_catalogued(self):
        self.routes[indicadores.BANXICO_META.format(series='SF43718,SP68257,SF331451,SF43783')] = (500, b'', {})
        self.go()
        self.assertEqual(self.run_.catalog.snapshot(self.SID), [])
        self.assertEqual(len(self.failed()), 4)

    def test_unchanged_rows_keep_their_raw_and_a_revision_appends_a_version(self):
        self.go()
        first = {e['entry_id']: e for e in self.entries('SF43718')}
        self.routes[self.datos_url('SF43718')] = (200, with_datos(lambda d: d[1].update(dato='14.8291')), JSON_CT)
        stats = self.go()
        self.assertEqual(self.failed(), [])
        self.assertEqual((stats['entries_new'], stats['entries_changed']), (0, 1))
        now = {e['entry_id']: e for e in self.entries('SF43718')}
        changed = 'mx.banxico-sie:SF43718.02-01-2015'
        self.assertEqual(now[changed]['observation']['value_printed'], '14.8291')
        self.assertEqual(len(now[changed]['versions']), 2)
        self.assertEqual({k: v for k, v in now.items() if k != changed}, {k: v for k, v in first.items() if k != changed})

    def test_an_observation_no_longer_served_fails_coverage(self):
        self.go()
        self.routes[self.datos_url('SF43718')] = (200, with_datos(lambda d: d.pop()), JSON_CT)
        self.go()
        self.assertEqual([(c['expected'], c['extracted']) for c in self.failed()], [(7, 8)])

    def test_a_response_that_echoes_the_token_is_not_stored(self):
        self.routes[self.datos_url('SP68257')] = (200, datos_for('SP68257').replace(b'Serie SP68257', BTOK.encode()), JSON_CT)
        self.go()
        self.assertEqual(self.entries('SP68257'), [])
        self.assertEqual(len(self.failed()), 1)
        for p in self.raw.rglob('*'):
            if p.is_file():
                self.assertNotIn(BTOK.encode(), p.read_bytes())
        self.assertNotIn(BTOK, json.dumps(self.run_.manifest))

    def test_without_a_valid_token_nothing_is_requested(self):
        for value in ('', BTOK[:40] + '\r\nX-Evil: 1'):
            with self.subTest(value=value[:10]), mock.patch.dict(os.environ, {'BANXICO_TOKEN': value}):
                self.calls.clear()
                self.go()
                self.assertEqual(self.calls, [])
                self.assertEqual(len(self.failed()), 4)


class InegiRun(_RunCase):
    SID = 'mx.inegi-bie'

    def urls(self):
        return indicadores.inegi_urls(self.src if hasattr(self, 'src') else source(self.SID), '628194', ITOK)

    def default_routes(self):
        (ind, _), (cl, _) = self.urls()
        return {IN + '/robots.txt': (200, b'User-Agent: *\nAllow: /app\n', {}), ind: (200, IND, JSON_CT), cl: (200, CL, JSON_CT)}

    def test_observations_with_the_official_description_and_no_token_recorded(self):
        stats = self.go()
        self.assertEqual(self.failed(), [])
        es = self.entries('628194')
        self.assertEqual([(e['observation']['date_printed'], e['observation']['value_printed']) for e in es],
                         [('2026/06', '100.000000'), ('2026/07', '100.500000'), ('2026/08', None), ('2026/09', '101.250000')])
        self.assertEqual({(e['title'], e['observation']['unit_printed']) for e in es}, {('Índice general', '96')})
        (ind, shown), (cl, cl_shown) = self.urls()
        self.assertIn(ITOK, ind)  # the documented syntax: the token is a path segment
        self.assertEqual(shown, ind.replace(ITOK, '<token>'))
        for e in es:
            self.assertEqual((e['url'], e['artifact']['url']), (shown, shown))
            self.assertEqual(validate('catalog_entry', e), [])
        self.assertEqual(stats['raw_stored'], 2)  # INDICATOR and CL_INDICATOR, byte-exact
        self.assertEqual((self.raw / stats['raw']['628194 CL_INDICATOR']).read_bytes(), CL)
        self.assertNotIn(ITOK, json.dumps(self.run_.manifest) + json.dumps(self.run_.catalog.snapshot()))
        self.assertEqual([u for u, _ in self.calls if ITOK in u], [cl, ind])  # only these two, both to www.inegi.org.mx
        self.assertEqual(self.secrets_seen, [{ITOK: 'www.inegi.org.mx'}])

    def test_a_refusal_or_an_error_page_is_recorded_without_the_token(self):
        (ind, _), (cl, _) = self.urls()
        self.routes[cl] = (302, b'', {'Location': ind.replace('https://', 'http://')})  # refused, and the refusal names the URL
        self.routes[ind] = (500, b'internal error for ' + ITOK.encode(), {})  # an error page that echoes it
        self.go()
        dump = json.dumps(self.run_.manifest)
        self.assertNotIn(ITOK, dump)
        self.assertIn('scheme or host not allowed: http://www.inegi.org.mx/', dump)
        self.assertIn('internal error for <token>', dump)

    def test_a_catalog_answer_for_another_indicator_stops_it(self):
        (_, _), (cl, _) = self.urls()
        self.routes[cl] = (200, CL.replace(b'"628194"', b'"628195"'), JSON_CT)
        self.go()
        self.assertEqual(self.entries('628194'), [])
        self.assertEqual(len(self.failed()), 1)

    def test_no_token_in_any_file_or_log_of_a_whole_run(self):
        (ind, _), (cl, _) = self.urls()
        self.routes[cl] = (302, b'', {'Location': ind.replace('https://', 'http://')})  # refused: names the URL
        self.routes[ind] = (500, b'internal error for ' + ITOK.encode(), {})  # an error page that echoes it
        bx = BanxicoRun.default_routes(BanxicoRun.__new__(BanxicoRun))
        self.routes.update(bx)
        log = io.StringIO()
        with mock.patch.object(Run, '_fetcher', lambda run_self, src, secrets=None: self.fake_fetcher(run_self)(src, secrets)), \
                contextlib.redirect_stdout(log):
            rc = main(['--country', 'mx', '--out', str(self.out), '--raw', str(self.raw), '--today', TODAY.isoformat(),
                       '--sources', 'mx.banxico-sie,mx.inegi-bie'])
        self.assertEqual(rc, 3)  # INEGI did not reconcile; Banxico did
        written = [p for p in Path(self.tmp.name).rglob('*') if p.is_file()]
        self.assertTrue(any(p.name.endswith('.json') and 'runs' in p.parts for p in written))
        self.assertTrue(list((self.out / 'mx' / 'banxico-sie').glob('*.jsonl')))
        for p in written:
            for tok in (BTOK, ITOK):
                self.assertNotIn(tok.encode(), p.read_bytes(), p)
        for tok in (BTOK, ITOK):
            self.assertNotIn(tok, log.getvalue())
        manifest = json.loads(next((self.out / 'mx' / 'runs').glob('*.json')).read_text(encoding='utf-8'))
        self.assertIn('<token>', json.dumps(manifest))  # the refusal and the error page were recorded, redacted


class Wiring(unittest.TestCase):
    def test_a_crash_message_never_carries_the_token(self):
        def boom(self_, src):
            raise RuntimeError(f'boom {os.environ["INEGI_TOKEN"]}')
        log = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {'INEGI_TOKEN': ITOK}), \
                mock.patch.object(Run, 'run_indicadores', boom), contextlib.redirect_stdout(log):
            rc = main(['--country', 'mx', '--out', tmp + '/o', '--raw', tmp + '/r', '--sources', 'mx.inegi-bie'])
            text = next(Path(tmp, 'o', 'mx', 'runs').glob('*.json')).read_text(encoding='utf-8')
        self.assertEqual(rc, 1)
        self.assertIn('boom <token>', text)
        self.assertNotIn(ITOK, text + log.getvalue())

    def test_the_run_fetcher_logs_robots_and_binds_the_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Run('MX', tmp + '/o', tmp + '/r', None, TODAY, 0, 0)
            f = run._fetcher(source('mx.banxico-sie'), secrets={BTOK: 'www.banxico.org.mx'})
        self.assertIs(f.robots_log, run.manifest['robots'])
        self.assertEqual(f.secrets, {BTOK: 'www.banxico.org.mx'})

    def test_trial_sources_run_only_when_named(self):
        ran = []
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(Run, 'run_indicadores', lambda self_, s: ran.append(s['source_id']) or {}), \
                mock.patch.object(Run, 'run_sidof', lambda self_, s: {}), mock.patch.object(Run, 'run_leyesbiblio', lambda self_, s: {}), \
                mock.patch.object(Run, 'run_ojn', lambda self_, s: {}), mock.patch.object(Run, 'run_ojn_municipal', lambda self_, s: {}), \
                mock.patch.object(Run, 'run_hf_tesis', lambda self_, s: {}):
            manifest = Run('MX', tmp + '/o', tmp + '/r', None, TODAY, 0, 0, parallel=False).execute()
            self.assertEqual(ran, [])  # the scheduled run (no --sources) never reaches a trial source
            self.assertNotIn('mx.banxico-sie', manifest['planned_sources'])  # trial is not 'planned': it has no blocker
            Run('MX', tmp + '/o', tmp + '/r', None, TODAY, 0, 0, parallel=False).execute({'mx.banxico-sie', 'mx.inegi-bie'})
        self.assertEqual(sorted(ran), ['mx.banxico-sie', 'mx.inegi-bie'])

    def test_a_series_id_is_active_only_when_an_official_page_confirms_it(self):
        official = {'mx.banxico-sie': ('https://www.banxico.org.mx/',), 'mx.inegi-bie': ('https://www.inegi.org.mx/',)}
        for src in registry()['sources']:
            if 'series' not in src:
                continue
            with self.subTest(src['source_id']):
                self.assertIn(src['status'], ('trial', 'active'))
                self.assertIn(src['token_host'], src['allowed_hosts'])
                for s in src['series']:
                    self.assertTrue(indicadores.valid_series(s['id']), s['id'])
                    self.assertTrue(all(u.startswith(official[src['source_id']]) for u in s['confirmed_by']), s['id'])
                    if src['status'] == 'active':
                        self.assertTrue(s['confirmed_by'], f"{s['id']}: an unconfirmed id never goes active")
                    if src['adapter'] == 'banxico-sie':
                        self.assertEqual(date.fromisoformat(s['start']).isoformat(), s['start'])
        self.assertTrue(all(s['confirmed_by'] for s in source('mx.banxico-sie')['series']))
        self.assertEqual([s['confirmed_by'] for s in source('mx.inegi-bie')['series']], [[]])  # HIPÓTESIS, see id_status

    def test_observations_go_one_file_per_series_and_load_back(self):
        src = source('mx.banxico-sie')
        art = {'artifact_id': 'SA-' + 'a' * 24, 'url': BX + '/x', 'retrieved_at': '2026-10-21T00:00:00Z', 'sha256': 'a' * 64,
               'bytes': 1, 'media_type': 'application/json', 'source_type': 'primary_official', 'publisher': 'Banco de México',
               'license': 'x', 'redistribution': 'allowed', 'stored_at': 'local_corpus'}
        with tempfile.TemporaryDirectory() as tmp:
            cat = Catalog(tmp, 'MX')
            for i, (sid, d) in enumerate((('SF43718', '02/01/2015'), ('SP68257', '04/04/1995')), 1):
                cat.upsert(indicadores.entry(src, 'MX', sid, 't', 'u', i, d, '1.0', BX + '/x', art,
                                             'sha256/aa/' + 'a' * 64 + '.json', '2026-10-21T00:00:00Z'))
            cat.write()
            files = sorted(p.relative_to(Path(tmp) / 'mx').as_posix() for p in (Path(tmp) / 'mx').rglob('*.jsonl'))
            self.assertEqual(files, ['banxico-sie/SF43718.jsonl', 'banxico-sie/SP68257.jsonl'])
            self.assertEqual(Catalog(tmp, 'MX').entries, cat.entries)

    def test_a_computed_value_does_not_fit_the_schema(self):
        src = source('mx.inegi-bie')
        e = indicadores.entry(src, 'MX', '628194', 't', '96', 1, '2026/09', '101.250000', IN + '/x',
                              {'artifact_id': 'SA-' + 'b' * 24, 'url': IN + '/x', 'retrieved_at': '2026-10-21T00:00:00Z',
                               'sha256': 'b' * 64, 'bytes': 1, 'media_type': 'application/json',
                               'source_type': 'primary_official', 'publisher': 'INEGI', 'license': 'x',
                               'redistribution': 'allowed', 'stored_at': 'local_corpus'},
                              'sha256/bb/' + 'b' * 64 + '.json', '2026-10-21T00:00:00Z')
        self.assertEqual(validate('catalog_entry', e), [])
        for bad in ({'value_printed': 101.25}, {'variation': '0.5'}, {'date_printed': '2026-09-01'}):
            with self.subTest(bad=bad):
                self.assertTrue(validate('catalog_entry', {**e, 'observation': {**e['observation'], **bad}}))

    def test_the_tokens_reach_only_the_dispatch_job_steps_that_need_them(self):
        wf = yaml.safe_load((ROOT / '.github' / 'workflows' / 'indicadores-mx.yml').read_text(encoding='utf-8'))
        self.assertEqual(list(wf.get('on') or wf.get(True)), ['workflow_dispatch'])  # never on a schedule
        self.assertEqual(wf['permissions'], {'contents': 'read'})
        steps = wf['jobs']['run']['steps']
        with_tokens = [s.get('name') for s in steps if 'TOKEN' in json.dumps(s.get('env', {}))]
        self.assertEqual(with_tokens, ['Indicators run (trial sources)', 'No token in anything that is uploaded'])
        run = next(s for s in steps if s.get('id') == 'ind')
        self.assertEqual((run['env']['BANXICO_TOKEN'], run['env']['INEGI_TOKEN'], run['env']['SOURCES']),
                         ('${{ secrets.BANXICO_TOKEN }}', '${{ secrets.INEGI_TOKEN }}', '${{ inputs.sources }}'))
        names = [s.get('name') for s in steps]
        self.assertLess(names.index('No token in anything that is uploaded'), names.index('Upload raw responses, catalog rows and manifest'))
        for s in steps:
            if 'uses' in s:
                self.assertRegex(s['uses'], r'^[\w.-]+/[\w.-]+@[0-9a-f]{40}$')
        sched = (ROOT / '.github' / 'workflows' / 'catalog-mx.yml').read_text(encoding='utf-8')
        self.assertNotIn('BANXICO_TOKEN', sched)
        self.assertNotIn('INEGI_TOKEN', sched)


if __name__ == '__main__':
    unittest.main()
