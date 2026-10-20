"""DOF day index from SIDOF (https://sidof.segob.gob.mx/welcome/DD-MM-YYYY).

Categories are the DOF's own structure, copied verbatim: edition (tab), section, branch (organismo) and issuer
(suborganismo). Every note with the official class 'sumario-nota' is kept even when its edition cannot be named
(edition = null); the run reconciles the count against the page. Raw: the note's official HTML at /notas/docFuente/<id>.
"""
import html
import re
from datetime import date
from html.parser import HTMLParser

from .categorize import fold

EDITIONS = {'matutina': 'MATUTINA', 'vespertina': 'VESPERTINA', 'extraordinaria': 'EXTRAORDINARIA'}


def day_url(base, day):
    return f'{base}/welcome/{day:%d-%m-%Y}'


def note_url(base, native_id):
    return f'{base}/notas/{native_id}'


def raw_url(base, native_id):
    return f'{base}/notas/docFuente/{native_id}'


def _clean(text):
    return ' '.join(html.unescape(text).split())


class _DayParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tab_edition = {}      # '#resp-tab2' -> 'VESPERTINA'
        self.edition = None
        self.pane = None
        self.printed = []          # text of span.edition-date ('Edición Matutina del 15 de octubre de 2026')
        self._in_printed = False
        self.section = self.branch = self.issuer = None
        self.items = []
        self.inputs = {}           # every <input id=... value=...>, whatever the attribute order
        self._depth = 0            # div depth, to know when a tab pane ends
        self._pane_depth = None
        self._capture = None       # ('section'|'issuer'|'note', buffer, note_id)
        self._in_issuer_heading = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get('class') or ''
        if tag == 'a' and a.get('href', '').startswith('#resp-tab'):
            for key, label in EDITIONS.items():
                if key in cls.split():
                    self.tab_edition[a['href'][1:]] = label
        if tag == 'div':
            self._depth += 1
            if 'tab-pane' in cls.split() and (a.get('id') or '').startswith('resp-tab'):
                self.edition, self.pane = self.tab_edition.get(a['id']), a['id']
                self._pane_depth = self._depth
                self.section = self.branch = self.issuer = None
            if 'click-to-collapse' in cls.split() and 'panel-heading' in cls.split():
                self._in_issuer_heading = True
        if tag == 'input' and a.get('id'):
            self.inputs.setdefault(a['id'], a.get('value') or '')
        if tag == 'span' and 'edition-date' in cls.split():
            self._in_printed = True
        if self._pane_depth is None:
            return  # outside the edition panes (menus, 'top notes' carousel of other days)
        if tag == 'h4' and 'power' in cls.split():
            self._capture = ('section', [], None)
        elif tag == 'h4' and 'ElipsisText' in cls.split() and a.get('title'):
            self.branch, self.issuer = _clean(a['title']).upper() or None, None
        elif tag == 'a' and 'accordion-toggle' in cls.split() and self._in_issuer_heading:
            self._capture = ('issuer', [], None)
        elif tag == 'a' and 'sumario-nota' in cls.split():
            m = re.fullmatch(r'/notas/(\d+)', a.get('href', ''))
            if m:
                self._capture = ('note', [], m.group(1))

    def handle_endtag(self, tag):
        if tag == 'div':
            if self._pane_depth is not None and self._depth == self._pane_depth:
                self.edition, self.pane, self._pane_depth = None, None, None
            self._depth -= 1
            self._in_issuer_heading = False
        if tag == 'span':
            self._in_printed = False
        if self._capture and ((tag == 'h4' and self._capture[0] == 'section') or
                              (tag == 'a' and self._capture[0] in ('issuer', 'note'))):
            kind, buf, note_id = self._capture
            text = _clean(''.join(buf))
            if kind == 'section':  # an empty heading in the source is 'no data' (None), never an empty label
                self.section, self.branch, self.issuer = text.upper() or None, None, None
            elif kind == 'issuer':
                self.issuer = text.upper() or None
            elif text:
                self.items.append({'native_id': note_id, 'title': text, 'edition': self.edition, 'pane': self.pane,
                                   'section': self.section, 'branch': self.branch, 'issuer': self.issuer})
            self._capture = None

    def handle_data(self, data):
        if self._in_printed:
            self.printed.append(data)
        if self._capture:
            self._capture[1].append(data)


_PDF_INPUT = {'MATUTINA': 'pdfMat', 'VESPERTINA': 'pdfVes', 'EXTRAORDINARIA': 'pdfExt'}


class _Inputs(HTMLParser):
    """Every <input id=... value=...> of the page, whatever the attribute order or quoting."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.values = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'input' and a.get('id'):
            self.values.setdefault(a['id'], a.get('value') or '')


def _inputs(page_html):
    p = _Inputs()
    p.feed(page_html)
    return p.values


def _iso(d, m, y):
    """A printed date that is not a real date (00-00-0000) is no date: None, never a string the run would trust."""
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except ValueError:
        return None


def edition_dates(page_html, values=None):
    """Official date of each edition shown on the page, from its own PDF link (/showPDF/DD-MM-YYYY/...). A weekend
    page with no edition of its own shows the last edition, so the requested day is NOT the publication date."""
    values, out = values if values is not None else _inputs(page_html), {}
    for edition, input_id in _PDF_INPUT.items():
        m = re.search(r'/showPDF/(\d{2})-(\d{2})-(\d{4})/', values.get(input_id, ''))
        if m:
            out[edition] = _iso(*m.groups())
    return out


def page_date(page_html, values=None):
    """The page's own publication date (<input id="fechaPub" value="DD-MM-YYYY">); on a weekend mirror it is the
    mirrored edition's date. None when the page does not give it: never replaced by the requested day."""
    values = values if values is not None else _inputs(page_html)
    m = re.fullmatch(r'(\d{2})-(\d{2})-(\d{4})', values.get('fechaPub', '').strip())
    return _iso(*m.groups()) if m else None


def parse_day(page_html):
    """Notes of one DOF page in page order; a note listed twice keeps its first position. Each note carries the
    official date of its edition (edition_date, from the edition's PDF link) and 'published': that date, else the
    page's own date (an edition the page cannot name), else None, which the run reports and never fills in."""
    p = _DayParser()
    p.feed(page_html)
    # A page without tab navigation (seen 2026-10-15) names its single edition only in its printed heading. Copied
    # when the page has exactly one pane and the heading names an edition; otherwise the edition stays null.
    words = [w for w in fold(' '.join(p.printed)).lower().split() if w in EDITIONS]
    if not p.tab_edition and len({i['pane'] for i in p.items}) == 1 and len(set(words)) == 1:
        for i in p.items:
            i['edition'] = EDITIONS[words[0]]
    for i in p.items:
        del i['pane']
    dates, fallback = edition_dates(page_html, p.inputs), page_date(page_html, p.inputs)  # one parse of the page
    seen, out = set(), []
    for item in p.items:
        if item['native_id'] not in seen:
            seen.add(item['native_id'])
            own = dates.get(item['edition'])
            out.append({**item, 'edition_date': own, 'published': own or fallback})
    return out


def count_listed(page_html):
    """Independent count for reconciliation: distinct note ids carrying the official 'sumario-nota' class."""
    return len(set(re.findall(r'<a[^>]*class="sumario-nota"[^>]*href="/notas/(\d+)"', page_html)))
