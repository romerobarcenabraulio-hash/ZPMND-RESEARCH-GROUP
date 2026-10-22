"""Probe which request shape INEGI's indicator API answers for a series: status codes only, no data kept (2026-10-22).

    INEGI_TOKEN=... python scripts/sondear_inegi.py 628194 [910392 ...]

The first real run got 400 "No se encontraron resultados" for INDICATOR 628194 with area 00 and fuente BIE, and 401 for
CL_INDICATOR. On 2026-10-22 the API page's own example (1002000001, BISE) answered 200 with the same token while 628194
and 910392 gave 400 in every BIE and BISE shape (runs 39870811830, 39870891633): the token works, the source or the id
does not. INEGI's query builder says BIE now sits inside BISE ("BIE EN BISE"), so BIE-BISE is tried too. The official API page shows areas 00000 and 0700 in its examples and only fuente BISE, so each id is tried
with every documented combination, through the catalog's Fetcher (robots, the single allowed host, the token sent only
to www.inegi.org.mx). One line per request: the URL with <token>, the HTTP status and at most 160 characters of
INEGI's answer with the token removed. Nothing is written to disk.
"""
import os
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rg.catalog.fetch import Fetcher, FetchRefused  # noqa: E402
from rg.catalog.indicadores import INEGI_CATALOG, INEGI_INDICATOR, TOKEN_SLOT  # noqa: E402

HOST = 'www.inegi.org.mx'
AREAS = ('00', '0700', '00000')  # 00 from the API page's text; 0700 and 00000 from its examples
FUENTES = ('BIE', 'BISE', 'BIE-BISE')  # BIE-BISE: HIPÓTESIS from INEGI's own query builder ("BIE EN BISE", 2026-10-22)


def shapes(series_id):
    """(template, fields) for every combination tried, INDICATOR first, then CL_INDICATOR."""
    out = [(INEGI_INDICATOR, {'series': series_id, 'lang': 'es', 'area': a, 'fuente': f}) for f in FUENTES for a in AREAS]
    out += [(INEGI_CATALOG, {'series': series_id, 'lang': 'es', 'fuente': f}) for f in FUENTES]
    return out


def budget_for(series_ids):
    """Every shape of every id plus one robots.txt: a budget that cannot run out before the last shape is tried."""
    return sum(len(shapes(i)) for i in series_ids) + 1


def make_fetcher(token, n_requests):
    """The catalog's Fetcher: one allowed host, and the token bound to it (a redirect elsewhere never carries it)."""
    return Fetcher([HOST], budget=n_requests, min_interval=1.0, secrets={token: HOST})


def redact(text, token):
    """The token removed in every form it travels (raw, and URL-quoted as it sits in the path)."""
    for form in {token, quote(token, safe='')}:
        text = text.replace(form, TOKEN_SLOT)
    return text


def probe(series_ids, token, fetcher=None, out=print):
    if not token:
        raise SystemExit('INEGI_TOKEN missing')
    fetcher = fetcher or make_fetcher(token, budget_for(series_ids))
    for series_id in series_ids:
        for tpl, kw in shapes(series_id):
            shown = tpl.format(**kw, token=TOKEN_SLOT)
            try:
                r = fetcher.get(tpl.format(**kw, token=token))
                answer = redact(r.body.decode('utf-8', 'replace'), token)  # redact the whole body, then cut
                out(f'{r.status} {shown} {" ".join(answer.split())[:160]}')
            except FetchRefused as exc:
                out(f'refused {shown} {redact(str(exc), token)[:160]}')


if __name__ == '__main__':
    ids = sys.argv[1:]
    if not ids or not all(i.isdigit() for i in ids):
        sys.exit('usage: sondear_inegi.py ID [ID ...] (digits only)')
    probe(ids, os.environ.get('INEGI_TOKEN', ''))
