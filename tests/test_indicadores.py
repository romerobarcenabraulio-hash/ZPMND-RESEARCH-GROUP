"""Calculation indicators (Banxico SIE, INEGI BIE): parsers, verbatim entries, coverage, token handling, wiring.

BANXICO FIXTURES ARE REAL BYTES of the first real run: workflow indicadores-mx, run 39709378896 (2026-10-22T02:06Z,
artifact indicadores-mx-39709378896-1), copied unedited from that run's RawStore (raw/sha256/<2>/<sha256>.json):
- banxico_sie_metadatos_2026-10-22.json, 1,058 bytes,
  sha256 6a05641d6412fd8aaab2589e5cf800a95643d092ffc2441334a4a8c8471268c4:
  the answer to GET series/SF43718,SP68257,SF331451,SF43783 (metadata of the four series, served in its own order).
- banxico_sie_datos_SF43783_2026-10-22.json, 311,383 bytes,
  sha256 d98bcf18b512b405dc58b349258e6a84c96cf8dfd230376da784f6a7e1e40a3d:
  the answer to GET series/SF43783/datos/1995-03-23/2026-10-21 (TIIE a 28 días): 7,943 observations, 200 of them
  "N/E". Chosen over SF331451 (204,693 bytes) because it is the only real answer that serves "N/E". The other three
  series are played here by these same bytes with only idSerie relabelled (datos_for).
That run reconciled all four series (SF43718 8783/8783, SP68257 11524/11524, SF331451 5231/5231, SF43783 7943/7943).

THE INEGI FIXTURE IS REAL BYTES too: workflow indicadores-mx, run 39877667471 (2026-10-23, branch inegi-fuente, fuente
BIE-BISE, artifact indicadores-mx-39877667471-1), copied unedited from that run's RawStore:
- inegi_bie_indicator_910392_2026-10-23.json, 102,668 bytes,
  sha256 8ad0a8b1013348720e34fb6804d24d7ebb35481f5deac78338ac2458308f2710: INDICATOR 910392 (INPC, índice general),
  693 monthly observations from 1969/01 to 2026/09, newest first. 2026/09 is 146.07499999999999000000 and 2026/08
  145.46199999999999000000; INEGI's note in the DOF of 2026-10-09 (5800864) prints 146.075 and 145.462.
CL_INDICATOR answered 401 in every run, so there is no real catalog answer and none is requested.
banxico_robots_2026-10-21.txt is real (anterior.banxico.org.mx/robots.txt). No network: a fake opener plays both hosts.
"""
import contextlib
import hashlib
import io
import json
import os
import re
import subprocess
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
# Real bytes of run 39709378896 (see the module docstring); the sha256 is the name the run's RawStore gave each one.
REAL = {'banxico_sie_metadatos_2026-10-22.json': '6a05641d6412fd8aaab2589e5cf800a95643d092ffc2441334a4a8c8471268c4',
        'banxico_sie_datos_SF43783_2026-10-22.json': 'd98bcf18b512b405dc58b349258e6a84c96cf8dfd230376da784f6a7e1e40a3d',
        'inegi_bie_indicator_910392_2026-10-23.json': '8ad0a8b1013348720e34fb6804d24d7ebb35481f5deac78338ac2458308f2710'}
META = (FIX / 'banxico_sie_metadatos_2026-10-22.json').read_bytes()
DATOS = (FIX / 'banxico_sie_datos_SF43783_2026-10-22.json').read_bytes()
SERVED_N, NE_N = 7943, 200  # observations and "N/E" values in DATOS, as the run counted them
IND = (FIX / 'inegi_bie_indicator_910392_2026-10-23.json').read_bytes()
INPC, IND_N = '910392', 693  # the key and the observations IND serves
JSON_CT = {'content-type': 'application/json;charset=UTF-8'}
META_URL = indicadores.BANXICO_META.format(series='SF43718,SP68257,SF331451,SF43783')
TIIE28 = 'TIIE a 28 días Tasa de interés en por ciento anual'  # the titulo SF43783 is served with
SCAN = 'No token in anything that is committed or uploaded'  # the token-scan step of catalog-mx.yml


def registry():
    return json.loads((ROOT / 'sources' / 'mx.json').read_text(encoding='utf-8'))


def source(sid):
    return next(s for s in registry()['sources'] if s['source_id'] == sid)


