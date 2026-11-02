"""OCR measurement on Orden Jurídico Nacional's own files, for a decision by numbers (ESTADO-RG-2026-11-02: OCR for OJN
.doc and scanned PDF; REGLAS 15). It publishes nothing to the catalog: every result goes to the run's artifact.

    python scripts/ocr_medir.py preparar --catalogo DIR --salida DIR [--paginas 10] [--docs 5]   (no key)
    python scripts/ocr_medir.py nvidia --salida DIR                                               (only the key)

- The sample is fixed by the catalog, not chosen by hand: OJN entries whose stored artifact is a PDF or a Word 97 .doc,
  in sha256 order. Each file is fetched again from its official URL with the catalog's Fetcher and kept only if its bytes
  have the catalog's sha256, so both engines read exactly the catalog's file.
- A PDF page is "scanned" when pdftotext finds fewer than MIN_CHARS characters in it; the first --paginas such pages go
  to both engines: Tesseract (language data hashed) on a 300 dpi PNG, and NVIDIA's nemotron-parse through its hosted
  API on a JPEG kept under the inline image limit. Each engine reads each page twice: identical output is the
  repeatability figure. A .doc goes to LibreOffice (no OCR), twice, the same way. Each engine's exact version is in the
  result (the apt package's, and the model as the API names it in each answer), or the phase fails.
- Two jobs (issue #90): `preparar` opens the PDFs and .doc files and runs Tesseract and LibreOffice with no key in its
  job, every parser as the OS user RG_EXTRACT_AS names (the workflow's rgparse), which cannot write the checkout or the
  results; `nvidia` runs in another job with the key, reads only the JPEGs `preparar` left (JPEG magic and size checked)
  and never opens a PDF. The key goes only to integrate.api.nvidia.com in the Authorization header; an error body is
  never read, and an answer that holds the key is refused before anything is written or derived from it.
- Each parser's output is read up to SALIDA_MAX bytes within its timeout; both phases save after every page and start
  nothing after their deadline (PLAZO_PREPARAR, PLAZO_FASE), so a job cut short keeps what it measured.
Output: <salida>/medicion.json (per page and per document: engine, version, characters, seconds, repeatable, agreement
between engines) plus every page image and text, named by sha256, for the hand check that gives the error rate.
"""
import argparse
import base64
import contextlib
import hashlib
import http.client
import json
import math
import os
import re
import resource
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter
from pathlib import Path

API_URL = 'https://integrate.api.nvidia.com/v1/chat/completions'  # fixed: the key never goes anywhere else
MODELO = 'nvidia/nemotron-parse'
HOSTS = ['www.ordenjuridico.gob.mx', 'ordenjuridico.gob.mx']
MIN_CHARS = 50  # fewer characters than this on a page means its text is in the image
IMG_MAX = 175_000  # bytes of the JPEG sent inline (the hosted API's inline limit, kept under)
TIPOS = {'application/pdf': 'pdf', 'application/msword': 'doc'}
MAX_RESPUESTA = 2_000_000  # bytes of one NVIDIA answer
MEMORIA = 2 * 1024 ** 3  # bytes each parser may take
SALIDA_MAX = 16 * 1024 ** 2  # bytes of one parser's output kept: a page's text or a .doc's is far less
MAX_PAGINAS = 40
PLAZO_LLAMADA = 30  # seconds for one whole NVIDIA answer: MAX_PAGINAS x 2 calls x 30 s = 40 min, inside PLAZO_FASE
PLAZO_FASE = 45 * 60  # no page starts after this; one more page (2 x 30 s) still ends inside the step's 50 minutes
PLAZO_PREPARAR = 30 * 60  # no file starts after this and no parser runs past it: the step has 40 minutes, the job 60
MAX_PAGINAS_PDF = 300  # pages of one PDF looked at (auditor on c9491d8: thousands of text pages, a pdftotext each)
PNG_MAX = 64 * 1024 ** 2  # bytes of one 300 dpi page image
TOPE_PARECIDO = 20_000  # characters of each text compared
PAQUETES = ('tesseract-ocr', 'tesseract-ocr-spa', 'poppler-utils', 'libreoffice-writer-nogui')  # what the workflow installs
COMO = 'RG_EXTRACT_AS'  # env: the OS user the parsers run as (rgparse, as in rg/text/run.py); unset: this process
USUARIO = re.compile(r'^[a-z_][a-z0-9_-]{0,31}$')
_CADENA = re.compile(r'"(?:[^"\\]|\\.)*"', re.S)  # one JSON string literal, escapes included


