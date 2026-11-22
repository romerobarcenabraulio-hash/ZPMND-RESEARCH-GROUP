"""The scripts of the comparison round of 2026-11-21 (docs/medicion/comparacion-2026-11-17/ronda-2026-11-21/): v_gate.py,
the V layer, downloads only through RG's Fetcher and checks each quote as the packet gate does; rehacer_calculos.py
redoes the arm's arithmetic and never passes a dollar amount it did not read. Built here (CONSTRUIDO): a small web
served by a fake opener, one URL whose host is a loopback address for the real opener, and formulas. No network."""
import importlib.util
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_catalog import FakeOpener

ROOT = Path(__file__).resolve().parents[1]
RONDA = ROOT / 'docs/medicion/comparacion-2026-11-17/ronda-2026-11-21'
spec = importlib.util.spec_from_file_location('v_gate', RONDA / 'v_gate.py')
v_gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v_gate)

QUOTE = 'El patrón deberá establecer por escrito una política de prevención de riesgos.'
PAGE = f'<html><body><h1>Norma</h1><p>5.1 {QUOTE}</p></body></html>'.encode()
HTML = {'Content-Type': 'text/html; charset=utf-8'}
ROUTES = {
    'https://a.gob.mx/robots.txt': (200, b'User-agent: *\nDisallow: /privado\n', {}),
    'https://a.gob.mx/nota': (200, PAGE, HTML),
    'https://a.gob.mx/privado/x': (200, PAGE, HTML),
    'https://a.gob.mx/no-existe': (404, PAGE, HTML),  # an error page that carries the quote
    'https://a.gob.mx/redirige': (302, b'', {'Location': 'https://c.example.com/x'}),  # to a host the answer never cites
    'https://c.example.com/robots.txt': (404, b'', {}),
    'https://c.example.com/x': (200, PAGE, HTML),
    'https://b.example.org/robots.txt': (404, b'', {}),
    'https://b.example.org/espejo': (200, PAGE, HTML),  # the same bytes as a.gob.mx/nota
    'https://a.gob.mx/otra': (200, b'<html><body><p>Una norma distinta que dice otra cosa por completo.</p></body></html>', HTML),
    'https://a.gob.mx/vacia': (200, b'', HTML),
    'https://a.gob.mx/roto.pdf': (200, b'%PDF-1.7\n5.1 ' + QUOTE.encode() + b'\n', {'Content-Type': 'application/pdf'}),  # rg.text fails on it
}


def claim(url, quote=QUOTE):
    return {'claim': 'Obliga a una política escrita.', 'url': url, 'quote': quote}


class VGate(unittest.TestCase):
    def run_gate(self, claims, opener='fake'):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        op = FakeOpener(dict(ROUTES)) if opener == 'fake' else None
        return v_gate.gate({'claims': claims}, Path(tmp.name), opener=op, sleep=lambda s: None)

    def results(self, out):
        return [(r['resultado'], r['compuerta']) for r in out['rows']]

    def test_a_quote_in_a_200_body_is_verified_and_the_hosts_are_only_the_cited_ones(self):
        out = self.run_gate([claim('https://a.gob.mx/nota')])
        self.assertEqual(self.results(out), [('verificada', True)])
        self.assertEqual(out['hosts'], ['a.gob.mx'])
        self.assertEqual(out['resumen'], {'afirmaciones': 1, 'compuerta': 1, 'por_resultado': {'verificada': 1}})

    def test_a_200_page_without_the_quote_or_without_text_is_not_verified(self):
        out = self.run_gate([claim('https://a.gob.mx/otra'), claim('https://a.gob.mx/roto.pdf'), claim('https://a.gob.mx/vacia'),
                             claim('https://a.gob.mx/nota')])
        self.assertEqual(self.results(out), [('cita_ausente', False), ('sin_texto', False), ('sin_cuerpo', False), ('verificada', True)])
        self.assertEqual(out['resumen'], {'afirmaciones': 4, 'compuerta': 1,
                                          'por_resultado': {'cita_ausente': 1, 'sin_texto': 1, 'sin_cuerpo': 1, 'verificada': 1}})

    def test_an_empty_or_short_quote_is_never_verified(self):
        out = self.run_gate([claim('https://a.gob.mx/nota', ''), claim('https://a.gob.mx/nota', 'patrón')])
        self.assertEqual(self.results(out), [('cita_corta', False), ('cita_corta', False)])

    def test_an_error_page_that_contains_the_quote_is_not_a_source(self):
        out = self.run_gate([claim('https://a.gob.mx/no-existe')])
        self.assertEqual(self.results(out), [('http_404', False)])
        self.assertIsNone(out['rows'][0]['sha256'])

    def test_robots_disallow_and_a_redirect_off_the_cited_hosts_are_refused(self):
        out = self.run_gate([claim('https://a.gob.mx/privado/x'), claim('https://a.gob.mx/redirige')])
        self.assertEqual(self.results(out), [('rechazada', False), ('rechazada', False)])

    def test_a_private_destination_is_refused_by_the_real_opener(self):
        with mock.patch.dict(os.environ, {k: '' for k in ('HTTPS_PROXY', 'https_proxy', 'ALL_PROXY', 'all_proxy')}):
            out = self.run_gate([claim('https://127.0.0.1/x')], opener=None)
        self.assertEqual(self.results(out), [('rechazada', False)])

    def test_a_second_url_with_the_same_bytes_is_checked_on_that_one_artifact(self):
        out = self.run_gate([claim('https://a.gob.mx/nota'), claim('https://b.example.org/espejo')])
        self.assertEqual(self.results(out), [('verificada', True), ('verificada', True)])
        self.assertEqual(out['rows'][0]['sha256'], out['rows'][1]['sha256'])
        self.assertEqual(out['rows'][1]['url'], 'https://b.example.org/espejo')


