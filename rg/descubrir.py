"""Discovery of the world map (docs/DESCUBRIR.md, docs/NORTE.md §19): for each cell of sources/cobertura.json (a UN
member state × a layer of law, standards or public data) one web search asks which official sites exist, and RG keeps
only what the search returned: each result's URL, title and snippet, never an answer written by a model. Braulio,
2026-10-31: Perplexity finds, RG verifies; a result is a candidate for the registry, never evidence and never coverage.

Two commands, two steps of .github/workflows/descubrir.yml:
  buscar     the only step with the key. Perplexity's Search API (POST /search, $5 per 1000 requests at search_type web,
             $1 at fast) is asked one query per request, built only from the country's name and the layer's fixed
             wording, so no question of ZPMND ever leaves RG. A country starts only when every layer it lacks fits in
             the run's searches and deadline; a layer that answered is kept and never asked (or paid) again.
             The key goes only to api.perplexity.ai: no redirect is followed, the address must be public, the answer
             is capped, refused when it echoes the key and read as JSON with a fixed shape. A 401, 402 or 403 (key
             refused, no credit) or a 429 stops the run and writes what that country gathered; an error never shows
             the answer's body (it could echo the key).
  verificar  no key. Each candidate (the first `por_capa` of each layer) is asked once with the catalog's Fetcher:
             https, its own host and its www twin only, robots.txt, public addresses, a size cap. Only the HTTP status,
             the size and the sha256 are kept (accesible on a 200): a page that answers says nothing of what it holds.

A result is kept only when its URL is https on a host name (no address, port, user or password), its text visible
(rg.catalog.categorize.clean_text) and cut to a fixed length; everything else is counted in `descartados`.
"""
import argparse
import hashlib
import http.client
import ipaddress
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from rg.catalog.categorize import clean_text
from rg.catalog.fetch import Fetcher, FetchRefused, _NoRedirect, _PublicHTTPS
from rg.sondeo import HOST

API = 'https://api.perplexity.ai/search'
TIPOS = ('web', 'fast')
POR_CELDA = 5  # results asked per search
MAX_RESPUESTA = 1_000_000  # bytes of one search answer
MAX_BUSQUEDAS = 2400  # one run: every cell of the per-country axes (2316) fits; $12 at most at search_type web
PAUSA = 1.0  # seconds between two searches
PLAZO_BUSCAR = 100 * 60  # the step allows 110 minutes
PLAZO_VERIFICAR = 80 * 60  # the step allows 90
ALTO = (401, 402, 403, 429)  # the key or the account says no: asking again only spends
ISO2, ISO3 = re.compile(r'[A-Z]{2}'), re.compile(r'[A-Z]{3}')
CAPA_ID = re.compile(r'[a-z_]{2,20}')
LARGO = {'title': 200, 'snippet': 300, 'date': 40}


class Alto(Exception):
    """The run stops: the key was refused, the account has no credit or the rate limit was reached. It carries the
    country's layers gathered so far (`doc`), so what was paid is written (GPT on 698a5b7, REGLAS 5)."""
    def __init__(self, motivo, doc):
        super().__init__(motivo)
        self.doc = doc


def cargar_cobertura(path):
    """The map, checked: countries with unique codes and a name, axes with layers whose query names {pais} once."""
    doc = json.loads(Path(path).read_text(encoding='utf-8'))
    errores = []
    paises = doc.get('paises') or []
    for p in paises:
        if not (ISO2.fullmatch(str(p.get('iso2'))) and ISO3.fullmatch(str(p.get('iso3'))) and p.get('nombre')):
            errores.append(f'pais {p}: iso2, iso3 and nombre')
    for k in ('iso2', 'iso3'):
        if len({p.get(k) for p in paises}) != len(paises):
            errores.append(f'{k} repeated')
    ejes = doc.get('ejes') or []
    for e in ejes:
        for c in e.get('capas') or []:
            q = str(c.get('consulta', ''))
            ok = CAPA_ID.fullmatch(str(c.get('id'))) and c.get('nombre') and q.count('{pais}') == 1 and len(q) <= 120
            if not ok:
                errores.append(f"capa {e.get('id')}/{c.get('id')}: id, nombre and a consulta naming {{pais}} once")
    if not paises or not ejes or not all(e.get('capas') for e in ejes):
        errores.append('paises and ejes with capas are required')
    if errores:
        raise SystemExit('cobertura: ' + '; '.join(errores[:10]))
    return doc


