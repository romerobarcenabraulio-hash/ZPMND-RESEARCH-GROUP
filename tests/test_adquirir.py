"""rg/adquirir.py and .github/workflows/adquirir.yml: a source is loaded by its `api` declaration with no code of its own;
raw first, records squared with the declared size, the credential only in a header to the source's host."""
import copy
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from rg import adquirir as q
from rg import sondeo
from rg.catalog.fetch import BudgetExhausted, FetchRefused, Response

ROOT = Path(__file__).resolve().parents[1]
FUENTES = {f['source_id']: f for _, f in sondeo.cargar(ROOT / 'sources' / 'registro')}
TEMAS = FUENTES['int.openalex-temas']
KEY = 'oa-TEST-0000-key'
AHORA = lambda: '2026-11-01T00:00:00Z'  # noqa: E731


def pagina(ids, siguiente, count=None):
    return json.dumps({'meta': {'count': count, 'next_cursor': siguiente}, 'results': [{'id': i, 'display_name': i} for i in ids]}).encode()


class Falso:
    """Answers like the API: the contador first, then the pages in order; records every URL and auth it was asked."""
    def __init__(self, cuerpos, declarado=3, status=200):
        self.cuerpos, self.pedidos, self.declarado, self.status = list(cuerpos), [], declarado, status

    def get(self, url, auth=None):
        self.pedidos.append((url, auth))
        if 'per-page=1' in url and 'cursor' not in url:
            return Response(200, json.dumps({'meta': {'count': self.declarado}}).encode(), url)
        cuerpo = self.cuerpos.pop(0)
        if isinstance(cuerpo, BaseException):
            raise cuerpo
        return Response(self.status, cuerpo, url)