class RehacerCalculos(unittest.TestCase):
    def rehacer(self, *calcs):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'a.json'
            f.write_text(json.dumps({'calculations': [{'provider': 'p', 'model': 'm', 'scenario': 's', 'formula': x, 'monthly_usd': y}
                                                      for x, y in calcs]}), encoding='utf-8')
            r = subprocess.run([sys.executable, '-I', str(RONDA / 'rehacer_calculos.py'), str(f)], capture_output=True, text=True, timeout=60)
        return json.loads(r.stdout)

    def test_the_written_products_are_redone_and_a_wrong_sum_does_not_square(self):
        out = self.rehacer(('3,600 x $2 + 480 x $10 = 7,200 + 4,800', 12000), ('100 x $2', 250), ('100 x $2 + $50', 250),
                           ('escrituras 34.56 MTok x $2.50 = 86.40; lecturas 2,365.44 x $0.005 = 11.827', 98.227))
        self.assertEqual([r['cuadra'] for r in out['rows']], [True, False, True, True])
        self.assertEqual(out['resumen'], {'calculos': 4, 'cuadran': 3, 'no_cuadran': 1, 'no_comprobables': 0})

    def test_a_false_equality_does_not_square_even_when_the_total_does(self):  # GPT on a522331
        out = self.rehacer(('100 x $2 = $999', 200), ('100 x $2 = $201', 200), ('100 x $2 = $999; 50 x $2', 100), ('100 x $2 = 200.004', 200))
        self.assertEqual([(r['cuadra'], r.get('igualdad_falsa')) for r in out['rows']],
                         [(False, ['100 x $2 = $999']), (False, ['100 x $2 = $201']), (False, ['100 x $2 = $999']), (True, None)])

    def test_nothing_read_or_an_amount_that_is_not_a_number_is_never_checked(self):  # GPT on 269352a
        out = self.rehacer(('', 0), ('   ', 0), ('; ;', 0), (None, 0), ('100 x $2', '200'), ('100 x $2', True), ('100 x $2', None),
                           ('0 x $2', 0))  # the last: a control that does read
        self.assertEqual([(r['cuadra'], r.get('motivo')) for r in out['rows']],
                         [(None, 'sin_tramos')] * 4 + [(None, 'sin_monto')] * 3 + [(True, None)])

    def test_what_the_grammar_does_not_read_whole_leaves_the_calculation_unchecked(self):  # GPT on 9ce44ea and 815764a
        f = ['100 x $2 / 2', '100 x $2 - 20 x $2', '100 x $2 + 50', 'creación 0.0012', 'creación 4,000 tokens x $0.75/M = 0.003',
             '100 x $2 + = 200', 'lecturas 600,000 x 4,000 = 2,400 MTok x $0.075 = 180']  # the last: a conversion it does not check
        out = self.rehacer(*[(x, 200) for x in f], ('creación 0.0012; salida 480 x $3.75 = 1,800', 1800.0012))
        self.assertEqual([(r['cuadra'], r['sin_interpretar']) for r in out['rows']], [(None, [x]) for x in f] + [(None, ['creación 0.0012'])])
        self.assertEqual(out['resumen'], {'calculos': 8, 'cuadran': 0, 'no_cuadran': 0, 'no_comprobables': 8})

    def texto(self, raw):  # the script on a file written by hand: JSON's own numbers, json.load's NaN and Infinity, anything
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'a.json'
            f.write_text(raw, encoding='utf-8')
            r = subprocess.run([sys.executable, '-I', str(RONDA / 'rehacer_calculos.py'), str(f)], capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout, r.stderr

    def estricto(self, out):  # JSON that any reader takes: json.loads alone accepts NaN and Infinity
        return json.loads(out, parse_constant=lambda c: self.fail(f'not strict JSON: {c}'))

    def test_an_amount_or_a_sum_past_a_float_is_never_checked(self):  # GPT on 0459898
        big = '9' * 400
        rows = {'1e309': '{"calculations":[{"formula":"100 x $2","monthly_usd":1e309}]}',  # GPT's own input
                'nan': '{"calculations":[{"formula":"100 x $2","monthly_usd":NaN}]}',
                'int': '{"calculations":[{"formula":"100 x $2","monthly_usd":' + '1' * 400 + '}]}'}
        for k, raw in rows.items():
            rc, out, err = self.texto(raw)
            self.assertEqual(rc, 0, err)
            self.assertEqual([(r['cuadra'], r['motivo']) for r in self.estricto(out)['rows']], [(None, 'sin_monto')], k)
        calcs = [('$' + big, 1), ('$' + '9' * 200 + ' x ' + '9' * 200, 1), ('$' + big + ' x 0', 0), ('$' + big + '; 100 x $2', 200),
                 ('100 x $2 = ' + big, 200)]
        out = self.estricto(self.texto(json.dumps({'calculations': [{'formula': f, 'monthly_usd': u} for f, u in calcs]}))[1])
        self.assertEqual([(r['cuadra'], r['desbordan']) for r in out['rows']], [(None, [f]) for f, _ in calcs[:3]]
                         + [(None, ['$' + big]), (None, ['100 x $2 = ' + big])])
        two = '$' + '9' * 308  # each a float, their sum not
        rc, out, err = self.texto(json.dumps({'calculations': [{'formula': two + '; ' + two, 'monthly_usd': 1}]}))
        self.assertEqual([(r['cuadra'], r['motivo'], r['rehecho']) for r in self.estricto(out)['rows']], [(None, 'desborda', None)])

    def test_any_json_gives_strict_json_and_squares_only_what_it_redid(self):  # the property, over hostile inputs
        rng = random.Random(20261122)
        piezas = ['100', '2', '0', '$2', '$0.005', '3,600', '9' * 309, '0.0012', 'x', '×', '*', '+', '=', ';', '/', '-', 'MTok',
                  'lecturas', 'é', '٣', '1,00', '1.', ' ']
        montos = ['200', '0', '-1', '1e-300', '1e308', '1e309', '-1e309', 'NaN', 'Infinity', '-Infinity', '1' * 400, 'true', 'null',
                  '"200"', '[]', '{}', '12000', '0.003']
        items = []
        for _ in range(400):
            f = ' '.join(rng.choice(piezas) for _ in range(rng.randint(0, 9)))
            items.append('{"provider":%s,"formula":%s,"monthly_usd":%s}' % (rng.choice(montos), json.dumps(f), rng.choice(montos)))
        items += ['[]', '7', '"x"', 'null', '{"formula":"100 x $2","monthly_usd":200}']
        rc, out, err = self.texto('{"calculations":[' + ','.join(items) + ']}')
        self.assertEqual(rc, 0, err)
        rows = self.estricto(out)['rows']
        self.assertEqual(len(rows), len(items))
        self.assertEqual([r['motivo'] for r in rows[400:404]], ['no_es_objeto'] * 4)
        self.assertIs(rows[-1]['cuadra'], True)
        for r in rows:
            self.assertIn(r['cuadra'], (True, False, None))
            if r['cuadra'] is True:  # only a finite amount within 1 % of what it redid, everything read
                self.assertTrue(isinstance(r['dice'], (int, float)) and not isinstance(r['dice'], bool) and math.isfinite(r['dice']))
                self.assertLessEqual(abs(r['rehecho'] - r['dice']), 0.01 * max(abs(r['dice']), 1e-9) + 1e-4)
                self.assertFalse({'sin_interpretar', 'igualdad_falsa', 'desbordan', 'motivo'} & set(r))
            if r['cuadra'] is False:
                self.assertFalse({'sin_interpretar', 'desbordan', 'motivo'} & set(r) and 'igualdad_falsa' not in r)
        for raw in ('[]', '{"calculations": 7}', '{"calculations": {"a": 1}}'):  # not an object with a list: an error, never rows
            rc, out, err = self.texto(raw)
            self.assertEqual((rc, out), (1, ''))
            self.assertIn('se espera un objeto JSON con una lista calculations', err)


if __name__ == '__main__':
    unittest.main()