def capas(cob):
    """(eje, capa) in the map's order: the cells of one country."""
    return [(e, c) for e in cob['ejes'] for c in e['capas']]


def consulta(capa, pais):
    return capa['consulta'].replace('{pais}', pais['nombre'])  # replace, not format: no field of the map is code


ESPERA = 10  # seconds one wait on the socket may last; the whole answer has `timeout`


def _abrir(req, timeout, reloj=time.monotonic):
    """No redirect, public addresses only, at most MAX_RESPUESTA bytes and `timeout` seconds in all. A socket timeout
    bounds one wait, not an answer that trickles in, and read(n) waits for n bytes; read1 returns what has arrived, so
    each turn of the loop lasts at most ESPERA and checks the whole deadline (GPT on cb11715 and 9829c21)."""
    fin = reloj() + timeout
    body = b''
    with urllib.request.build_opener(_NoRedirect, _PublicHTTPS).open(req, timeout=min(timeout, ESPERA)) as r:
        while chunk := r.read1(64 * 1024):
            body += chunk
            if len(body) > MAX_RESPUESTA:
                raise ValueError(f'answer larger than {MAX_RESPUESTA} bytes')
            if reloj() > fin:
                raise TimeoutError(f'answer still arriving after {timeout} s')
    return body


def buscar(query, iso2, key, tipo, abrir=_abrir):
    payload = {'query': query, 'max_results': POR_CELDA, 'search_type': tipo, 'country': iso2,
               'max_tokens_per_page': 64}  # the snippet is enough: no page text is kept
    req = urllib.request.Request(API, data=json.dumps(payload).encode('utf-8'), method='POST',
                                 headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
    return json.loads(abrir(req, 60).decode('utf-8'))


def _contiene(x, key, hondo=0):
    """True when any text holds the key; too deep a nesting counts as holding it."""
    if hondo > 50:
        return True
    if isinstance(x, str):
        return key in x
    if isinstance(x, dict):  # what is kept has fixed keys: only the values come from the answer
        return any(_contiene(v, key, hondo + 1) for v in x.values())
    if isinstance(x, list):
        return any(_contiene(v, key, hondo + 1) for v in x)
    return False


def _url(u):
    """The URL and its host when it is https on a host name; None for anything else."""
    if not isinstance(u, str) or len(u) > 500:
        return None
    try:
        p = urlsplit(u.strip())
        port = p.port
    except ValueError:
        return None
    host = (p.hostname or '').lower()
    if p.scheme != 'https' or p.username or p.password or port not in (None, 443) or not HOST.fullmatch(host):
        return None
    try:
        ipaddress.ip_address(host)
        return None  # an address is not a site
    except ValueError:
        return u.strip(), host


def _texto(x, n):
    return clean_text(x)[0].strip()[:n] if isinstance(x, str) else ''


def resultados(resp):
    """The kept results and how many were dropped; ValueError when the answer is not a list of results."""
    items = resp.get('results') if isinstance(resp, dict) else None
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise ValueError('answer without a list of results')
    out, fuera = [], 0
    for i in items[:POR_CELDA]:
        u = _url(i.get('url'))
        if not u:
            fuera += 1; continue
        out.append({'rank': len(out) + 1, 'url': u[0], 'host': u[1],
                    **{k: _texto(i.get(k), n) for k, n in LARGO.items()}})
    return out, fuera + max(0, len(items) - POR_CELDA)


def _clave(e, c, pais):
    return e['id'], c['id'], consulta(c, pais)


def hechas(previo, pais, cob):
    """The layers of a country's earlier file that already answered the same query: kept, never asked or paid again."""
    vigentes = {_clave(e, c, pais) for e, c in capas(cob)}
    return {k: x for x in (previo or {}).get('capas', []) if isinstance(x, dict) and x.get('estado') == 'ok'
            and (k := (x.get('eje'), x.get('capa'), x.get('consulta'))) in vigentes}


def _doc(pais, tipo, ahora, capas_out, total):
    return {'pais': pais, 'generado': ahora(), 'proveedor': 'perplexity search', 'tipo_busqueda': tipo, 'capas': capas_out,
            'completo': len(capas_out) == total and all(x['estado'] == 'ok' for x in capas_out)}


def un_pais(pais, cob, key, tipo, ahora, buscar=buscar, sleep=time.sleep, previo=None):
    """Every layer of one country, asking only the ones `previo` lacks; raises Alto with the layers gathered so far
    (asked now or kept from before) when the key or the account says no."""
    ya, claves, capas_out = hechas(previo, pais, cob), [_clave(e, c, pais) for e, c in capas(cob)], []
    for i, (e, c) in enumerate(capas(cob)):
        k = claves[i]
        if k in ya:
            capas_out.append(ya[k]); continue
        x = {'eje': e['id'], 'capa': c['id'], 'nombre': c['nombre'], 'consulta': k[2]}
        try:
            res, fuera = resultados(buscar(k[2], pais['iso2'], key, tipo))
            if key and _contiene(res, key):  # on what is kept, decoded and cleaned (GPT on 698a5b7, 2ebcc5b, 41182c5)
                raise ValueError('the answer echoes the key')
            x.update(estado='ok', resultados=res, descartados=fuera)
        except urllib.error.HTTPError as err:  # its body is never read: it can echo part of the key
            err.close()
            if err.code in ALTO:
                resto = [ya[r] for r in claves[i + 1:] if r in ya]  # nothing paid before is dropped by a stop
                raise Alto(f'http {err.code}', _doc(pais, tipo, ahora, capas_out + resto, len(claves))) from None
            x.update(estado='error', error=f'http {err.code}')
        except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException, RecursionError) as err:
            # JSONDecodeError, UnicodeDecodeError and a body cut short (IncompleteRead: GPT on 2ebcc5b) are that layer's
            # error: the country goes on and what it paid is written; only the kind, a message can carry a URL or a key
            x.update(estado='error', error=type(err).__name__)
        capas_out.append(x)
        sleep(PAUSA)
    return _doc(pais, tipo, ahora, capas_out, len(claves))


