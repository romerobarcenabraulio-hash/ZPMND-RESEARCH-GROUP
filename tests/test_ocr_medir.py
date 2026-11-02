"""scripts/ocr_medir.py and .github/workflows/ocr-medir.yml: the sample comes from the catalog, the NVIDIA key goes only
to NVIDIA and never sits where a PDF is opened, and the job that has it reads only checked JPEGs."""
import contextlib
import hashlib
import http.client
import importlib.util
import io
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
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
PNG = b'\x89PNG\r\n\x1a\n' + b'x' * 100
MOD = 'nvidia/nemotron-parse'
LEIDA = ('Texto', 'ok', MOD)  # nvidia(): a reading, with its model as the API names it
EXIGIR = os.environ.get('RG_OCR_EXIGIR_AISLADO') == '1'  # ocr-medir.yml: the real write attempt runs there, never skipped


def fila(sha, media, url='https://www.ordenjuridico.gob.mx/Documentos/x.pdf', redistribucion='allowed'):
    return {'artifact': {'sha256': sha, 'media_type': media, 'url': url, 'redistribution': redistribucion}}


def listas(d, n):
    """n pages as `preparar` leaves them for the key phase."""
    shas = [c * 64 for c in 'abcdef'[:n]]
    (d / 'medicion.json').write_text(json.dumps({'paginas': [{'sha256': x, 'pagina': 1} for x in shas],
                                                 'documentos': [], 'saltados': {}}))
    for x in shas:
        (d / f'{x}-p1.jpg').write_bytes(JPEG); (d / f'{x}-p1.tesseract.txt').write_text('Texto')


def catalogo(d, cuerpos):
    """d/cat with one OJN PDF row per body, and a Fetcher that answers each row's URL with its body."""
    from rg.catalog.fetch import Response
    por_sha = {hashlib.sha256(b).hexdigest(): b for b in cuerpos}
    (d / 'cat').mkdir()
    (d / 'cat' / 'x.jsonl').write_text(''.join(json.dumps(fila(h, 'application/pdf', url=f'https://www.ordenjuridico.gob.mx/{h}')) + '\n' for h in por_sha))
    falso = mock.Mock(); falso.return_value.get.side_effect = lambda u: Response(200, por_sha[u.rsplit('/', 1)[1]], u)
    return falso, sorted(por_sha)


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

    def test_agreement_reads_only_the_first_characters_of_each_text(self):
        comun = 'palabra ' * (o.TOPE_PARECIDO // 8 + 1)
        self.assertEqual(o.parecido(comun + 'uno ' * 5000, comun + 'dos ' * 5000), 1.0)

    def test_agreement_on_hostile_repetitive_text_ends_at_once_and_the_page_keeps_its_result(self):
        # GPT on c9491d8: SequenceMatcher with no cap was quadratic on repetitive text, outside any deadline
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); listas(d, 1); (d / f'{SHA}-p1.tesseract.txt').write_text('ab ' * 3_000_000)
            hecho = {}
            with mock.patch.object(o, 'nvidia', return_value=('ab ' * 2_999_999 + 'zz', 'ok', MOD)):
                hilo = threading.Thread(target=lambda: hecho.update(out=o.fase_nvidia(d, 'llave')), daemon=True)
                t0 = time.monotonic(); hilo.start(); hilo.join(30)  # bounded even if the cost came back (REGLAS 13)
            self.assertLess(time.monotonic() - t0, 10)
            pagina = json.loads((d / 'medicion.json').read_text())['paginas'][0]
            self.assertEqual((pagina['nvidia']['estado'], pagina['parecido']), ('ok', 1.0))


