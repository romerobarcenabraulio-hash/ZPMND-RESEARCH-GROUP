"""docs/ADQUISICION.md, schemas/adquisicion.schema.json and its check in rg/sondeo.py: a source declares how it is
loaded (its route and what the route needs) and nothing in that declaration can reach outside the source's own hosts."""
import copy
import unittest

from rg import sondeo

BASE = {'source_id': 'int.ejemplo', 'status': 'candidate', 'subarea': 'I01', 'clase': 'dataset', 'title': 'Ejemplo',
        'publisher': 'Quien', 'base_url': 'https://ejemplo.org', 'allowed_hosts': ['ejemplo.org', 'datos.ejemplo.org'],
        'alcance': 'Mundo', 'license': 'CC0'}
VALID = {
    'volcado_archivos': {'via': 'volcado', 'archivos': [{'url': 'https://datos.ejemplo.org/todo.jsonl.gz', 'formato': 'jsonl',
                                                       'compresion': 'gz', 'checksum': {'algoritmo': 'sha256', 'url': 'https://datos.ejemplo.org/todo.sha256'}}],
                         'registro': {'id_ruta': ['id']}, 'frecuencia': 'mensual', 'licencia_url': 'https://ejemplo.org/licencia'},
    'volcado_indice': {'via': 'volcado', 'indice': {'url': 'https://datos.ejemplo.org/base/', 'sufijo': '.xml.gz', 'formato': 'xml',
                                                    'compresion': 'gz', 'max_archivos': 1500},
                       'registro': {'elemento': 'PubmedArticle', 'id_elemento': 'PMID'}, 'frecuencia': 'anual'},
    'api': {'via': 'api', 'url': 'https://datos.ejemplo.org/v1/obras',
            'paginacion': {'tipo': 'cursor', 'parametro': 'cursor', 'tamano_parametro': 'per-page', 'tamano': 200,
                           'ruta_items': ['results'], 'ruta_siguiente': ['meta', 'next_cursor'], 'max_paginas': 100000},
            'registro': {'id_ruta': ['id']}, 'frecuencia': 'semanal'},
    'sitemap': {'via': 'sitemap', 'url': 'https://ejemplo.org/sitemap.xml', 'prefijo': 'https://ejemplo.org/leyes/',
                'max_urls': 50000, 'frecuencia': 'semanal'},
    'rastreo': {'via': 'rastreo', 'semillas': ['https://ejemplo.org/leyes/'], 'prefijo': 'https://ejemplo.org/leyes/',
                'profundidad_max': 3, 'max_paginas': 20000, 'frecuencia': 'mensual'},
    'manual': {'via': 'manual', 'quien': 'Braulio', 'nota': 'Catálogo de pago: se compra la licencia de metadatos.'},
}


def errores(adq, via=None):
    f = copy.deepcopy(BASE)
    f['via'] = via or adq.get('via', 'volcado')
    f['adquisicion'] = adq
    return sondeo.errores({'familia': 'I', 'nombre': 'I', 'fuentes': [f]}, 'I')


class Contrato(unittest.TestCase):
    def test_every_route_has_a_valid_declaration(self):
        for name, adq in VALID.items():
            with self.subTest(name):
                self.assertEqual(errores(adq), [])

    def test_a_declaration_the_contract_does_not_allow_is_refused(self):
        bad = {
            'http url': {**VALID['sitemap'], 'url': 'http://ejemplo.org/sitemap.xml'},
            'unknown key': {**VALID['manual'], 'script': 'run.sh'},
            'dump with no files and no index': {k: v for k, v in VALID['volcado_archivos'].items() if k != 'archivos'},
            'dump with files and index': {**VALID['volcado_archivos'], 'indice': VALID['volcado_indice']['indice']},
            'api with no page cap': {**VALID['api'], 'paginacion': {k: v for k, v in VALID['api']['paginacion'].items() if k != 'max_paginas'}},
            'two ways to find the id': {**VALID['api'], 'registro': {'id_ruta': ['id'], 'id_columna': 'id'}},
            'checksum with no value nor url': {**VALID['volcado_archivos'], 'archivos': [{**VALID['volcado_archivos']['archivos'][0], 'checksum': {'algoritmo': 'sha256'}}]},
            'crawl too deep': {**VALID['rastreo'], 'profundidad_max': 6},
            'xml element that is not a name': {**VALID['volcado_indice'], 'registro': {'elemento': '<!ENTITY', 'id_elemento': 'PMID'}},
        }
        for name, adq in bad.items():
            with self.subTest(name):
                self.assertTrue(errores(adq), name)

    def test_the_route_must_be_the_sources_route(self):
        self.assertTrue(any('is not the source' in e for e in errores(VALID['api'], via='volcado')))

    def test_no_url_of_the_declaration_leaves_the_sources_hosts(self):
        for where, adq in (('licence', {**VALID['volcado_archivos'], 'licencia_url': 'https://otro.org/licencia'}),
                           ('prefix', {**VALID['rastreo'], 'prefijo': 'https://otro.org/'}),
                           ('seed', {**VALID['rastreo'], 'semillas': ['https://otro.org/']}),
                           ('checksum', {**VALID['volcado_archivos'], 'archivos': [{**VALID['volcado_archivos']['archivos'][0],
                                         'checksum': {'algoritmo': 'md5', 'url': 'https://otro.org/x.md5'}}]})):
            with self.subTest(where):
                self.assertTrue(any('host not in allowed_hosts' in e for e in errores(adq)))


if __name__ == '__main__':
    unittest.main()
