"""rg/llamada.py (SECURITY.md T27): every test runs pedir. The network is a stub transport in place of _PublicHTTPS, and
every socket call is a stub that refuses, so no test opens a connection, not even under a mutant. UnaSola scans the repo
for a call with a key written outside pedir."""
import ast
import http.client
import io
import json
import re
import shutil
import socket
import tempfile
import threading
import time
import unittest
import urllib.request
from collections import Counter
from pathlib import Path
from unittest import mock

import yaml

from rg import llamada
from rg.llamada import Rechazo, pedir

KEY = 'nTEST-0000-llave+de/prueba'  # starts with n (the \n escape can swallow it) and holds characters a URL encodes
HOST = 'api.example.com'
URL = 'https://api.example.com/v1/buscar'


class Resp:
    """One answer of the transport: status, headers and a body read with read1, maybe dripping one byte per `goteo` s."""
    length = None  # no Content-Length still due when the body ends (http.client's own count)

    def __init__(self, status=200, body=b'{}', headers=(), goteo=None):
        self.status = self.code = status
        self.reason = self.msg = 'x'
        self.headers = http.client.HTTPMessage()
        for k, v in headers:
            self.headers[k] = v
        self.body, self.goteo, self.leidas, self.closed = body, goteo, 0, False

    def info(self):
        return self.headers

    def read1(self, n=-1):
        self.leidas += 1
        if self.goteo:
            time.sleep(self.goteo)
            return b' '
        out, self.body = self.body[:n], self.body[n:]
        return out
    read = read1

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class Base(unittest.TestCase):
    def setUp(self):
        self.sockets = {}
        for name in ('create_connection', 'getaddrinfo'):
            p = mock.patch(f'socket.{name}', side_effect=OSError('no network in tests'))
            self.sockets[name] = p.start()
            self.addCleanup(p.stop)
        p = mock.patch('urllib.request.getproxies', return_value={})  # no proxy from the environment or the system
        p.start()
        self.addCleanup(p.stop)

    def red(self, *respuestas):
        """Puts a transport that records every request and answers from `respuestas` in place of _PublicHTTPS."""
        pedidas = []

        class Falso(urllib.request.HTTPSHandler):
            def https_open(self, req):
                pedidas.append(req)
                r = respuestas[len(pedidas) - 1]
                return r() if callable(r) else r
        p = mock.patch.object(llamada, '_PublicHTTPS', Falso)
        p.start()
        self.addCleanup(p.stop)
        return pedidas

    def rechazo(self, *args, **kw):
        kw = {'llave': KEY, 'host': HOST, 'plazo': 5, 'tope': 100_000, **kw}
        with self.assertRaises(Rechazo) as c:
            pedir(*args, **kw)
        self.assertIsNone(c.exception.__context__)  # nothing of the answer is chained to it
        return c.exception


