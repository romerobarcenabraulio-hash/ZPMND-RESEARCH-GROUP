"""scripts/ocr_medir.py and .github/workflows/ocr-medir.yml: the sample comes from the catalog, the NVIDIA key goes only
to NVIDIA and never sits where a PDF is opened, and the job that has it reads only checked JPEGs."""
import http.client
import importlib.util
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
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


def fila(sha, media, url='https://www.ordenjuridico.gob.mx/Documentos/x.pdf', redistribucion='allowed'):
    return {'artifact': {'sha256': sha, 'media_type': media, 'url': url, 'redistribution': redistribucion}}


def listas(d, n):
    """n pages as `preparar` leaves them for the key phase."""
    shas = [c * 64 for c in 'abcdef'[:n]]
    (d / 'medicion.json').write_text(json.dumps({'paginas': [{'sha256': x, 'pagina': 1} for x in shas],
                                                 'documentos': [], 'saltados': {}}))
    for x in shas:
        (d / f'{x}-p1.jpg').write_bytes(JPEG); (d / f'{x}-p1.tesseract.txt').write_text('Texto')


def _vivo(pid):
    """Whether pid is a live process; a zombie waiting for its reaper is not."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0] != 'Z'
    except OSError:  # no /proc (macOS): launchd reaps an orphan at once
        return True


def _muere(pid, plazo=10):
    fin = time.monotonic() + plazo
    while _vivo(pid):
        if time.monotonic() > fin:
            return False
        time.sleep(0.05)
    return True


class Muestra(unittest.TestCase):
    def test_only_stored_pdf_and_doc_once_each_in_sha_order(self):
        filas = [fila('c' * 64, 'application/pdf'), fila('b' * 64, 'application/msword'), fila('c' * 64, 'application/pdf'),
                 fila('d' * 64, 'text/html'), fila('short', 'application/pdf'), {'artifact': None}]
        self.assertEqual([(s[:1], t) for s, _, t in o.muestra(filas)], [('b', 'doc'), ('c', 'pdf')])

    def test_only_files_the_catalog_may_redistribute(self):
        # GPT on 212e8f8: the sample is kept in the artifact and sent to NVIDIA, so a hash alone is no permission
        for r in (None, 'restricted', 'unknown'):
            with self.subTest(redistribucion=r):
                self.assertEqual(o.muestra([fila('c' * 64, 'application/pdf', redistribucion=r)]), [])

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

    def test_a_file_that_breaks_a_parser_is_its_own_result_and_the_next_one_goes_on(self):
        # GPT and the auditor on 212e8f8: one corrupt file ended the job and lost what was measured
        import hashlib
        import subprocess
        from rg.catalog.fetch import Response
        uno, dos = b'%PDF uno', b'%PDF dos'
        s1, s2 = sorted([hashlib.sha256(uno).hexdigest(), hashlib.sha256(dos).hexdigest()])
        cuerpos = {hashlib.sha256(uno).hexdigest(): uno, hashlib.sha256(dos).hexdigest(): dos}
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); (d / 'cat').mkdir()
            (d / 'cat' / 'x.jsonl').write_text(''.join(json.dumps(fila(h, 'application/pdf', url=f'https://www.ordenjuridico.gob.mx/{h}')) + '\n' for h in cuerpos))
            falso = mock.Mock(); falso.return_value.get.side_effect = lambda u: Response(200, cuerpos[u.rsplit('/', 1)[1]], u)

            def correr(cmd, timeout=300):
                if cmd[0] == 'pdfinfo' and s1 in cmd[1]:
                    raise subprocess.CalledProcessError(1, cmd)
                return b'Pages: 0\n' if cmd[0] == 'pdfinfo' else b'v 1\n'
            with mock.patch('rg.catalog.fetch.Fetcher', falso), mock.patch.object(o, 'correr', correr):
                out = o.preparar(d / 'cat', d / 'out', 5, 0)
            self.assertEqual(out['saltados'], {s1: 'CalledProcessError'})
            self.assertEqual(json.loads((d / 'out' / 'medicion.json').read_text())['saltados'], {s1: 'CalledProcessError'})

    def test_what_was_measured_is_on_disk_when_a_later_file_stops_the_run(self):
        import hashlib
        from rg.catalog.fetch import Response
        uno, dos = b'%PDF uno', b'%PDF dos'
        h = sorted([hashlib.sha256(uno).hexdigest(), hashlib.sha256(dos).hexdigest()])
        cuerpos = {hashlib.sha256(uno).hexdigest(): uno, hashlib.sha256(dos).hexdigest(): dos}

        def get(u):
            k = u.rsplit('/', 1)[1]
            if k == h[1]:
                raise KeyboardInterrupt
            return Response(200, b'otros', u)
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); (d / 'cat').mkdir()
            (d / 'cat' / 'x.jsonl').write_text(''.join(json.dumps(fila(k, 'application/pdf', url=f'https://www.ordenjuridico.gob.mx/{k}')) + '\n' for k in cuerpos))
            falso = mock.Mock(); falso.return_value.get.side_effect = get
            with mock.patch('rg.catalog.fetch.Fetcher', falso), mock.patch.object(o, 'correr', return_value=b'v\n'), \
                    self.assertRaises(KeyboardInterrupt):
                o.preparar(d / 'cat', d / 'out', 5, 0)
            self.assertEqual(json.loads((d / 'out' / 'medicion.json').read_text())['saltados'], {h[0]: 'otro sha256'})

    def test_a_doc_counts_characters_not_bytes(self):
        import hashlib
        from rg.catalog.fetch import Response
        doc = b'\xd0\xcf\x11\xe0 doc'; h = hashlib.sha256(doc).hexdigest()
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); (d / 'cat').mkdir()
            (d / 'cat' / 'x.jsonl').write_text(json.dumps(fila(h, 'application/msword')) + '\n')
            falso = mock.Mock(); falso.return_value.get.return_value = Response(200, doc, 'u')
            with mock.patch('rg.catalog.fetch.Fetcher', falso), mock.patch.object(o, 'correr', return_value='Artículo'.encode()):
                out = o.preparar(d / 'cat', d / 'out', 0, 1)
            self.assertEqual(out['documentos'][0]['caracteres'], 8)

    def test_a_run_that_measured_nothing_is_never_green(self):
        with mock.patch.dict(os.environ, {'NVIDIA_API_KEY': ''}), \
                mock.patch.object(o, 'preparar', return_value={'paginas': [], 'documentos': [], 'saltados': {}}), \
                self.assertRaises(SystemExit):
            o.main(['preparar', '--catalogo', '.', '--salida', '.'])


class Nvidia(unittest.TestCase):
    def test_the_key_goes_only_to_nvidia_in_a_header_with_the_page_as_a_jpeg(self):
        seen = {}

        def post(req, timeout):
            seen.update(url=req.full_url, auth=req.get_header('Authorization'), body=json.loads(req.data), timeout=timeout)
            return json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': 'Texto'}}]}).encode()
        self.assertEqual(o.nvidia(JPEG, 'llave', post=post), ('Texto', 'ok'))
        self.assertEqual(seen['url'], 'https://integrate.api.nvidia.com/v1/chat/completions')
        self.assertEqual((seen['auth'], seen['timeout']), ('Bearer llave', o.PLAZO_LLAMADA))
        part = seen['body']['messages'][0]['content'][0]
        self.assertTrue(part['image_url']['url'].startswith('data:image/jpeg;base64,'))
        self.assertNotIn('llave', json.dumps(seen['body']))

    def test_an_error_or_a_cut_answer_is_never_a_reading(self):
        for code in (401, 302):  # a redirect is an error, never followed: the key would go with it (212e8f8)
            err = urllib.error.HTTPError(o.API_URL, code, 'no', {}, io.BytesIO(b'eco de la llave'))
            with self.subTest(code=code):
                self.assertEqual(o.nvidia(JPEG, 'llave', post=mock.Mock(side_effect=err)), (None, f'http {code}'))
        self.assertIsNone(o.leer_respuesta({'choices': [{'finish_reason': 'length', 'message': {'content': 'a medias'}}]}))
        cortada = http.client.IncompleteRead(b'{"choices"')
        self.assertEqual(o.nvidia(JPEG, 'llave', post=mock.Mock(side_effect=cortada)), (None, 'IncompleteRead'))

    def test_the_post_uses_the_catalogs_no_redirect_and_public_address_handlers(self):
        from rg.catalog.fetch import _NoRedirect, _PublicHTTPS
        handlers = []

        class Abierto(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        opener = mock.Mock(); opener.open.return_value = Abierto(b'{}')
        with mock.patch.object(o.urllib.request, 'build_opener', lambda *h: handlers.extend(h) or opener):
            self.assertEqual(o._post(mock.Mock(), 5), b'{}')
        self.assertEqual(handlers, [_NoRedirect, _PublicHTTPS])
        opener.open.return_value = Abierto(b'x' * (o.MAX_RESPUESTA + 1))
        with mock.patch.object(o.urllib.request, 'build_opener', lambda *h: opener), self.assertRaises(ValueError):
            o._post(mock.Mock(), 5)

    def test_the_key_phase_reads_only_checked_jpegs(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            paginas = [{'sha256': SHA, 'pagina': 1}, {'sha256': 'b' * 64, 'pagina': 1}, {'sha256': '../x', 'pagina': 1},
                       {'sha256': list('a' * 64), 'pagina': 1}, {'sha256': 'c' * 64, 'pagina': 1}, {'sha256': 'd' * 64, 'pagina': 1}]
            (d / 'medicion.json').write_text(json.dumps({'paginas': paginas}))
            (d / f'{SHA}-p1.jpg').write_bytes(JPEG); (d / f'{SHA}-p1.tesseract.txt').write_text('Texto')
            (d / f'{"b" * 64}-p1.jpg').write_bytes(b'%PDF-1.7 not an image')
            (d / 'fuera.jpg').write_bytes(JPEG); os.symlink(d / 'fuera.jpg', d / f'{"d" * 64}-p1.jpg')  # c has no image
            with mock.patch.object(o, 'nvidia', return_value=('Texto', 'ok')) as nv:
                out = o.fase_nvidia(d, 'llave')
            self.assertEqual(nv.call_count, 2)  # the one good page, twice: the repeatability figure
            self.assertEqual([p['nvidia']['estado'] for p in out['paginas']],
                             ['ok', 'imagen inesperada', 'nombre inesperado', 'nombre inesperado', 'falta la imagen',
                              'imagen inesperada'])
            self.assertEqual((out['paginas'][0]['nvidia']['repetible'], out['paginas'][0]['parecido']), (True, 1.0))

    def test_an_answer_that_holds_the_key_leaves_nothing_of_it_on_disk(self):
        # GPT on 2b460e3: a 200 that echoed the key went to .nvidia.md and the artifact; the check of PR #89
        llave = 'llave-de-prueba-nv'
        esc = llave.replace('v', '\\u0076')

        def resp(mensaje):
            return ('{"choices": [{"finish_reason": "stop", "message": ' + mensaje + '}]}').encode()
        cuerpos = {'literal': resp('{"content": "texto ' + llave + '"}'), 'escapada': resp('{"content": "texto ' + esc + '"}'),
                   'propiedad repetida': resp('{"content": "' + esc + '", "content": "limpio"}'),
                   'no es JSON': b'<html>texto</html>', 'no es UTF-8': b'\xff\xfe'}
        for nombre, cuerpo in cuerpos.items():
            with self.subTest(nombre), tempfile.TemporaryDirectory() as d:
                d = Path(d); listas(d, 1)
                with mock.patch.object(o, '_post', return_value=cuerpo):
                    pagina = o.fase_nvidia(d, llave)['paginas'][0]
                self.assertEqual((pagina['nvidia']['estado'], pagina['nvidia']['caracteres'], pagina['nvidia']['repetible']),
                                 ('rechazada: trae la llave o no se puede revisar entera', 0, None))
                self.assertNotIn('parecido', pagina)
                self.assertEqual(list(d.glob('*.nvidia.md')), [])
                for f in d.iterdir():
                    self.assertNotIn(llave.encode(), f.read_bytes())

    def test_repeatable_only_from_two_readings_and_a_phase_with_no_reading_is_red_after_saving(self):
        # GPT on 2b460e3: all 401 gave zero characters, 'repetible' true and a green phase
        for respuestas, rojo in (([(None, 'http 401')] * 4, True), ([('Texto', 'ok')] * 2 + [(None, 'TimeoutError')] * 2, False)):
            with self.subTest(rojo=rojo), tempfile.TemporaryDirectory() as d:
                d = Path(d); listas(d, 2)
                with mock.patch.dict(os.environ, {'NVIDIA_API_KEY': 'llave'}), mock.patch.object(o, 'nvidia', side_effect=respuestas), \
                        mock.patch('sys.stdout', io.StringIO()):
                    if rojo:
                        with self.assertRaises(SystemExit) as e:
                            o.main(['nvidia', '--salida', str(d)])
                        self.assertIn('no reading', e.exception.code)
                    else:
                        self.assertEqual(o.main(['nvidia', '--salida', str(d)]), 0)
                guardado = [p['nvidia'] for p in json.loads((d / 'medicion.json').read_text())['paginas']]
                self.assertEqual([(p['estado'], p['repetible']) for p in guardado],
                                 [('http 401', None)] * 2 if rojo else [('ok', True), ('TimeoutError', None)])

    def test_each_page_is_on_disk_before_the_next_is_asked(self):
        # GPT on 2b460e3: medicion.json was written only at the end, and the job can be cut short
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); listas(d, 2)
            with mock.patch.object(o, 'nvidia', side_effect=[('Texto', 'ok'), ('Texto', 'ok'), KeyboardInterrupt]), \
                    self.assertRaises(KeyboardInterrupt):
                o.fase_nvidia(d, 'llave')
            guardado = json.loads((d / 'medicion.json').read_text())['paginas']
            self.assertEqual([p.get('nvidia', {}).get('estado') for p in guardado], ['ok', None])

    def test_a_page_whose_files_cannot_be_read_is_its_own_result_and_the_next_is_read(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); listas(d, 2); (d / f'{SHA}-p1.tesseract.txt').unlink()
            with mock.patch.object(o, 'nvidia', return_value=('Texto', 'ok')):
                out = o.fase_nvidia(d, 'llave')
            self.assertEqual([p['nvidia']['estado'] for p in out['paginas']], ['FileNotFoundError', 'ok'])

    def test_no_page_starts_after_the_phase_deadline_and_the_rest_stay_pending(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); listas(d, 3)
            reloj = iter([0, 0, o.PLAZO_FASE, o.PLAZO_FASE + 1]).__next__
            with mock.patch.object(o, 'nvidia', return_value=('Texto', 'ok')) as nv:
                o.fase_nvidia(d, 'llave', reloj=reloj)
            guardado = json.loads((d / 'medicion.json').read_text())['paginas']
            self.assertEqual([p['nvidia']['estado'] for p in guardado], ['ok', 'pendiente', 'pendiente'])
            self.assertEqual(nv.call_count, 2)

    def test_each_phase_refuses_the_wrong_side_of_the_key(self):
        with mock.patch.dict(os.environ, {'NVIDIA_API_KEY': 'llave'}), mock.patch.object(o, 'preparar') as prep, \
                self.assertRaises(SystemExit) as e:
            o.main(['preparar', '--catalogo', '.', '--salida', '.'])
        self.assertIn('never runs where the NVIDIA key is', str(e.exception.code))
        prep.assert_not_called()
        with mock.patch.dict(os.environ, {'NVIDIA_API_KEY': ''}), self.assertRaises(SystemExit):
            o.main(['nvidia', '--salida', '.'])


class Correr(unittest.TestCase):
    """correr with real processes (GPT on 2b460e3: the tests replaced it, so no limit of it was proven)."""

    def test_a_parser_that_ends_gives_its_output_and_one_that_fails_is_an_error(self):
        self.assertEqual(o.correr([sys.executable, '-c', 'print("hola")']), b'hola\n')
        with self.assertRaises(subprocess.CalledProcessError):
            o.correr([sys.executable, '-c', 'import sys; sys.exit(3)'])

    def test_a_parser_that_prints_without_end_is_cut_at_the_cap_and_killed(self):
        with tempfile.TemporaryDirectory() as d:
            pid = Path(d) / 'pid'
            sin_fin = (f'import os, sys, time\nopen({str(pid)!r}, "w").write(str(os.getpid()))\n'
                       'while True:\n    sys.stdout.buffer.write(b"x" * 65536); sys.stdout.buffer.flush(); time.sleep(0.001)\n')
            with self.assertRaises(o.SalidaGrande):
                o.correr([sys.executable, '-c', sin_fin], timeout=5, tope=1_000_000)
            self.assertTrue(_muere(int(pid.read_text())))

    def test_at_the_deadline_the_whole_group_dies_a_child_included(self):
        with tempfile.TemporaryDirectory() as d:
            hijo = Path(d) / 'hijo'
            duerme = ('import subprocess, sys, time\n'
                      'h = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], stdout=subprocess.DEVNULL)\n'
                      f'open({str(hijo)!r}, "w").write(str(h.pid))\ntime.sleep(10)\n')
            gotea = 'import sys, time\nfor _ in range(50):\n    sys.stdout.write("x"); sys.stdout.flush(); time.sleep(0.2)\n'
            for nombre, codigo in (('duerme con un hijo', duerme), ('gotea', gotea)):
                with self.subTest(nombre):
                    t0 = time.monotonic()
                    with self.assertRaises(subprocess.TimeoutExpired):
                        o.correr([sys.executable, '-c', codigo], timeout=3)
                    self.assertLess(time.monotonic() - t0, 8)  # the deadline, not the parser's own end at 10 s
                    if nombre == 'duerme con un hijo':
                        h = int(hijo.read_text())
                        self.addCleanup(lambda: _vivo(h) and os.kill(h, signal.SIGKILL))
                        self.assertTrue(_muere(h))

    def test_each_parser_asks_for_its_memory_cap(self):
        with mock.patch.object(o.resource, 'setrlimit') as lim:
            o._limites()
        lim.assert_called_once_with(o.resource.RLIMIT_AS, (o.MEMORIA, o.MEMORIA))

    @unittest.skipUnless(sys.platform.startswith('linux'),
                         'RLIMIT_AS is enforced only on Linux (macOS cannot lower it); CI runs this suite on Linux')
    def test_a_parser_cannot_take_more_than_its_memory_cap(self):
        mapa = 'import mmap; mmap.mmap(-1, {} << 30, mmap.MAP_PRIVATE); print("ok")'
        self.assertEqual(o.correr([sys.executable, '-c', mapa.format(1)], timeout=30), b'ok\n')
        with self.assertRaises(subprocess.CalledProcessError):
            o.correr([sys.executable, '-c', mapa.format(3)], timeout=30)  # 3 GiB against a cap of 2


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

    def test_the_key_phase_fits_in_its_step_and_its_job(self):
        # GPT on 2b460e3: 40 pages x 2 calls x 180 s was four hours in a 60-minute job
        paso = next(s for s in self.jobs['nvidia']['steps'] if 'secrets.' in yaml.safe_dump(s))
        self.assertLessEqual(o.MAX_PAGINAS * 2 * o.PLAZO_LLAMADA, o.PLAZO_FASE)
        self.assertLess(o.PLAZO_FASE + 2 * o.PLAZO_LLAMADA, paso['timeout-minutes'] * 60)
        self.assertLess(paso['timeout-minutes'], self.jobs['nvidia']['timeout-minutes'])

    def test_the_page_count_reaches_the_script_through_the_environment_and_is_checked(self):
        step = next(s for s in self.jobs['preparar']['steps'] if 'ocr_medir.py preparar' in s.get('run', ''))
        self.assertEqual(step['env'], {'PAGINAS': '${{ inputs.paginas }}'})
        self.assertIn('[[ "$PAGINAS" =~ ^[0-9]{1,2}$ ]]', step['run'])
        self.assertNotIn('${{', step['run'])


if __name__ == '__main__':
    unittest.main()