def _escribir(path, doc, key=''):
    """Whole or not at all; with `key`, a text that holds it is never written (the last boundary before the data branch,
    whatever path the key took to get here: GPT on 41182c5)."""
    text = json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + '\n'
    if key and key in text:
        raise ValueError(f'{path.name} would hold the key: not written')
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    os.replace(tmp, path)


def _leer(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def pendientes(cob, carpeta):
    """Countries lacking an answered layer of the current map, in its order: a failed layer, a layer added to the map or
    a changed query is asked again (GPT on 41182c5), whatever an older file says of itself."""
    por_pais = len(capas(cob))
    return [p for p in cob['paises'] if len(hechas(_leer(carpeta / f"{p['iso3']}.json"), p, cob)) < por_pais]


def correr_busqueda(cob, carpeta, key, max_busquedas, tipo, ahora=None, buscar=buscar, sleep=time.sleep,
                    reloj=time.monotonic, plazo=PLAZO_BUSCAR):
    """Searches country by country (only the layers each one lacks) until the next one would pass max_busquedas or the
    deadline; a country is written when its layers are asked, or at a stop with what it gathered. Returns what it did."""
    ahora = ahora or (lambda: datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
    carpeta.mkdir(parents=True, exist_ok=True)
    por_pais, fin, hechos, usadas = len(capas(cob)), reloj() + plazo, [], [0]

    def contada(*args):  # every request is counted, kept or not: the count is what was paid
        usadas[0] += 1
        return buscar(*args)
    for p in pendientes(cob, carpeta):
        path = carpeta / f"{p['iso3']}.json"
        previo = _leer(path)
        falta = por_pais - len(hechas(previo, p, cob))
        if usadas[0] + falta > max_busquedas or reloj() + falta * (PAUSA + 60) > fin:
            break  # a country starts only when every layer it lacks fits
        try:
            doc = un_pais(p, cob, key, tipo, ahora, contada, sleep, previo)
        except Alto as e:
            _escribir(path, e.doc, key)
            return {'busquedas': usadas[0], 'paises': hechos, 'alto': str(e)}
        _escribir(path, doc, key)
        hechos.append(p['iso3'])
    return {'busquedas': usadas[0], 'paises': hechos, 'pendientes': len(pendientes(cob, carpeta))}


def verificar(carpeta, por_capa, nuevo_fetcher=None, ahora=None, reloj=time.monotonic, plazo=PLAZO_VERIFICAR):
    """Asks each unverified candidate once; saves every country as soon as its candidates are asked."""
    ahora = ahora or (lambda: datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
    fin, ritmo, n = reloj() + plazo, {}, 0
    nuevo_fetcher = nuevo_fetcher or (lambda hosts: Fetcher(hosts, budget=6, max_bytes=5_000_000, timeout=45, retries=1,
                                                            clock=reloj, deadline=fin, compartido=ritmo))
    for path in sorted(carpeta.glob('[A-Z][A-Z][A-Z].json')):
        doc, cambio = _leer(path), False
        for capa in (doc or {}).get('capas', []):
            for r in capa.get('resultados', [])[:por_capa]:
                if 'verificacion' in r or reloj() >= fin:
                    continue
                r['verificacion'] = _ver(r, nuevo_fetcher, ahora)
                cambio, n = True, n + 1
        if cambio:
            _escribir(path, doc)
    return n


def _ver(r, nuevo_fetcher, ahora):
    u = _url(r.get('url'))  # the file is data: checked again before any request
    if not u:
        return {'estado': 'rechazado', 'error': 'not an https URL on a host name', 'fecha': ahora()}
    host = u[1]
    gemelo = host[4:] if host.startswith('www.') else 'www.' + host
    try:
        resp = nuevo_fetcher([host, gemelo]).get(u[0])
    except FetchRefused as e:
        return {'estado': 'rechazado', 'error': str(e)[:200], 'fecha': ahora()}
    except Exception as e:  # noqa: BLE001 - one candidate's failure is its own result
        return {'estado': 'error', 'error': type(e).__name__, 'fecha': ahora()}
    return {'estado': 'accesible' if resp.status == 200 else 'http', 'http': resp.status, 'bytes': len(resp.body),
            'sha256': hashlib.sha256(resp.body).hexdigest(), 'fecha': ahora()}


def resumen(cob, carpeta):
    """Per layer: countries searched, countries with a candidate that answers 200. Candidates, never coverage."""
    out = {f"{e['id']}/{c['id']}": {'buscados': 0, 'con_candidato_accesible': 0} for e, c in capas(cob)}
    for p in cob['paises']:
        for capa in hechas(_leer(carpeta / f"{p['iso3']}.json"), p, cob).values():  # current queries only (GPT on 9829c21)
            x = out[f"{capa['eje']}/{capa['capa']}"]
            x['buscados'] += 1
            x['con_candidato_accesible'] += any((r.get('verificacion') or {}).get('estado') == 'accesible'
                                                for r in capa.get('resultados', []))
    return out


def main(argv=None):
    a = argparse.ArgumentParser(description='find candidate official sources for each cell of the world map')
    sub = a.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('buscar')
    b.add_argument('--cobertura', default='sources/cobertura.json')
    b.add_argument('--carpeta', required=True)
    b.add_argument('--max-busquedas', type=int, required=True)
    b.add_argument('--tipo', choices=TIPOS, default='web')
    v = sub.add_parser('verificar')
    v.add_argument('--cobertura', default='sources/cobertura.json')
    v.add_argument('--carpeta', required=True)
    v.add_argument('--por-capa', type=int, default=2)
    x = a.parse_args(argv)
    cob, carpeta = cargar_cobertura(x.cobertura), Path(x.carpeta)
    if x.cmd == 'buscar':
        if not len(capas(cob)) <= x.max_busquedas <= MAX_BUSQUEDAS:  # fewer than one country's layers never advances
            raise SystemExit(f'--max-busquedas must be {len(capas(cob))} to {MAX_BUSQUEDAS}')
        key = os.environ.get('PERPLEXITY_API_KEY', '')
        if not key:
            raise SystemExit('PERPLEXITY_API_KEY is not set: nothing was asked')
        out = correr_busqueda(cob, carpeta, key, x.max_busquedas, x.tipo, buscar=buscar)
        print(json.dumps(out, ensure_ascii=False))
        return 3 if 'alto' in out else 0
    if not 1 <= x.por_capa <= POR_CELDA:
        raise SystemExit(f'--por-capa must be 1 to {POR_CELDA}')
    print(json.dumps({'verificados': verificar(carpeta, x.por_capa)}))
    _escribir(carpeta / 'resumen.json', resumen(cob, carpeta))
    return 0


if __name__ == '__main__':
    sys.exit(main())