class Peticion(Base):
    def test_a_request_outside_the_rules_is_refused_before_anything_is_sent(self):
        casos = {
            'http': (('GET', 'http://api.example.com/v1'), {}),
            'another host': (('GET', 'https://otro.example.com/v1'), {}),
            'a host that ends like it': (('GET', 'https://api.example.com.evil.net/v1'), {}),
            'a user': (('GET', 'https://u@api.example.com/v1'), {}),
            'a port': (('GET', 'https://api.example.com:8443/v1'), {}),
            'a host with a port': (('GET', 'https://api.example.com:8443/v1'), {'host': 'api.example.com:8443'}),
            'an upper-case host': (('GET', 'https://API.example.com/v1'), {'host': 'API.example.com'}),
            'a tab urlsplit drops': (('GET', 'https://api.exam\tple.com/v1'), {}),
            'the key in the URL': (('GET', URL + '?key=' + KEY), {}),
            'the key percent-encoded in the URL': (('GET', URL + '?key=' + KEY.replace('+', '%2B')), {}),
            'the key percent-encoded twice': (('GET', URL + '?key=' + KEY.replace('+', '%252B')), {}),
            'a bracket urlsplit refuses': (('GET', 'https://[api.example.com/v1'), {}),
            'the key in the body': (('POST', URL), {'cuerpo': json.dumps({'k': KEY}).encode()}),
            'no key': (('GET', URL), {'llave': ''}),
            'a key that breaks the header': (('GET', URL), {'llave': 'abc\r\nX-Otra: 1'}),
            'DELETE': (('DELETE', URL), {}),
            'GET with a body': (('GET', URL), {'cuerpo': b'{}'}),
            'no deadline': (('GET', URL), {'plazo': None}),
            'a deadline past the max': (('GET', URL), {'plazo': float('inf')}),
            'no cap': (('GET', URL), {'tope': 0}),
            'no wait on the socket': (('GET', URL), {'espera': 0}),
        }
        for name, (args, kw) in casos.items():
            with self.subTest(name):
                pedidas = self.red(Resp(200, b'{}'))
                self.assertEqual(self.rechazo(*args, **kw).motivo, 'peticion')
                self.assertEqual(pedidas, [])
                self.assertEqual(self.sockets['create_connection'].call_count, 0)

    def test_a_clean_200_returns_its_bytes_and_the_key_went_only_in_authorization(self):
        body = json.dumps({'results': [{'url': 'https://x.org/', 'title': 'nTEST-0000'}]}).encode()
        pedidas = self.red(Resp(200, body), Resp(200, body))
        self.assertEqual(pedir('GET', URL, llave=KEY, host=HOST, plazo=60, tope=1000), body)
        self.assertEqual(pedir('POST', URL, llave=KEY, host=HOST, cuerpo=b'{"q": 1}', plazo=60, tope=1000, espera=30),
                         body)
        for req, metodo, espera in zip(pedidas, ('GET', 'POST'), (llamada.ESPERA, 30)):
            self.assertEqual((req.full_url, req.get_method()), (URL, metodo))
            self.assertEqual(req.get_header('Authorization'), 'Bearer ' + KEY)
            self.assertEqual(req.timeout, espera)  # one wait on the socket, not the whole deadline
        self.assertEqual((pedidas[1].data, pedidas[1].get_header('Content-type')), (b'{"q": 1}', 'application/json'))


class Respuesta(Base):
    def test_a_redirect_is_an_error_and_no_second_request_is_sent(self):
        pedidas = self.red(Resp(302, b'moved', [('Location', 'https://otro.example.net/x')]), Resp(200, b'{}'))
        e = self.rechazo('GET', URL)
        self.assertEqual((e.motivo, e.codigo), ('http', 302))
        self.assertEqual(len(pedidas), 1)

    def test_an_error_or_another_status_is_closed_unread_and_only_its_code_comes_back(self):
        for status in (401, 403, 500, 201, 204):
            with self.subTest(status):
                r = Resp(status, json.dumps({'error': 'bad key ' + KEY}).encode())
                self.red(r)
                e = self.rechazo('GET', URL)
                self.assertEqual((e.motivo, e.codigo, str(e)), ('http', status, f'http {status}'))
                self.assertEqual((r.leidas, r.closed), (0, True))

    def test_an_answer_past_the_cap_is_refused_and_one_at_the_cap_is_not(self):
        self.red(Resp(200, json.dumps('a' * 99).encode()))
        self.assertEqual(self.rechazo('GET', URL, tope=100).motivo, 'tope')
        self.red(Resp(200, json.dumps('a' * 98).encode()))
        self.assertEqual(len(pedir('GET', URL, llave=KEY, host=HOST, plazo=5, tope=100)), 100)

    def test_a_body_cut_before_its_framing_ends_is_refused_and_a_whole_one_is_not(self):
        # a real http.client.HTTPResponse over a socket that only replays these bytes: framing as the library reads it
        cab = b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n'
        for resto, sale in ((b'Content-Length: 100\r\n\r\n{}', None), (b'Content-Length: 2\r\n\r\n{}', b'{}'),
                            (b'Transfer-Encoding: chunked\r\n\r\n2\r\n{}\r\n', None),
                            (b'Transfer-Encoding: chunked\r\n\r\n2\r\n{}\r\n0\r\n\r\n', b'{}')):
            with self.subTest(resto):
                r = http.client.HTTPResponse(mock.Mock(makefile=lambda *a, x=cab + resto: io.BytesIO(x)), method='GET')
                r.begin()
                self.red(r)
                if sale is None:
                    e = self.rechazo('GET', URL)
                    self.assertEqual((e.motivo, e.tipo), ('red', 'IncompleteRead'))
                else:
                    self.assertEqual(pedir('GET', URL, llave=KEY, host=HOST, plazo=5, tope=100), sale)

    def test_a_network_error_carries_only_its_kind(self):
        def falla():
            raise http.client.BadStatusLine('HTTP/1.1 ' + KEY)  # what the server sent, inside the error's message
        self.red(falla)
        e = self.rechazo('GET', URL)
        self.assertEqual((e.motivo, e.tipo), ('red', 'BadStatusLine'))
        self.assertNotIn(KEY, str(e))

    def test_only_public_addresses_are_reached(self):
        # no stub transport here: the real _PublicHTTPS runs, on stub sockets
        for addr, conecta in (('10.0.0.1', False), ('127.0.0.1', False), ('169.254.169.254', False),
                              ('93.184.216.34', True)):
            with self.subTest(addr):
                self.sockets['create_connection'].reset_mock()
                self.sockets['getaddrinfo'].side_effect = None
                self.sockets['getaddrinfo'].return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (addr, 443))]
                self.assertEqual(self.rechazo('GET', URL).motivo, 'red')
                llamadas = self.sockets['create_connection'].call_args_list
                self.assertEqual([c.args[0] for c in llamadas], [(addr, 443)] if conecta else [])


