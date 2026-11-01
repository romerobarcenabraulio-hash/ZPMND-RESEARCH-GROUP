"""rg/descubrir.py and .github/workflows/descubrir.yml: a web search finds candidate official sites per cell of the world
map; only what the search returned is kept, the key reaches only api.perplexity.ai and the step that searches, and each
candidate is asked once with the catalog's Fetcher, without the key."""
import copy
import http.client
import json
import os
import subprocess
import time
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import yaml

from rg import descubrir as d
from rg.catalog.fetch import FetchRefused, Response, _NoRedirect, _PublicHTTPS

ROOT = Path(__file__).resolve().parents[1]
COB = d.cargar_cobertura(ROOT / 'sources' / 'cobertura.json')
MINI = {'paises': [{'iso2': 'KE', 'iso3': 'KEN', 'nombre': 'Kenya'}, {'iso2': 'MX', 'iso3': 'MEX', 'nombre': 'Mexico'}],
        'ejes': [{'id': 'ley', 'nombre': 'Ley', 'capas': [{'id': 'diario', 'nombre': 'Diario oficial',
                                                            'consulta': '{pais} official gazette'}]},
                 {'id': 'datos', 'nombre': 'Datos', 'capas': [{'id': 'estadistica', 'nombre': 'Estadística',
                                                               'consulta': '{pais} national statistics office'}]}]}
HIT = {'title': 'Kenya Gazette', 'url': 'https://kenyalaw.org/kenya_gazette/', 'snippet': 'Official gazette', 'date': None}
AHORA = lambda: '2026-11-01T00:00:00Z'  # noqa: E731
KEY = 'pplx-TEST-0000-key'  # never a substring of the fixtures


def http_error(code):
    return urllib.error.HTTPError(d.API, code, 'no', {}, None)  # no body: reading it would fail


class Mapa(unittest.TestCase):
    def test_the_map_in_the_repo_is_the_un_by_twelve_layers(self):
        self.assertEqual(len(COB['paises']), 193)  # Naciones Unidas, Estados miembros (checked 2026-11-01)
        self.assertEqual([(e['id'], len(e['capas'])) for e in COB['ejes']], [('ley', 7), ('estandares', 2), ('datos', 3)])
        self.assertEqual(len(COB['paises']) * len(d.capas(COB)), 2316)
        self.assertIn({'iso2': 'MX', 'iso3': 'MEX', 'nombre': 'Mexico'}, COB['paises'])

    def test_a_broken_map_is_refused_before_anything_is_asked(self):
        def falla(change):
            doc = copy.deepcopy(MINI); change(doc)
            with tempfile.TemporaryDirectory() as t:
                (Path(t) / 'c.json').write_text(json.dumps(doc), encoding='utf-8')
                with self.assertRaises(SystemExit):
                    d.cargar_cobertura(Path(t) / 'c.json')
        falla(lambda x: x['paises'].append(dict(x['paises'][0], iso3='KEX')))  # iso2 repeated
        falla(lambda x: x['paises'].append({'iso2': 'ke', 'iso3': 'KEY', 'nombre': 'K'}))
        falla(lambda x: x['ejes'][0]['capas'][0].update(consulta='official gazette'))
        falla(lambda x: x['ejes'][0]['capas'][0].update(consulta='{pais} {pais} gazette'))
        falla(lambda x: x['ejes'][0]['capas'][0].update(id='Diario Oficial'))
        falla(lambda x: x['ejes'][1].update(capas=[]))
        falla(lambda x: x.update(paises=[]))

    def test_a_query_is_only_the_country_and_the_fixed_wording(self):
        capa = MINI['ejes'][0]['capas'][0]
        self.assertEqual(d.consulta(capa, {'nombre': 'Kenya'}), 'Kenya official gazette')
        self.assertEqual(d.consulta(capa, {'nombre': '{0.__class__}'}), '{0.__class__} official gazette')  # no format


