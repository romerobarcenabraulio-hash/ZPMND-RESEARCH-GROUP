"""Acquisition by declaration (docs/ADQUISICION.md, contract on main since #85): a source of sources/registro/ whose
`adquisicion` says how to load it is loaded with no code of its own. This module runs the `api` route; the others follow.

  python -m rg.adquirir --solo int.openalex-temas --salida DIR

For each source, with the catalog's Fetcher (https, the source's hosts, robots.txt, public addresses, a size cap, a
budget of max_paginas plus a few, the pause per host):
- its declared size first, read from its `contador` with the sounding's reader (rg.sondeo.leer);
- then its pages: cursor, page number, offset or a single answer, as declared; every page goes to the RawStore by its
  sha256 before anything is read from it (raw first), and the manifest lists each one;
- each record is the item at `ruta_items` with its id at `registro.id_ruta`; a page that is not a list of such records
  ends the source as `ilegible`; a repeated id is counted, never kept twice;
- it ends on the source's own last page, on a cursor seen before, at max_paginas or at the run's deadline, and says
  which; a cursor route ends only on an explicit null or empty next cursor, so an empty page that still names a next
  cursor goes on and a page without that field is `ilegible` (GPT on 17d66b3); only an end on the last page whose
  distinct records equal the declared size is `completo` (cuadre);
- a credential (`credencial.secreto`, the name of an environment variable the workflow sets from a repo secret) goes
  only in the header Authorization: Bearer, only to the host of `url` (Fetcher secrets): never in a URL, a manifest or
  a message; a page whose body holds it, raw or JSON-decoded, is refused and nothing of it is kept.
Each page's new records go to registros/<n>.jsonl.gz, written whole (os.replace) before the manifest names them, and
the manifest is written after every page: a run cut short keeps every record its manifest announces (GPT on d705bce).
Every source of a run shares one deadline (main's), so the last one never outlives the step. Each source writes into a
folder of its own that did not exist (a repeated source_id or an old output is refused before anything is asked), and
`publicar` copies only the manifest and the record files it names: a complete source replaces its folder on the data
branch, any other end goes to its parcial/ and never touches complete records (GPT and the auditor on 17d66b3).
"""
import argparse
import gzip
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from rg import sondeo
from rg.catalog.fetch import BudgetExhausted, Fetcher, FetchRefused
from rg.catalog.store import RawStore

CAP = 20_000_000  # bytes of one page
PLAZO = 100 * 60  # seconds: the step allows 110
_FALTA = object()  # a path the answer does not have, told apart from a null at that path


def _ruta(x, ruta, falta=None):
    for k in ruta:
        if isinstance(k, int) and isinstance(x, list) and -len(x) <= k < len(x):
            x = x[k]
        elif isinstance(k, str) and isinstance(x, dict) and k in x:
            x = x[k]
        else:
            return falta
    return x


def _con(url, **params):
    """The URL with these query parameters set, the declared ones kept."""
    p = urlsplit(url)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k not in params]
    return urlunsplit(p._replace(query=urlencode(q + [(k, str(v)) for k, v in params.items()])))


def _contiene(x, key, hondo=0):
    """True when any text of a decoded answer holds the key; too deep a nesting counts as holding it."""
    if hondo > 50:
        return True
    if isinstance(x, str):
        return key in x
    if isinstance(x, dict):
        return any(_contiene(k, key, hondo + 1) or _contiene(v, key, hondo + 1) for k, v in x.items())
    if isinstance(x, list):
        return any(_contiene(v, key, hondo + 1) for v in x)
    return False


def _primero(pag):
    """The first value of the paging parameter: the declared start, else page 1 or offset 0 (a cursor may have none)."""
    if pag['tipo'] == 'pagina':
        return int(pag.get('inicio') or 1)
    if pag['tipo'] == 'offset':
        return int(pag.get('inicio') or 0)
    return pag.get('inicio')


