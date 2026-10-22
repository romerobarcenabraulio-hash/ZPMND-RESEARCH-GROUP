"""Plain text of one stored raw file, so a ChangeEvent or relation can quote it exactly (schemas/common, evidence).

The format comes from the first bytes, never from the file name (docs/DIMENSIONES.md: 917 '.doc' files are DOCX, 6 are
RTF, some '.bin' are PDF). Each format has one pinned extractor, `name==version`, the evidence field of the contract:
- HTML: html.parser; script and style dropped; block elements break lines. Charset: UTF-8 BOM, else valid UTF-8, else
  the declared one (unless it says UTF-8 and the bytes are not), else windows-1252; decoded by the catalog's decode_html.
- DOCX: zipfile and ElementTree (stdlib) over word/document.xml, then footnotes and endnotes. Deleted or moved-away
  text, field codes and the fallback copy of alternate content stay out. No text and embedded images = necesita_ocr.
- PDF: pypdf (pinned in requirements-dev.txt), page by page. A page has text when its layer gives at least MIN_CHARS
  non-blank characters (as scripts/medir_extraible.py). Fewer than TEXT_SHARE of the pages with text = necesita_ocr;
  the text of the pages that have it is kept. No OCR here.
- Word 97 (OLE2), RTF, other zips, JSON and anything else: formato_no_soportado, no text.
Every text then loses its invisible characters (the catalog's clean_text, counted), keeps at most one blank line in a
row, and is NFC-normalized. Bump a format's version whenever its output can change: tests/test_texto.py pins the sha256
of each golden text and fails until you do.
"""
import codecs
import io
import logging
import re
import unicodedata
import xml.etree.ElementTree as ET  # expat: no external entities; entity expansion is bounded (billion laughs)
import zipfile
from html.parser import HTMLParser

from pypdf import PdfReader, __version__ as PYPDF_VERSION

from ..catalog.categorize import clean_text
from ..catalog.fetch import decode_html

logging.getLogger('pypdf').setLevel(logging.ERROR)  # a warning per odd PDF would flood the run log

OK, OCR, UNSUPPORTED, FAILED = 'ok', 'necesita_ocr', 'formato_no_soportado', 'fallo'
STATUSES = (OK, OCR, UNSUPPORTED, FAILED)
EXTRACTORS = {'html': 'rg-html==1', 'docx': 'rg-docx==1', 'pdf': f'rg-pdf==1+pypdf.{PYPDF_VERSION}'}
SNIFF = 'rg-sniff==1'  # formats without an extractor carry the version of what told them apart
VERSIONS = {**EXTRACTORS, 'sniff': SNIFF}  # what a done bundle is done with: any change here reopens it
SUPPORTED = ('html', 'pdf', 'zip')  # a zip is read as DOCX when it holds word/document.xml
MIN_CHARS = 30
TEXT_SHARE = 0.9
MAX_PART = 100_000_000  # decompressed bytes read from one DOCX part (zip bomb)
HEAD = 4096
OLE2 = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'
_HTML = re.compile(rb'<(?:!doctype\s+html|html|head|body|title|meta|p|div|table)\b', re.I)
_META = re.compile(rb'<meta[^>]+charset\s*=\s*["\']?\s*([A-Za-z0-9._:-]+)', re.I)


def extractor(fmt):
    return EXTRACTORS.get(fmt, SNIFF)


def sniff(head):
    """'zip', 'ole2', 'pdf', 'rtf', 'json', 'html' or 'otro', from the first bytes only."""
    if head.startswith(b'PK\x03\x04'):
        return 'zip'
    if head.startswith(OLE2):
        return 'ole2'
    if b'%PDF-' in head[:1024]:  # readers accept the header anywhere in the first 1024 bytes
        return 'pdf'
    start = head[:1024].lstrip(b'\xef\xbb\xbf \t\r\n')
    if start.startswith(b'{\\rtf'):
        return 'rtf'
    if start[:1] in (b'{', b'['):  # before HTML: a JSON string may hold markup
        return 'json'
    if _HTML.search(head[:1024]):
        return 'html'
    return 'otro'


def _finish(text):
    """Invisible characters out (counted), stripped lines, at most one blank line in a row, NFC. Apart from the removed
    invisible characters this changes whitespace only, so the folded text (rg.quotes._fold) stays the same."""
    text, removed = clean_text(text)
    lines = []
    for line in text.split('\n'):
        line = line.strip()
        if line or (lines and lines[-1]):
            lines.append(line)
    while lines and not lines[-1]:
        lines.pop()
    return unicodedata.normalize('NFC', '\n'.join(lines)), removed


def _result(fmt, status, text=None, removed=0, **extra):
    return {'format': fmt, 'status': status, 'extractor': extractor(fmt), 'text': text, 'invisibles_removed': removed,
            **extra}


def html_charset(body):
    if body.startswith(codecs.BOM_UTF8):
        return 'utf-8'
    try:
        body.decode('utf-8')
        return 'utf-8'
    except UnicodeDecodeError:
        pass
    m = _META.search(body[:1024])
    declared = m.group(1).decode('ascii').lower() if m else ''
    return declared if declared not in ('', 'utf-8', 'utf8') else 'windows-1252'


