"""Federal laws (index.htm) and regulations (regla.htm) listed by the Cámara de Diputados (LeyesBiblio).

Every listed row is kept, including abrogated ones and rows whose number cell is malformed on the official page
(e.g. 'nos' for the ISR regulation, seen 2026-10-19). Text is verbatim: name, printed dates, printed status.
The raw artifact is the current-text PDF; history documents are listed, not downloaded.
"""
import hashlib
import html
import re

from .categorize import fold

_ROW = re.compile(r'<tr[^>]*>(.*?)</tr>', re.S | re.I)
_CELL = re.compile(r'<td[^>]*>(.*?)</td>', re.S | re.I)
_HREF = re.compile(r'href="([^"]+)"', re.I)
_DATE = re.compile(r'(\d{2})/(\d{2})/(\d{4})')
_CUT = re.compile(r'\s(DOF\s\d|Original DOF|Reglamento Abrogado|Ley Abrogada|Abrogad[oa]\b)')
_HEADER = {'NO.', 'NO', ''}


def _text(fragment):
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', fragment)).split())


def _first_date(text):
    m = _DATE.search(text or '')
    return f'{m.group(3)}-{m.group(2)}-{m.group(1)}' if m else None


def _stem(href):
    return href.rsplit('/', 1)[-1].rsplit('.', 1)[0]


def _is_pdf(h):
    return h.lower().endswith('.pdf') and not h.startswith('pdf_mov/')


def parse_listing(page_html, base_url):
    """All listed instruments in page order. The current text is the first PDF in the official text column
    (4th cell, headed 'TEXTO VIGENTE'); history documents are the links in the name cell. A row is an instrument
    when its text column has a link, whatever its title says (ORDENANZA, PRESUPUESTO, IMPUESTO... are real rows).
    Nothing is skipped silently: a row without a PDF keeps raw_url None so the gap is visible."""
    out = []
    for row in _ROW.findall(page_html):
        raw_cells = _CELL.findall(row)
        cells = [_text(c) for c in raw_cells]
        if len(cells) < 4 or fold(cells[0]) in _HEADER or not cells[1]:
            continue
        text_links = [h for c in raw_cells[3:] for h in _HREF.findall(c)]
        if not text_links:
            continue  # layout or legend row: no official text column
        history = _HREF.findall(raw_cells[1])
        pdfs = [h for h in text_links if _is_pdf(h)]
        docs = [h for h in text_links if h.lower().endswith(('.doc', '.docx'))]
        current = pdfs[0] if pdfs else None
        name_cell = cells[1]
        cut = _CUT.search(name_cell)
        title = (name_cell[:cut.start()] if cut else name_cell).strip()
        is_regla = 'regley/' in ' '.join(text_links)  # abrogated laws are marked 'A' in the number cell: still laws
        if current:
            native_id = _stem(current)
        elif docs:
            native_id = _stem(docs[0])
        else:
            native_id = 'T' + hashlib.sha256(fold(title).encode()).hexdigest()[:12]
        out.append({
            'native_id': native_id,
            'page_order': len(out) + 1,
            'list_marker': cells[0],                      # verbatim number cell ('001', '07', 'A', 'nos', ...)
            'status_printed': 'ABROGADO' if (cells[0] == 'A' or re.search(r'Abrogad[oa]', name_cell)) else 'VIGENTE',
            'title': title,
            'listing_text': name_cell,                    # verbatim, includes printed reform history
            'original_publication': (_first_date(cells[2]) or _first_date(name_cell)) if is_regla else _first_date(name_cell),
            'last_reform_printed': None if is_regla else _first_date(cells[2]),
            'raw_url': base_url + current if current else None,
            'related_urls': [base_url + h for h in pdfs[1:]],
            'history_urls': [base_url + h for h in history],
        })
    return out


def accounted_pdfs(rows, base_url):
    """Every PDF the parsed rows account for: current text, related, history."""
    n = len(base_url)
    urls = set()
    for r in rows:
        urls.update(u[n:] for u in [r['raw_url']] + r['related_urls'] + r['history_urls'] if u and _is_pdf(u[n:]))
    return urls


def count_text_pdfs(page_html):
    """Independent count for reconciliation: distinct PDF links anywhere on the page (mobile copies excluded)."""
    return len({h for h in _HREF.findall(page_html) if _is_pdf(h)})
