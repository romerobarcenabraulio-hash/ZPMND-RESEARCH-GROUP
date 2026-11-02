"""OCR measurement on Orden Jurídico Nacional's own files, for a decision by numbers (ESTADO-RG-2026-11-02: OCR for OJN
.doc and scanned PDF; REGLAS 15). It publishes nothing to the catalog: every result goes to the run's artifact.

    python scripts/ocr_medir.py preparar --catalogo DIR --salida DIR [--paginas 10] [--docs 5]   (no key)
    python scripts/ocr_medir.py nvidia --salida DIR                                               (only the key)

- The sample is fixed by the catalog, not chosen by hand: OJN entries whose stored artifact is a PDF or a Word 97 .doc,
  in sha256 order. Each file is fetched again from its official URL with the catalog's Fetcher and kept only if its bytes
  have the catalog's sha256, so both engines read exactly the catalog's file.
- A PDF page is "scanned" when pdftotext finds fewer than MIN_CHARS characters in it; the first --paginas such pages go
  to both engines: Tesseract (version and language data recorded) on a 300 dpi PNG, and NVIDIA's nemotron-parse through
  its hosted API on a JPEG kept under the inline image limit. Each engine reads each page twice: identical output is the
  repeatability figure. A .doc goes to LibreOffice (no OCR), twice, the same way.
- Two jobs (issue #90): `preparar` opens the PDFs and .doc files and runs Tesseract and LibreOffice with no key in its
  job; `nvidia` runs in another job with the key, reads only the JPEGs `preparar` left (JPEG magic and size checked) and
  never opens a PDF. The key goes only to integrate.api.nvidia.com in the Authorization header; an error body is never
  read.
Output: <salida>/medicion.json (per page and per document: engine, version, characters, seconds, repeatable, agreement
between engines) plus every page image and text, named by sha256, for the hand check that gives the error rate.
"""
import argparse
import base64
import difflib
import hashlib
import json
import os
import re
import resource
import signal
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

API_URL = 'https://integrate.api.nvidia.com/v1/chat/completions'  # fixed: the key never goes anywhere else
MODELO = 'nvidia/nemotron-parse'
HOSTS = ['www.ordenjuridico.gob.mx', 'ordenjuridico.gob.mx']
MIN_CHARS = 50  # fewer characters than this on a page means its text is in the image
IMG_MAX = 175_000  # bytes of the JPEG sent inline (the hosted API's inline limit, kept under)
TIPOS = {'application/pdf': 'pdf', 'application/msword': 'doc'}
MAX_RESPUESTA = 2_000_000  # bytes of one NVIDIA answer
MEMORIA = 2 * 1024 ** 3  # bytes each parser may take


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
    """Agreement between two texts, 0 to 1, on their words (case and spacing aside)."""
    a, b = ' '.join(a.lower().split()), ' '.join(b.lower().split())
    return round(difflib.SequenceMatcher(None, a, b, autojunk=False).ratio(), 4) if (a or b) else 1.0


def _limites():
    resource.setrlimit(resource.RLIMIT_AS, (MEMORIA, MEMORIA))


