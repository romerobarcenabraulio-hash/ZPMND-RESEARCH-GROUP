"""Raws a packet cites but does not keep, downloaded again so the gate reads their quotes without republishing them
(docs/NORTE.md, hueco 3; SECURITY T29). scripts/packet_gate.py runs it (verificar) on each packet a PR head changes.
- Asked: each artifact a quote cites and the folder does not keep (stored_at not repo), with redistribution allowed or
  metadata_only, of a packet.json that validates; at most MAX_ARTIFACTS, each declaring at most MAX_BYTES, MAX_TOTAL
  in all. Only through the catalog's Fetcher, at its own url, allowlisted to the hosts of the artifacts asked: https,
  public addresses, robots.txt, redirects re-checked, 1 s per host, the body streamed to disk and cut at its declared
  size. Each download runs in a thread of its own; the caller stops waiting at PER_ARTIFACT or the deadline, whatever
  the server drips (a thread left behind dies with the process; its bytes are never read).
- Kept at <work>/raw/sha256/<2>/<sha>.bin only when sha256 and size are the declared ones; any other body is deleted
  at once. <work> is never published. The receipt gets one JSON line per artifact as soon as it is decided, then one
  per quote: fixed codes, digests, sizes and ids, never a URL, a message or any text of a raw.
"""
import json
import threading
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from .catalog.fetch import BudgetExhausted, Fetcher, FetchRefused, FileSink
from .packets import check
from .schemas import validate

READABLE = ('allowed', 'metadata_only')
MAX_ARTIFACTS, MAX_BYTES, MAX_TOTAL = 40, 100_000_000, 500_000_000  # per packet; one body as packet_gate's MAX_BLOB
PER_ARTIFACT = 240  # seconds for one download, robots.txt and redirects included; HIPÓTESIS until measured in CI
PLAZO = 1080  # seconds for all a call asks and extracts (the gate: one per head), inside auditor.yml's 30 minutes


class _Body(FileSink):
    """A FileSink that knows whether a 200 body began: the Fetcher resets it then."""
    def __init__(self, path, limit):
        super().__init__(path, limit)
        self.began = False

    def reset(self):
        super().reset()
        self.began = True


def _line(recibo, **row):
    if recibo is not None:
        recibo.write(json.dumps(row, sort_keys=True) + '\n')
        recibo.flush()  # each line on disk before the next request: a cut run keeps what it decided


def _host(url):
    try:
        return (urlsplit(url).hostname or '').lower()
    except ValueError:  # asks nothing here; the Fetcher refuses it in its thread
        return ''


def _one(n, a, work, hosts, shared, deadline, clock, kw):
    """(estado, fields) for the n-th artifact asked."""
    part = work / 'parcial' / f'{n}.part'  # its own file: a thread left behind never writes another's
    body, box = _Body(part, a['bytes']), {}
    fetcher = Fetcher(hosts, budget=12, min_interval=1.0, max_bytes=2_000_000, timeout=30, retries=1,
                      deadline=deadline, clock=clock, compartido=shared, **kw)

    def download():
        try:
            box['r'] = fetcher.get(a['url'], sink=body)
        except BaseException as e:  # noqa: BLE001 - handed to the caller as it is
            box['e'] = e
    thread = threading.Thread(target=download, daemon=True)
    thread.start()
    thread.join(max(0.0, min(PER_ARTIFACT, deadline - clock())))
    if thread.is_alive():
        return 'no_descargable', {'motivo': 'plazo'}
    e, r = box.get('e'), box.get('r')
    if e is not None:  # a refusal once a 200 began is a body longer than declared, not a block
        why = 'tope' if isinstance(e, BudgetExhausted) else 'rechazada' if isinstance(e, FetchRefused) else 'error'
        return ('sha_distinto', {'motivo': 'mayor'}) if why == 'rechazada' and body.began else ('no_descargable', {'motivo': why})
    if r.status != 200:
        return 'no_descargable', {'motivo': 'red' if r.status == 0 else 'http', 'http': r.status}
    if body.sha256 != a['sha256'] or body.bytes != a['bytes']:
        part.unlink(missing_ok=True)
        return 'sha_distinto', {'sha256': body.sha256, 'bytes': body.bytes}
    dest = work / 'raw' / 'sha256' / a['sha256'][:2] / f"{a['sha256']}.bin"
    dest.parent.mkdir(parents=True, exist_ok=True)
    part.replace(dest)
    return 'sha_coincide', {'bytes': body.bytes}


def bajar(folder, work, recibo=None, deadline=None, clock=time.monotonic, **kw):
    """{artifact_id: sha_coincide | sha_distinto | no_descargable} of the artifacts asked."""
    folder, work = Path(folder), Path(work)
    packet = json.loads((folder / 'packet.json').read_text(encoding='utf-8'))
    if validate('research_packet', packet):
        return {}
    deadline = clock() + PLAZO if deadline is None else deadline
    quoted = {i for g in ('confirmed', 'conflicting') for f in packet['findings'][g] if 'quote' in f for i in f['artifact_ids']}
    asked = [a for a in packet['artifacts'] if a['artifact_id'] in quoted and a['stored_at'] != 'repo']
    hosts = sorted({_host(a['url']) for a in asked} - {''})
    shared, left, out = {}, MAX_TOTAL, {}
    for n, a in enumerate(asked):
        if a['redistribution'] not in READABLE:
            estado, fields = 'no_descargable', {'motivo': 'derechos'}
        elif n >= MAX_ARTIFACTS or a['bytes'] > min(MAX_BYTES, left):
            estado, fields = 'no_descargable', {'motivo': 'tope'}
        elif clock() >= deadline:
            estado, fields = 'no_descargable', {'motivo': 'plazo'}
        else:
            left -= a['bytes']
            estado, fields = _one(n, a, work, hosts, shared, deadline, clock, kw)
        out[a['artifact_id']] = estado
        _line(recibo, paquete=folder.name, artefacto=a['artifact_id'], estado=estado, **fields)
    return out


def anotar(folder, citas, bajados, recibo=None):
    """{estado: count} of the quotes, one receipt line each: rg.packets' outcome, except that one with no raw at hand
    (sin_crudo) takes what happened to the raws it cites, sha_distinto before no_descargable."""
    packet, final = json.loads((Path(folder) / 'packet.json').read_text(encoding='utf-8')), {}
    for group in ('confirmed', 'conflicting'):
        for i, finding in enumerate(packet.get('findings', {}).get(group, [])):
            estado = citas.get(cid := f'{group}[{i}]')
            if estado == 'sin_crudo':
                got = {bajados.get(a) for a in finding['artifact_ids']}
                estado = next((s for s in ('sha_distinto', 'no_descargable') if s in got), estado)
            if estado is not None:
                final[cid] = estado
                _line(recibo, paquete=Path(folder).name, cita=cid, estado=estado)
    return dict(Counter(final.values()))


def verificar(folder, work, recibo=None, deadline=None, **kw):
    """rg.packets.check of the folder with its quoted raws downloaded again; stats['citas'] counts each outcome."""
    bajados, citas = bajar(folder, work, recibo, deadline, **kw), {}
    problems, warnings, stats = check(folder, [Path(work) / 'raw'], citas, deadline)
    return problems, warnings, {**stats, 'citas': anotar(folder, citas, bajados, recibo)}