def _escribir(path, doc):
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def adquirir(f, salida, entorno=None, nuevo_fetcher=None, ahora=None, reloj=None, fin=None, compartido=None):
    """One source by its `api` declaration until `fin` (a reloj() value, the run's deadline); returns its manifest (also
    written to <salida>/<source_id>/manifiesto.json)."""
    a, entorno = f['adquisicion'], os.environ if entorno is None else entorno
    reloj = reloj or time.monotonic  # read at call time: a default bound at import would ignore the host's clock in tests
    pag = a['paginacion']
    ahora = ahora or (lambda: datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
    host = urlsplit(a['url']).hostname
    carpeta = Path(salida) / f['source_id']
    carpeta.mkdir(parents=True)  # a folder of its own: never records left by another acquisition
    m = {'source_id': f['source_id'], 'via': 'api', 'inicio': ahora(), 'paginas': [], 'leidos': 0, 'distintos': 0,
         'repetidos': 0, 'estado': 'en_curso'}
    guardar = lambda: _escribir(carpeta / 'manifiesto.json', m)  # noqa: E731
    key = ''
    if a.get('credencial'):
        key = entorno.get(a['credencial']['secreto'], '')
        if not key:  # nothing is asked without the key the declaration names
            m.update(estado='sin_credencial'); guardar(); return m
    fin = reloj() + PLAZO if fin is None else fin
    if reloj() >= fin:  # the run's deadline came before this source: nothing is asked
        m.update(estado='pendiente', motivo='plazo de la corrida'); guardar(); return m
    nuevo_fetcher = nuevo_fetcher or (lambda: Fetcher(f['allowed_hosts'], budget=pag['max_paginas'] + 8, max_bytes=CAP,
                                                      timeout=60, retries=2, clock=reloj, deadline=fin,
                                                      secrets={key: host} if key else None,
                                                      compartido=compartido))  # one pace per host for the run
    fx, auth = nuevo_fetcher(), (f'Bearer {key}' if key else None)
    raws, vistos, ids = RawStore(carpeta / 'crudos'), set(), set()
    c = f.get('contador')
    try:
        if c and c.get('tipo') == 'json':
            r = fx.get(c['url'], auth=auth if urlsplit(c['url']).hostname == host else None)
            m['declarado'] = sondeo.leer(r.body, c) if r.status == 200 and not _eco(r.body, key) else None
        url, valor, n = a['url'], _primero(pag), 0
        (carpeta / 'registros').mkdir(exist_ok=True)
        while True:
            if reloj() >= fin:
                m.update(estado='pendiente', motivo='plazo de la corrida'); break
            if n >= pag['max_paginas']:
                m.update(estado='incompleto', motivo='max_paginas'); break
            params = {pag['tamano_parametro']: pag['tamano']} if pag.get('tamano_parametro') and pag.get('tamano') else {}
            if pag['tipo'] != 'ninguna' and valor is not None:
                params[pag['parametro']] = valor
            r = fx.get(_con(url, **params), auth=auth)
            n += 1
            if r.status != 200:
                m.update(estado='http', http=r.status); break
            if _eco(r.body, key):
                m.update(estado='rechazado', motivo='la respuesta contiene la llave o no se puede revisar entera: no se guarda'); break
            sha, rel = raws.put(r.body, 'json')
            m['paginas'].append({'n': n, 'sha256': sha, 'crudo': rel, 'bytes': len(r.body)})
            doc = json.loads(r.body.decode('utf-8'))
            items = _ruta(doc, pag['ruta_items'])
            if not isinstance(items, list):  # an item without its id (not an object, no id) is caught below
                m.update(estado='ilegible', motivo='la página no trae una lista de registros'); break
            nuevos = []
            for i in items:
                rid = _ruta(i, a['registro']['id_ruta'])
                if isinstance(rid, bool) or not isinstance(rid, (str, int)):
                    raise ValueError('un registro sin su id')
                m['leidos'] += 1
                if rid in ids:
                    m['repetidos'] += 1; continue
                ids.add(rid)
                nuevos.append(json.dumps({'id': rid, 'registro': i}, ensure_ascii=False, sort_keys=True))
            rel_r = f'registros/{n:05d}.jsonl.gz'
            tmp = carpeta / (rel_r + '.tmp')
            tmp.write_bytes(gzip.compress(''.join(x + '\n' for x in nuevos).encode('utf-8'), mtime=0))
            os.replace(tmp, carpeta / rel_r)  # whole on disk before the manifest names it
            m['paginas'][-1].update(registros=rel_r, nuevos=len(nuevos))
            m['distintos'] = len(ids)
            guardar()
            if pag['tipo'] == 'ninguna':
                m.update(estado='fin'); break
            if pag['tipo'] == 'cursor':  # only the source's own next cursor ends it, never an empty page (GPT on 17d66b3)
                valor = _ruta(doc, pag['ruta_siguiente'], _FALTA)
                if valor is _FALTA:
                    m.update(estado='ilegible', motivo='la página no trae el campo del cursor'); break
                if valor is None or valor == '':
                    m.update(estado='fin'); break
                if not isinstance(valor, str) or len(valor) > 2000:  # GPT on d705bce: [] or {} is not a cursor
                    m.update(estado='ilegible', motivo='cursor con forma inesperada'); break
                if valor in vistos:
                    m.update(estado='incompleto', motivo='cursor repetido'); break
                vistos.add(valor)
            else:
                if not items or len(items) < pag.get('tamano', 1):
                    m.update(estado='fin'); break  # nothing more, or a short last page
                valor += 1 if pag['tipo'] == 'pagina' else pag['tamano']
    except BudgetExhausted as e:  # the Fetcher's deadline (the run's) or its request budget
        m.update(estado='pendiente' if 'deadline' in str(e) else 'incompleto', motivo=str(e)[:200])
    except FetchRefused as e:
        robots = 'robots.txt disallows' in str(e)
        m.update(estado='bloqueada_por_robots' if robots else 'rechazado', motivo=str(e)[:200])
    except (ValueError, UnicodeDecodeError, RecursionError) as e:
        m.update(estado='ilegible', motivo=f'{type(e).__name__}: {str(e)[:120]}')
    if m['estado'] == 'fin':  # the source's own end: complete only when the records square with what it declares
        m['estado'] = ('sin_conteo' if m.get('declarado') is None else
                       'completo' if m['declarado'] == m['distintos'] else 'no_cuadra')
    m['fin'] = ahora()
    guardar()
    return m


def _eco(body, key):
    """True when a body holds the key in any text once decoded as JSON (\\u escapes included). With a key, a body that
    cannot be decoded whole counts as holding it, so a key outside a JSON string, in a page that is not JSON or under a
    nesting too deep for the decoder is never kept (GPT on bbf8695); a separate bytes search would add nothing."""
    if not key:
        return False
    try:
        return _contiene(json.loads(body.decode('utf-8')), key)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return True


def publicar(salida, destino):
    """Copies each source's manifest and only the record files it names from <salida>/<source_id>/ into
    <destino>/<source_id>/ when it is complete (the folder is replaced whole) or <destino>/<source_id>/parcial/ otherwise."""
    for carpeta in sorted(Path(salida).iterdir()):
        mf = carpeta / 'manifiesto.json'
        if not mf.is_file():
            continue
        m = json.loads(mf.read_text(encoding='utf-8'))
        dest = Path(destino) / carpeta.name
        if m.get('estado') != 'completo':  # a partial run never replaces complete records
            dest = dest / 'parcial'
        shutil.rmtree(dest, ignore_errors=True)  # nothing of an older publication stays beside what this manifest names
        (dest / 'registros').mkdir(parents=True)
        for p in m.get('paginas') or []:
            rel = p.get('registros')
            if rel is None:
                continue
            if not isinstance(rel, str) or not re.fullmatch(r'registros/[0-9]{5}\.jsonl\.gz', rel):
                raise ValueError(f'{carpeta.name}: el manifiesto nombra un archivo inesperado')
            shutil.copyfile(carpeta / rel, dest / rel)
        shutil.copyfile(mf, dest / 'manifiesto.json')


def main(argv=None):
    p = argparse.ArgumentParser(description='load registered sources by their api declaration')
    p.add_argument('--registro', default='sources/registro')
    p.add_argument('--solo', nargs='+', required=True)
    p.add_argument('--salida', required=True)
    x = p.parse_args(argv)
    fuentes = {f['source_id']: f for _, f in sondeo.cargar(x.registro)}  # the registry is checked whole first
    faltan = [s for s in x.solo if s not in fuentes or (fuentes[s].get('adquisicion') or {}).get('via') != 'api']
    if faltan:
        raise SystemExit(f'not registered with an api acquisition: {" ".join(faltan)}')
    if len(set(x.solo)) != len(x.solo):  # two acquisitions of one source would share its folder (GPT on 17d66b3)
        raise SystemExit('a source_id is repeated in --solo')
    ya = [s for s in x.solo if (Path(x.salida) / s).exists()]
    if ya:
        raise SystemExit(f'the output already holds {" ".join(ya)}: an acquisition writes into a new folder')
    # one deadline and one pause per host (robots.txt, Crawl-delay) for the whole run (GPT on d705bce and a886619)
    fin, ritmo, res = time.monotonic() + PLAZO, {}, []
    for s in x.solo:
        try:
            res.append(adquirir(fuentes[s], x.salida, fin=fin, compartido=ritmo))
        except Exception as e:  # noqa: BLE001 - one source's failure is its own result; the others still run
            m = {'source_id': s, 'via': 'api', 'estado': 'error', 'motivo': type(e).__name__}
            carpeta = Path(x.salida) / s
            previo = None
            try:
                previo = json.loads((carpeta / 'manifiesto.json').read_text(encoding='utf-8'))
            except (OSError, ValueError):
                pass
            if isinstance(previo, dict):  # the pages it already announced stay announced (GPT on a886619)
                m = {**previo, 'estado': 'error', 'motivo': type(e).__name__}
            carpeta.mkdir(parents=True, exist_ok=True)
            _escribir(carpeta / 'manifiesto.json', m)  # every source has a manifest, so publishing never stops
            res.append(m)
    print(json.dumps([{k: r.get(k) for k in ('source_id', 'estado', 'motivo', 'declarado', 'distintos', 'repetidos')}
                      for r in res], ensure_ascii=False))
    return 0 if all(r['estado'] == 'completo' for r in res) else 3


if __name__ == '__main__':
    sys.exit(main())
