"""SCJN tesis from a SECONDARY source: the Hugging Face dataset ayaxrojo/tesis_scjn_v5_complete (CC-BY-4.0, gated).

The SCJN's own Semanario (sjf2.scjn.gob.mx) answers robots.txt with 403 and is never bypassed (REGLAS 8). This dataset
is catalogued with its own provenance and never presented as the primary.

Layout read 2026-10-21 at revision f233341 (tests/fixtures/hf_tesis_scjn_sample.json): ONE JSON object of 3.6 GB, a
Qdrant export

  {"collection": ..., "server": ..., "timestamp": ..., "total_points": 59678, "points": [{"id", "payload", "vector"}...]}

with payload.metadata = registro_digital, instancia, epoca, materias, tesis, fuente, tipo, rubro, texto, precedente,
publicacion, url, and a 4096-number vector per point. The file is read as a stream, one point at a time.

Fields are copied verbatim. doc_type comes from a fixed table over the printed 'tipo'. The only date is the one
printed in 'publicacion' ("Esta tesis se publicó el viernes 27 de junio de 2014 a las 09:30 horas ..."). Nothing is
inferred: no date from 'fuente' (it prints month and year only), no URL is built, no época is guessed. The dataset
card's statistics do not match the rows; only the rows and the file's own total_points are used.

A row the catalog cannot cite (no registro digital to identify it, or no rubro to name it) is not catalogued and not
completed by guessing: it is counted, with the Qdrant ids of its first points, and nothing of its content is kept.
"""
import codecs
import json
import re
from datetime import date

from .categorize import fold

API_URL = 'https://huggingface.co/api/datasets/{dataset}?blobs=true'
RESOLVE_URL = 'https://huggingface.co/datasets/{dataset}/resolve/{revision}/{file}'

# Fixed table over the printed 'tipo' (folded). No match = OTRO.
TIPO_TYPES = {'AISLADA': 'TESIS AISLADA', 'JURISPRUDENCIA': 'JURISPRUDENCIA'}
MONTHS = {'ENERO': 1, 'FEBRERO': 2, 'MARZO': 3, 'ABRIL': 4, 'MAYO': 5, 'JUNIO': 6, 'JULIO': 7, 'AGOSTO': 8,
          'SEPTIEMBRE': 9, 'SETIEMBRE': 9, 'OCTUBRE': 10, 'NOVIEMBRE': 11, 'DICIEMBRE': 12}
_PUBLISHED = re.compile(r'se public[oó] el (?:[a-záéíóú]+ )?(\d{1,2}) de ([a-záéíóú]+) de (\d{4})', re.I)
_REVISION = re.compile(r'[0-9a-f]{40}')
_SHA256 = re.compile(r'[0-9a-f]{64}')
_UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
SAMPLE = 20  # point ids kept per kind of uncatalogued row
_WS = re.compile(r'[ \t\n\r]*')
_DELIMITERS = frozenset(' \t\n\r,:]}')
_DECODER = json.JSONDecoder()


def doc_type(tipo_printed):
    return TIPO_TYPES.get(fold(tipo_printed or ''), 'OTRO')


def published(publicacion):
    """ISO date of the publication sentence printed in 'publicacion', or None (absent, or not a real date)."""
    m = _PUBLISHED.search(publicacion or '')
    month = MONTHS.get(fold(m.group(2))) if m else None
    if not month:
        return None
    try:
        return date(int(m.group(3)), month, int(m.group(1))).isoformat()
    except ValueError:
        return None


def redact(text):
    """A refused redirect names a signed CDN URL, a short-lived credential: its query never reaches the manifest."""
    return re.sub(r'\?\S*', '?<redacted>', text)


def parse_meta(body, file, license_id):
    """Revision (commit), sha256 and size of `file` from the Hub API answer (?blobs=true). ValueError when the declared
    license is not the registered one (rights changed upstream: nothing is ingested) or anything else is missing."""
    meta = json.loads(body)
    license_ = (meta.get('cardData') or {}).get('license')
    if license_ != license_id:
        raise ValueError(f'declared license is {license_!r}, registered {license_id!r}')
    sibling = next((s for s in meta.get('siblings') or [] if s.get('rfilename') == file), {})
    lfs = sibling.get('lfs') or {}
    revision, sha, size = meta.get('sha'), lfs.get('sha256'), lfs.get('size')
    if not (isinstance(revision, str) and _REVISION.fullmatch(revision) and isinstance(sha, str)
            and _SHA256.fullmatch(sha) and isinstance(size, int) and size > 0):
        raise ValueError(f'{file}: revision, sha256 or size missing in the Hub metadata')
    return {'revision': revision, 'sha256': sha, 'size': size}