class Busqueda(unittest.TestCase):
    def test_the_request_goes_to_the_api_with_the_key_and_nothing_else(self):
        seen = []

        def abrir(req, timeout):
            seen.append(req); return json.dumps({'results': [HIT]}).encode()
        out = d.buscar('Kenya official gazette', 'KE', 'k-123', 'web', abrir=abrir)
        req = seen[0]
        self.assertEqual((req.full_url, req.get_method()), ('https://api.perplexity.ai/search', 'POST'))
        self.assertEqual(req.get_header('Authorization'), 'Bearer k-123')
        self.assertEqual(json.loads(req.data), {'query': 'Kenya official gazette', 'max_results': 5, 'search_type': 'web',
                                                'country': 'KE', 'max_tokens_per_page': 64})
        self.assertEqual(out, {'results': [HIT]})

    def test_the_answer_is_read_without_redirects_from_public_addresses_and_capped(self):
        class Resp:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read1(self, n): out, self.body = self.body[:n], self.body[n:]; return out
        opener = mock.Mock()
        with mock.patch('urllib.request.build_opener', return_value=opener) as build:
            opener.open.return_value = Resp(b'{"results": []}')
            self.assertEqual(d._abrir('req', 60), b'{"results": []}')
            build.assert_called_with(_NoRedirect, _PublicHTTPS)
            opener.open.return_value = Resp(b'x' * (d.MAX_RESPUESTA + 1))
            with self.assertRaises(ValueError):
                d._abrir('req', 60)

    def test_a_key_in_what_would_be_kept_refuses_that_layer_however_it_came(self):
        # GPT on 698a5b7 (literal), 2ebcc5b (\\u escape) and 41182c5 (an invisible character the cleaning removes)
        bodies = (json.dumps({'results': [dict(HIT, snippet='leaked ' + KEY)]}).encode(),
                  json.dumps({'results': [dict(HIT, snippet=KEY)]}).encode().replace(b'"pplx', b'"\\u0070plx'),
                  json.dumps({'results': [dict(HIT, title=KEY[:5] + '\u200b' + KEY[5:])]}, ensure_ascii=False).encode())
        for i, body in enumerate(bodies):
            with self.subTest(body=body), tempfile.TemporaryDirectory() as tmp:
                self.assertEqual(KEY.encode() in body, i == 0)  # only the first carries it as written
                buscar = lambda q, iso2, key, tipo, body=body: d.buscar(q, iso2, key, tipo, abrir=lambda req, timeout: body)
                d.correr_busqueda(MINI, Path(tmp), KEY, 12, 'web', AHORA, buscar, sleep=lambda s: None)
                written = ''.join(p.read_text() for p in Path(tmp).iterdir())
                self.assertNotIn(KEY, written)
                self.assertIn('"error": "ValueError"', written)

    def test_nothing_holding_the_key_is_ever_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, 'KEN.json')
            with self.assertRaises(ValueError):
                d._escribir(path, {'x': [{'y': 'a' + KEY}]}, KEY)
            self.assertFalse(path.exists())
            d._escribir(path, {'x': 'nada'}, KEY)
            self.assertTrue(path.exists())
        deep = 'x'
        for _ in range(60):
            deep = {'x': deep}
        self.assertTrue(d._contiene(deep, KEY))  # too deep to read whole counts as holding it

    def test_an_answer_that_trickles_in_past_its_deadline_is_cut(self):
        # GPT on cb11715 and 9829c21: a real server that drips one byte every 0.2 s, far under each socket wait
        import http.server, socketserver, threading
        class Gotea(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200); self.send_header('Content-Length', '100000'); self.end_headers()
                try:
                    for _ in range(100000):
                        self.wfile.write(b'x'); self.wfile.flush(); time.sleep(0.2)
                except OSError:
                    pass
            def log_message(self, *a): pass
        srv = socketserver.ThreadingTCPServer(('127.0.0.1', 0), Gotea)
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close); self.addCleanup(srv.shutdown)
        req = urllib.request.Request(f'http://127.0.0.1:{srv.server_address[1]}/')
        got = []

        def leer():  # in a thread of its own, so a read that never returns fails this test instead of hanging the suite
            try:
                d._abrir(req, 2)
                got.append('read whole')
            except Exception as e:  # noqa: BLE001
                got.append(type(e).__name__)
        with mock.patch('urllib.request.build_opener', return_value=urllib.request.build_opener()):
            hilo = threading.Thread(target=leer, daemon=True)
            hilo.start()
            hilo.join(8)  # the 2 s deadline plus at most one wait of the socket
        self.assertEqual(got, ['TimeoutError'])

    def test_only_https_results_on_a_host_name_are_kept(self):
        hits = [dict(HIT, url=u) for u in ('http://gov.ke/', 'https://10.0.0.1/', 'https://[::1]/', 'https://gov.ke:8443/',
                                           'https://u:p@gov.ke/', 'javascript:alert(1)', 'https://localhost/', None,
                                           'https://' + 'a' * 500 + '.ke/', 'https://GAZETTE.go.ke/x')]
        kept, fuera = d.resultados({'results': hits[5:]})
        self.assertEqual([(k['rank'], k['host']) for k in kept], [(1, 'gazette.go.ke')])
        self.assertEqual(fuera, 4)
        kept, fuera = d.resultados({'results': hits[:5]})
        self.assertEqual((kept, fuera), ([], 5))

    def test_text_is_visible_and_cut_and_no_more_than_five_results(self):
        hits = [dict(HIT, title='Ga​zette‮' + 't' * 300, snippet=7, date='2026-01-01')] + [HIT] * 6
        kept, fuera = d.resultados({'results': hits})
        self.assertEqual(len(kept), 5)
        self.assertEqual(fuera, 2)
        self.assertTrue(kept[0]['title'].startswith('Gazettet') and len(kept[0]['title']) == 200)
        self.assertEqual((kept[0]['snippet'], kept[0]['date']), ('', '2026-01-01'))

    def test_an_answer_without_a_list_of_results_is_unreadable(self):
        for resp in ({}, {'results': 'x'}, {'results': ['x']}, [HIT], {'error': 'quota'}):
            with self.assertRaises(ValueError):
                d.resultados(resp)