class SalidaGrande(ValueError):
    """A parser wrote more than its cap: its process group is killed and the file is its own result."""


def muestra(filas):
    """(sha256, url, tipo) of every OJN entry stored as PDF or .doc whose artifact says it may be redistributed (it is
    kept in the artifact and sent to NVIDIA: GPT on 212e8f8), in sha256 order, each sha once."""
    vistos, out = set(), []
    for f in filas:
        a = f.get('artifact') or {}
        tipo, sha, url = TIPOS.get(a.get('media_type')), a.get('sha256'), a.get('url')
        if a.get('redistribution') != 'allowed':
            continue
        if tipo and isinstance(sha, str) and len(sha) == 64 and isinstance(url, str) and sha not in vistos:
            vistos.add(sha); out.append((sha, url, tipo))
    return sorted(out)


def parecido(a, b):
    """Agreement between two texts, 0 to 1: the words both have, each counted as often as both have it (Dice on word
    multisets, case and spacing aside), on the first TOPE_PARECIDO characters of each. Linear in that cap whatever the
    text (GPT on c9491d8: SequenceMatcher with no cap was quadratic on repetitive text)."""
    a, b = (Counter(t[:TOPE_PARECIDO].lower().split()) for t in (a, b))
    n = sum(a.values()) + sum(b.values())
    return round(2 * sum((a & b).values()) / n, 4) if n else 1.0


def _limites():
    resource.setrlimit(resource.RLIMIT_AS, (MEMORIA, MEMORIA))


def _como():
    u = os.environ.get(COMO, '')
    if u and not USUARIO.match(u):
        raise ValueError(f'{COMO}: not a user name')
    return u


def _sudo(u, *cmd, check=False):
    subprocess.run(['sudo', '-n', '-u', u, '--', *cmd], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=60, check=check)


@contextlib.contextmanager
def _carpeta(u):
    """A fresh folder only the parsers' user can write (0755: this process reads it), held open by its handle."""
    d = Path(tempfile.gettempdir()) / f'rg-ocr-{uuid.uuid4().hex}'
    _sudo(u, 'mkdir', '-m', '0755', '--', str(d), check=True) if u else d.mkdir(0o755)
    dfd = os.open(d, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)  # this folder, even if the parser renames it
    try:
        yield d, dfd
    finally:
        os.close(dfd)
        _sudo(u, 'rm', '-rf', '--', str(d)) if u else shutil.rmtree(d, ignore_errors=True)


