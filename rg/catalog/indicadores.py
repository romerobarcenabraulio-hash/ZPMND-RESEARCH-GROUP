"""Mexico's official calculation indicators: Banxico SIE API and INEGI BIE API (read-only, token per institution).

One catalog entry per observation, with value, date and unit copied exactly as the API serves them: nothing is
computed, converted or derived (no variations, no averages, no rebasing). Numbers are kept as the literal text of the
response (json parse_float/parse_int=str), so '14.8290' never becomes 14.829.

Formats were read from the official documentation on 2026-10-21; the test fixtures are CONSTRUCTED from it and stay
HIPÓTESIS until the first real run replaces them with real bytes:
- Banxico SIE (https://www.banxico.org.mx/SieAPIRest/service/v1/doc/consultaDatosSerieRango and doc/consultaSeries):
  GET series/:idSerie/datos/:fechaIni/:fechaFin -> {"bmx": {"series": [{"idSerie", "titulo", "datos": [{"fecha":
  "dd/mm/yyyy", "dato": "14.8290" | "N/E"}]}]}}; GET series/:idSerie -> metadata with "unidad". Token in the header
  Bmx-Token (doc/ejemplos). Limits: 200 historical queries per 5 min, 80 metadata queries per minute (doc/limiteConsultas).
- INEGI BIE (https://www.inegi.org.mx/servicios/api_indicadores.html): GET .../INDICATOR/{id}/{idioma}/{area}/false/
  {fuente}/2.0/{token}?type=json -> {"Header": ..., "Series": [{"INDICADOR", "UNIT", ..., "OBSERVATIONS":
  [{"TIME_PERIOD", "OBS_VALUE", ...}]}]}; catalog method CL_INDICATOR -> {"CODE": [{"value", "Description"}]}. The
  token is a path segment, so every URL that is recorded carries '<token>' in its place.

Coverage by construction: neither API prints a total, so the count of observations the API served is taken from the
raw bytes (occurrences of the observation's date key), apart from the parser, and must equal the entries stored for
that series. Zero served observations is a failure: every request asks for the whole history.
"""
import json
import re
from urllib.parse import quote

BANXICO_DATOS = 'https://www.banxico.org.mx/SieAPIRest/service/v1/series/{series}/datos/{start}/{end}'
BANXICO_META = 'https://www.banxico.org.mx/SieAPIRest/service/v1/series/{series}'
INEGI_INDICATOR = ('https://www.inegi.org.mx/app/api/indicadores/desarrolladores/jsonxml/INDICATOR/{series}/{lang}/{area}/'
                   'false/{fuente}/2.0/{token}?type=json')
INEGI_CATALOG = ('https://www.inegi.org.mx/app/api/indicadores/desarrolladores/jsonxml/CL_INDICATOR/{series}/{lang}/{fuente}/'
                 '2.0/{token}?type=json')
TOKEN_SLOT = '<token>'
DOC_TYPE = 'INDICADOR ECONOMICO'  # fixed: the same category the DOF gives to published calculation values

# A token is only letters, digits and dashes: it can never add a header line, a path segment or a query (Banxico's
# examples are 64 hex characters, INEGI's a UUID).
_TOKEN = re.compile(r'[A-Za-z0-9-]{16,128}')
_SERIES = re.compile(r'[A-Za-z0-9]{1,30}')
_DATE = re.compile(r'[0-9]{1,4}(?:/[0-9]{1,4}){0,2}')  # 'dd/mm/yyyy' (Banxico), 'yyyy/mm' (INEGI, HIPÓTESIS)


def valid_token(token):
    return bool(token) and _TOKEN.fullmatch(token) is not None


def valid_series(series_id):
    return _SERIES.fullmatch(series_id or '') is not None


def redact(text, secret):
    """Every recorded string goes through here: the token never reaches the manifest, the catalog or a log."""
    return text.replace(secret, TOKEN_SLOT) if secret else text


def served_count(body, key):
    """Observations the API served, counted on the raw bytes, independent of the JSON parser: one date key each."""
    return len(re.findall(rb'"' + re.escape(key.encode()) + rb'"\s*:', body))


def _load(body):
    doc = json.loads(body, parse_float=str, parse_int=str)  # numbers stay the literal text the API served
    if not isinstance(doc, dict):
        raise ValueError('the response is not a JSON object')
    return doc


def _str(v):
    return v if isinstance(v, str) else None