class _Reader:
    """Incremental reader over a binary UTF-8 stream; holds at most one pending value plus one chunk."""

    def __init__(self, stream, chunk, max_value):
        self.stream, self.chunk, self.max_value = stream, chunk, max_value
        self.decoder = codecs.getincrementaldecoder('utf-8')()
        self.buf, self.pos, self.eof = '', 0, False

    def more(self):
        if len(self.buf) - self.pos > self.max_value:
            raise ValueError(f'a value larger than {self.max_value} characters')
        data = self.stream.read(self.chunk)
        self.buf = self.buf[self.pos:] + self.decoder.decode(data, final=not data)
        self.pos, self.eof = 0, not data

    def peek(self):
        """The next non-blank character, '' at the end of the file."""
        while True:
            self.pos = _WS.match(self.buf, self.pos).end()
            if self.pos < len(self.buf) or self.eof:
                return self.buf[self.pos:self.pos + 1]
            self.more()

    def take(self, char):
        if self.peek() != char:
            raise ValueError(f'expected {char!r}, found {self.peek()!r}')
        self.pos += 1

    def value(self):
        self.peek()
        while True:
            try:
                obj, end = _DECODER.raw_decode(self.buf, self.pos)
                # A number cut by the chunk boundary still decodes ('2.' of '2.5e-05' reads as 2): a value counts only
                # when what follows it is a delimiter already in the buffer, or the file has ended.
                if (end < len(self.buf) and self.buf[end] in _DELIMITERS) or self.eof:
                    self.pos = end
                    return obj
            except json.JSONDecodeError:
                if self.eof:
                    raise ValueError('malformed JSON value') from None
            self.more()


def iter_points(stream, header, chunk=1 << 20, max_value=64 << 20):
    """Yield each element of the top-level "points" array, in file order, one at a time; every other top-level key
    goes into `header` (total_points is the dataset's own count, used for the coverage check). ValueError on a
    malformed file, on data after the object, or on one value larger than `max_value` characters."""
    r = _Reader(stream, chunk, max_value)
    r.take('{')
    if r.peek() == '}':
        r.pos += 1
    else:
        while True:
            key = r.value()
            if not isinstance(key, str):
                raise ValueError('object key is not a string')
            r.take(':')
            if key == 'points':
                r.take('[')
                if r.peek() == ']':
                    r.pos += 1
                else:
                    while True:
                        yield r.value()
                        if r.peek() != ',':
                            r.take(']')
                            break
                        r.pos += 1
            else:
                header[key] = r.value()
            if r.peek() != ',':
                r.take('}')
                break
            r.pos += 1
    if r.peek() != '':
        raise ValueError('data after the end of the JSON object')


def _str(v):
    return v.strip() if isinstance(v, str) else ('' if v is None else str(v))


def _label(v):
    return ' '.join(_str(v).split()) or None


def point_id(point):
    """The Qdrant id of a point (an unsigned integer or a UUID), the only thing of an uncatalogued row the manifest
    names; anything else is None, so no row content can reach the manifest through it."""
    pid = point.get('id') if isinstance(point, dict) else None
    if isinstance(pid, int) and not isinstance(pid, bool) and pid >= 0:
        return pid
    return pid if isinstance(pid, str) and _UUID.fullmatch(pid) else None


def uncitable(entry):
    """Why the row behind `entry` cannot be catalogued, or None. A tesis is cited by its registro digital and named by
    its rubro (whitespace already normalised by to_entry); a row missing one is counted once, registro first. The size
    of the registro number is never judged: a row with both stays, whatever its registro."""
    if not entry['native_id']:
        return 'without_registro'
    if not entry['title']:
        return 'without_rubro'
    return None


def to_entry(src, country, point, order, artifact, raw_path, seen_at):
    """One catalog entry per tesis, every field copied from the row. The entry's url is the SCJN detail URL printed in
    the row; a row without one points at the dataset file it came from."""
    payload = point.get('payload') if isinstance(point, dict) else None
    md = (payload or {}).get('metadata') if isinstance(payload, dict) else None
    md = md if isinstance(md, dict) else {}
    native_id, tipo, marker = _str(md.get('registro_digital')), _str(md.get('tipo')), _str(md.get('tesis'))
    printed = [_str(md.get(k)) for k in ('tesis', 'tipo', 'epoca', 'instancia', 'materias', 'fuente', 'publicacion')]
    pub = published(_str(md.get('publicacion')))
    listing = {'page_order': order}
    if marker:
        listing['list_marker'] = marker  # the tesis number as printed, e.g. 'PC.I.A. J/155 A (10a.)'
    if tipo:
        listing['type_printed'] = tipo
    if any(printed):
        listing['listing_text'] = ' | '.join(p for p in printed if p)
    return {
        'entry_id': f"{src['source_id']}:{native_id}", 'country': country, 'source_id': src['source_id'],
        'native_id': native_id, 'title': ' '.join(_str(md.get('rubro')).split()),
        'url': _str(md.get('url')) or artifact['url'],
        'category': {**src['category'], 'edition': _label(md.get('epoca')), 'section': _label(md.get('materias')),
                     'issuer': _label(md.get('instancia')), 'doc_type': doc_type(tipo)},
        'dates': {'published': pub} if pub else {},
        'listing': listing,
        'raw_status': 'stored', 'raw_path': raw_path, 'artifact': artifact, 'first_seen': seen_at,
    }
