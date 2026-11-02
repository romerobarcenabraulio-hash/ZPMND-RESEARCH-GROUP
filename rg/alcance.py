"""Rules 21 and 23 (docs/REGLAS.md): RG is not frozen, it acquires for whoever asks. A source runs (status active or
trial: rg/catalog/run.py runs active always and trial when named) only naming who asked for it and how it is acquired.

In all of RG's source registry (sources/mx.json and sources/registro/):
- a source that runs and is not on the legacy frontier carries `consumer` (the request_id of a request in requests/,
  or a ZPPMND unit as zpmnd:<name>) and a valid `adquisicion` block (rg/sondeo.py: its schema, the source's own route
  and its own hosts);
- an `adquisicion` that runs (any route but manual) needs that consumer whatever the source's status;
- the legacy frontier is the sources of sources/mx.json, either list, marked "legacy": true (the seven Mexico adapters
  that ran on 2026-11-02): they keep running without either field and are not rewritten. tests/test_registro.py pins
  that frontier by hand, so a "legacy" mark anywhere else (a registry source, a text "true") grants nothing.

Nothing here reads verdicts/: a VerdictEvent counts only with its constancia verified (rule 22), a later PR.
"""
import json
import re
from pathlib import Path

from rg.sondeo import _adquisicion_errores

CORREN = ('active', 'trial')
UNIDAD = re.compile(r'zpmnd:[a-z0-9][a-z0-9._-]{0,63}')


def frontera(mx):
    """The legacy frontier: id -> adapter of every source of sources/mx.json (both lists) marked "legacy": true."""
    mexico = list(mx.get('sources', [])) + list(mx.get('secondary_sources', []))
    return {s['source_id']: s.get('adapter') for s in mexico if s.get('legacy') is True}


def pedidos(carpeta):
    """The request_ids of requests/ (a file that cannot be read names nobody)."""
    out = set()
    for p in sorted(Path(carpeta).glob('*.json')):
        try:
            d = json.loads(p.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and isinstance(d.get('request_id'), str):
            out.add(d['request_id'])
    return out


def consumidor(c, pedidos):
    """A request_id of requests/ or a ZPPMND unit (zpmnd:<name>); nothing else names who asked."""
    if not isinstance(c, str):
        return False
    return c in pedidos or UNIDAD.fullmatch(c) is not None


def errores(mx, registro, pedidos):
    """Every breach of rules 21 and 23, as text; empty when they hold. mx: sources/mx.json; registro: the (letter,
    source) pairs of rg.sondeo.cargar; pedidos: the request_ids of requests/ (pedidos())."""
    legado = frontera(mx)
    mexico = list(mx.get('sources', [])) + list(mx.get('secondary_sources', []))
    todas = [(f, f['source_id'] in legado) for f in mexico] + [(f, False) for _, f in registro]
    out = []
    for f, es_legado in todas:
        sid, a = f['source_id'], f.get('adquisicion')
        nombrado = consumidor(f.get('consumer'), pedidos)
        if f.get('status') in CORREN and not es_legado:
            if not nombrado:
                out.append(f'{sid}: runs without a consumer (a request_id of requests/ or zpmnd:<unit>)')
            if a is None or _adquisicion_errores(a, f, f.get('allowed_hosts') or []):
                out.append(f'{sid}: runs without a valid adquisicion')
        elif a is not None and not (isinstance(a, dict) and a.get('via') == 'manual') and not nombrado:
            out.append(f'{sid}: adquisicion that runs without a consumer')
    return out
