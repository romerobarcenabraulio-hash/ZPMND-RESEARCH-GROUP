"""State legislation from the Orden Jurídico Nacional (SEGOB): https://www.ordenjuridico.gob.mx

One format for the 32 states: a listing per state and power (despliegaedo.php?edo=E&idPoder=P), whose rows carry the
official title, publication date, last-reform date and type; a record sheet (fichaOrdenamiento.php) with status,
locality and the link to the document. Pages are ISO-8859-1. Every value is copied verbatim.
"""
import html
import re
from urllib.parse import quote, urlsplit, urlunsplit

POWERS = {1: 'PODER EJECUTIVO', 2: 'PODER LEGISLATIVO', 3: 'PODER JUDICIAL', 4: 'ORGANOS AUTONOMOS'}
_ROW = re.compile(r'<tr>\s*<td bgcolor="[^"]*" align=left>(.*?)</tr>', re.S | re.I)
_TD = re.compile(r'<td[^>]*>(.*?)</td>', re.S | re.I)
_FICHA = re.compile(r'fichaOrdenamiento\.php\?idArchivo=(\d+)&ambito=ESTATAL')
_TOTAL = re.compile(r'Existen un total de\s*(?:&nbsp;)?\s*(?:<strong>)?\s*(\d+)')


def _text(fragment):
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', fragment)).split())


def _iso(dmy):
    m = re.fullmatch(r'(\d{2})-(\d{2})-(\d{4})', dmy or '')
    return f'{m.group(3)}-{m.group(2)}-{m.group(1)}' if m else None


def list_url(base, edo, power, liberado):
    return f'{base}despliegaedo.php?edo={edo}&idPoder={power}&liberado={liberado}'


def ficha_url(base, native_id):
    return f'{base}fichaOrdenamiento.php?idArchivo={native_id}&ambito=ESTATAL'


def printed_total(page_html):
    """The total the page itself prints ('Existen un total de N Ordenamientos'); None if absent."""
    m = _TOTAL.search(page_html)
    return int(m.group(1)) if m else None


def state_name(page_html):
    """State name as printed in the listing header."""
    m = re.search(r'<font size="\+1"><b>([^<]+)</b></font>', page_html)
    return _text(m.group(1)) if m else None


def count_rows(page_html):
    """Rows on the page that link a record sheet, duplicates included (the source repeats some rows verbatim)."""
    return sum(1 for row in _ROW.findall(page_html) if _FICHA.search(row))


def parse_list(page_html):
    out, seen = [], set()
    for row in _ROW.findall(page_html):
        m = _FICHA.search(row)
        cells = [_text(c) for c in _TD.findall('<td>' + row)]
        if not m or len(cells) < 4 or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        out.append({'native_id': m.group(1), 'title': cells[0], 'published_printed': cells[1],
                    'last_reform_printed': cells[2], 'type_printed': cells[3],
                    'published': _iso(cells[1]), 'last_reform': _iso(cells[2])})
    return out


def _field(page_html, label):
    """First non-empty cell after the label, within the label's own table row."""
    m = re.search(re.escape(label) + r'(.*?)</tr>', page_html, re.S | re.I)
    if not m:
        return None
    for cell in _TD.findall(m.group(1)):
        value = _text(cell).strip()
        if value:
            return value
    return None


def parse_ficha(page_html, base):
    """Status, locality, power, type and the document link, verbatim. The link is normalized to https and its path
    percent-encoded (the site prints spaces in paths); the host must stay the OJN host."""
    m = re.search(r'Descargar Ordenamiento:.*?<a href="([^"]+)"', page_html, re.S | re.I)
    doc = None
    if m:
        parts = urlsplit(html.unescape(m.group(1)).strip())
        host = urlsplit(base).netloc
        if parts.netloc in (host, host.replace('www.', '', 1)) or not parts.netloc:
            path = re.sub(r'/\./', '/', parts.path if parts.netloc else '/' + parts.path.lstrip('./'))
            doc = urlunsplit(('https', host, quote(path, safe='/%'), '', ''))
    return {'status_printed': _field(page_html, 'Estatus:'), 'locality': _field(page_html, 'Localidad:'),
            'power_printed': _field(page_html, 'Poder:'), 'type_printed': _field(page_html, 'Tipo:'),
            'published_printed': _field(page_html, 'Fecha de Publicaci'), 'doc_url': doc}