def parse_banxico_datos(body, series_id):
    """(titulo, [(fecha, dato)]) for a response to ONE requested series. ValueError on any other shape."""
    series = (_load(body).get('bmx') or {}).get('series')
    if not isinstance(series, list) or len(series) != 1 or not isinstance(series[0], dict):
        raise ValueError('expected exactly one series in bmx.series')
    s = series[0]
    if s.get('idSerie') != series_id:
        raise ValueError(f"served idSerie {s.get('idSerie')!r} is not the requested {series_id}")
    datos = s.get('datos')
    if not isinstance(datos, list):
        raise ValueError('bmx.series[0].datos is not a list')
    return _str(s.get('titulo')), [(_str(d.get('fecha')) if isinstance(d, dict) else None,
                                    _str(d.get('dato')) if isinstance(d, dict) else None) for d in datos]


def parse_banxico_meta(body):
    """{idSerie: {'titulo', 'unidad'}} from GET series/:idSerie, as served."""
    series = (_load(body).get('bmx') or {}).get('series')
    if not isinstance(series, list):
        raise ValueError('bmx.series is not a list')
    return {s['idSerie']: {'titulo': _str(s.get('titulo')), 'unidad': _str(s.get('unidad'))}
            for s in series if isinstance(s, dict) and isinstance(s.get('idSerie'), str)}


def parse_inegi_indicator(body, series_id):
    """(UNIT as served, [(TIME_PERIOD, OBS_VALUE)]) for the requested indicator. ValueError on any other shape."""
    series = _load(body).get('Series')
    if not isinstance(series, list) or len(series) != 1 or not isinstance(series[0], dict):
        raise ValueError('expected exactly one element in Series')
    s = series[0]
    if s.get('INDICADOR') != series_id:
        raise ValueError(f"served INDICADOR {s.get('INDICADOR')!r} is not the requested {series_id}")
    obs = s.get('OBSERVATIONS')
    if not isinstance(obs, list):
        raise ValueError('Series[0].OBSERVATIONS is not a list')
    return _str(s.get('UNIT')), [(_str(o.get('TIME_PERIOD')) if isinstance(o, dict) else None,
                                  _str(o.get('OBS_VALUE')) if isinstance(o, dict) else None) for o in obs]


def parse_inegi_catalog(body, series_id):
    """The official description of the indicator (CL_INDICATOR), or ValueError."""
    code = _load(body).get('CODE')
    match = [c for c in code if isinstance(c, dict) and c.get('value') == series_id] if isinstance(code, list) else []
    if len(match) != 1 or not _str(match[0].get('Description')):
        raise ValueError(f'CL_INDICATOR does not describe {series_id} exactly once')
    return match[0]['Description']


def native_id(series_id, date_printed):
    """series.date with '/' as '-': an identifier only; the date itself is kept verbatim in the observation."""
    if not (isinstance(date_printed, str) and _DATE.fullmatch(date_printed)):
        return None
    return f"{series_id}.{date_printed.replace('/', '-')}"


def banxico_urls(series_id, start, end):
    return BANXICO_DATOS.format(series=series_id, start=start, end=end), BANXICO_META.format(series=series_id)


def inegi_urls(src, series_id, token):
    """(url to request, url to record) for INDICATOR and CL_INDICATOR; the recorded ones carry '<token>'."""
    kw = {'series': series_id, 'lang': src['language'], 'area': src['area'], 'fuente': src['fuente']}
    out = []
    for tpl in (INEGI_INDICATOR, INEGI_CATALOG):
        out.append((tpl.format(**kw, token=quote(token, safe='')), tpl.format(**kw, token=TOKEN_SLOT)))
    return out


def entry(src, country, series_id, title, unit, order, date_printed, value_printed, url, artifact, raw_path, seen_at):
    nid = native_id(series_id, date_printed)
    return {
        'entry_id': f"{src['source_id']}:{nid}", 'country': country, 'source_id': src['source_id'], 'native_id': nid,
        'title': title, 'url': url,
        'category': {**src['category'], 'issuer': src['publisher'], 'section': series_id, 'doc_type': DOC_TYPE},
        'dates': {}, 'listing': {'page_order': order, 'list_marker': series_id},
        'observation': {'series_id': series_id, 'date_printed': date_printed, 'value_printed': value_printed,
                        'unit_printed': unit},
        'raw_status': 'stored', 'raw_path': raw_path, 'artifact': artifact, 'first_seen': seen_at,
        'versions': [{'sha256': artifact['sha256'], 'retrieved_at': artifact['retrieved_at'], 'raw_path': raw_path}],
    }