def datos_url(series_id):
    start = next(s['start'] for s in source('mx.banxico-sie')['series'] if s['id'] == series_id)
    return indicadores.BANXICO_DATOS.format(series=series_id, start=start, end=TODAY.isoformat())


def datos_for(series_id, body=DATOS):
    """The real SF43783 answer played for another series: only idSerie changes, every other byte is the real one."""
    return body.replace(b'"idSerie":"SF43783"', f'"idSerie":"{series_id}"'.encode(), 1)


def with_datos(edit, body=DATOS):
    """The real answer with one edit, written back in the API's own compact form: no other byte changes
    (Parsers.test_the_fixtures_are_the_real_bytes_unedited checks that an empty edit gives the real bytes back)."""
    doc = json.loads(body)
    edit(doc['bmx']['series'][0]['datos'])
    return json.dumps(doc, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def first(n):
    """The first n real observations of DATOS: for tests about tokens, not volume."""
    def cut(datos):
        del datos[n:]
    return with_datos(cut)


class Parsers(unittest.TestCase):
    def test_the_fixtures_are_the_real_bytes_unedited(self):
        for name, sha in REAL.items():
            self.assertEqual(hashlib.sha256((FIX / name).read_bytes()).hexdigest(), sha, name)
        self.assertEqual(with_datos(lambda d: None), DATOS)  # an edited variant differs from the real bytes only by its edit
        self.assertEqual(datos_for('SF43783'), DATOS)

    def test_banxico_values_and_dates_are_the_served_text(self):
        title, obs = indicadores.parse_banxico_datos(DATOS, 'SF43783')
        self.assertEqual(title, TIIE28)
        self.assertEqual(obs[:3], [('23/03/1995', '90.5000'), ('24/03/1995', 'N/E'), ('27/03/1995', 'N/E')])
        self.assertEqual(obs[-1], ('21/10/2026', '6.7760'))
        self.assertEqual((len(obs), indicadores.served_count(DATOS, 'fecha')), (SERVED_N, SERVED_N))
        # As served: every date dd/mm/yyyy; every value a JSON string, "N/E" or a number with 4 decimals, never parsed.
        self.assertTrue(all(re.fullmatch(r'\d{2}/\d{2}/\d{4}', d) for d, _ in obs))
        self.assertTrue(all(v == 'N/E' or re.fullmatch(r'\d{1,2}\.\d{4}', v) for _, v in obs))
        self.assertNotRegex(DATOS, rb'"dato":[^"]')
        ne = [d for d, v in obs if v == 'N/E']  # all of them in the series' first year
        self.assertEqual((len(ne), ne[0], ne[-1]), (NE_N, '24/03/1995', '27/03/1996'))

    def test_banxico_metadata_is_read_by_series_not_by_position(self):
        # Served in its own order, not the requested one (SF43718,SP68257,SF331451,SF43783).
        self.assertEqual([s['idSerie'] for s in json.loads(META)['bmx']['series']], ['SP68257', 'SF43718', 'SF331451', 'SF43783'])
        meta = indicadores.parse_banxico_meta(META)
        self.assertEqual({k: v['unidad'] for k, v in meta.items()},
                         {'SF43718': 'Pesos por Dólar', 'SP68257': 'Unidades de Inversión', 'SF331451': 'Porcentajes',
                          'SF43783': 'Sin Unidad'})
        # Titles are kept verbatim, SF43718's run of 42 spaces included.
        self.assertEqual(meta['SF43718']['titulo'], 'Tipo de cambio' + ' ' * 42 + 'Pesos por dólar E.U.A. Tipo de cambio para '
                         'solventar obligaciones denominadas en moneda extranjera Fecha de determinación (FIX)')
        self.assertEqual(meta['SF43783']['titulo'], TIIE28)
        self.assertEqual(indicadores.served_count(META, 'fecha'), 0)  # its fechaInicio and fechaFin are no observations

    def test_numbers_keep_their_literal_text(self):
        body = b'{"bmx":{"series":[{"idSerie":"SF43718","titulo":"t","datos":[{"fecha":"02/01/2015","dato":14.8290},' \
               b'{"fecha":"05/01/2015","dato":15}]}]}}'
        self.assertEqual(indicadores.parse_banxico_datos(body, 'SF43718')[1], [('02/01/2015', '14.8290'), ('05/01/2015', '15')])
        ind = IND.replace(b'"OBS_VALUE":"146.07499999999999000000"', b'"OBS_VALUE":146.07499999999999000000') \
                 .replace(b'"INDICADOR":"910392"', b'"INDICADOR":910392')
        self.assertNotEqual(ind, IND)
        self.assertEqual(indicadores.parse_inegi_indicator(ind, INPC)[1][0], ('2026/09', '146.07499999999999000000'))

    def test_a_response_for_another_or_for_several_series_is_refused(self):
        example = json.loads(DATOS)
        example['bmx']['series'].append(dict(example['bmx']['series'][0], idSerie='SF61745'))
        for body, sid in ((DATOS, 'SP68257'), (json.dumps(example).encode(), 'SF43783'), (b'[]', 'SF43718'),
                          (b'{"bmx": {"series": [{"idSerie": "SF43718"}]}}', 'SF43718')):
            with self.subTest(sid=sid, body=body[:30]), self.assertRaises(ValueError):
                indicadores.parse_banxico_datos(body, sid)
        with self.assertRaises(ValueError):
            indicadores.parse_inegi_indicator(IND, '628194')

    def test_inegi_unit_and_values_are_the_served_text(self):
        unit, obs = indicadores.parse_inegi_indicator(IND, INPC)
        self.assertEqual((unit, len(obs), len(dict(obs))), ('1051', IND_N, IND_N))
        by = dict(obs)
        # INEGI's note in the DOF of 2026-10-09 (5800864): "... del mes de septiembre de 2026 es 146.075 ... agosto de
        # 2026, que fue de 145.462": the same values, as the API serves them.
        self.assertEqual((by['2026/09'], by['2026/08']), ('146.07499999999999000000', '145.46199999999999000000'))
        self.assertEqual((obs[0][0], obs[-1][0]), ('2026/09', '1969/01'))  # newest first, as served
        self.assertEqual(indicadores.served_count(IND, 'TIME_PERIOD'), IND_N)

    def test_the_served_count_reads_bytes_not_the_parser(self):
        body = b'{"bmx":{"series":[{"idSerie":"SF1","fechaInicio":"x","datos":[{"fecha" : "01/01/2015","dato":"1"},' \
               b'{"fecha":"02/01/2015","dato":"2"}]}]}}'
        self.assertEqual(indicadores.served_count(body, 'fecha'), 2)  # "fechaInicio" is not an observation

    def test_ids_are_identifiers_and_dates_stay_verbatim(self):
        self.assertEqual(indicadores.native_id('SF43783', '24/03/1995'), 'SF43783.24-03-1995')
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

    def default_routes(self, body=DATOS):
        routes = {BX + '/robots.txt': (302, b'', {'Location': BX_OLD + '/robots.txt'}), BX_OLD + '/robots.txt': (200, ROBOTS_BX, {}),
                  META_URL: (200, META, JSON_CT)}
        for s in source(self.SID)['series']:
            routes[datos_url(s['id'])] = (200, datos_for(s['id'], body), JSON_CT)
        return routes

    def datos_url(self, series_id):
        return datos_url(series_id)

    def test_every_observation_is_catalogued_exactly_as_served(self):
        stats = self.go()
        self.assertEqual(self.failed(), [])
        es = sorted(self.entries('SF43783'), key=lambda x: x['listing']['page_order'])
        served = [(o['fecha'], o['dato']) for o in json.loads(DATOS)['bmx']['series'][0]['datos']]  # read apart from the parser
        self.assertEqual([(e['observation']['date_printed'], e['observation']['value_printed']) for e in es], served)
        self.assertEqual(sum(e['observation']['value_printed'] == 'N/E' for e in es), NE_N)  # "N/E" is kept as served
        # Each series takes the unit of its own metadata row, although the metadata came in another order.
        self.assertEqual({sid: {e['observation']['unit_printed'] for e in self.entries(sid)}
                          for sid in ('SF43718', 'SP68257', 'SF331451', 'SF43783')},
                         {'SF43718': {'Pesos por Dólar'}, 'SP68257': {'Unidades de Inversión'}, 'SF331451': {'Porcentajes'},
                          'SF43783': {'Sin Unidad'}})
        e = next(x for x in es if x['observation']['date_printed'] == '24/03/1995')
        self.assertEqual((e['native_id'], e['url'], e['category']['doc_type'], e['category']['issuer'], e['title']),
                         ('SF43783.24-03-1995', self.datos_url('SF43783'), 'INDICADOR ECONOMICO', 'Banco de México', TIIE28))
        self.assertEqual((self.raw / e['raw_path']).read_bytes(), DATOS)  # the raw response, byte-exact
        self.assertEqual((stats['raw_stored'], stats['observations_served'], stats['entries_new']), (5, 4 * SERVED_N, 4 * SERVED_N))
        # The schema, on one row per distinct shape of the real bytes plus the first and the last row: every row costs
        # ~3 s per 7,943 here, and the real run already validated all 33,481 rows it wrote (none quarantined).
        shapes = {}
        for x in es:
            shapes.setdefault(tuple(re.sub(r'\d', '9', x['observation'][k]) for k in ('date_printed', 'value_printed')), x)
        self.assertEqual(sorted(shapes), [('99/99/9999', '9.9999'), ('99/99/9999', '99.9999'), ('99/99/9999', 'N/E')])
        for x in [*shapes.values(), es[0], es[-1]]:
            self.assertEqual(validate('catalog_entry', x), [], x['entry_id'])
        # the token went in Bmx-Token to the API, never to robots.txt; the robots redirect is in the manifest
        for url in [self.datos_url('SF43783'), META_URL]:
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
            'a date the id cannot carry': with_datos(lambda d: d[0].update(fecha='1995-03-23')),
            'no observations': with_datos(lambda d: d.clear()),
            'a key repeated in the JSON (the parser keeps the last)':
                DATOS.replace(b'"datos":[', b'"datos":[{"fecha":"22/03/1995","dato":"N/E"}],"datos":[', 1),
        }
        for name, body in cases.items():
            with self.subTest(name):
                self.run_.catalog.entries.clear()
                self.routes[self.datos_url('SF43783')] = (200, body, JSON_CT)
                self.go()
                bad = [c for c in self.failed() if c['scope'].startswith('SF43783')]
                self.assertEqual(len(bad), 1, name)
                self.assertNotEqual(bad[0]['expected'], bad[0]['extracted'])
                self.assertEqual([c for c in self.failed() if not c['scope'].startswith('SF43783')], [])

    def test_without_the_served_unit_nothing_is_catalogued(self):
        self.routes[META_URL] = (500, b'', {})
        self.go()
        self.assertEqual(self.run_.catalog.snapshot(self.SID), [])
        self.assertEqual(len(self.failed()), 4)

    def test_unchanged_rows_keep_their_raw_and_a_revision_appends_a_version(self):
        self.go()
        before = {e['entry_id']: e for e in self.entries('SF43783')}
        self.routes[self.datos_url('SF43783')] = (200, with_datos(lambda d: d[1].update(dato='89.9900')), JSON_CT)  # was N/E
        stats = self.go()
        self.assertEqual(self.failed(), [])
        self.assertEqual((stats['entries_new'], stats['entries_changed']), (0, 1))
        now = {e['entry_id']: e for e in self.entries('SF43783')}
        changed = 'mx.banxico-sie:SF43783.24-03-1995'
        self.assertEqual((before[changed]['observation']['value_printed'], now[changed]['observation']['value_printed']), ('N/E', '89.9900'))
        self.assertEqual(len(now[changed]['versions']), 2)
        self.assertEqual({k: v for k, v in now.items() if k != changed}, {k: v for k, v in before.items() if k != changed})

    def test_an_observation_no_longer_served_fails_coverage(self):
        self.go()
        self.routes[self.datos_url('SF43783')] = (200, with_datos(lambda d: d.pop()), JSON_CT)
        self.go()
        self.assertEqual([(c['expected'], c['extracted']) for c in self.failed()], [(SERVED_N - 1, SERVED_N)])

    def test_a_response_that_echoes_the_token_is_not_stored(self):
        self.routes[self.datos_url('SP68257')] = (200, datos_for('SP68257').replace(TIIE28.encode(), BTOK.encode()), JSON_CT)
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
        return indicadores.inegi_url(self.src if hasattr(self, 'src') else source(self.SID), INPC, ITOK)

    def default_routes(self):
        ind, _ = self.urls()
        return {IN + '/robots.txt': (200, b'User-Agent: *\nAllow: /app\n', {}), ind: (200, IND, JSON_CT)}

    def test_observations_with_the_confirmed_title_and_no_token_recorded(self):
        stats = self.go()
        self.assertEqual(self.failed(), [])
        es = self.entries(INPC)
        self.assertEqual(len(es), IND_N)
        by = {e['observation']['date_printed']: e['observation']['value_printed'] for e in es}
        self.assertEqual((by['2026/09'], by['2024/07']), ('146.07499999999999000000', '136.00299999999999000000'))
        title = source(self.SID)['series'][0]['title']  # copied from the DOF note in confirmed_by
        self.assertEqual({(e['title'], e['observation']['unit_printed']) for e in es}, {(title, '1051')})
        ind, shown = self.urls()
        self.assertIn(ITOK, ind)  # the documented syntax: the token is a path segment
        self.assertEqual(shown, ind.replace(ITOK, '<token>'))
        for e in es[:20]:
            self.assertEqual((e['url'], e['artifact']['url']), (shown, shown))
            self.assertEqual(validate('catalog_entry', e), [])
        self.assertEqual(stats['raw_stored'], 1)  # INDICATOR, byte-exact
        self.assertEqual((self.raw / stats['raw'][INPC]).read_bytes(), IND)
        self.assertNotIn(ITOK, json.dumps(self.run_.manifest) + json.dumps(self.run_.catalog.snapshot()))
        self.assertEqual([u for u, _ in self.calls if ITOK in u], [ind])  # INDICATOR only: CL_INDICATOR answers 401 to us
        self.assertEqual(self.secrets_seen, [{ITOK: 'www.inegi.org.mx'}])

    def test_an_unconfirmed_key_is_fetched_but_never_catalogued(self):
        self.src = {**self.src, 'series': [{**self.src['series'][0], 'confirmed_by': []}]}  # its title stays: not enough
        self.go()
        self.assertEqual(self.entries(INPC), [])
        self.assertEqual(len(self.failed()), 1)

    def test_a_refusal_or_an_error_page_is_recorded_without_the_token(self):
        ind, _ = self.urls()
        for route, recorded in (((302, b'', {'Location': ind.replace('https://', 'http://')}),  # the refusal names the URL
                                 'scheme or host not allowed: http://www.inegi.org.mx/'),
                                ((500, b'internal error for ' + ITOK.encode(), {}), 'internal error for <token>')):
            with self.subTest(recorded):
                self.routes[ind] = route
                self.go()
                dump = json.dumps(self.run_.manifest)
                self.assertNotIn(ITOK, dump)
                self.assertIn(recorded, dump)

    def test_no_token_in_any_file_or_log_of_a_whole_run(self):
        ind, _ = self.urls()
        self.routes[ind] = (500, b'internal error for ' + ITOK.encode(), {})  # an error page that echoes it
        bx = BanxicoRun.default_routes(BanxicoRun.__new__(BanxicoRun), first(3))  # tokens, not volume, are checked here
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
            def with_inegi_trial():  # both indicator sources are active now; the rule is checked on a trial copy
                run = Run('MX', tmp + '/o', tmp + '/r', None, TODAY, 0, 0, parallel=False)
                next(s for s in run.registry['sources'] if s['source_id'] == 'mx.inegi-bie')['status'] = 'trial'
                return run
            manifest = with_inegi_trial().execute()
            # the scheduled run (no --sources) reaches the active indicator source and never the trial one
            self.assertEqual(ran, ['mx.banxico-sie'])
            self.assertNotIn('mx.inegi-bie', manifest['planned_sources'])  # trial is not 'planned': it has no blocker
            ran.clear()
            with_inegi_trial().execute({'mx.banxico-sie', 'mx.inegi-bie'})
        self.assertEqual(sorted(ran), ['mx.banxico-sie', 'mx.inegi-bie'])
        self.assertEqual((source('mx.banxico-sie')['status'], source('mx.inegi-bie')['status']), ('active', 'active'))

    def test_an_active_indicator_source_is_tested_on_real_bytes(self):
        # trial -> active only once a real run has served real bytes: an active source keeps no fixture built from the
        # docs, and its real fixtures are byte for byte what that run stored (Parsers checks their sha256).
        prefix = {'banxico-sie': 'banxico_', 'inegi-bie': 'inegi_'}
        active = [s for s in registry()['sources'] if 'series' in s and s['status'] == 'active']
        self.assertEqual([s['source_id'] for s in active], ['mx.banxico-sie', 'mx.inegi-bie'])
        for src in active:
            self.assertEqual(sorted(p.name for p in FIX.glob(prefix[src['adapter']] + '*CONSTRUIDO*')), [], src['source_id'])
        self.assertEqual(sorted(p.name for p in [*FIX.glob('banxico_sie_*.json'), *FIX.glob('inegi_bie_*.json')]), sorted(REAL))

    def test_a_series_id_is_active_only_when_an_official_page_confirms_it(self):
        # INEGI publishes the INPC in the DOF by law (LSNIEG art. 59 III a; CFF 20 and 20-bis): a note there confirms a key
        official = {'mx.banxico-sie': ('https://www.banxico.org.mx/',),
                    'mx.inegi-bie': ('https://www.inegi.org.mx/', 'https://sidof.segob.gob.mx/notas/docFuente/')}
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
        self.assertTrue(all(s['confirmed_by'] and s['title'] for s in source('mx.inegi-bie')['series']))

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

    def test_the_tokens_reach_only_the_steps_that_need_them(self):
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
        # The scheduled run fetches both active indicator sources: each token reaches the catalog step and the scan that
        # runs before anything is uploaded or committed, and no other step.
        steps = yaml.safe_load((ROOT / '.github' / 'workflows' / 'catalog-mx.yml').read_text(encoding='utf-8'))['jobs']['run']['steps']
        names = [s.get('name') for s in steps]
        catalog = next(s for s in steps if s.get('id') == 'catalog')
        for tok in ('BANXICO_TOKEN', 'INEGI_TOKEN'):
            self.assertEqual([s.get('name') for s in steps if tok in json.dumps(s.get('env', {}))], [catalog['name'], SCAN], tok)
            self.assertEqual(catalog['env'][tok], '${{ secrets.%s }}' % tok)
        scan = names.index(SCAN)
        self.assertLess(names.index(catalog['name']), scan)
        self.assertLess(scan, min(i for i, n in enumerate(names) if n and n.startswith(('Upload raw bundle', 'Commit catalog'))))

    @staticmethod
    def scan(wf_name, step_name, cwd):
        """Exit code of a workflow's token-scan step, run as GitHub runs it (bash -eo pipefail) in `cwd`."""
        wf = yaml.safe_load((ROOT / '.github' / 'workflows' / wf_name).read_text(encoding='utf-8'))
        script = next(s for s in wf['jobs']['run']['steps'] if s.get('name') == step_name)['run']
        return subprocess.run(['bash', '--noprofile', '--norc', '-eo', 'pipefail', '-c', script], cwd=cwd, capture_output=True,
                              env={'PATH': os.environ.get('PATH', ''), 'BANXICO_TOKEN': BTOK, 'INEGI_TOKEN': ITOK}).returncode

    def test_the_token_scan_stops_an_output_that_holds_a_token(self):
        for wf_name, step_name, folders in (('catalog-mx.yml', SCAN, ('data', 'raw')),
                                            ('indicadores-mx.yml', 'No token in anything that is uploaded', ('out', 'raw'))):
            for holder in (None,) + folders:
                with self.subTest(wf_name, holder=holder), tempfile.TemporaryDirectory() as tmp:
                    for d in folders:
                        Path(tmp, d, 'mx').mkdir(parents=True)
                        Path(tmp, d, 'mx', 'x.json').write_bytes(DATOS)
                    if holder:
                        Path(tmp, holder, 'mx', 'y.json').write_text(f'{{"url": "x/{BTOK}"}}', encoding='utf-8')
                    self.assertEqual(self.scan(wf_name, step_name, tmp), 1 if holder else 0)
                with self.subTest(wf_name, token='INEGI'), tempfile.TemporaryDirectory() as tmp:
                    for d in folders:
                        Path(tmp, d, 'mx').mkdir(parents=True)
                    Path(tmp, folders[-1], 'mx', 'y.json').write_text(f'{{"url": "x/{ITOK}"}}', encoding='utf-8')
                    self.assertEqual(self.scan(wf_name, step_name, tmp), 1)
        with tempfile.TemporaryDirectory() as tmp:  # a run with no new raw files leaves no raw folder: nothing to stop
            Path(tmp, 'data').mkdir()
            self.assertEqual(self.scan('catalog-mx.yml', SCAN, tmp), 0)


if __name__ == '__main__':
    unittest.main()