_BLOCK = frozenset('address article aside blockquote br caption center dd div dl dt fieldset figcaption figure footer '
                   'form h1 h2 h3 h4 h5 h6 header hr li main nav ol p pre section table tbody tfoot thead title tr ul'
                   .split())
_CELL = frozenset(('td', 'th'))
_SKIP = frozenset(('script', 'style'))
_WS = re.compile(r'\s+')


class _HtmlText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.pre = [], 0, 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self.skip += 1
        elif tag in _BLOCK:
            self.out.append('\n')
        elif tag in _CELL:
            self.out.append('\t')
        self.pre += tag == 'pre'

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in _BLOCK:
            self.out.append('\n')
        if tag == 'pre':
            self.pre = max(0, self.pre - 1)

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data if self.pre else _WS.sub(' ', data))


def _html(body):
    charset = html_charset(body)
    p = _HtmlText()
    p.feed(decode_html(body, charset))
    p.close()
    text, removed = _finish(''.join(p.out))
    return _result('html', OK, text, removed, charset=charset)


_W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
_MC = '{http://schemas.openxmlformats.org/markup-compatibility/2006}'
_DOCX_PARTS = ('word/document.xml', 'word/footnotes.xml', 'word/endnotes.xml')
# Only w:t carries text, so deleted text (w:delText) and field codes (w:instrText) never enter. Skipped as well: text
# moved away (its w:t stay where they were) and the fallback copy of alternate content (the same text box again).
_DOCX_SKIP = frozenset((_W + 'moveFrom', _MC + 'Fallback'))
_DOCX_CHAR = {_W + 'tab': '\t', _W + 'ptab': '\t', _W + 'br': '\n', _W + 'cr': '\n', _W + 'noBreakHyphen': '-'}


def _docx_walk(el, out):
    if el.tag in _DOCX_SKIP:
        return
    out.append((el.text or '') if el.tag == _W + 't' else _DOCX_CHAR.get(el.tag, ''))
    for child in el:
        _docx_walk(child, out)
    if el.tag == _W + 'p':
        out.append('\n')


def _docx(body):
    z = zipfile.ZipFile(io.BytesIO(body))
    names = set(z.namelist())
    if 'word/document.xml' not in names:
        return _result('zip', UNSUPPORTED)
    out = []
    for part in _DOCX_PARTS:
        if part in names:
            with z.open(part) as fh:
                data = fh.read(MAX_PART + 1)
            if len(data) > MAX_PART:
                raise ValueError(f'{part} larger than {MAX_PART} bytes')
            _docx_walk(ET.fromstring(data), out)
            out.append('\n')
    text, removed = _finish(''.join(out))
    scanned = len(''.join(text.split())) < MIN_CHARS and any(n.startswith('word/media/') for n in names)
    return _result('docx', OCR if scanned else OK, text, removed)


def _pdf(body):
    reader = PdfReader(io.BytesIO(body), strict=False)
    if reader.is_encrypted and not reader.decrypt(''):
        return _result('pdf', FAILED, error='encrypted: needs a password')
    texts, without, removed = [], [], 0
    for n, page in enumerate(reader.pages, 1):
        text, r = _finish(page.extract_text() or '')
        texts.append(text)
        removed += r
        if len(''.join(text.split())) < MIN_CHARS:
            without.append(n)
    if not texts:
        return _result('pdf', FAILED, error='no pages')
    pages, pos = [], 0
    for text in texts:
        pages.append([pos, pos + len(text) + 1])
        pos = pages[-1][1]
    status = OK if 1 - len(without) / len(texts) >= TEXT_SHARE else OCR
    if len(without) == len(texts):  # no text layer at all: nothing to keep until OCR
        return _result('pdf', OCR, None, 0, pages_without_text=without)
    return _result('pdf', status, ''.join(t + '\n' for t in texts), removed, pages=pages, pages_without_text=without)


def extract(body):
    """{'format', 'status', 'extractor', 'text' (str or None), 'invisibles_removed'} plus 'charset' (HTML), 'pages'
    ([start, end) code-point offsets of each page in text) and 'pages_without_text' (1-based) for PDF, 'error' (fallo)."""
    fmt = sniff(body[:HEAD])
    if fmt not in SUPPORTED:
        return _result(fmt, UNSUPPORTED)
    try:
        return {'html': _html, 'pdf': _pdf, 'zip': _docx}[fmt](body)
    except Exception as e:  # a broken or hostile file is a status, never a crash
        return _result('docx' if fmt == 'zip' else fmt, FAILED, error=clean_text(f'{type(e).__name__}: {e}')[0][:300])


def failed(head, error):
    """fallo for a raw whose extraction did not finish (time limit, crashed process, too large), by its first bytes."""
    fmt = sniff(head)
    return _result('docx' if fmt == 'zip' else fmt, FAILED, error=error)


def too_large(head, limit):
    """A raw over the size limit is not read whole: formato_no_soportado if its format has no extractor anyway, else fallo."""
    return _result(sniff(head), UNSUPPORTED) if sniff(head) not in SUPPORTED else failed(head, f'larger than {limit} bytes')
