"""The one way to call an API with a key (SECURITY.md T27). Every call that carries a key must use `pedir`:
tests/test_llamada.py scans rg/, scripts/ and the workflows and fails on one written anywhere else, but for a dated list
of older callers that cannot use it yet, a list that only shrinks. The audits of #86 (Perplexity), #89 (OpenAlex), #91
and #93 (NVIDIA) found the same holes again and again in each script's own defenses; here they are closed once:

- https only, to exactly the host the caller fixes (a lower-case name: no user, password or port), the URL in visible
  ASCII; GET or POST; the key goes only in `Authorization: Bearer`: a URL that holds it (as written or percent-decoded,
  as many times as decoding changes it) or a body that holds its bytes is refused before anything is sent;
- no redirect is followed (a 3xx is an error) and the socket opens only to a public address: the catalog's own
  `_NoRedirect` and `_PublicHTTPS` (rg/catalog/fetch.py; through HTTPS_PROXY the proxy's policy decides);
- the body is read as it arrives (read1) and refused past `tope` bytes; the whole request, opening, headers, chunk framing
  and body, ends within `plazo` seconds in a thread of its own, whatever the server drips (rg/descubrir.py's pattern);
  past the deadline the thread stops after its next chunk; one stuck in the headers is left behind, its answer unread;
  one wait on the socket lasts `espera` s at most (10 by default; an API that answers only when done passes more);
- a body that ends before its Content-Length or its last chunk is refused like any network error (IncompleteRead);
- an HTTP error, and any status other than 200, is closed unread (its body can echo the key) and reported by its code;
- a 200 is returned only when it does not hold the key: not in its bytes, and not in any JSON string literal of the raw
  text (a property name or a value), each decoded on its own, so no nesting depth, repeated property or escape hides it;
  a body that is not UTF-8 or not valid JSON (nested past what the decoder reads included) counts as holding it;
- every refusal is a `Rechazo` carrying a fixed reason, an HTTP code or an error's kind, never the answer's text, and
  the answer's headers never reach the caller.

Residual: a key split across two literals or re-encoded inside one (base64, HTML entities) is not seen; a body framed
only by the connection's close (neither Content-Length nor chunked) cannot be told from one cut short, it must still be
whole JSON; the callers on the scan's list keep their own guards until they are migrated.
"""
import json
import re
import threading
import urllib.error
import urllib.request
from urllib.parse import unquote, urlsplit

from rg.catalog.fetch import _NoRedirect, _PublicHTTPS
from rg.sondeo import HOST  # a lower-case DNS name

ESPERA = 10  # seconds one wait on the socket may last
TROZO = 64 * 1024  # bytes asked per read1
PLAZO_MAX = 3600
METODOS = ('GET', 'POST')
USER_AGENT = 'ZPMND-RESEARCH-GROUP/llamada'
VISIBLE = re.compile(r'[\x21-\x7e]+')  # no space, control or non-ASCII character: nothing a parser could drop or split
CADENA = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"', re.S)  # a JSON string literal: in valid JSON every other '"' opens one


class Rechazo(Exception):
    """pedir returned no body. `motivo` is 'peticion' (the request is not allowed and was not sent), 'http' (`codigo` is
    the status), 'tope', 'plazo', 'red' (`tipo` is the error's kind) or 'eco'. Nothing the server sent travels in it."""

    def __init__(self, motivo, codigo=None, tipo=None):
        super().__init__(' '.join(str(x) for x in (motivo, codigo, tipo) if x is not None))
        self.motivo, self.codigo, self.tipo = motivo, codigo, tipo