class Preparar(unittest.TestCase):
    def test_only_the_catalogs_own_bytes_are_read(self):
        from rg.catalog.fetch import Response
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); (d / 'cat').mkdir()
            (d / 'cat' / 'x.jsonl').write_text(json.dumps(fila(SHA, 'application/pdf')) + '\n')
            falso = mock.Mock(); falso.return_value.get.return_value = Response(200, b'otros bytes', 'u')
            with mock.patch('rg.catalog.fetch.Fetcher', falso), mock.patch.object(o, 'correr', return_value=b'tesseract 5\n'):
                out = o.preparar(d / 'cat', d / 'out', 1, 0, paquetes={'tesseract-ocr': '5.3.4-1build5'})
            self.assertEqual((out['saltados'], out['paginas']), ({SHA: 'otro sha256'}, []))
            self.assertEqual(out['versiones']['tesseract-ocr'], '5.3.4-1build5')
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

            def correr(cmd, **kw):
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
        with mock.patch.dict(os.environ, {'NVIDIA_API_KEY': '', o.COMO: 'rgparse'}), \
                mock.patch.object(o, 'versiones', return_value=dict.fromkeys(o.PAQUETES, '1.0')), \
                mock.patch.object(o, 'preparar', return_value={'paginas': [], 'documentos': [], 'saltados': {}}), \
                self.assertRaises(SystemExit) as e:
            o.main(['preparar', '--catalogo', '.', '--salida', '.'])
        self.assertIn('nothing was measured', e.exception.code)

    def test_a_cut_inside_one_pdf_keeps_its_measured_pages_in_the_receipt(self):
        # GPT on c9491d8: medicion.json was saved only after each file, and preparar had no deadline
        for corte in (KeyboardInterrupt(), subprocess.TimeoutExpired('pdftotext', 0)):  # the job stopped; the phase's deadline
            with self.subTest(corte=type(corte).__name__), tempfile.TemporaryDirectory() as d:
                d = Path(d); falso, (h,) = catalogo(d, [b'%PDF largo'])
                (d / 'out').mkdir(); os.chmod(d / 'out', 0o777)
                modos = []

                def correr(cmd, **kw):
                    if cmd[0] == 'pdfinfo':
                        modos.append((stat.S_IMODE(os.stat(cmd[1]).st_mode), stat.S_IMODE(os.stat(Path(cmd[1]).parent).st_mode)))
                        return b'Pages: 9\n'
                    if cmd[0] == 'pdftotext':
                        if cmd[2] == '3':
                            raise corte
                        return b''
                    return b'Texto' if cmd[0] == 'tesseract' else PNG if kw['archivo'] == 'img.png' else JPEG
                with mock.patch('rg.catalog.fetch.Fetcher', falso), mock.patch.object(o, 'correr', correr), \
                        contextlib.suppress(KeyboardInterrupt):
                    o.preparar(d / 'cat', d / 'out', 5, 0)
                guardado = json.loads((d / 'out' / 'medicion.json').read_text())
                self.assertEqual([(p['sha256'], p['pagina']) for p in guardado['paginas']], [(h, 1), (h, 2)])
                self.assertEqual(guardado['saltados'], {} if isinstance(corte, KeyboardInterrupt) else {h: 'TimeoutExpired'})
                self.assertEqual(modos, [(0o444, 0o755)])  # the parsers' input: read-only, in a folder they cannot write
                self.assertEqual(stat.S_IMODE(os.stat(d / 'out').st_mode), 0o755)  # nor can they write the results

    def test_no_file_starts_after_the_phase_deadline(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); falso, _ = catalogo(d, [b'%PDF uno'])
            with mock.patch('rg.catalog.fetch.Fetcher', falso), mock.patch.object(o, 'correr') as nunca:
                out = o.preparar(d / 'cat', d / 'out', 5, 0, plazo=0)
            falso.return_value.get.assert_not_called(); nunca.assert_not_called()
            self.assertIn('plazo', out['cortada'])

    def test_one_pdf_is_read_up_to_its_page_cap_and_a_page_image_must_be_a_png(self):
        # auditor on c9491d8: a PDF of thousands of text pages made a pdftotext each
        for paginas, imagen, esperado in (('100000', None, ({}, o.MAX_PAGINAS_PDF)), ('1', JPEG, ('ValueError', 1))):
            with self.subTest(imagen=imagen), tempfile.TemporaryDirectory() as d:
                d = Path(d); falso, (h,) = catalogo(d, [b'%PDF largo'])
                vistos = []

                def correr(cmd, **kw):
                    vistos.append(cmd[0])
                    return {'pdfinfo': f'Pages: {paginas}\n'.encode(), 'pdftotext': b'' if imagen else b'x' * o.MIN_CHARS}.get(cmd[0], imagen)
                with mock.patch('rg.catalog.fetch.Fetcher', falso), mock.patch.object(o, 'correr', correr):
                    out = o.preparar(d / 'cat', d / 'out', 5, 0)
                self.assertEqual((out['saltados'].get(h, {}), vistos.count('pdftotext')), esperado)

    def test_a_page_too_big_for_nvidia_is_made_smaller_and_must_be_a_jpeg(self):
        with mock.patch.object(o, 'correr', side_effect=[o.SalidaGrande('x'), JPEG]) as c:
            self.assertEqual(o.jpeg_bajo_limite('f.pdf', 1), JPEG)
        self.assertEqual([k.kwargs['tope'] for k in c.call_args_list], [o.IMG_MAX] * 2)
        with mock.patch.object(o, 'correr', side_effect=[o.SalidaGrande('x')] * 3):
            self.assertIsNone(o.jpeg_bajo_limite('f.pdf', 1))
        with mock.patch.object(o, 'correr', return_value=PNG), self.assertRaises(ValueError):
            o.jpeg_bajo_limite('f.pdf', 1)

    def test_each_engines_exact_apt_version_is_recorded_or_preparar_never_starts(self):
        dpkg = {'tesseract-ocr': '5.3.4-1build5', 'poppler-utils': '24.02.0-1ubuntu9.8', 'libreoffice-writer-nogui': 'x; y'}
        with mock.patch.object(o.subprocess, 'run', lambda c, **k: subprocess.CompletedProcess(c, 0 if c[-1] in dpkg else 1, dpkg.get(c[-1], ''), '')):
            v = o.versiones()
        self.assertEqual(v, {'tesseract-ocr': '5.3.4-1build5', 'tesseract-ocr-spa': None, 'poppler-utils': '24.02.0-1ubuntu9.8',
                             'libreoffice-writer-nogui': None})
        for dadas in (v, dict.fromkeys(o.PAQUETES, '1.0')):
            with self.subTest(dadas=dadas), mock.patch.dict(os.environ, {'NVIDIA_API_KEY': '', o.COMO: 'rgparse'}), \
                    mock.patch.object(o, 'versiones', return_value=dadas), mock.patch('sys.stdout', io.StringIO()), \
                    mock.patch.object(o, 'preparar', return_value={'paginas': [{}], 'documentos': [], 'saltados': {}}) as prep:
                try:
                    o.main(['preparar', '--catalogo', '.', '--salida', '.'])
                except SystemExit as e:
                    self.assertEqual(e.code, 'no exact apt version of tesseract-ocr-spa, libreoffice-writer-nogui')
                self.assertEqual(prep.call_args and prep.call_args.kwargs['paquetes'], None if dadas is v else dadas)

    def test_preparar_parses_only_as_another_user(self):
        # GPT on c9491d8: the parsers ran as the runner's user and could write the checkout and the results
        for como in ('', 'root; rm -rf /'):
            with self.subTest(como=como), mock.patch.dict(os.environ, {'NVIDIA_API_KEY': '', o.COMO: como}), \
                    mock.patch.object(o, 'versiones', return_value=dict.fromkeys(o.PAQUETES, '1.0')), \
                    mock.patch.object(o, 'preparar') as prep, self.assertRaises((SystemExit, ValueError)):
                o.main(['preparar', '--catalogo', '.', '--salida', '.'])
            prep.assert_not_called()


