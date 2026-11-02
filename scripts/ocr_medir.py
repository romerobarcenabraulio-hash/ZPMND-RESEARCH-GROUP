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
import subprocess
import sys
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


def muestra(filas):
    """(sha256, url, tipo) of every OJN entry stored as PDF or .doc, in sha256 order, each sha once."""
    vistos, out = set(), []
    for f in filas:
        a = f.get('artifact') or {}
        tipo, sha, url = TIPOS.get(a.get('media_type')), a.get('sha256'), a.get('url')
        if tipo and isinstance(sha, str) and len(sha) == 64 and isinstance(url, str) and sha not in vistos:
            vistos.add(sha); out.append((sha, url, tipo))
    return sorted(out)


def parecido(a, b):
    """Agreement between two texts, 0 to 1, on their words (case and spacing aside)."""
    a, b = ' '.join(a.lower().split()), ' '.join(b.lower().split())
    return round(difflib.SequenceMatcher(None, a, b, autojunk=False).ratio(), 4) if (a or b) else 1.0


def correr(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, timeout=300, **kw).stdout


def leer_respuesta(resp):
    """The text of one choice that stopped by itself, or None."""
    ch = resp.get('choices') if isinstance(resp, dict) else None
    if not isinstance(ch, list) or len(ch) != 1 or not isinstance(ch[0], dict) or ch[0].get('finish_reason') != 'stop':
        return None
    c = (ch[0].get('message') or {}).get('content')
    return c if isinstance(c, str) else None


def nvidia(jpeg, key):
    """(text or None, status) of nemotron-parse on one page image."""
    url = 'data:image/jpeg;base64,' + base64.b64encode(jpeg).decode('ascii')
    payload = {'model': MODELO, 'max_tokens': 8192,
               'messages': [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': url}}]}]}
    req = urllib.request.Request(API_URL, data=json.dumps(payload).encode('utf-8'), method='POST',
                                 headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            texto = leer_respuesta(json.loads(r.read().decode('utf-8')))
            return texto, 'ok' if texto is not None else 'sin texto'
    except urllib.error.HTTPError as e:  # its body is never read: it could echo part of the key
        e.close()
        return None, f'http {e.code}'
    except (urllib.error.URLError, OSError, ValueError) as e:
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


def preparar(catalogo, salida, paginas, docs):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the catalog's Fetcher, only in the job that fetches
    from rg.catalog.fetch import Fetcher, FetchRefused
    filas = [json.loads(x) for f in sorted(Path(catalogo).glob('*.jsonl')) for x in f.read_text(encoding='utf-8').splitlines() if x.strip()]
    fx = Fetcher(HOSTS, budget=400, max_bytes=50_000_000, timeout=60, retries=1)
    tess = correr(['tesseract', '--version']).decode('utf-8', 'replace').splitlines()[0]
    out, salida = {'tesseract': tess, 'modelo_nvidia': MODELO, 'paginas': [], 'documentos': [], 'saltados': {}}, Path(salida)
    salida.mkdir(parents=True, exist_ok=True)
    for sha, url, tipo in muestra(filas):
        if len(out['paginas']) >= paginas and len(out['documentos']) >= docs:
            break
        if (tipo == 'pdf' and len(out['paginas']) >= paginas) or (tipo == 'doc' and len(out['documentos']) >= docs):
            continue
        try:
            r = fx.get(url)
        except FetchRefused as e:
            out['saltados'][sha] = str(e)[:120]; continue
        if r.status != 200 or hashlib.sha256(r.body).hexdigest() != sha:  # only the catalog's own bytes
            out['saltados'][sha] = f'http {r.status}' if r.status != 200 else 'otro sha256'; continue
        f = salida / f'{sha}.{tipo}'; f.write_bytes(r.body)
        if tipo == 'doc':
            txt = lambda: correr(['soffice', '--headless', '--cat', str(f)])  # noqa: E731
            t, s, igual = dos_veces(txt)
            out['documentos'].append({'sha256': sha, 'caracteres': len(t), 'segundos': s, 'repetible': igual})
            (salida / f'{sha}.doc.txt').write_bytes(t); continue
        n = int(next(x.split()[1] for x in correr(['pdfinfo', str(f)]).decode('latin-1').splitlines() if x.startswith('Pages:')))
        for p in range(1, n + 1):
            if len(out['paginas']) >= paginas:
                break
            capa = correr(['pdftotext', '-f', str(p), '-l', str(p), '-layout', str(f), '-']).decode('utf-8', 'replace')
            if len(capa.strip()) >= MIN_CHARS:
                continue  # it has its text: no OCR needed
            png = salida / f'{sha}-p{p}'
            correr(['pdftoppm', '-f', str(p), '-l', str(p), '-r', '300', '-gray', '-png', '-singlefile', str(f), str(png)])
            t_tess, s_tess, rep_tess = dos_veces(lambda: correr(['tesseract', f'{png}.png', '-', '-l', 'spa']).decode('utf-8'))
            fila = {'sha256': sha, 'pagina': p, 'tesseract': {'caracteres': len(t_tess), 'segundos': s_tess,
                                                              'repetible': rep_tess}}
            (salida / f'{sha}-p{p}.tesseract.txt').write_text(t_tess, encoding='utf-8')
            jpeg = jpeg_bajo_limite(f, p, salida)
            if jpeg is None:
                fila['nvidia'] = {'estado': f'la imagen no cabe en {IMG_MAX} bytes'}
            else:
                (salida / f'{sha}-p{p}.jpg').write_bytes(jpeg)
            out['paginas'].append(fila)
    (salida / 'medicion.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    return out


def fase_nvidia(salida, key):
    """Adds NVIDIA's reading of every page `preparar` left as a JPEG; opens no PDF."""
    salida = Path(salida); out = json.loads((salida / 'medicion.json').read_text(encoding='utf-8'))
    for fila in out['paginas']:
        if 'nvidia' in fila:
            continue
        nombre = f"{fila['sha256']}-p{int(fila['pagina'])}"
        if len(fila['sha256']) != 64 or not all(c in '0123456789abcdef' for c in fila['sha256']):
            fila['nvidia'] = {'estado': 'nombre inesperado'}; continue
        jpeg = (salida / f'{nombre}.jpg').read_bytes()
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
    else:
        key = os.environ.get('NVIDIA_API_KEY', '')
        if not key:
            sys.exit('no NVIDIA_API_KEY')
        out = fase_nvidia(a.salida, key)
    print(json.dumps({'paginas': len(out['paginas']), 'documentos': len(out['documentos']), 'saltados': len(out['saltados'])}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