def _comprobar(metodo, url, llave, host, cuerpo, plazo, tope, espera):
    if not isinstance(url, str) or not VISIBLE.fullmatch(url):
        raise Rechazo('peticion', tipo='url')
    if not isinstance(llave, str) or not VISIBLE.fullmatch(llave):
        raise Rechazo('peticion', tipo='llave')
    try:
        p = urlsplit(url)
    except ValueError:  # a bracket that is not an IPv6 address
        p = None
    if p is None:
        raise Rechazo('peticion', tipo='url')
    if p.scheme != 'https':
        raise Rechazo('peticion', tipo='https')
    if not isinstance(host, str) or not HOST.fullmatch(host):
        raise Rechazo('peticion', tipo='host')
    if p.netloc != host:
        raise Rechazo('peticion', tipo='host')
    vista = url
    while llave not in vista and unquote(vista) != vista:  # %252B is %2B once decoded: decoded until nothing changes
        vista = unquote(vista)
    if llave in vista:
        raise Rechazo('peticion', tipo='llave en la url')
    if metodo not in METODOS or (cuerpo is not None and (metodo != 'POST' or not isinstance(cuerpo, bytes))):
        raise Rechazo('peticion', tipo='metodo')
    if cuerpo is not None and llave.encode() in cuerpo:
        raise Rechazo('peticion', tipo='llave en el cuerpo')
    if not (isinstance(plazo, (int, float)) and 0 < plazo <= PLAZO_MAX and isinstance(tope, int) and tope > 0):
        raise Rechazo('peticion', tipo='plazo o tope')
    if not (isinstance(espera, (int, float)) and 0 < espera <= PLAZO_MAX):
        raise Rechazo('peticion', tipo='espera')


def _peticion(req, plazo, tope, espera, alto):
    """{'cuerpo': bytes} of a whole 200, {'codigo': status} of anything else (never read), {'motivo': 'tope'} or
    {'tipo': 'IncompleteRead'}."""
    try:
        r = urllib.request.build_opener(_NoRedirect, _PublicHTTPS).open(req, timeout=min(plazo, espera))
    except urllib.error.HTTPError as e:  # 3xx, 4xx, 5xx: its body is never read, it can echo the key
        e.close()
        return {'codigo': e.code}
    with r:
        if r.status != 200:
            return {'codigo': r.status}
        cuerpo = bytearray()
        while not alto.is_set() and (trozo := r.read1(TROZO)):
            cuerpo += trozo
            if len(cuerpo) > tope:
                return {'motivo': 'tope'}
        if r.length:  # read1 returns b'' at EOF with bytes of the Content-Length still due (a cut chunk raises itself)
            return {'tipo': 'IncompleteRead'}
        return {'cuerpo': bytes(cuerpo)}


def _abrir(req, plazo, tope, espera):
    out, alto = {}, threading.Event()

    def trabajo():
        try:
            out.update(_peticion(req, plazo, tope, espera, alto))
        except BaseException as e:  # noqa: BLE001 - only its kind leaves the thread: a message can carry what was sent
            out['tipo'] = type(e).__name__
    hilo = threading.Thread(target=trabajo, daemon=True)
    hilo.start()
    hilo.join(plazo)
    if hilo.is_alive():
        alto.set()
        raise Rechazo('plazo')
    if 'codigo' in out:
        raise Rechazo('http', codigo=out['codigo'])
    if 'cuerpo' not in out:
        raise Rechazo(out.get('motivo', 'red'), tipo=out.get('tipo'))
    return out['cuerpo']


def _eco(cuerpo, llave):
    if llave.encode() in cuerpo:
        return True
    try:
        texto = cuerpo.decode('utf-8')
        json.loads(texto)
    except (ValueError, RecursionError):  # not UTF-8, not JSON, or nested past the decoder: it cannot be read whole
        return True
    return any(llave in json.loads(m.group()) for m in CADENA.finditer(texto))


def pedir(metodo, url, *, llave, host, cuerpo=None, plazo, tope, espera=ESPERA):
    """The bytes of a 200 from `url` on `host` that does not echo `llave`; anything else raises Rechazo. `cuerpo` (bytes,
    POST only) is sent as application/json; the answer must be JSON."""
    _comprobar(metodo, url, llave, host, cuerpo, plazo, tope, espera)
    cabeceras = {'Authorization': f'Bearer {llave}', 'Accept': 'application/json', 'Accept-Encoding': 'identity',
                 'User-Agent': USER_AGENT}
    if cuerpo is not None:
        cabeceras['Content-Type'] = 'application/json'
    respuesta = _abrir(urllib.request.Request(url, data=cuerpo, method=metodo, headers=cabeceras), plazo, tope, espera)
    if _eco(respuesta, llave):
        raise Rechazo('eco')
    return respuesta