class Nvidia(unittest.TestCase):
    def test_the_key_goes_only_to_nvidia_in_a_header_with_the_page_as_a_jpeg(self):
        seen = {}

        def post(req, timeout):
            seen.update(url=req.full_url, auth=req.get_header('Authorization'), body=json.loads(req.data), timeout=timeout)
            return json.dumps({'model': MOD, 'choices': [{'finish_reason': 'stop', 'message': {'content': 'Texto'}}]}).encode()
        self.assertEqual(o.nvidia(JPEG, 'llave', post=post), LEIDA)
        self.assertEqual(seen['url'], 'https://integrate.api.nvidia.com/v1/chat/completions')
        self.assertEqual((seen['auth'], seen['timeout']), ('Bearer llave', o.PLAZO_LLAMADA))
        part = seen['body']['messages'][0]['content'][0]
        self.assertTrue(part['image_url']['url'].startswith('data:image/jpeg;base64,'))
        self.assertNotIn('llave', json.dumps(seen['body']))

    def test_an_error_or_a_cut_answer_is_never_a_reading(self):
        for code in (401, 302):  # a redirect is an error, never followed: the key would go with it (212e8f8)
            err = urllib.error.HTTPError(o.API_URL, code, 'no', {}, io.BytesIO(b'eco de la llave'))
            with self.subTest(code=code):
                self.assertEqual(o.nvidia(JPEG, 'llave', post=mock.Mock(side_effect=err)), (None, f'http {code}', None))
        self.assertIsNone(o.leer_respuesta({'choices': [{'finish_reason': 'length', 'message': {'content': 'a medias'}}]}))
        cortada = http.client.IncompleteRead(b'{"choices"')
        self.assertEqual(o.nvidia(JPEG, 'llave', post=mock.Mock(side_effect=cortada)), (None, 'IncompleteRead', None))

    def test_a_message_that_is_not_an_object_is_that_pages_result_and_the_next_page_is_read(self):
        # GPT on c9491d8: a 200 whose `message` was a string raised AttributeError and ended the phase
        malo = b'{"choices":[{"finish_reason":"stop","message":"x"}]}'
        bueno = json.dumps({'model': MOD, 'choices': [{'finish_reason': 'stop', 'message': {'content': 'Texto'}}]}).encode()
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); listas(d, 2)
            with mock.patch.object(o, '_post', side_effect=[malo, malo, bueno, bueno]):
                out = o.fase_nvidia(d, 'llave')
            self.assertEqual([p['nvidia']['estado'] for p in out['paginas']], ['sin texto', 'ok'])

    def test_a_reading_names_its_model_as_the_api_does_or_it_is_none(self):
        # the owner's order: pinned versions; the hosted model is named by each answer, never assumed
        def resp(**extra):
            return json.dumps({**extra, 'choices': [{'finish_reason': 'stop', 'message': {'content': 'Texto'}}]}).encode()
        self.assertEqual(o.nvidia(JPEG, 'llave', post=lambda r, t: resp(model=MOD)), LEIDA)
        for malo in ({}, {'model': ['x']}, {'model': 'a b\n'}, {'model': 'x' * 121}):
            with self.subTest(malo=malo):
                self.assertEqual(o.nvidia(JPEG, 'llave', post=lambda r, t: resp(**malo)), (None, 'sin modelo', None))

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
            with mock.patch.object(o, 'nvidia', return_value=LEIDA) as nv:
                out = o.fase_nvidia(d, 'llave')
            self.assertEqual(nv.call_count, 2)  # the one good page, twice: the repeatability figure
            self.assertEqual([p['nvidia']['estado'] for p in out['paginas']],
                             ['ok', 'imagen inesperada', 'nombre inesperado', 'nombre inesperado', 'falta la imagen',
                              'imagen inesperada'])
            self.assertEqual((out['paginas'][0]['nvidia']['repetible'], out['paginas'][0]['parecido']), (True, 1.0))
            self.assertEqual(out['paginas'][0]['nvidia']['modelo'], MOD)  # the model as the API named it

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
        for respuestas, rojo in (([(None, 'http 401', None)] * 4, True), ([LEIDA] * 2 + [(None, 'TimeoutError', None)] * 2, False)):
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
            with mock.patch.object(o, 'nvidia', side_effect=[LEIDA, LEIDA, KeyboardInterrupt]), \
                    self.assertRaises(KeyboardInterrupt):
                o.fase_nvidia(d, 'llave')
            guardado = json.loads((d / 'medicion.json').read_text())['paginas']
            self.assertEqual([p.get('nvidia', {}).get('estado') for p in guardado], ['ok', None])

    def test_a_page_whose_files_cannot_be_read_is_its_own_result_and_the_next_is_read(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); listas(d, 2); (d / f'{SHA}-p1.tesseract.txt').unlink()
            with mock.patch.object(o, 'nvidia', return_value=LEIDA):
                out = o.fase_nvidia(d, 'llave')
            self.assertEqual([p['nvidia']['estado'] for p in out['paginas']], ['FileNotFoundError', 'ok'])

    def test_no_page_starts_after_the_phase_deadline_and_the_rest_stay_pending(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); listas(d, 3)
            reloj = iter([0, 0, o.PLAZO_FASE, o.PLAZO_FASE + 1]).__next__
            with mock.patch.object(o, 'nvidia', return_value=LEIDA) as nv:
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

    def test_no_parser_runs_past_the_phases_deadline(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(o.subprocess, 'Popen') as nunca, self.assertRaises(subprocess.TimeoutExpired):
                o.correr([sys.executable, '-c', 'pass'], fin=time.monotonic() - 1)  # past it, nothing starts
            nunca.assert_not_called()
            t0 = time.monotonic()
            with self.assertRaises(subprocess.TimeoutExpired):  # the phase's deadline cuts a call that has 300 s of its own
                o.correr([sys.executable, '-c', 'import time; time.sleep(30)'], fin=time.monotonic() + 1)
            self.assertLess(time.monotonic() - t0, 10)

    def test_with_a_user_each_parser_runs_as_it_in_a_clean_environment_and_its_processes_die_after(self):
        # GPT on c9491d8. The real attempt is Aislado (CI); here, what correr asks of sudo
        hechos, vistos, real = [], [], subprocess.Popen

        def sudo(u, *c, check=False):  # kill -1 is only recorded: as this user it would end every process of ours
            hechos.append((u, *c))
            if c[0] == 'mkdir':
                os.mkdir(c[-1], 0o755)
            if c[0] == 'rm':
                shutil.rmtree(c[-1])

        def popen(argv, **kw):
            vistos.append((argv, kw['cwd']))
            return real(argv[17:], **kw)
        with mock.patch.dict(os.environ, {o.COMO: 'rgparse'}), mock.patch.object(o, '_sudo', sudo), \
                mock.patch.object(o.subprocess, 'Popen', popen):
            self.assertEqual(o.correr([sys.executable, '-c', 'print("hola")'], timeout=50), b'hola\n')
        [(argv, cwd)] = vistos
        self.assertEqual(argv[:17], ['sudo', '-n', '-u', 'rgparse', '--', 'env', '-i', 'PATH=/usr/bin:/bin', f'HOME={cwd}',
                                     'LANG=C.UTF-8', 'timeout', '-s', 'KILL', '50', 'prlimit', f'--as={o.MEMORIA}', '--'])
        self.assertEqual(hechos, [('rgparse', 'mkdir', '-m', '0755', '--', str(cwd)), ('rgparse', 'kill', '-s', 'KILL', '--', '-1'),
                                  ('rgparse', 'rm', '-rf', '--', str(cwd))])
        with mock.patch.dict(os.environ, {o.COMO: 'root; rm -rf /'}), self.assertRaises(ValueError):
            o.correr(['true'])

    def test_a_file_a_parser_leaves_is_read_only_as_a_regular_file_under_its_cap(self):
        with tempfile.TemporaryDirectory() as t, mock.patch.object(o.tempfile, 'gettempdir', return_value=t):
            (Path(t) / 'otra').mkdir(); (Path(t) / 'otra' / 'img.png').write_bytes(PNG)

            def destapa():  # a fifo opened without O_NONBLOCK waits for a writer: this one makes it a slow failure, not a hang
                time.sleep(4)
                for _ in range(60):
                    for f in Path(t).glob('rg-ocr-*/img.png'):
                        with contextlib.suppress(OSError):
                            os.close(os.open(f, os.O_WRONLY | os.O_NONBLOCK))
                    time.sleep(0.5)
            threading.Thread(target=destapa, daemon=True).start()
            casos = {'a link': ('import os; os.symlink(%r, "img.png")' % str(Path(t) / 'otra' / 'img.png'), OSError),
                     'a fifo': ('import os; os.mkfifo("img.png")', ValueError),
                     'its folder swapped for a link': ('import os; d = os.getcwd(); os.rename(d, d + "-x"); os.symlink(%r, d)'
                                                       % str(Path(t) / 'otra'), OSError),
                     'over the cap': ('open("img.png", "wb").write(b"x" * 2000)', o.SalidaGrande)}
            for nombre, (codigo, error) in casos.items():
                with self.subTest(nombre):
                    t0 = time.monotonic()
                    with self.assertRaises(error):
                        o.correr([sys.executable, '-c', codigo], tope=1000, archivo='img.png')
                    self.assertLess(time.monotonic() - t0, 3)
            self.assertEqual(o.correr([sys.executable, '-c', 'open("img.png", "wb").write(b"png")'], tope=1000, archivo='img.png'), b'png')
            self.assertEqual([p for p in Path(t).glob('rg-ocr-*') if not p.is_symlink() and not p.name.endswith('-x')], [])

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


HOSTIL = '''import json, os, sys
r = {'uid': os.getuid(), 'canario': os.environ.get('RG_CANARIO')}
def intenta(nombre, fn):
    try:
        fn(); r[nombre] = 'hecho'
    except OSError as e:
        r[nombre] = type(e).__name__
codigo, res = sys.argv[1], sys.argv[2]
intenta('checkout', lambda: os.close(os.open(codigo, os.O_WRONLY | os.O_APPEND)))
intenta('checkout: nuevo', lambda: os.close(os.open(os.path.join(os.path.dirname(codigo), 'nuevo.py'), os.O_WRONLY | os.O_CREAT | os.O_EXCL)))
intenta('resultados', lambda: os.close(os.open(os.path.join(res, 'medicion.json'), os.O_WRONLY | os.O_TRUNC)))
intenta('resultados: nuevo', lambda: os.close(os.open(os.path.join(res, 'nuevo.png'), os.O_WRONLY | os.O_CREAT | os.O_EXCL)))
intenta('leer resultados', lambda: open(os.path.join(res, 'medicion.json')).read())
intenta('su carpeta', lambda: open('img.png', 'w').write('x'))
print(json.dumps(r))
'''


def _sudo_ok():
    return sys.platform.startswith('linux') and subprocess.run(['sudo', '-n', 'true'], capture_output=True).returncode == 0


@unittest.skipUnless(EXIGIR or _sudo_ok(), 'needs Linux and passwordless sudo, as in CI; ocr-medir.yml runs it before '
                                           'fetching anything with RG_OCR_EXIGIR_AISLADO=1, so there it never skips')
class Aislado(unittest.TestCase):
    """The real attempt (GPT on c9491d8: the parsers ran as the runner's user and could write the checkout and the
    results): a parser taken over, run by correr as rgparse, tries to write both and fails."""
    USUARIO = 'rgparse'

    @classmethod
    def setUpClass(cls):
        if subprocess.run(['id', cls.USUARIO], capture_output=True).returncode != 0:
            subprocess.run(['sudo', '-n', 'useradd', '--system', '--no-create-home', '--shell', '/usr/sbin/nologin', cls.USUARIO],
                           check=True, capture_output=True)

    def setUp(self):
        p = mock.patch.dict(os.environ, {o.COMO: self.USUARIO, 'RG_CANARIO': 'no debe verse'})
        p.start(); self.addCleanup(p.stop)

    def test_a_parser_as_its_user_cannot_write_the_checkout_or_the_results(self):
        res = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, res)
        os.chmod(res, 0o755); (res / 'medicion.json').write_text('{"paginas": []}')  # as preparar leaves its results
        codigo = ROOT / 'scripts' / 'ocr_medir.py'
        antes = {f: f.read_bytes() for f in (codigo, res / 'medicion.json')}
        r = json.loads(o.correr([sys.executable, '-c', HOSTIL, str(codigo), str(res)], timeout=60))
        self.assertNotEqual(r.pop('uid'), os.getuid())
        self.assertEqual(r, {'canario': None, 'checkout': 'PermissionError', 'checkout: nuevo': 'PermissionError',
                             'resultados': 'PermissionError', 'resultados: nuevo': 'PermissionError',
                             'leer resultados': 'hecho', 'su carpeta': 'hecho'})
        self.assertEqual({f: f.read_bytes() for f in antes}, antes)
        self.assertEqual(sorted(res.iterdir()), [res / 'medicion.json'])

    def test_as_its_user_a_parser_keeps_its_memory_cap_and_leaves_no_process_behind(self):
        with self.assertRaises(subprocess.CalledProcessError):
            o.correr([sys.executable, '-c', 'import mmap; mmap.mmap(-1, 3 << 30, mmap.MAP_PRIVATE)'], timeout=60)
        deja = 'import os, time\nif os.fork() == 0:\n    os.setsid(); os.close(1); time.sleep(120); os._exit(0)\nprint("listo")\n'
        self.assertEqual(o.correr([sys.executable, '-c', deja], timeout=60), b'listo\n')
        ps = subprocess.run(['ps', '-u', self.USUARIO, '-o', 'stat='], capture_output=True, text=True).stdout.split()
        self.assertEqual([s for s in ps if not s.startswith('Z')], [])


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

    def test_preparar_parses_as_its_own_user_only_after_the_real_write_attempt(self):
        # GPT on c9491d8: the Aislado tests skip where sudo fails, so this job runs them first and forbids the skip
        pasos = self.jobs['preparar']['steps']
        donde = {k: next(i for i, s in enumerate(pasos) if k in s.get('run', ''))
                 for k in ('useradd', 'unittest tests.test_ocr_medir', 'git fetch', 'ocr_medir.py preparar')}
        self.assertEqual(sorted(donde, key=donde.get), list(donde))
        self.assertEqual(pasos[donde['useradd']]['run'], 'sudo useradd --system --no-create-home --shell /usr/sbin/nologin rgparse')
        self.assertEqual(pasos[donde['unittest tests.test_ocr_medir']]['env'], {'RG_OCR_EXIGIR_AISLADO': '1'})

    def test_preparar_closes_and_saves_inside_its_step_and_its_job(self):
        paso = next(s for s in self.jobs['preparar']['steps'] if 'ocr_medir.py preparar' in s.get('run', ''))
        self.assertLessEqual(o.PLAZO_PREPARAR + 5 * 60, paso['timeout-minutes'] * 60)  # a fetch under way and the save
        self.assertLess(paso['timeout-minutes'] + 10, self.jobs['preparar']['timeout-minutes'])  # setup and engines first

    def test_the_page_count_reaches_the_script_through_the_environment_and_is_checked(self):
        step = next(s for s in self.jobs['preparar']['steps'] if 'ocr_medir.py preparar' in s.get('run', ''))
        self.assertEqual(step['env'], {'PAGINAS': '${{ inputs.paginas }}', 'RG_EXTRACT_AS': 'rgparse'})
        self.assertIn('[[ "$PAGINAS" =~ ^[0-9]{1,2}$ ]]', step['run'])
        self.assertNotIn('${{', step['run'])


if __name__ == '__main__':
    unittest.main()