class Pais(unittest.TestCase):
    def test_a_country_has_every_layer_and_is_complete_only_when_all_answered(self):
        calls = []

        def buscar(q, iso2, key, tipo):
            calls.append((q, iso2))
            if 'statistics' in q:
                raise http_error(500)
            return {'results': [HIT]}
        sleeps = []
        doc = d.un_pais(MINI['paises'][0], MINI, KEY, 'web', AHORA, buscar, sleep=sleeps.append)
        self.assertEqual(calls, [('Kenya official gazette', 'KE'), ('Kenya national statistics office', 'KE')])
        self.assertEqual(sleeps, [d.PAUSA, d.PAUSA])  # one search a second at most
        self.assertEqual([(c['capa'], c['estado']) for c in doc['capas']], [('diario', 'ok'), ('estadistica', 'error')])
        self.assertEqual(doc['capas'][1]['error'], 'http 500')
        self.assertFalse(doc['completo'])

    def test_a_refused_key_or_no_credit_or_a_rate_limit_stops_the_run(self):
        for code in (401, 402, 403, 429):
            def buscar(*a, code=code):
                raise http_error(code)
            with self.assertRaises(d.Alto):
                d.un_pais(MINI['paises'][0], MINI, KEY, 'web', AHORA, buscar, sleep=lambda s: None)

    def test_an_error_never_carries_the_key(self):
        def buscar(*a):
            raise urllib.error.URLError('bad k-SECRET')
        doc = d.un_pais(MINI['paises'][0], MINI, 'k-SECRET', 'web', AHORA, buscar, sleep=lambda s: None)
        self.assertNotIn('k-SECRET', json.dumps(doc))
        self.assertEqual(doc['capas'][0]['error'], 'URLError')