class Plazo(Base):
    def correr(self, **kw):
        """pedir in its own thread: a call that never returns fails the test instead of hanging the suite."""
        got, t0 = [], time.monotonic()

        def uno():
            try:
                got.append(pedir('GET', URL, llave=KEY, host=HOST, **kw))
            except Rechazo as e:
                got.append(e.motivo)
        hilo = threading.Thread(target=uno, daemon=True)
        hilo.start()
        hilo.join(6)
        return got, time.monotonic() - t0

    def test_a_server_that_drips_the_body_or_the_headers_is_cut_at_the_deadline(self):
        suelta = threading.Event()
        self.addCleanup(suelta.set)
        cuerpo = Resp(200, goteo=0.05)
        for name, r in (('body', cuerpo), ('headers', lambda: suelta.wait(30) and Resp(200))):
            with self.subTest(name):
                self.red(r)
                got, dt = self.correr(plazo=1, tope=10_000)
                self.assertEqual(got, ['plazo'])
                self.assertLess(dt, 3)
        time.sleep(0.3)  # past the deadline the reading thread stops at its next chunk and closes the answer
        n = cuerpo.leidas
        time.sleep(0.3)
        self.assertEqual((cuerpo.leidas, cuerpo.closed), (n, True))


class Eco(Base):
    def cuerpo(self, body):
        self.red(Resp(200, body))
        e = self.rechazo('GET', URL, tope=1_000_000)
        self.assertEqual((e.motivo, str(e)), ('eco', 'eco'))

    def test_the_key_as_written_in_the_bytes_even_where_decoding_changes_it(self):
        self.cuerpo(json.dumps({'a': 'x ' + KEY}).encode())
        self.cuerpo(b'{"a": "\\' + KEY.encode() + b'"}')  # decoded, \n takes its first letter: only the bytes hold it

    def test_the_key_escaped(self):
        self.cuerpo(b'{"a": "\\u006e' + KEY[1:].encode() + b'"}')

    def test_the_key_nested_deep(self):
        for n in (5000, 100_000):  # parsed whole by some Pythons, past the decoder in others
            with self.subTest(n):
                self.cuerpo(b'[' * n + b'"\\u006e' + KEY[1:].encode() + b'"' + b']' * n)

    def test_the_key_in_a_repeated_property(self):
        self.assertEqual(json.loads('{"a": "\\u006e' + KEY[1:] + '", "a": "x"}'), {'a': 'x'})  # a parser keeps the last
        self.cuerpo(b'{"a": "\\u006e' + KEY[1:].encode() + b'", "a": "x"}')

    def test_the_key_in_a_property_name(self):
        self.cuerpo(b'{"\\u006e' + KEY[1:].encode() + b'": 1}')

    def test_a_body_that_is_not_json_or_not_utf8_counts_as_an_echo(self):
        for body in (b'<html>hola</html>', b'{"a": 1', b'"\xff"', b'\xef\xbb\xbf{}'):
            with self.subTest(body):
                self.cuerpo(body)


