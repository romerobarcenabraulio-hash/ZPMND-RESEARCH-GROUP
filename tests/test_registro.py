"""Rules 21 and 23 (docs/REGLAS.md, rg/alcance.py, SECURITY.md T28): a source runs only naming who asked for it (a request
of requests/ or a ZPPMND unit) and how it is acquired; the legacy frontier of sources/mx.json keeps running as it is."""
import ast
import copy
import json
import tempfile
import unittest
from pathlib import Path

from rg import alcance, sondeo

ROOT = Path(__file__).resolve().parents[1]
# The frontier by hand, never read from the data: the seven adapters of rg/catalog/run.py and the eight sources that
# ran on 2026-11-02 (leyesbiblio serves two). Changing it is a decision of its own PR.
LEGADO = {'mx.dof': 'sidof', 'mx.leyes-federales': 'leyesbiblio', 'mx.reglamentos-federales': 'leyesbiblio',
          'mx.ojn-estatal': 'ojn', 'mx.ojn-municipal': 'ojn-municipal', 'mx.hf-tesis-scjn': 'hf-tesis',
          'mx.banxico-sie': 'banxico-sie', 'mx.inegi-bie': 'inegi-bie'}
PIDE = 'RR-2026-11-02-nom035-autoauditoria'
API = {'via': 'api', 'url': 'https://datos.ejemplo.org/v1/obras',
       'paginacion': {'tipo': 'cursor', 'parametro': 'cursor', 'ruta_items': ['results'],
                      'ruta_siguiente': ['meta', 'next_cursor'], 'max_paginas': 100},
       'registro': {'id_ruta': ['id']}, 'frecuencia': 'semanal'}
MX = {'sources': [{'source_id': 'mx.viejo', 'status': 'active', 'legacy': True, 'adapter': 'x'},
                  {'source_id': 'mx.plan', 'status': 'planned'}],
      'secondary_sources': [{'source_id': 'mx.otro', 'status': 'candidate'}]}
REG = [('I', {'source_id': 'int.uno', 'status': 'candidate', 'via': 'api', 'allowed_hosts': ['datos.ejemplo.org']}),
       ('J', {'source_id': 'int.dos', 'status': 'candidate', 'via': 'manual'})]


def leer(nombre):
    return json.loads((ROOT / 'sources' / nombre).read_text(encoding='utf-8'))


def errores(cambio):
    mx, reg = copy.deepcopy(MX), copy.deepcopy(REG)
    cambio(mx, {f['source_id']: f for _, f in reg})
    return alcance.errores(mx, reg, {PIDE})


def corre(**kw):
    """int.uno set to run: active, asked for by PIDE, acquired by API; kw overrides (None drops the field)."""
    def cambio(mx, reg):
        f = reg['int.uno']
        f.update(status='active', consumer=PIDE, adquisicion=copy.deepcopy(API))
        f.update(kw)
        for k in [k for k, v in kw.items() if v is None]:
            del f[k]
    return cambio


class Frontera(unittest.TestCase):
    def test_the_legacy_frontier_is_exactly_the_seven_adapters_that_ran(self):
        legado = alcance.frontera(leer('mx.json'))  # both lists of sources/mx.json
        self.assertEqual(legado, LEGADO)
        self.assertEqual(len(set(legado.values())), 7)

    def test_a_legacy_mark_in_either_list_counts_so_the_pin_above_catches_it(self):
        mx = copy.deepcopy(MX)
        mx['secondary_sources'][0].update(legacy=True, status='active')
        self.assertIn('mx.otro', alcance.frontera(mx))
        mx['sources'][0]['legacy'] = 'true'
        self.assertNotIn('mx.viejo', alcance.frontera(mx))  # only the JSON true is legacy


