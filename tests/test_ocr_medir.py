"""scripts/ocr_medir.py and .github/workflows/ocr-medir.yml: the sample comes from the catalog, the NVIDIA key goes only
to NVIDIA and never sits where a PDF is opened, and the job that has it reads only checked JPEGs."""
import importlib.util
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('ocr_medir', ROOT / 'scripts' / 'ocr_medir.py')
o = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(o)
SHA = 'a' * 64
JPEG = b'\xff\xd8\xff\xe0' + b'x' * 100


def fila(sha, media, url='https://www.ordenjuridico.gob.mx/Documentos/x.pdf'):
    return {'artifact': {'sha256': sha, 'media_type': media, 'url': url}}


class Muestra(unittest.TestCase):
    def test_only_stored_pdf_and_doc_once_each_in_sha_order(self):
        filas = [fila('c' * 64, 'application/pdf'), fila('b' * 64, 'application/msword'), fila('c' * 64, 'application/pdf'),
                 fila('d' * 64, 'text/html'), fila('short', 'application/pdf'), {'artifact': None}]
        self.assertEqual([(s[:1], t) for s, _, t in o.muestra(filas)], [('b', 'doc'), ('c', 'pdf')])

    def test_agreement_ignores_case_and_spacing(self):
        self.assertEqual(o.parecido('Artículo  1.\nLa ley', 'artículo 1. la LEY'), 1.0)
        self.assertLess(o.parecido('Artículo 1', 'Capítulo 9'), 1.0)


class Preparar(unittest.TestCase):
    def test_only_the_catalogs_own_bytes_are_read(self):
        from rg.catalog.fetch import Response
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); (d / 'cat').mkdir()
            (d / 'cat' / 'x.jsonl').write_text(json.dumps(fila(SHA, 'application/pdf')) + '\n')
            falso = mock.Mock(); falso.return_value.get.return_value = Response(200, b'otros bytes', 'u')
            with mock.patch('rg.catalog.fetch.Fetcher', falso), mock.patch.object(o, 'correr', return_value=b'tesseract 5\n'):
                out = o.preparar(d / 'cat', d / 'out', 1, 0)
            self.assertEqual((out['saltados'], out['paginas']), ({SHA: 'otro sha256'}, []))
            self.assertFalse((d / 'out' / f'{SHA}.pdf').exists())


class Nvidia(unittest.TestCase):
    def test_the_key_goes_only_to_nvidia_in_a_header_with_the_page_as_a_jpeg(self):
        seen = {}

        def urlopen(req, timeout):
            seen.update(url=req.full_url, auth=req.get_header('Authorization'), body=json.loads(req.data))
            return io.BytesIO(json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': 'Texto'}}]}).encode())
        with mock.patch.object(o.urllib.request, 'urlopen', urlopen):
            self.assertEqual(o.nvidia(JPEG, 'llave'), ('Texto', 'ok'))
        self.assertEqual(seen['url'], 'https://integrate.api.nvidia.com/v1/chat/completions')
        self.assertEqual(seen['auth'], 'Bearer llave')
        part = seen['body']['messages'][0]['content'][0]
        self.assertTrue(part['image_url']['url'].startswith('data:image/jpeg;base64,'))
        self.assertNotIn('llave', json.dumps(seen['body']))

    def test_an_error_or_a_cut_answer_is_never_a_reading(self):
        err = urllib.error.HTTPError(o.API_URL, 401, 'no', {}, io.BytesIO(b'eco de la llave'))
        with mock.patch.object(o.urllib.request, 'urlopen', side_effect=err):
            self.assertEqual(o.nvidia(JPEG, 'llave'), (None, 'http 401'))
        self.assertIsNone(o.leer_respuesta({'choices': [{'finish_reason': 'length', 'message': {'content': 'a medias'}}]}))

    def test_the_key_phase_reads_only_checked_jpegs(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            paginas = [{'sha256': SHA, 'pagina': 1}, {'sha256': 'b' * 64, 'pagina': 1}, {'sha256': '../x', 'pagina': 1}]
            (d / 'medicion.json').write_text(json.dumps({'paginas': paginas}))
            (d / f'{SHA}-p1.jpg').write_bytes(JPEG); (d / f'{SHA}-p1.tesseract.txt').write_text('Texto')
            (d / f'{"b" * 64}-p1.jpg').write_bytes(b'%PDF-1.7 not an image')
            with mock.patch.object(o, 'nvidia', return_value=('Texto', 'ok')) as nv:
                out = o.fase_nvidia(d, 'llave')
            self.assertEqual(nv.call_count, 2)  # the one good page, twice: the repeatability figure
            self.assertEqual([p['nvidia']['estado'] for p in out['paginas']], ['ok', 'imagen inesperada', 'nombre inesperado'])
            self.assertEqual((out['paginas'][0]['nvidia']['repetible'], out['paginas'][0]['parecido']), (True, 1.0))

    def test_each_phase_refuses_the_wrong_side_of_the_key(self):
        with mock.patch.dict(os.environ, {'NVIDIA_API_KEY': 'llave'}), self.assertRaises(SystemExit):
            o.main(['preparar', '--catalogo', '.', '--salida', '.'])
        with mock.patch.dict(os.environ, {'NVIDIA_API_KEY': ''}), self.assertRaises(SystemExit):
            o.main(['nvidia', '--salida', '.'])


class Flujo(unittest.TestCase):
    raw = (ROOT / '.github' / 'workflows' / 'ocr-medir.yml').read_text(encoding='utf-8')
    doc = yaml.safe_load(raw)
    jobs = doc['jobs']

    def test_mains_code_only_by_dispatch(self):
        self.assertEqual(set(self.doc[True]), {'workflow_dispatch'})
        self.assertEqual(self.doc['permissions'], {})
        for name, job in self.jobs.items():
            with self.subTest(job=name):
                self.assertEqual(job['if'], "github.ref == 'refs/heads/main'")
                self.assertEqual(job['permissions'], {'contents': 'read'})
                self.assertEqual(job['steps'][0]['with'], {'ref': 'main', 'persist-credentials': False})

    def test_the_key_never_sits_where_a_file_is_opened(self):
        self.assertEqual(self.raw.count('secrets.'), 1)
        self.assertNotIn('secrets.', yaml.safe_dump(self.jobs['preparar']))
        holders = [s for s in self.jobs['nvidia']['steps'] if 'secrets.' in yaml.safe_dump(s)]
        self.assertEqual(len(holders), 1)
        self.assertEqual(holders[0]['run'].strip(), 'python3 -I scripts/ocr_medir.py nvidia --salida "$RUNNER_TEMP/ocr"')
        nv = yaml.safe_dump(self.jobs['nvidia'])
        for parser in ('apt-get', 'pdftotext', 'pdftoppm', 'tesseract', 'soffice', 'pip install'):
            self.assertNotIn(parser, nv)
        self.assertEqual(self.jobs['nvidia']['needs'], 'preparar')

    def test_the_page_count_reaches_the_script_through_the_environment_and_is_checked(self):
        step = next(s for s in self.jobs['preparar']['steps'] if 'ocr_medir.py preparar' in s.get('run', ''))
        self.assertEqual(step['env'], {'PAGINAS': '${{ inputs.paginas }}'})
        self.assertIn('[[ "$PAGINAS" =~ ^[0-9]{1,2}$ ]]', step['run'])
        self.assertNotIn('${{', step['run'])


if __name__ == '__main__':
    unittest.main()