# The owner's order (2026-11-02): no call with a key outside the one function, checked on the code, never on the docs.
CREDENCIAL = re.compile(r'(?i)\b(authorization|bearer|x-api-key|api-key|bmx-token|x-auth-token|private-token)\b')
EN_URL = re.compile(r'(?i)^https?://\S*(\{(token|key|llave|api_?key)\W|[?&;](api_?key|apikey|key|token|access_token)=)')
NOMBRE = re.compile(r'(?i)token|key|llave|secret')  # a value formatted into a URL
ARGUMENTO = {'auth', 'secrets', 'token', 'api_key', 'llave'}  # a credential handed to a call that is not pedir
RED = re.compile(r'\b(curl|wget|Invoke-WebRequest)\b')
CLIENTE = re.compile(r'\b(urllib\.request|http\.client|requests|httpx|urllib3|aiohttp|socket)\b')  # a module that sends
# Callers that predate pedir: the marks the scan finds in each and why each cannot use it yet. A new mark anywhere, or
# one fewer here, fails until this table says so: a migrated caller leaves the list, a new one shows in its diff.
FUERA = {
    'rg/catalog/fetch.py': (1, "2026-11-02: the catalog Fetcher's credential path (auth, secrets), for the next ones"),
    'rg/catalog/indicadores.py': (4, '2026-11-02: INEGI takes its token only as a URL path segment; pedir refuses '
                                     'a key in a URL'),
    'rg/catalog/run.py': (6, '2026-11-02: HF answers with a 302 to a signed CDN and a file streamed to disk (pedir: '
                             'no redirect, JSON in memory); Banxico takes its token in Bmx-Token; INEGI in the path; '
                             "all go through the Fetcher's robots.txt, budget and pace"),
    'rg/descubrir.py': (3, "2026-11-02: Perplexity; main's mutants anchor its own transport (_peticion, _abrir), the "
                           'same guards as pedir, and a move to pedir would drop them'),
    'scripts/automerge.py': (2, "2026-11-02: GitHub's own API with the job's GITHUB_TOKEN (out of scope, as "
                                'secrets.GITHUB_TOKEN in a workflow); it needs PUT'),
    'scripts/consumidor.py': (7, "2026-11-02: GitHub's own API with a read token, run by the consumer: it imports "
                                 'no RG module by design'),
    'scripts/sondear_inegi.py': (3, '2026-11-02: INEGI takes its token only as a URL path segment'),
}


def _ambiente(n):
    """The name of the environment variable `n` reads when it is written out: os.environ[...], .get(...), os.getenv."""
    if isinstance(n, ast.Subscript) and ast.unparse(n.value) == 'os.environ':
        x = n.slice
    elif isinstance(n, ast.Call) and ast.unparse(n.func) in ('os.environ.get', 'os.getenv') and n.args:
        x = n.args[0]
    else:
        return ''
    return x.value if isinstance(x, ast.Constant) and isinstance(x.value, str) else ''


def con_llave(raiz):
    """{path: marks} where code could call an API with a key outside rg/llamada.py. Python under rg/ and scripts/
    (docstrings aside; scripts/mutar.py holds code as text): a string naming a credential header or scheme, a URL that
    carries a key, a credential argument to a call other than pedir, a key formatted into a URL, a key read from the
    environment by a module that imports an HTTP client. Shell under scripts/ and every workflow step: curl or wget with
    a credential in reach (a workflow's GITHUB_TOKEN aside)."""
    marcas = Counter()
    for p in sorted([*(raiz / 'rg').rglob('*.py'), *(raiz / 'scripts').rglob('*.py')]):
        rel = p.relative_to(raiz).as_posix()
        if rel in ('rg/llamada.py', 'scripts/mutar.py'):
            continue
        arbol = ast.parse(p.read_text(encoding='utf-8'))
        docs = {id(n.value) for n in ast.walk(arbol) if isinstance(n, ast.Expr)}
        cliente = any(isinstance(n, (ast.Import, ast.ImportFrom)) and CLIENTE.search(ast.unparse(n))
                      for n in ast.walk(arbol))
        for n in ast.walk(arbol):
            marcas[rel] += bool(cliente and NOMBRE.search(_ambiente(n)))
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs:
                marcas[rel] += bool(CREDENCIAL.search(n.value) or EN_URL.search(n.value))
            elif isinstance(n, ast.Call) and getattr(n.func, 'attr', getattr(n.func, 'id', None)) != 'pedir':
                marcas[rel] += sum(k.arg in ARGUMENTO for k in n.keywords)
            elif isinstance(n, ast.JoinedStr) and n.values and isinstance(n.values[0], ast.Constant) \
                    and re.match('https?://', n.values[0].value):
                marcas[rel] += sum(isinstance(v, ast.FormattedValue) and bool(NOMBRE.search(ast.unparse(v.value)))
                                   for v in n.values)
    for p in sorted((raiz / 'scripts').glob('*.sh')):
        marcas[p.relative_to(raiz).as_posix()] += sum(
            bool(RED.search(x) and (CREDENCIAL.search(x) or NOMBRE.search(x))) for x in p.read_text().splitlines()
            if not x.lstrip().startswith('#'))
    for p in sorted((raiz / '.github' / 'workflows').glob('*.yml')):
        flujo = yaml.safe_load(p.read_text(encoding='utf-8'))
        for job in (flujo.get('jobs') or {}).values():
            for paso in job.get('steps') or []:
                alcance = json.dumps([flujo.get('env'), job.get('env'), paso.get('env'), paso.get('run')])
                secretos = set(re.findall(r'secrets\.(\w+)', alcance)) - {'GITHUB_TOKEN'}
                marcas[p.relative_to(raiz).as_posix()] += bool(RED.search(paso.get('run') or '') and secretos)
    return {k: n for k, n in sorted(marcas.items()) if n}