class Corrida(unittest.TestCase):
    def run_(self, carpeta, max_b, buscar, reloj=lambda: 0.0):
        return d.correr_busqueda(MINI, carpeta, KEY, max_b, 'web', AHORA, buscar, sleep=lambda s: None, reloj=reloj)

    def test_whole_countries_only_and_a_complete_country_is_never_asked_again(self):
        with tempfile.TemporaryDirectory() as t:
            c = Path(t)
            out = self.run_(c, 3, lambda *a: {'results': [HIT]})  # 2 per country: the second does not fit
            self.assertEqual(out, {'busquedas': 2, 'paises': ['KEN'], 'pendientes': 1})
            self.assertEqual(sorted(p.name for p in c.iterdir()), ['KEN.json'])
            asked = []
            out = self.run_(c, 10, lambda q, *a: asked.append(q) or {'results': [HIT]})
            self.assertEqual(out['paises'], ['MEX'])
            self.assertTrue(all(q.startswith('Mexico') for q in asked))

    def test_an_incomplete_country_is_asked_again(self):
        with tempfile.TemporaryDirectory() as t:
            c = Path(t)
            fail = {'n': 0}

            def buscar(*a):
                fail['n'] += 1
                if fail['n'] == 1:
                    raise http_error(500)
                return {'results': [HIT]}
            self.run_(c, 2, buscar)
            self.assertFalse(json.loads((c / 'KEN.json').read_text())['completo'])
            asked = []
            out = self.run_(c, 2, lambda q, *a: asked.append(q) or buscar(q, *a))
            self.assertEqual((out['paises'], asked), (['KEN'], ['Kenya official gazette']))  # the answered one is kept
            self.assertTrue(json.loads((c / 'KEN.json').read_text())['completo'])

    def test_a_stop_keeps_what_was_paid_and_the_next_run_asks_only_the_rest(self):
        # GPT on 698a5b7 (REGLAS 5): a 429 on a country's last layer used to drop the layers already paid
        with tempfile.TemporaryDirectory() as t:
            c, n = Path(t), {'n': 0}

            def buscar(*a):
                n['n'] += 1
                if n['n'] == 4:
                    raise http_error(402)
                return {'results': [HIT]}
            out = self.run_(c, 10, buscar)
            self.assertEqual(out, {'busquedas': 4, 'paises': ['KEN'], 'alto': 'http 402'})
            mex = json.loads((c / 'MEX.json').read_text())
            self.assertEqual(([x['capa'] for x in mex['capas']], mex['completo']), (['diario'], False))
            asked = []
            out = self.run_(c, 10, lambda q, *a: asked.append(q) or {'results': [HIT]})
            self.assertEqual((asked, out['paises'], out['pendientes']), (['Mexico national statistics office'], ['MEX'], 0))

    def test_a_stop_never_drops_a_layer_paid_in_an_earlier_run(self):
        with tempfile.TemporaryDirectory() as t:
            c = Path(t)
            self.run_(c, 2, lambda q, *a: (_ for _ in ()).throw(http_error(500)) if 'gazette' in q else {'results': [HIT]})
            out = self.run_(c, 2, lambda *a: (_ for _ in ()).throw(http_error(429)))
            self.assertEqual(out['alto'], 'http 429')
            ken = json.loads((c / 'KEN.json').read_text())
            self.assertEqual([(x['capa'], x['estado']) for x in ken['capas']], [('estadistica', 'ok')])

    def test_a_body_cut_short_keeps_what_was_paid_and_is_asked_again_alone(self):
        # GPT on 2ebcc5b: IncompleteRead was not caught and ended the run before the country was written
        with tempfile.TemporaryDirectory() as t:
            c = Path(t)

            def buscar(q, *a):
                if 'statistics' in q:
                    raise http.client.IncompleteRead(b'{"res')
                return {'results': [HIT]}
            self.run_(c, 2, buscar)
            ken = json.loads((c / 'KEN.json').read_text())
            self.assertEqual([(x['capa'], x['estado'], x.get('error')) for x in ken['capas']],
                             [('diario', 'ok', None), ('estadistica', 'error', 'IncompleteRead')])
            asked = []
            self.run_(c, 2, lambda q, *a: asked.append(q) or {'results': [HIT]})
            self.assertEqual(asked, ['Kenya national statistics office'])

    def test_no_country_starts_past_the_deadline(self):
        with tempfile.TemporaryDirectory() as t:
            out = self.run_(Path(t), 10, lambda *a: {'results': [HIT]}, reloj=iter([0.0, d.PLAZO_BUSCAR - 1]).__next__)
            self.assertEqual(out, {'busquedas': 0, 'paises': [], 'pendientes': 2})


