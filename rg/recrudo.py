"""Raws a packet cites but does not keep, downloaded again so the gate reads their quotes without republishing them
(docs/NORTE.md hueco 3); what is asked, through which limits, and kept where is SECURITY T29. One Comun per gate run
carries the pause per host, Crawl-delay, robots.txt and the hosts of stalled threads across its packets (T10)."""
import hashlib
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


class Comun:
    """What every download of one gate run shares: the Fetchers' state per host and the threads left behind."""
    def __init__(self):
        self.fetch, self.vivos = {}, []  # vivos: (thread, frozenset of the hosts its Fetcher may reach)
        self.sellados = None  # the folder abrir_sellados.sh opened R2's sealed copies into, if any (SECURITY T31)

    def ocupados(self):
        return set().union(*(h for t, h in self.vivos if t.is_alive()))


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


def _one(n, a, work, hosts, comun, deadline, clock, kw):
    part = work / 'parcial' / f'{n}.part'  # its own file: a thread left behind never writes another's
    body, box = _Body(part, a['bytes']), {}
    fetcher = Fetcher(hosts, budget=12, min_interval=1.0, max_bytes=2_000_000, timeout=30, retries=1,
                      deadline=deadline, clock=clock, compartido=comun.fetch, **kw)

    def download():
        try:
            box['r'] = fetcher.get(a['url'], sink=body)
        except BaseException as e:  # noqa: BLE001 - handed to the caller as it is
            box['e'] = e
    thread = threading.Thread(target=download, daemon=True)
    thread.start()
    thread.join(max(0.0, min(PER_ARTIFACT, deadline - clock())))
    if thread.is_alive():
        comun.vivos.append((thread, frozenset(hosts)))  # its hosts stay busy while it lives
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


def pedidos(packet):
    """The artifacts a quote cites that the folder does not keep, of a packet that validates; [] otherwise."""
    if validate('research_packet', packet):
        return []
    quoted = {i for g in ('confirmed', 'conflicting') for f in packet['findings'][g] if 'quote' in f for i in f['artifact_ids']}
    return [a for a in packet['artifacts'] if a['artifact_id'] in quoted and a['stored_at'] != 'repo']


def _sellado(sellados, a, work):
    """The copy R2 kept sealed (scripts/abrir_sellados.sh opened it into sellados/sha256/<aa>/<sha>/<url hash>/; SECURITY
    T31) written to work/raw when it was fetched from a's url and its bytes are a's sha256 and size, so nothing is asked
    of the host; None otherwise (then the raw is downloaded again)."""
    d = Path(sellados or '.') / 'sha256' / a['sha256'][:2] / a['sha256'] / hashlib.sha256(a['url'].encode('utf-8')).hexdigest()
    u = d / f"{a['sha256']}.url"
    if not sellados or not u.is_file() or u.read_text(encoding='utf-8', errors='replace') != a['url']:
        return None
    for f in sorted(x for x in d.glob(a['sha256'] + '.*') if x != u):
        b = f.read_bytes() if f.is_file() else b''
        if len(b) == a['bytes'] and hashlib.sha256(b).hexdigest() == a['sha256']:
            dest = Path(work) / 'raw' / 'sha256' / a['sha256'][:2] / f"{a['sha256']}.bin"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b)
            return dest
    return None


def bajar(folder, work, recibo, deadline, clock=time.monotonic, comun=None, **kw):
    """{artifact_id: sha_coincide | sha_distinto | no_descargable} of the artifacts asked."""
    folder, work = Path(folder), Path(work)
    packet = json.loads((folder / 'packet.json').read_text(encoding='utf-8'))
    if validate('research_packet', packet):
        return {}
    asked = pedidos(packet)
    hosts = sorted({_host(a['url']) for a in asked} - {''})
    comun, left, out = Comun() if comun is None else comun, MAX_TOTAL, {}
    for n, a in enumerate(asked):
        if a['redistribution'] not in READABLE:
            estado, fields = 'no_descargable', {'motivo': 'derechos'}
        elif n >= MAX_ARTIFACTS or a['bytes'] > min(MAX_BYTES, left):
            estado, fields = 'no_descargable', {'motivo': 'tope'}
        elif _sellado(comun.sellados, a, work):  # the bytes acquired, so a page that changes on every request still verifies
            left = left - a['bytes']  # within T29's caps, as a download
            estado, fields = 'sha_coincide', {'bytes': a['bytes'], 'origen': 'sellado'}
        elif clock() >= deadline:
            estado, fields = 'no_descargable', {'motivo': 'plazo'}
        elif set(hosts) & comun.ocupados():
            estado, fields = 'no_descargable', {'motivo': 'ocupado'}
        else:
            left -= a['bytes']
            estado, fields = _one(n, a, work, hosts, comun, deadline, clock, kw)
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


def verificar(folder, work, recibo=None, deadline=None, comun=None, **kw):
    """rg.packets.check of the folder with its quoted raws downloaded again; stats['citas'] counts each outcome."""
    deadline = time.monotonic() + PLAZO if deadline is None else deadline  # one plazo for the downloads and the extraction
    bajados, citas = bajar(folder, work, recibo, deadline, comun=comun, **kw), {}
    problems, warnings, stats = check(folder, [Path(work) / 'raw'], citas, deadline)
    return problems, warnings, {**stats, 'citas': anotar(folder, citas, bajados, recibo)}