class UnaSola(unittest.TestCase):
    RAIZ = Path(__file__).resolve().parents[1]

    def test_no_call_with_a_key_outside_pedir_but_the_dated_list(self):
        self.assertEqual(con_llave(self.RAIZ), {k: n for k, (n, _) in FUERA.items()})

    def test_a_call_with_a_key_written_anywhere_else_fails_the_scan(self):
        falsos = {
            'rg/a.py': "import urllib.request\nR = urllib.request.Request(U, headers={'X-Api-Key': k})\n",
            'rg/catalog/b.py': "import requests\nR = requests.get(f'https://api.x.org/v1?api_key={k}')\n",
            'scripts/c.py': 'R = Fetcher([H]).get(u, auth=t)\n',
            'scripts/d.py': "import urllib.request\nR = urllib.request.urlopen(f'https://api.x.org/{token}/x')\n",
            'scripts/h.py': "import os, urllib.request\nK = os.environ['X_API_KEY']\n",
            'scripts/e.sh': '#!/bin/bash\ncurl -sS -H "X-Api-Key: $API_KEY" https://api.x.org/v1\n',
            '.github/workflows/f.yml': yaml.safe_dump({'on': 'push', 'jobs': {'j': {'runs-on': 'x', 'steps': [
                {'env': {'K': '${{ secrets.OTRA }}'}, 'run': 'curl -H "Authorization: Bearer $K" https://api.x.org'},
                {'env': {'GH_TOKEN': '${{ secrets.GITHUB_TOKEN }}'}, 'run': 'curl -H "Bearer $GH_TOKEN" x'}]}}}),
            'rg/g.py': '"""Authorization: Bearer, in prose only."""\nfrom rg.llamada import pedir\n'
                       "R = pedir('GET', U, llave=k, host=H, plazo=5, tope=9)\n",  # what is allowed: no mark
        }
        with tempfile.TemporaryDirectory() as d:
            raiz = Path(d)
            for x in ('rg', 'scripts', '.github/workflows'):
                shutil.copytree(self.RAIZ / x, raiz / x, ignore=shutil.ignore_patterns('__pycache__'))
            for rel, texto in falsos.items():
                (raiz / rel).write_text(texto, encoding='utf-8')
            with open(raiz / 'rg/descubrir.py', 'a', encoding='utf-8') as f:  # one more inside a file of the list
                f.write("\nOTRA = {'Authorization': 'x'}\n")
            got = con_llave(raiz)
        esperado = {k: n for k, (n, _) in FUERA.items()}
        self.assertNotEqual(got, esperado)  # the repo test above fails on this tree
        nuevos = {k: 1 for k in falsos if k != 'rg/g.py'}
        self.assertEqual(got, {**esperado, **nuevos, 'rg/descubrir.py': esperado['rg/descubrir.py'] + 1})


if __name__ == '__main__':
    unittest.main()