class Api(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.out = Path(self.t.name)

    def run_(self, cuerpos, fuente=TEMAS, entorno=None, declarado=3, **kw):
        self.fx = Falso(cuerpos, declarado, **{k: kw.pop(k) for k in ('status',) if k in kw})
        return q.adquirir(fuente, self.out, entorno={'OPENALEX_API_KEY': KEY} if entorno is None else entorno,
                          nuevo_fetcher=lambda: self.fx, ahora=AHORA, **kw)

    def registros(self, sid='int.openalex-temas'):
        out = []
        for f in sorted((self.out / sid / 'registros').glob('*.jsonl.gz')):
            with gzip.open(f, 'rt') as fh:
                out += [json.loads(line)['id'] for line in fh]
        return out

    def test_cursor_pages_until_the_last_one_and_squares_with_the_declared_size(self):
        m = self.run_([pagina(['T1', 'T2'], 'c2'), pagina(['T3'], None)])
        self.assertEqual((m['estado'], m['declarado'], m['distintos'], len(m['paginas'])), ('completo', 3, 3, 2))
        self.assertEqual(self.registros(), ['T1', 'T2', 'T3'])
        urls = [u for u, _ in self.fx.pedidos[1:]]
        self.assertIn('cursor=%2A', urls[0]); self.assertIn('per-page=100', urls[0]); self.assertIn('select=id', urls[0])
        self.assertIn('cursor=c2', urls[1])

    def test_every_page_is_kept_raw_by_its_sha256_before_it_is_read(self):
        cuerpos = [pagina(['T1', 'T2'], 'c2'), pagina(['T3'], None)]
        m = self.run_(list(cuerpos))
        import hashlib
        for p, cuerpo in zip(m['paginas'], cuerpos):
            self.assertEqual(p['sha256'], hashlib.sha256(cuerpo).hexdigest())
            self.assertEqual((self.out / 'int.openalex-temas' / 'crudos' / p['crudo']).read_bytes(), cuerpo)
        m = self.run_([b'{"meta": {}, "results": "x"}'])  # unreadable, yet its raw is kept for whoever looks
        self.assertEqual((m['estado'], len(m['paginas'])), ('ilegible', 1))

    def test_a_count_that_does_not_square_is_never_complete(self):
        self.assertEqual(self.run_([pagina(['T1', 'T2'], None)], declarado=3)['estado'], 'no_cuadra')
        sin = copy.deepcopy(TEMAS); del sin['contador']
        self.assertEqual(self.run_([pagina(['T1'], None)], fuente=sin)['estado'], 'sin_conteo')

    def test_a_repeated_id_is_counted_once_and_the_repeats_are_said(self):
        m = self.run_([pagina(['T1', 'T2'], 'c2'), pagina(['T2', 'T3'], None)])
        self.assertEqual((m['leidos'], m['distintos'], m['repetidos'], m['estado']), (4, 3, 1, 'completo'))
        self.assertEqual(self.registros(), ['T1', 'T2', 'T3'])

    def test_it_ends_at_max_paginas_on_a_repeated_cursor_and_on_a_page_that_is_not_records(self):
        corto = copy.deepcopy(TEMAS); corto['adquisicion']['paginacion']['max_paginas'] = 1
        m = self.run_([pagina(['T1'], 'c2')], fuente=corto)
        self.assertEqual((m['estado'], m['motivo']), ('incompleto', 'max_paginas'))
        m = self.run_([pagina(['T1'], 'c2'), pagina(['T2'], 'c2'), pagina(['T3'], None)])
        self.assertEqual((m['estado'], m['motivo']), ('incompleto', 'cursor repetido'))
        for cuerpo in (b'{"results": [1, 2]}', b'{"results": {"a": 1}}', b'<html>', b'{"results": [{"name": "sin id"}]}'):
            with self.subTest(cuerpo=cuerpo):
                self.assertEqual(self.run_([cuerpo])['estado'], 'ilegible')

    def test_the_credential_goes_only_in_the_header_and_only_to_its_host(self):
        self.run_([pagina(['T1', 'T2', 'T3'], None)])
        self.assertTrue(all(a == f'Bearer {KEY}' for _, a in self.fx.pedidos))
        self.assertTrue(all(KEY not in u for u, _ in self.fx.pedidos))
        built = {}
        with mock.patch.object(q, 'Fetcher', side_effect=lambda *a, **k: built.update(k) or Falso([pagina(['T1'], None)], 1)):
            q.adquirir(TEMAS, self.out, entorno={'OPENALEX_API_KEY': KEY}, ahora=AHORA)
        self.assertEqual(built['secrets'], {KEY: 'api.openalex.org'})  # the Fetcher refuses it to any other host
        self.assertEqual(built['budget'], 68)  # max_paginas 60, plus the contador and robots.txt

    def test_no_request_without_the_credential_it_declares(self):
        m = self.run_([pagina(['T1'], None)], entorno={})
        self.assertEqual((m['estado'], self.fx.pedidos), ('sin_credencial', []))

    def test_a_page_that_echoes_the_key_is_refused_and_nothing_of_it_is_kept(self):
        for eco in (KEY.encode(), KEY.replace('o', '\\u006f', 1).encode(), b'<html>' + KEY.encode()):
            with self.subTest(eco=eco):  # literal, \\u-escaped, and in a body that is not even JSON
                cuerpo = eco if eco.startswith(b'<') else b'{"meta": {"next_cursor": null, "x": "' + eco + b'"}, "results": [{"id": "T1"}]}'
                m = self.run_([cuerpo], declarado=1)
                self.assertEqual((m['estado'], m['paginas'], m['distintos']), ('rechazado', [], 0))
                self.assertNotIn(KEY, (self.out / 'int.openalex-temas' / 'manifiesto.json').read_text())

    def test_robots_a_refusal_a_status_and_the_deadline_each_end_the_source_with_their_reason(self):
        self.assertEqual(self.run_([FetchRefused('robots.txt disallows https://api.openalex.org/topics')])['estado'],
                         'bloqueada_por_robots')
        self.assertEqual(self.run_([FetchRefused('host not in allowlist: x.org')])['estado'], 'rechazado')
        self.assertEqual(self.run_([BudgetExhausted('run deadline reached')])['estado'], 'pendiente')
        self.assertEqual(self.run_([pagina(['T1'], None)], status=503)['estado'], 'http')
        clock = iter([0, 0, 0, q.PLAZO + 1])
        self.assertEqual(self.run_([pagina(['T1'], 'c2'), pagina(['T2'], None)], reloj=lambda: next(clock))['estado'], 'pendiente')

    def test_a_cursor_that_is_not_text_is_unreadable(self):
        # GPT on d705bce: [] or {} raised TypeError and ended the whole run
        for cursor in ([], {}, 7):
            with self.subTest(cursor=cursor):
                m = self.run_([pagina(['T1'], cursor)], declarado=1)
                self.assertEqual((m['estado'], m['motivo']), ('ilegible', 'cursor con forma inesperada'))

    def test_every_record_the_manifest_announces_is_on_disk_even_when_the_run_dies(self):
        # GPT on d705bce: the records file stayed open and buffered until the source ended
        with self.assertRaises(KeyboardInterrupt):
            self.run_([pagina(['T1', 'T2'], 'c2'), KeyboardInterrupt()])
        m = json.loads((self.out / 'int.openalex-temas' / 'manifiesto.json').read_text())
        self.assertEqual(sum(p['nuevos'] for p in m['paginas']), m['distintos'])
        self.assertEqual(self.registros(), ['T1', 'T2'])

    def test_every_source_of_a_run_shares_one_deadline(self):
        # GPT on d705bce: each source had a fresh 100 minutes inside a 110-minute step
        reloj = iter([0] + [q.PLAZO + 1] * 50)
        with tempfile.TemporaryDirectory() as t, mock.patch('time.monotonic', lambda: next(reloj)), \
                mock.patch.object(q, 'Fetcher') as F, mock.patch('sys.stdout'), \
                mock.patch.dict('os.environ', {'OPENALEX_API_KEY': KEY}):
            rc = q.main(['--solo', 'int.openalex-temas', 'int.openalex-campos', '--salida', t])
            estados = [json.loads((Path(t) / s / 'manifiesto.json').read_text())['estado']
                       for s in ('int.openalex-temas', 'int.openalex-campos')]
        self.assertEqual((rc, estados), (3, ['pendiente', 'pendiente']))
        F.return_value.get.assert_not_called()

    def test_one_source_that_breaks_never_stops_the_others(self):
        calls = iter([RuntimeError('boom'), {'source_id': 'int.openalex-campos', 'estado': 'completo'}])

        def una(f, *a, **k):
            r = next(calls)
            if isinstance(r, Exception):
                raise r
            return r
        with tempfile.TemporaryDirectory() as t, mock.patch.object(q, 'adquirir', side_effect=una), \
                mock.patch('sys.stdout') as out:
            self.assertEqual(q.main(['--solo', 'int.openalex-temas', 'int.openalex-campos', '--salida', t]), 3)
        self.assertIn('"estado": "error"', ''.join(str(c.args[0]) for c in out.write.call_args_list if c.args))

    def test_page_and_offset_routes_advance_and_stop_on_a_short_page(self):
        for tipo, segundo in (('pagina', 'page=2'), ('offset', 'offset=2')):
            with self.subTest(tipo=tipo):
                f = copy.deepcopy(TEMAS)
                f['adquisicion']['paginacion'].update(tipo=tipo, parametro='page' if tipo == 'pagina' else 'offset', tamano=2)
                f['adquisicion']['paginacion'].pop('inicio')
                m = self.run_([pagina(['T1', 'T2'], None), pagina(['T3'], None)], fuente=f)
                self.assertEqual(m['estado'], 'completo')
                from urllib.parse import parse_qs, urlsplit
                pedidas = [parse_qs(urlsplit(u).query) for u, _ in self.fx.pedidos[1:]]
                k = 'page' if tipo == 'pagina' else 'offset'
                self.assertEqual([x[k] for x in pedidas], [['1'], ['2']] if tipo == 'pagina' else [['0'], ['2']])

    def test_the_manifest_is_saved_after_every_page(self):
        saved = []
        real = q._escribir
        with mock.patch.object(q, '_escribir', side_effect=lambda p, d: saved.append(d['distintos']) or real(p, d)):
            self.run_([pagina(['T1', 'T2'], 'c2'), pagina(['T3'], None)])
        self.assertEqual(saved[:2], [2, 3])


class Reales(unittest.TestCase):
    """Answers captured from api.openalex.org on 2026-11-01 (tests/fixtures/openalex): their real shape, count and end."""
    FX = ROOT / 'tests' / 'fixtures' / 'openalex'

    def correr(self, fuente, paginas, count):
        cuerpos = [(self.FX / p).read_bytes() for p in paginas]
        contador = (self.FX / count).read_bytes()

        class Real:
            def __init__(self): self.pedidos = []
            def get(self, url, auth=None):
                self.pedidos.append(url)
                if '/' + fuente['contador']['url'].split('/')[-1] == '/' + url.split('/')[-1]:
                    return Response(200, contador, url)
                cuerpo = cuerpos.pop(0)
                return Response(401 if b'API key required' in cuerpo else 200, cuerpo, url)
        with tempfile.TemporaryDirectory() as t:
            return q.adquirir(fuente, t, entorno={'OPENALEX_API_KEY': KEY}, nuevo_fetcher=Real, ahora=AHORA)

    def test_the_four_domains_end_on_their_real_last_page_and_square(self):
        m = self.correr(FUENTES['int.openalex-dominios'], ['domains-p1.json'], 'domains-count.json')
        self.assertEqual((m['estado'], m['declarado'], m['distintos']), ('completo', 4, 4))

    def test_the_26_fields_by_page_number_end_on_the_short_page_and_square(self):
        f = copy.deepcopy(FUENTES['int.openalex-campos'])
        f['adquisicion']['paginacion'] = {'tipo': 'pagina', 'parametro': 'page', 'tamano_parametro': 'per-page', 'tamano': 10,
                                          'ruta_items': ['results'], 'max_paginas': 5}
        m = self.correr(f, ['fields-page1.json', 'fields-page2.json', 'fields-page3.json'], 'fields-count.json')
        self.assertEqual((m['estado'], m['declarado'], m['distintos'], len(m['paginas'])), ('completo', 26, 26, 3))

    def test_a_second_cursor_page_without_the_key_is_a_401_never_a_record(self):
        # captured: OpenAlex refuses cursor paging past page one without a key
        m = self.correr(FUENTES['int.openalex-campos'], ['fields-cursor-p1.json', 'cursor-sin-llave.json'], 'fields-count.json')
        self.assertEqual((m['estado'], m.get('http'), m['distintos']), ('http', 401, 10))


class Contrato(unittest.TestCase):
    def test_the_credential_names_a_secret_and_nothing_else(self):
        from rg.schemas import validate
        a = copy.deepcopy(TEMAS['adquisicion'])
        self.assertEqual(validate('adquisicion', a), [])
        for bad in ({'secreto': 'openalex'}, {'secreto': 'OPENALEX_API_KEY', 'valor': 'x'}, {}):
            with self.subTest(bad=bad):
                self.assertTrue(validate('adquisicion', dict(a, credencial=bad)))

    def test_main_is_red_unless_every_source_is_complete(self):
        with tempfile.TemporaryDirectory() as t:
            for estados, rc in ((['completo'], 0), (['completo', 'no_cuadra'], 3), (['pendiente'], 3)):
                res = iter([{'source_id': 'x', 'estado': e} for e in estados])
                with self.subTest(estados=estados), mock.patch.object(q, 'adquirir', side_effect=lambda *a, **k: next(res)), \
                        mock.patch('sys.stdout'):
                    solo = ['int.openalex-temas', 'int.openalex-campos'][:len(estados)]
                    self.assertEqual(q.main(['--solo', *solo, '--salida', t]), rc)

    def test_main_runs_only_registered_api_sources(self):
        with tempfile.TemporaryDirectory() as t, mock.patch.object(q, 'adquirir') as a:
            for solo in (['no.existe'], ['int.openalex']):  # unknown, and registered without an acquisition block
                with self.assertRaises(SystemExit):
                    q.main(['--solo', *solo, '--salida', t])
            a.assert_not_called()


class Workflow(unittest.TestCase):
    raw = (ROOT / '.github' / 'workflows' / 'adquirir.yml').read_text(encoding='utf-8')
    doc = yaml.safe_load(raw)
    job = doc['jobs']['adquirir']

    def test_mains_code_only_by_dispatch(self):
        self.assertEqual(set(self.doc[True]), {'workflow_dispatch'})
        self.assertEqual(self.job['if'], "github.ref == 'refs/heads/main'")
        self.assertEqual((self.doc['permissions'], self.job['permissions']), ({}, {'contents': 'write'}))
        self.assertEqual(self.job['steps'][0]['with'], {'ref': 'main', 'persist-credentials': False})

    def test_the_key_reaches_only_the_step_that_acquires(self):
        self.assertEqual(self.raw.count('secrets.'), 1)
        holders = [s for s in self.job['steps'] if 'secrets.' in yaml.safe_dump(s)]
        self.assertEqual(len(holders), 1)
        self.assertEqual([v for v in holders[0]['env'].values() if 'secrets.' in v], ['${{ secrets.OPENALEX_API_KEY }}'])
        self.assertIn('python -m rg.adquirir', holders[0]['run'])
        last = self.job['steps'][-1]
        self.assertEqual((last['if'], last['run'].strip()), ("steps.adquirir.outputs.rc != '0'", 'exit 1'))
        self.assertNotIn('github.token', yaml.safe_dump(holders[0]))