class NadieLeeVeredictos(unittest.TestCase):
    """Rule 22, T28: until the PR that verifies the constancia, no code of RG names verdicts/ (docstrings aside), so a
    file put there, even a schema-valid one, changes nothing."""
    @staticmethod
    def nombran(raiz):
        out = []
        for f in sorted(list(Path(raiz).glob('rg/**/*.py')) + list(Path(raiz).glob('scripts/**/*.py'))):
            if f.name == 'mutar.py':  # mutant definitions name files, they read nothing
                continue
            tree = ast.parse(f.read_text(encoding='utf-8'))
            docs = {id(n.body[0].value) for n in ast.walk(tree)
                    if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body
                    and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
            out += [f'{f}:{n.lineno}' for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and 'verdicts' in n.value and id(n) not in docs]
        return out

    def test_no_code_names_verdicts(self):
        self.assertEqual(self.nombran(ROOT), [])

    def test_a_reader_would_be_caught(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'rg').mkdir()
            (Path(d) / 'rg' / 'x.py').write_text('"""Mentions verdicts/ in a docstring."""\nP = "verdicts/a.json"\n', encoding='utf-8')
            self.assertEqual(len(self.nombran(d)), 1)


class Pedidos(unittest.TestCase):
    def test_the_consumers_are_the_request_ids_of_requests(self):
        self.assertIn('RR-2026-10-29-prueba-estres-norte', alcance.pedidos(ROOT / 'requests'))
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'otro-nombre.json').write_text(json.dumps({'request_id': 'RR-2026-11-02-x'}), encoding='utf-8')
            (Path(d) / 'roto.json').write_text('{', encoding='utf-8')
            (Path(d) / 'lista.json').write_text('["RR-2026-11-02-y"]', encoding='utf-8')
            self.assertEqual(alcance.pedidos(d), {'RR-2026-11-02-x'})


class Regla21(unittest.TestCase):
    def test_the_repo_names_a_consumer_for_every_source_that_runs(self):
        registro = sondeo.cargar(ROOT / 'sources' / 'registro')
        self.assertEqual(alcance.errores(leer('mx.json'), registro, alcance.pedidos(ROOT / 'requests')), [])

    def test_what_names_who_asked_and_how_it_is_acquired_runs(self):
        cases = {
            'nothing runs but the legacy frontier': lambda mx, reg: None,
            'active con consumer y adquisicion': corre(),
            'trial con consumer y adquisicion': corre(status='trial'),
            'a ZPPMND unit as consumer': corre(consumer='zpmnd:autoauditoria-nom035'),
            'planned sin consumer': lambda mx, reg: reg['int.uno'].update(status='planned'),
            'manual route without a consumer': lambda mx, reg: reg['int.dos'].update(
                adquisicion={'via': 'manual', 'quien': 'Braulio', 'nota': 'Se compra la licencia.'}),
            'removing a source': lambda mx, reg: mx['sources'].pop(1),
        }
        for name, cambio in cases.items():
            with self.subTest(name):
                self.assertEqual(errores(cambio), [])

    def test_every_way_to_run_without_naming_who_asked_is_an_error(self):
        cases = {
            'active sin consumer': corre(consumer=None),
            'trial sin consumer': lambda mx, reg: reg['int.uno'].update(status='trial'),
            'consumer con request_id inexistente': corre(consumer='RR-2026-11-02-no-existe'),
            'consumer vacío': corre(consumer=''),
            'a unit with no name': corre(consumer='zpmnd:'),
            'a consumer that is not text': corre(consumer=[PIDE]),
            'active sin adquisicion': corre(adquisicion=None),
            'adquisicion of another route': corre(adquisicion={**API, 'via': 'volcado'}),
            'adquisicion outside its hosts': corre(adquisicion={**API, 'url': 'https://otro.org/v1'}),
            'mx source runs outside the frontier': lambda mx, reg: mx['sources'][1].update(status='active'),
            'secondary source set to run': lambda mx, reg: mx['secondary_sources'][0].update(status='active'),
            'legacy as text is not legacy': lambda mx, reg: mx['sources'][0].update(legacy='true'),
            'a legacy mark in the registry grants nothing': lambda mx, reg: reg['int.uno'].update(status='active', legacy=True),
            'api route that runs, not asked for': lambda mx, reg: reg['int.uno'].update(adquisicion=copy.deepcopy(API)),
            'a block that is not an object': lambda mx, reg: reg['int.uno'].update(adquisicion='manual'),
            'legacy source with a route that runs': lambda mx, reg: mx['sources'][0].update(adquisicion={'via': 'sitemap'}),
        }
        for name, cambio in cases.items():
            with self.subTest(name):
                self.assertTrue(errores(cambio), name)


if __name__ == '__main__':
    unittest.main()