class Mapa2(unittest.TestCase):
    def ken(self, *capas):
        return {'pais': MINI['paises'][0], 'capas': [dict(x) for x in capas], 'completo': False}

    DIARIO = {'eje': 'ley', 'capa': 'diario', 'nombre': 'Diario oficial', 'consulta': 'Kenya official gazette', 'estado': 'ok',
              'resultados': [dict(HIT, rank=1, host='kenyalaw.org')], 'descartados': 0}
    ESTAD = {'eje': 'datos', 'capa': 'estadistica', 'nombre': 'Estadística', 'consulta': 'Kenya national statistics office',
             'estado': 'ok', 'resultados': [dict(HIT, rank=1, host='kenyalaw.org')], 'descartados': 0}

    def test_a_layer_added_to_the_map_makes_a_finished_country_pending_again(self):
        # GPT on 41182c5: completo is what the file says of an older map
        with tempfile.TemporaryDirectory() as b:
            rama = Path(b)
            (rama / 'KEN.json').write_text(json.dumps(dict(self.ken(self.DIARIO), completo=True)))
            self.assertEqual([p['iso3'] for p in d.pendientes(MINI, rama)], ['KEN', 'MEX'])

class Verificacion(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.c = Path(self.t.name)
        res = [dict(HIT, rank=i + 1, host='kenyalaw.org', url=f'https://kenyalaw.org/{i}') for i in range(3)]
        doc = {'completo': True, 'capas': [{'eje': 'ley', 'capa': 'diario', 'consulta': 'Kenya official gazette', 'estado': 'ok',
                                            'resultados': res}]}
        (self.c / 'KEN.json').write_text(json.dumps(doc), encoding='utf-8')

    def tearDown(self):
        self.t.cleanup()

    def doc(self):
        return json.loads((self.c / 'KEN.json').read_text())['capas'][0]['resultados']

    def test_only_the_first_candidates_are_asked_once_on_their_host_and_its_www_twin(self):
        hosts = []

        def nuevo(h):
            hosts.append(h); f = mock.Mock(); f.get.return_value = Response(200, b'ok', 'u'); return f
        self.assertEqual(d.verificar(self.c, 2, nuevo, AHORA), 2)
        self.assertEqual(hosts, [['kenyalaw.org', 'www.kenyalaw.org']] * 2)
        r = self.doc()
        self.assertEqual(r[0]['verificacion']['estado'], 'accesible')
        self.assertEqual(r[0]['verificacion']['sha256'], '2689367b205c16ce32ed4200942b8b8b1e262dfc70d9bc9fbc77c49699a4f1df')
        self.assertNotIn('verificacion', r[2])
        self.assertEqual(d.verificar(self.c, 2, nuevo, AHORA), 0)  # already asked: never again

    def test_a_refusal_a_status_and_a_url_that_is_not_https_are_their_own_results(self):
        docs = json.loads((self.c / 'KEN.json').read_text())
        docs['capas'][0]['resultados'][2]['url'] = 'http://kenyalaw.org/'
        (self.c / 'KEN.json').write_text(json.dumps(docs))
        answers = iter([FetchRefused('robots.txt disallows'), Response(404, b'', 'u')])

        def nuevo(h):
            f = mock.Mock(); a = next(answers)
            f.get.side_effect = a if isinstance(a, Exception) else None
            f.get.return_value = a; return f
        d.verificar(self.c, 3, nuevo, AHORA)
        self.assertEqual([r['verificacion']['estado'] for r in self.doc()], ['rechazado', 'http', 'rechazado'])

    def test_the_default_fetcher_has_its_budget_cap_deadline_and_one_shared_pace(self):
        # GPT on 41182c5: the guards of the factory verificar builds, not only of one injected in the tests
        with mock.patch.object(d, 'Fetcher') as F:
            F.return_value.get.return_value = Response(200, b'', 'u')
            d.verificar(self.c, 2, ahora=AHORA, reloj=lambda: 100.0, plazo=50)
        self.assertEqual(F.call_count, 2)
        for call in F.call_args_list:
            self.assertEqual(call.args, (['kenyalaw.org', 'www.kenyalaw.org'],))
            self.assertEqual({k: call.kwargs[k] for k in ('budget', 'max_bytes', 'deadline')}, {'budget': 6, 'max_bytes': 5_000_000,
                                                                                                  'deadline': 150.0})
        self.assertIs(F.call_args_list[0].kwargs['compartido'], F.call_args_list[1].kwargs['compartido'])  # one pace per host

    def test_nothing_is_asked_past_the_deadline(self):
        clock = iter([0.0, d.PLAZO_VERIFICAR + 1, d.PLAZO_VERIFICAR + 1, d.PLAZO_VERIFICAR + 1])
        self.assertEqual(d.verificar(self.c, 2, mock.Mock(), AHORA, reloj=clock.__next__), 0)

    def test_the_summary_counts_only_layers_of_the_current_map(self):
        # GPT on 9829c21: a layer whose query changed is pending, never counted with its old answer
        cambiado = {'paises': MINI['paises'], 'ejes': [dict(MINI['ejes'][0], capas=[dict(MINI['ejes'][0]['capas'][0],
                                                                                         consulta='{pais} gazette new')])]}
        d.verificar(self.c, 1, lambda h: mock.Mock(get=mock.Mock(return_value=Response(200, b'', 'u'))), AHORA)
        self.assertEqual(d.resumen(cambiado, self.c)['ley/diario'], {'buscados': 0, 'con_candidato_accesible': 0})

    def test_the_summary_counts_candidates_never_coverage(self):
        d.verificar(self.c, 1, lambda h: mock.Mock(get=mock.Mock(return_value=Response(200, b'', 'u'))), AHORA)
        out = d.resumen({'paises': MINI['paises'], 'ejes': MINI['ejes']}, self.c)
        self.assertEqual(out['ley/diario'], {'buscados': 1, 'con_candidato_accesible': 1})
        self.assertEqual(out['datos/estadistica'], {'buscados': 0, 'con_candidato_accesible': 0})


class Main(unittest.TestCase):
    def test_no_key_or_a_budget_out_of_range_stops_before_anything_is_asked(self):
        with tempfile.TemporaryDirectory() as t, mock.patch.object(d, 'buscar') as b:
            with mock.patch.dict('os.environ', {}, clear=True), self.assertRaises(SystemExit):
                d.main(['buscar', '--carpeta', t, '--max-busquedas', '12'])
            with mock.patch.dict('os.environ', {'PERPLEXITY_API_KEY': 'k'}):
                for n in ('0', '11', str(d.MAX_BUSQUEDAS + 1)):  # 11: less than one country's 12 layers
                    with self.assertRaises(SystemExit):
                        d.main(['buscar', '--carpeta', t, '--max-busquedas', n])
            with self.assertRaises(SystemExit):
                d.main(['verificar', '--carpeta', t, '--por-capa', '6'])
            b.assert_not_called()


class Workflow(unittest.TestCase):
    raw = (ROOT / '.github' / 'workflows' / 'descubrir.yml').read_text(encoding='utf-8')
    doc = yaml.safe_load(raw)
    job = doc['jobs']['descubrir']

    def test_mains_code_only_by_schedule_or_dispatch(self):
        self.assertEqual(set(self.doc[True]), {'schedule', 'workflow_dispatch'})
        self.assertEqual(self.job['if'], "github.ref == 'refs/heads/main'")
        self.assertEqual(self.doc['permissions'], {})
        self.assertEqual(self.job['permissions'], {'contents': 'write'})
        self.assertEqual(self.job['steps'][0]['with'], {'ref': 'main', 'persist-credentials': False})

    def test_a_data_branch_that_cannot_be_read_stops_the_run_before_any_search(self):
        # GPT on 2ebcc5b: any ls-remote failure used to start an empty orphan branch and search everything again
        step = next(s for s in self.job['steps'] if s.get('name', '').startswith('Read what was already found'))
        for rc, exit_ok, done in ((128, False, None), (2, True, 'checkout -q --orphan descubrimiento'),
                                  (0, True, 'checkout -q -b descubrimiento FETCH_HEAD')):
            with self.subTest(rc=rc), tempfile.TemporaryDirectory() as tmp:
                bin_, log = Path(tmp, 'bin'), Path(tmp, 'git.log')
                bin_.mkdir()
                (bin_ / 'git').write_text(f'#!/bin/bash\necho "$*" >> {log}\n'
                                          f'[ "$1" = init ] && mkdir -p "${{@: -1}}"\n'
                                          f'[ "$1" = ls-remote ] && exit {rc}\nexit 0\n')
                (bin_ / 'base64').write_text('#!/bin/bash\ncat >/dev/null; echo eA==\n')
                (bin_ / 'gh').write_text('#!/bin/bash\nexit 0\n')  # no artifact listed: never the real gh (CI has one)
                for f in bin_.iterdir():
                    f.chmod(0o755)
                env = {'PATH': f'{bin_}:/usr/bin:/bin', 'RUNNER_TEMP': tmp, 'GH_TOKEN': 'x', 'GITHUB_REPOSITORY': 'o/r'}
                r = subprocess.run(['bash', '-c', step['run']], env=env, capture_output=True, text=True)
                self.assertEqual(r.returncode == 0, exit_ok, r.stdout + r.stderr)
                text = log.read_text()
                self.assertNotIn('--orphan', text) if rc == 128 else self.assertIn(done, text)

    def test_the_push_is_tried_three_times_and_a_third_failure_turns_the_run_red(self):
        step = next(s for s in self.job['steps'] if s.get('name') == 'Commit the result to the data branch')
        for fails, ok in ((2, True), (3, False)):
            with self.subTest(fails=fails), tempfile.TemporaryDirectory() as tmp:
                tmp = Path(tmp)
                (tmp / 'datos' / 'descubrimiento').mkdir(parents=True)
                (tmp / 'datos' / 'descubrimiento' / 'KEN.json').write_text('{}')
                bin_ = tmp / 'bin'
                bin_.mkdir()
                (bin_ / 'git').write_text(f'#!/bin/bash\necho "$*" >> {tmp}/git.log\n'
                                          '[ "$1" = diff ] && exit 1\n'  # there is something to commit
                                          f'if [ "$1" = push ]; then n=$(grep -c "^push" {tmp}/git.log); [ "$n" -gt {fails} ] && exit 0; exit 1; fi\nexit 0\n')
                (bin_ / 'base64').write_text('#!/bin/bash\ncat >/dev/null; echo eA==\n')
                (bin_ / 'sleep').write_text('#!/bin/bash\nexit 0\n')
                for f in bin_.iterdir():
                    f.chmod(0o755)
                env = {'PATH': f'{bin_}:/usr/bin:/bin', 'RUNNER_TEMP': str(tmp), 'GH_TOKEN': 'x', 'GITHUB_RUN_ID': '1'}
                r = subprocess.run(['bash', '-c', step['run']], env=env, capture_output=True, text=True)
                self.assertEqual(r.returncode == 0, ok, r.stdout + r.stderr)
                self.assertEqual((tmp / 'git.log').read_text().count('push'), min(fails + 1, 3))

    def test_the_key_reaches_only_the_search_step_and_the_token_only_the_data_branch_steps(self):
        self.assertEqual(self.raw.count('secrets.'), 1)
        self.assertNotIn('env', self.doc)
        self.assertNotIn('env', self.job)
        holders = {s.get('name'): s for s in self.job['steps'] if 'secrets.' in yaml.safe_dump(s)}
        self.assertEqual(list(holders), ['Search the next countries (the only step with the key)'])
        step = holders['Search the next countries (the only step with the key)']
        self.assertEqual([v for v in step['env'].values() if 'secrets.' in v], ['${{ secrets.PERPLEXITY_API_KEY }}'])
        self.assertIn('python -m rg.descubrir buscar', step['run'])
        tokens = [s['name'] for s in self.job['steps'] if 'github.token' in yaml.safe_dump(s)]
        self.assertEqual(tokens, ['Read what was already found (branch descubrimiento)', 'Commit the result to the data branch'])
        ver = [s for s in self.job['steps'] if 'rg.descubrir verificar' in s.get('run', '')]
        self.assertEqual(len(ver), 1)
        self.assertNotIn('env', ver[0])  # the step that asks candidate sites holds no credential at all