def _archivo(dfd, nombre, tope):
    """A file the parser left in its folder, read only as a regular file (no link, fifo or device) of `tope` bytes at most."""
    fd = os.open(nombre, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
    with os.fdopen(fd, 'rb') as fh:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError(f'{nombre}: not a regular file')
        b = fh.read(tope + 1)
    if len(b) > tope:
        raise SalidaGrande(f'{nombre}: more than {tope} bytes')
    return b


def correr(cmd, timeout=300, tope=SALIDA_MAX, archivo=None, fin=None):
    """A parser in a fresh folder of its own (its home and working folder), never past `fin`, the phase's deadline. When
    RG_EXTRACT_AS names a user it runs as that user with a clean environment, its own memory cap and its own deadline,
    so it cannot write the checkout, the results or its own inputs (GPT on c9491d8); every process of that user is killed
    when the call ends. With `archivo`, the answer is that file of its folder, else its output (_proceso)."""
    u, fin = _como(), min(time.monotonic() + timeout, fin or math.inf)
    if fin <= time.monotonic():
        raise subprocess.TimeoutExpired(cmd, 0)  # past the phase's deadline nothing starts
    with _carpeta(u) as (d, dfd):
        if u:
            cmd = ['sudo', '-n', '-u', u, '--', 'env', '-i', 'PATH=/usr/bin:/bin', f'HOME={d}', 'LANG=C.UTF-8', 'timeout',
                   '-s', 'KILL', str(math.ceil(fin - time.monotonic())), 'prlimit', f'--as={MEMORIA}', '--', *cmd]
        out = _proceso(cmd, d, fin, tope, u)
        return out if archivo is None else _archivo(dfd, archivo, tope)


def _proceso(cmd, d, fin, tope, u):
    """cmd in a session of its own, with a memory cap; its output is read up to `tope` bytes until `fin`, and past
    either, or when it ends, its whole process group and every process of user u are killed (GPT on 2b460e3:
    communicate() kept all of it)."""
    p = subprocess.Popen(cmd, cwd=d, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         start_new_session=True, preexec_fn=_limites)
    out = bytearray()
    try:
        with selectors.DefaultSelector() as sel:
            sel.register(p.stdout, selectors.EVENT_READ)
            while True:
                quedan = fin - time.monotonic()
                if quedan <= 0:
                    raise subprocess.TimeoutExpired(cmd, 0)
                if not sel.select(quedan):
                    continue
                chunk = os.read(p.stdout.fileno(), 64 * 1024)
                if not chunk:
                    break
                out += chunk
                if len(out) > tope:
                    raise SalidaGrande(f'{cmd[0]}: more than {tope} bytes')
        p.wait(max(fin - time.monotonic(), 0))
    finally:
        if u:
            _sudo(u, 'kill', '-s', 'KILL', '--', '-1')  # every process of the parsers' user: one detached from the group too
        try:
            os.killpg(p.pid, signal.SIGKILL)  # the whole group: at the deadline, past the cap, or a child left behind
        except (ProcessLookupError, PermissionError):
            pass
        with contextlib.suppress(OSError):  # sudo is root's to signal, not this process's
            p.kill()
        p.wait(); p.stdout.close()
    if p.returncode != 0:
        raise subprocess.CalledProcessError(p.returncode, cmd)
    return bytes(out)


def leer_respuesta(resp):
    """The text of one choice that stopped by itself, or None; each level checked for its type (GPT on c9491d8: a
    `message` that was a string ended the phase)."""
    ch = resp.get('choices') if isinstance(resp, dict) else None
    if not isinstance(ch, list) or len(ch) != 1 or not isinstance(ch[0], dict) or ch[0].get('finish_reason') != 'stop':
        return None
    m = ch[0].get('message')
    c = m.get('content') if isinstance(m, dict) else None
    return c if isinstance(c, str) else None


def _post(req, timeout):
    """The catalog's guards (rg/catalog/fetch.py): no redirect followed, public addresses only; at most MAX_RESPUESTA
    bytes; the whole answer within `timeout`, in a thread the caller stops waiting for."""
    if str(Path(__file__).resolve().parents[1]) not in sys.path:  # python -I: the checkout's rg, never the cwd
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from rg.catalog.fetch import _NoRedirect, _PublicHTTPS
    out = {}

    def trabajo():
        try:
            body = b''
            with urllib.request.build_opener(_NoRedirect, _PublicHTTPS).open(req, timeout=timeout) as r:
                while chunk := r.read1(64 * 1024):
                    body += chunk
                    if len(body) > MAX_RESPUESTA:
                        raise ValueError('answer too large')
            out['body'] = body
        except BaseException as e:  # noqa: BLE001 - handed to the caller as it is
            out['error'] = e
    hilo = threading.Thread(target=trabajo, daemon=True)
    hilo.start(); hilo.join(timeout)
    if hilo.is_alive():
        raise TimeoutError('no whole answer in time')
    if 'error' in out:
        raise out['error']
    return out['body']


def _eco(body, key):
    """True when the key is in the body's bytes or in any of its JSON string literals, each decoded on its own: the raw
    text, not the decoded tree, so no repeated property, nesting or escape hides it (the check reviewed in PR #89,
    rg/adquirir.py). A body that is not UTF-8 JSON counts as holding it."""
    if key.encode('utf-8') in body:
        return True
    try:
        texto = body.decode('utf-8')
        json.loads(texto)  # JSON only: outside JSON the escapes this scan decodes mean nothing
        return any(key in json.loads(c) for c in _CADENA.findall(texto) if '\\' in c)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return True


def nvidia(jpeg, key, post=None):
    """(text or None, status, model or None) of nemotron-parse on one page image; a reading names its model as the API
    does, or it is none. A redirect is an error, never followed (the key would go with it: auditor and GPT on 212e8f8);
    an answer that holds the key, or cannot be checked whole for it, is refused before anything is read from it (GPT on
    2b460e3: a 200 that echoed it went to .nvidia.md)."""
    url = 'data:image/jpeg;base64,' + base64.b64encode(jpeg).decode('ascii')
    payload = {'model': MODELO, 'max_tokens': 8192,
               'messages': [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': url}}]}]}
    req = urllib.request.Request(API_URL, data=json.dumps(payload).encode('utf-8'), method='POST',
                                 headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
    try:
        body = (post or _post)(req, PLAZO_LLAMADA)
        if _eco(body, key):
            return None, 'rechazada: trae la llave o no se puede revisar entera', None
        resp = json.loads(body.decode('utf-8'))
        texto, modelo = leer_respuesta(resp), resp.get('model') if isinstance(resp, dict) else None
        if texto is None:
            return None, 'sin texto', None
        if not isinstance(modelo, str) or not re.fullmatch(r'[\w./:@+-]{1,120}', modelo):
            return None, 'sin modelo', None  # the owner's pinned versions: a reading whose model is unnamed is none
        return texto, 'ok', modelo
    except urllib.error.HTTPError as e:  # a 3xx too; its body is never read: it could echo part of the key
        e.close()
        return None, f'http {e.code}', None
    except (urllib.error.URLError, OSError, ValueError, TimeoutError, http.client.HTTPException) as e:
        return None, type(e).__name__, None  # a body cut short (IncompleteRead) is this call's error, not the phase's


def jpeg_bajo_limite(pdf, pagina, fin=None):
    """The page as a grayscale JPEG under IMG_MAX bytes: 150 dpi first, then smaller until it fits."""
    for escala, calidad in ((1700, 80), (1400, 70), (1100, 60)):
        try:
            b = correr(['pdftoppm', '-f', str(pagina), '-l', str(pagina), '-gray', '-jpeg', '-jpegopt', f'quality={calidad}',
                        '-scale-to', str(escala), '-singlefile', str(pdf), 'img'], tope=IMG_MAX, archivo='img.jpg', fin=fin)
        except SalidaGrande:
            continue  # over the inline limit: smaller
        if not b.startswith(b'\xff\xd8\xff'):
            raise ValueError('pdftoppm left no JPEG')
        return b
    return None


def dos_veces(fn):
    """(text of the first run, seconds of the first run, whether the second run gave the same text)."""
    t0 = time.monotonic(); a = fn(); s = round(time.monotonic() - t0, 2)
    return a, s, fn() == a


def versiones():
    """{apt package: exact version} of each engine as dpkg has it installed (dpkg, not a parser, says it); None where
    it cannot say (the owner's order: pinned versions)."""
    v = {}
    for p in PAQUETES:
        try:
            r = subprocess.run(['dpkg-query', '-W', '-f', '${Version}', p], capture_output=True, text=True, timeout=60)
            v[p] = r.stdout if r.returncode == 0 and re.fullmatch(r'[0-9][0-9A-Za-z.+~:-]{0,99}', r.stdout) else None
        except (OSError, subprocess.SubprocessError):
            v[p] = None
    return v


def _guardar(salida, out):
    (salida / 'medicion.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


def _entrada(entrada, nombre, datos):
    """datos as a 0444 file in entrada (0755, this process's): the parsers' user reads it there and changes nothing."""
    f = entrada / nombre
    f.write_bytes(datos)
    os.chmod(f, 0o444)
    return f


def _paginas_de(f, sha, salida, entrada, out, paginas, fin=None):
    """Each scanned page of f measured, and saved as soon as it is (GPT on c9491d8: a long PDF lost its measured
    pages); at the phase's deadline the next parser call raises, so the file ends there."""
    n = int(next(x.split()[1] for x in correr(['pdfinfo', str(f)], fin=fin).decode('latin-1').splitlines() if x.startswith('Pages:')))
    for p in range(1, min(n, MAX_PAGINAS_PDF) + 1):
        if len(out['paginas']) >= paginas:
            return
        capa = correr(['pdftotext', '-f', str(p), '-l', str(p), '-layout', str(f), '-'], fin=fin).decode('utf-8', 'replace')
        if len(capa.strip()) >= MIN_CHARS:
            continue  # it has its text: no OCR needed
        png = correr(['pdftoppm', '-f', str(p), '-l', str(p), '-r', '300', '-gray', '-png', '-singlefile', str(f), 'img'],
                     tope=PNG_MAX, archivo='img.png', fin=fin)
        if not png.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('pdftoppm left no PNG')
        (salida / f'{sha}-p{p}.png').write_bytes(png)
        img = _entrada(entrada, f'{sha}-p{p}.png', png)
        t_tess, s_tess, rep_tess = dos_veces(lambda: correr(['tesseract', str(img), '-', '-l', 'spa'], fin=fin).decode('utf-8'))
        fila = {'sha256': sha, 'pagina': p, 'tesseract': {'caracteres': len(t_tess), 'segundos': s_tess, 'repetible': rep_tess}}
        (salida / f'{sha}-p{p}.tesseract.txt').write_text(t_tess, encoding='utf-8')
        jpeg = jpeg_bajo_limite(f, p, fin)
        if jpeg is None:
            fila['nvidia'] = {'estado': f'la imagen no cabe en {IMG_MAX} bytes'}
        else:
            (salida / f'{sha}-p{p}.jpg').write_bytes(jpeg)
        out['paginas'].append(fila)
        _guardar(salida, out)  # after every page: a run cut short inside a long PDF keeps the pages it measured


def preparar(catalogo, salida, paginas, docs, paquetes=None, plazo=PLAZO_PREPARAR):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the catalog's Fetcher, only in the job that fetches
    from rg.catalog.fetch import Fetcher, FetchRefused
    fin = time.monotonic() + plazo
    filas = [json.loads(x) for f in sorted(Path(catalogo).glob('*.jsonl')) for x in f.read_text(encoding='utf-8').splitlines() if x.strip()]
    fx = Fetcher(HOSTS, budget=400, max_bytes=50_000_000, timeout=60, retries=1)
    datos = sorted(Path('/usr/share/tesseract-ocr').rglob('spa.traineddata')) if Path('/usr/share/tesseract-ocr').is_dir() else []
    salida = Path(salida)
    out = {'modelo_nvidia': MODELO, 'versiones': {**(paquetes or {}),
           'spa.traineddata': hashlib.sha256(datos[0].read_bytes()).hexdigest() if datos else None},
           'paginas': [], 'documentos': [], 'saltados': {}}
    salida.mkdir(parents=True, exist_ok=True)
    os.chmod(salida, 0o755)  # the parsers' user may read the results and never write them
    entrada = Path(tempfile.mkdtemp(prefix='rg-ocr-'))  # the parsers' inputs, 0444 in a 0755 folder of this process: the
    os.chmod(entrada, 0o755)                            # job's own folders may be closed to that user
    for sha, url, tipo in muestra(filas):
        if time.monotonic() >= fin:
            out['cortada'] = 'plazo de la fase: no file starts after it'
            break
        if len(out['paginas']) >= paginas and len(out['documentos']) >= docs:
            break
        if (tipo == 'pdf' and len(out['paginas']) >= paginas) or (tipo == 'doc' and len(out['documentos']) >= docs):
            continue
        try:
            r = fx.get(url)
            if r.status != 200 or hashlib.sha256(r.body).hexdigest() != sha:  # only the catalog's own bytes
                out['saltados'][sha] = f'http {r.status}' if r.status != 200 else 'otro sha256'
            elif tipo == 'doc':
                (salida / f'{sha}.doc').write_bytes(r.body); f = _entrada(entrada, f'{sha}.doc', r.body)
                t, s, igual = dos_veces(lambda: correr(['soffice', '--headless', '--cat', str(f)], fin=fin).decode('utf-8', 'replace'))
                out['documentos'].append({'sha256': sha, 'caracteres': len(t), 'segundos': s, 'repetible': igual})
                (salida / f'{sha}.doc.txt').write_text(t, encoding='utf-8')
            else:
                (salida / f'{sha}.pdf').write_bytes(r.body)
                _paginas_de(_entrada(entrada, f'{sha}.pdf', r.body), sha, salida, entrada, out, paginas, fin)
        except FetchRefused as e:
            out['saltados'][sha] = str(e)[:120]
        except (subprocess.SubprocessError, OSError, ValueError, StopIteration) as e:  # one file is its own result (GPT, auditor on 212e8f8)
            out['saltados'][sha] = type(e).__name__
        _guardar(salida, out)  # after every file: a run cut short keeps what it measured
    _guardar(salida, out)
    shutil.rmtree(entrada, ignore_errors=True)
    return out


def _una_pagina(fila, salida, key):
    """NVIDIA's entry for one page `preparar` left, its JPEG checked again; read twice, and repeatable only when both
    readings are text (GPT on 2b460e3: two equal errors were 'repetible')."""
    sha, pag = fila.get('sha256'), fila.get('pagina')
    if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha) or isinstance(pag, bool) or not isinstance(pag, int):
        return {'estado': 'nombre inesperado'}
    nombre = f'{sha}-p{pag}'
    try:
        st = os.lstat(salida / f'{nombre}.jpg')
    except OSError:
        return {'estado': 'falta la imagen'}
    if not stat.S_ISREG(st.st_mode) or st.st_size > IMG_MAX:  # a symlink or a big file is not what preparar left
        return {'estado': 'imagen inesperada'}
    jpeg = (salida / f'{nombre}.jpg').read_bytes()
    if not jpeg.startswith(b'\xff\xd8\xff') or len(jpeg) > IMG_MAX:  # data from the other job, checked again
        return {'estado': 'imagen inesperada'}
    t0 = time.monotonic(); t1, estado, m1 = nvidia(jpeg, key); s = round(time.monotonic() - t0, 2)
    t2, estado_2, m2 = nvidia(jpeg, key)
    r = {'estado': estado, 'estado_2': estado_2, 'modelo': m1, 'modelo_2': m2, 'caracteres': len(t1 or ''), 'segundos': s,
         'repetible': t1 == t2 if t1 is not None and t2 is not None else None, 'tablas': (t1 or '').count('\n|')}
    if t1 is not None:
        (salida / f'{nombre}.nvidia.md').write_text(t1, encoding='utf-8')
        fila['parecido'] = parecido((salida / f'{nombre}.tesseract.txt').read_text(encoding='utf-8'), t1)
    return r


def fase_nvidia(salida, key, reloj=time.monotonic):
    """Adds NVIDIA's reading of every page `preparar` left as a JPEG; opens no PDF. Saved after every page, and no page
    starts after PLAZO_FASE: the rest stay 'pendiente' (GPT on 2b460e3: a job cut short lost every reading)."""
    salida = Path(salida); out = json.loads((salida / 'medicion.json').read_text(encoding='utf-8'))
    fin = reloj() + PLAZO_FASE
    for fila in out['paginas']:
        if 'nvidia' in fila:
            continue
        try:
            fila['nvidia'] = (_una_pagina(fila, salida, key) if reloj() < fin else
                              {'estado': 'pendiente', 'motivo': 'plazo de la fase'})
        except (OSError, ValueError) as e:  # a page whose files cannot be read is its own result, never the phase's
            fila['nvidia'] = {'estado': type(e).__name__}
        _guardar(salida, out)  # after every page: a job cut short keeps what was read
    _guardar(salida, out)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('fase', choices=('preparar', 'nvidia'))
    ap.add_argument('--catalogo', type=Path)
    ap.add_argument('--salida', required=True, type=Path)
    ap.add_argument('--paginas', type=int, default=10)
    ap.add_argument('--docs', type=int, default=5)
    a = ap.parse_args(argv)
    if a.fase == 'preparar':
        if os.environ.get('NVIDIA_API_KEY'):
            sys.exit('preparar opens hostile files: it never runs where the NVIDIA key is')
        if not _como():
            sys.exit(f'preparar runs its parsers only as another OS user: set {COMO} (GPT on c9491d8)')
        v = versiones()
        if not all(v.values()):  # the owner's order: pinned versions, so a measurement never starts without them
            sys.exit(f'no exact apt version of {", ".join(k for k, x in v.items() if not x)}')
        out = preparar(a.catalogo, a.salida, min(a.paginas, MAX_PAGINAS), min(a.docs, 10), paquetes=v)
        if not out['paginas'] and not out['documentos']:
            sys.exit('nothing was measured: every file was skipped or none was selected')  # never a green run with no data
    else:
        key = os.environ.get('NVIDIA_API_KEY', '')
        if not key:
            sys.exit('no NVIDIA_API_KEY')
        out = fase_nvidia(a.salida, key)
        if not any((p.get('nvidia') or {}).get('estado') == 'ok' for p in out['paginas']):
            sys.exit('NVIDIA gave no reading: red, with what it answered saved')  # GPT on 2b460e3: all 401 was green
    print(json.dumps({'paginas': len(out['paginas']), 'documentos': len(out['documentos']), 'saltados': len(out['saltados'])}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
