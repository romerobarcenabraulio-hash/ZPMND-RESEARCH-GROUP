"""The registry's sounding (docs/NORTE.md §9, §19): each source of sources/registro/ says, in its own words, how much it
holds; RG writes down that number, where it came from and when, and nothing else. Braulio, 2026-10-30: the board's
"por medir" must be filled by the data, not by hand, down to each book and database, from more to less (RG maps the
whole world; ZPMND narrows it per client and country).

A registry file (sources/registro/<letter>.json) lists candidate sources of one family of NORTE §3. A source may carry
a `contador`, the one place where it declares its size:
  {"tipo": "json", "url": ..., "ruta": ["meta", "count"], "unidad": "obras"}   a number at that path of a JSON answer
  {"tipo": "contar", "url": ..., "literal": "<rfc-entry>", "unidad": "RFC"}    how many times that text occurs
Nothing else is interpreted: no regular expression, no HTML parsing, no XML parser (no entity expansion), no code per
source. Each source is fetched with the catalog's Fetcher (rg/catalog/fetch.py): https only, its own allowed hosts,
robots.txt, public addresses only, a size cap and a request budget of its own, so one source cannot reach another's
host or spend another's budget. A source without a `contador` is never guessed: its base_url is fetched once and only
the HTTP answer is kept (estado `existe` on a 200), so a book or database named wrongly shows on the first sounding.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from rg.catalog.fetch import Fetcher, FetchRefused

FAMILIAS = tuple('ABCDEFGHIJKLMNOP')
TIPOS = ('json', 'contar')
CLASES = ('libro', 'base_de_datos', 'api', 'catalogo', 'dataset', 'repositorio', 'portal_oficial', 'diario_oficial',
          'revista', 'video', 'foro', 'curso', 'documentacion', 'registro')
# The fastest route each source offers, best first (Braulio, 2026-10-30: "extraer información mucho más rápido"): a bulk
# dump gives millions of records in one download, an API pages through them, a sitemap lists every page, a crawl walks
# them one by one, and manual means a purchase or a person. Acquisition is planned in this order.
VIAS = ('volcado', 'api', 'sitemap', 'rastreo', 'manual')
CAP = {'json': 5_000_000, 'contar': 40_000_000, 'base': 5_000_000}  # bytes: an index or a page, never a corpus
ID = re.compile(r'[a-z]{2,3}\.[a-z0-9][a-z0-9.-]{1,60}')
SUB = re.compile(r'[A-PST]\d{2}')  # the board's sub-area (desglose): A01..P99
HOST = re.compile(r'[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+')
REQUIRED = ('source_id', 'subarea', 'clase', 'title', 'publisher', 'base_url', 'allowed_hosts', 'alcance', 'license', 'via')


def errores(doc, letra):
    """Every reason this registry file cannot be used, as text; empty when it can."""
    out = []
    if doc.get('familia') != letra or letra not in FAMILIAS:
        out.append(f'{letra}: familia must be {letra}')
    fuentes = doc.get('fuentes')
    if not isinstance(fuentes, list) or not fuentes:
        return out + [f'{letra}: fuentes must be a non-empty list']
    seen = set()
    for i, f in enumerate(fuentes):
        where = f"{letra}[{i}] {f.get('source_id', '?') if isinstance(f, dict) else '?'}"
        if not isinstance(f, dict):
            out.append(f'{where}: not an object'); continue
        for k in REQUIRED:
            if not f.get(k):
                out.append(f'{where}: {k} missing')
        sid = f.get('source_id', '')
        if not ID.fullmatch(str(sid)):
            out.append(f'{where}: source_id must look like xx.name')
        if sid in seen:
            out.append(f'{where}: source_id repeated')
        seen.add(sid)
        if f.get('subarea') and not (SUB.fullmatch(str(f['subarea'])) and str(f['subarea'])[0] == letra):
            out.append(f'{where}: subarea must be {letra}NN')
        if f.get('via') and f['via'] not in VIAS:
            out.append(f'{where}: via not one of {VIAS}')
        if f.get('clase') and f['clase'] not in CLASES:
            out.append(f'{where}: clase not one of {CLASES}')
        hosts = f.get('allowed_hosts') or []
        if not (isinstance(hosts, list) and all(isinstance(h, str) and HOST.fullmatch(h) for h in hosts)):
            out.append(f'{where}: allowed_hosts must be host names')
        base = urlsplit(str(f.get('base_url', '')))
        if f.get('base_url') and (base.scheme != 'https' or (base.hostname or '') not in hosts):
            out.append(f'{where}: base_url must be https and its host one of allowed_hosts')
        c = f.get('contador')
        if c is not None:
            out += [f'{where}: contador {e}' for e in _contador_errores(c, hosts)]
    return out


def _contador_errores(c, hosts):
    if not isinstance(c, dict) or c.get('tipo') not in TIPOS:
        return [f'tipo must be one of {TIPOS}']
    out = []
    parts = urlsplit(str(c.get('url', '')))
    if parts.scheme != 'https' or (parts.hostname or '') not in hosts:
        out.append('url must be https and its host one of allowed_hosts')
    if not c.get('unidad'):
        out.append('unidad missing')
    if c['tipo'] == 'json' and not (isinstance(c.get('ruta'), list) and c['ruta']
                                    and all(isinstance(k, (str, int)) and not isinstance(k, bool) for k in c['ruta'])):
        out.append('ruta must be a non-empty list of keys and indexes')
    if c['tipo'] == 'contar' and not (isinstance(c.get('literal'), str) and 3 <= len(c['literal']) <= 200):
        out.append('literal must be text of 3 to 200 characters')
    return out


def cargar(carpeta):
    """(letter, source) for every source of every registry file, in order; SystemExit(2) naming every problem."""
    out, probs = [], []
    for p in sorted(Path(carpeta).glob('*.json')):
        letra = p.stem
        try:
            doc = json.loads(p.read_text(encoding='utf-8'))
        except (OSError, ValueError) as e:
            probs.append(f'{p.name}: {type(e).__name__}'); continue
        e = errores(doc, letra) if isinstance(doc, dict) else [f'{p.name}: not an object']
        probs += e
        if not e:
            out += [(letra, f) for f in doc['fuentes']]
    ids = [f['source_id'] for _, f in out]
    probs += [f'{i}: source_id in more than one file' for i in sorted({i for i in ids if ids.count(i) > 1})]
    if probs:
        raise SystemExit('registro inválido:\n' + '\n'.join(probs))
    return out


def leer(body, c):
    """The count a body declares for its contador, or ValueError. json: the value at `ruta` must be a whole number
    (an int, or a string of digits with optional thousands separators); contar: occurrences of `literal`."""
    if c['tipo'] == 'contar':
        return body.count(c['literal'].encode('utf-8'))
    x = json.loads(body.decode('utf-8'))
    for k in c['ruta']:
        if isinstance(k, int) and isinstance(x, list) and -len(x) <= k < len(x):
            x = x[k]
        elif isinstance(k, str) and isinstance(x, dict) and k in x:
            x = x[k]
        else:
            raise ValueError(f'no {k!r} in the answer')
    if isinstance(x, bool):
        raise ValueError('not a count')
    if isinstance(x, int) and x >= 0:
        return x
    if isinstance(x, str) and re.fullmatch(r'\d{1,3}(?:[,.]\d{3})*|\d+', x.strip()):
        return int(re.sub(r'[,.]', '', x.strip()))
    raise ValueError('not a count')


def sondear(fuentes, nuevo_fetcher=None, ahora=None):
    """One result per source, in source_id order. A failure is that source's result (its kind, never a URL with a
    credential, since no credential is ever sent), never the run's."""
    nuevo_fetcher = nuevo_fetcher or (lambda hosts, cap: Fetcher(hosts, budget=6, max_bytes=cap, timeout=45, retries=1))
    ahora = ahora or (lambda: datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
    out = []
    for letra, f in sorted(fuentes, key=lambda x: x[1]['source_id']):
        r = {'source_id': f['source_id'], 'familia': letra, 'subarea': f['subarea'], 'title': f['title'], 'via': f['via']}
        c = f.get('contador')
        url = c['url'] if c else f['base_url']
        r.update(url=url, fecha=ahora(), **({'unidad': c['unidad']} if c else {}))
        try:
            resp = nuevo_fetcher(f['allowed_hosts'], CAP[c['tipo'] if c else 'base']).get(url)
        except FetchRefused as e:
            out.append({**r, 'estado': 'rechazado', 'error': str(e)[:200]}); continue
        except Exception as e:  # noqa: BLE001 - one source's failure is its own result
            out.append({**r, 'estado': 'error', 'error': type(e).__name__}); continue
        r.update(http=resp.status, bytes=len(resp.body), sha256=hashlib.sha256(resp.body).hexdigest())
        if resp.status != 200:
            out.append({**r, 'estado': 'http'}); continue
        if not c:
            out.append({**r, 'estado': 'existe'}); continue
        try:
            out.append({**r, 'estado': 'medido', 'valor': leer(resp.body, c)})
        except (ValueError, UnicodeDecodeError, RecursionError) as e:
            out.append({**r, 'estado': 'ilegible', 'error': f'{type(e).__name__}: {str(e)[:120]}'})
    return out


def resumen(resultados):
    """Per family: sources, measured, existing, failed; and how many offer each route (the speed of the map)."""
    por = {}
    for r in resultados:
        x = por.setdefault(r['familia'], {'fuentes': 0, 'medidas': 0, 'existen': 0, 'fallidas': 0})
        x['fuentes'] += 1
        x['medidas' if r['estado'] == 'medido' else 'existen' if r['estado'] == 'existe' else 'fallidas'] += 1
        vias = x.setdefault('vias', {})
        vias[r.get('via', '?')] = vias.get(r.get('via', '?'), 0) + 1
    return dict(sorted(por.items()))


def main(argv=None):
    a = argparse.ArgumentParser(description='measure what each registered source declares it holds')
    a.add_argument('--registro', default='sources/registro')
    a.add_argument('--out', required=True)
    a.add_argument('--solo', nargs='*', default=None, help='only these source_ids')
    x = a.parse_args(argv)
    fuentes = cargar(x.registro)
    if x.solo is not None:
        fuentes = [(l, f) for l, f in fuentes if f['source_id'] in set(x.solo)]
    res = sondear(fuentes)
    doc = {'generado': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'resumen': resumen(res), 'resultados': res}
    Path(x.out).write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps(doc['resumen'], ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