def correr(cmd, timeout=300):
    """A parser in a session of its own, with a memory cap; at the timeout its whole process group is killed."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True,
                         preexec_fn=_limites)
    try:
        out, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL); p.communicate()
        raise
    if p.returncode != 0:
        raise subprocess.CalledProcessError(p.returncode, cmd)
    return out


def leer_respuesta(resp):
    """The text of one choice that stopped by itself, or None."""
    ch = resp.get('choices') if isinstance(resp, dict) else None
    if not isinstance(ch, list) or len(ch) != 1 or not isinstance(ch[0], dict) or ch[0].get('finish_reason') != 'stop':
        return None
    c = (ch[0].get('message') or {}).get('content')
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


def nvidia(jpeg, key, post=_post):
    """(text or None, status) of nemotron-parse on one page image. A redirect is an error, never followed (the key
    would go with it: auditor and GPT on 212e8f8)."""
    url = 'data:image/jpeg;base64,' + base64.b64encode(jpeg).decode('ascii')
    payload = {'model': MODELO, 'max_tokens': 8192,
               'messages': [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': url}}]}]}
    req = urllib.request.Request(API_URL, data=json.dumps(payload).encode('utf-8'), method='POST',
                                 headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
    try:
        texto = leer_respuesta(json.loads(post(req, 180).decode('utf-8')))
        return texto, 'ok' if texto is not None else 'sin texto'
    except urllib.error.HTTPError as e:  # a 3xx too; its body is never read: it could echo part of the key
        e.close()
        return None, f'http {e.code}'
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
        return None, type(e).__name__


def jpeg_bajo_limite(pdf, pagina, d):
    """The page as a grayscale JPEG under IMG_MAX bytes: 150 dpi first, then smaller until it fits."""
    for escala, calidad in ((1700, 80), (1400, 70), (1100, 60)):
        base = d / f'p{pagina}-{escala}'
        correr(['pdftoppm', '-f', str(pagina), '-l', str(pagina), '-gray', '-jpeg', '-jpegopt', f'quality={calidad}',
                '-scale-to', str(escala), '-singlefile', str(pdf), str(base)])
        b = Path(str(base) + '.jpg').read_bytes()
        if len(b) <= IMG_MAX:
            return b
    return None


def dos_veces(fn):
    """(text of the first run, seconds of the first run, whether the second run gave the same text)."""
    t0 = time.monotonic(); a = fn(); s = round(time.monotonic() - t0, 2)
    return a, s, fn() == a


def _version(cmd):
    try:
        return correr(cmd, timeout=60).decode('utf-8', 'replace').strip().splitlines()[0][:120]
    except (subprocess.SubprocessError, OSError, IndexError):
        return None


def _guardar(salida, out):
    (salida / 'medicion.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


def _paginas_de(f, sha, salida, out, paginas):
    n = int(next(x.split()[1] for x in correr(['pdfinfo', str(f)]).decode('latin-1').splitlines() if x.startswith('Pages:')))
    for p in range(1, n + 1):
        if len(out['paginas']) >= paginas:
            return
        capa = correr(['pdftotext', '-f', str(p), '-l', str(p), '-layout', str(f), '-']).decode('utf-8', 'replace')
        if len(capa.strip()) >= MIN_CHARS:
            continue  # it has its text: no OCR needed
        png = salida / f'{sha}-p{p}'
        correr(['pdftoppm', '-f', str(p), '-l', str(p), '-r', '300', '-gray', '-png', '-singlefile', str(f), str(png)])
        t_tess, s_tess, rep_tess = dos_veces(lambda: correr(['tesseract', f'{png}.png', '-', '-l', 'spa']).decode('utf-8'))
        fila = {'sha256': sha, 'pagina': p, 'tesseract': {'caracteres': len(t_tess), 'segundos': s_tess, 'repetible': rep_tess}}
        (salida / f'{sha}-p{p}.tesseract.txt').write_text(t_tess, encoding='utf-8')
        jpeg = jpeg_bajo_limite(f, p, salida)
        if jpeg is None:
            fila['nvidia'] = {'estado': f'la imagen no cabe en {IMG_MAX} bytes'}
        else:
            (salida / f'{sha}-p{p}.jpg').write_bytes(jpeg)
        out['paginas'].append(fila)


def preparar(catalogo, salida, paginas, docs):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the catalog's Fetcher, only in the job that fetches
    from rg.catalog.fetch import Fetcher, FetchRefused
    filas = [json.loads(x) for f in sorted(Path(catalogo).glob('*.jsonl')) for x in f.read_text(encoding='utf-8').splitlines() if x.strip()]
    fx = Fetcher(HOSTS, budget=400, max_bytes=50_000_000, timeout=60, retries=1)
    datos = sorted(Path('/usr/share/tesseract-ocr').rglob('spa.traineddata')) if Path('/usr/share/tesseract-ocr').is_dir() else []
    salida = Path(salida)
    out = {'modelo_nvidia': MODELO, 'versiones': {'tesseract': _version(['tesseract', '--version']),
           'poppler': _version(['pdftotext', '-v']) or _version(['pdfinfo', '-v']), 'libreoffice': _version(['soffice', '--version']),
           'spa.traineddata': hashlib.sha256(datos[0].read_bytes()).hexdigest() if datos else None},
           'paginas': [], 'documentos': [], 'saltados': {}}
    salida.mkdir(parents=True, exist_ok=True)
    for sha, url, tipo in muestra(filas):
        if len(out['paginas']) >= paginas and len(out['documentos']) >= docs:
            break
        if (tipo == 'pdf' and len(out['paginas']) >= paginas) or (tipo == 'doc' and len(out['documentos']) >= docs):
            continue
        try:
            r = fx.get(url)
            if r.status != 200 or hashlib.sha256(r.body).hexdigest() != sha:  # only the catalog's own bytes
                out['saltados'][sha] = f'http {r.status}' if r.status != 200 else 'otro sha256'
            elif tipo == 'doc':
                f = salida / f'{sha}.doc'; f.write_bytes(r.body)
                t, s, igual = dos_veces(lambda: correr(['soffice', '--headless', '--cat', str(f)]).decode('utf-8', 'replace'))
                out['documentos'].append({'sha256': sha, 'caracteres': len(t), 'segundos': s, 'repetible': igual})
                (salida / f'{sha}.doc.txt').write_text(t, encoding='utf-8')
            else:
                f = salida / f'{sha}.pdf'; f.write_bytes(r.body)
                _paginas_de(f, sha, salida, out, paginas)
        except FetchRefused as e:
            out['saltados'][sha] = str(e)[:120]
        except (subprocess.SubprocessError, OSError, ValueError, StopIteration) as e:  # one file is its own result (GPT, auditor on 212e8f8)
            out['saltados'][sha] = type(e).__name__
        _guardar(salida, out)  # after every file: a run cut short keeps what it measured
    _guardar(salida, out)
    return out


def fase_nvidia(salida, key):
    """Adds NVIDIA's reading of every page `preparar` left as a JPEG; opens no PDF."""
    salida = Path(salida); out = json.loads((salida / 'medicion.json').read_text(encoding='utf-8'))
    for fila in out['paginas']:
        if 'nvidia' in fila:
            continue
        sha, pag = fila.get('sha256'), fila.get('pagina')
        if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha) or isinstance(pag, bool) or not isinstance(pag, int):
            fila['nvidia'] = {'estado': 'nombre inesperado'}; continue
        img = salida / f'{sha}-p{pag}.jpg'
        try:
            st = os.lstat(img)
        except OSError:
            fila['nvidia'] = {'estado': 'falta la imagen'}; continue
        if not stat.S_ISREG(st.st_mode) or st.st_size > IMG_MAX:  # a symlink or a big file is not what preparar left
            fila['nvidia'] = {'estado': 'imagen inesperada'}; continue
        nombre, jpeg = f'{sha}-p{pag}', img.read_bytes()
        if not jpeg.startswith(b'\xff\xd8\xff') or len(jpeg) > IMG_MAX:  # data from the other job, checked again
            fila['nvidia'] = {'estado': 'imagen inesperada'}; continue
        (t_nv, estado), s_nv, rep_nv = dos_veces(lambda: nvidia(jpeg, key))
        fila['nvidia'] = {'estado': estado, 'caracteres': len(t_nv or ''), 'segundos': s_nv, 'repetible': rep_nv,
                          'tablas': (t_nv or '').count('\n|')}
        if t_nv is not None:
            (salida / f'{nombre}.nvidia.md').write_text(t_nv, encoding='utf-8')
            fila['parecido'] = parecido((salida / f'{nombre}.tesseract.txt').read_text(encoding='utf-8'), t_nv)
    (salida / 'medicion.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
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
        out = preparar(a.catalogo, a.salida, min(a.paginas, 40), min(a.docs, 10))
        if not out['paginas'] and not out['documentos']:
            sys.exit('nothing was measured: every file was skipped or none was selected')  # never a green run with no data
    else:
        key = os.environ.get('NVIDIA_API_KEY', '')
        if not key:
            sys.exit('no NVIDIA_API_KEY')
        out = fase_nvidia(a.salida, key)
    print(json.dumps({'paginas': len(out['paginas']), 'documentos': len(out['documentos']), 'saltados': len(out['saltados'])}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
