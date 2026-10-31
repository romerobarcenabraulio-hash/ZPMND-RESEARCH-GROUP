"""rg/sondeo.py and .github/workflows/sondeo.yml: every registered source says how much it holds, in its own words,
through the catalog's Fetcher with its own hosts; nothing is guessed, nothing reaches another source's host."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from rg import sondeo
from rg.catalog.fetch import FetchRefused, Response

ROOT = Path(__file__).resolve().parents[1]
GOOD = {'source_id': 'int.ejemplo', 'status': 'candidate', 'subarea': 'I01', 'clase': 'api', 'title': 'Ejemplo',
        'publisher': 'Quien', 'base_url': 'https://ejemplo.org', 'allowed_hosts': ['ejemplo.org', 'api.ejemplo.org'],
        'alcance': 'Mundo', 'license': 'CC0', 'via': 'api',
        'contador': {'tipo': 'json', 'url': 'https://api.ejemplo.org/obras', 'ruta': ['meta', 'count'], 'unidad': 'obras'}}


def doc(*fuentes, familia='I'):
    return {'familia': familia, 'nombre': 'I. Ciencia', 'fuentes': list(fuentes)}


class Registro(unittest.TestCase):
    def test_the_registry_in_the_repo_loads(self):
        fuentes = sondeo.cargar(ROOT / 'sources' / 'registro')
        self.assertTrue(fuentes)
        mx = json.loads((ROOT / 'sources' / 'mx.json').read_text(encoding='utf-8'))
        catalogo = {s['source_id'] for k in ('sources', 'secondary_sources') for s in mx.get(k, [])}
        self.assertFalse(catalogo & {f['source_id'] for _, f in fuentes})  # one id names one source in all of RG

    def test_a_good_source_has_no_errors(self):
        self.assertEqual(sondeo.errores(doc(GOOD), 'I'), [])

    def test_every_broken_rule_is_named(self):
        def bad(change, letra='I'):
            f = copy.deepcopy(GOOD); change(f)
            return sondeo.errores(doc(f), letra)
        cases = {
            'familia': lambda: sondeo.errores(doc(GOOD, familia='J'), 'I'),
            'title missing': lambda: bad(lambda f: f.pop('title')),
            'source_id': lambda: bad(lambda f: f.update(source_id='Sin Punto')),
            'subarea': lambda: bad(lambda f: f.update(subarea='J01')),
            'clase': lambda: bad(lambda f: f.update(clase='rumor')),
            'via missing': lambda: bad(lambda f: f.pop('via')),
            'via': lambda: bad(lambda f: f.update(via='telepatia')),
            'host names': lambda: bad(lambda f: f.update(allowed_hosts=['https://ejemplo.org'])),
            'base_url must be https': lambda: bad(lambda f: f.update(base_url='http://ejemplo.org')),
            'base_url host': lambda: bad(lambda f: f.update(base_url='https://otro.org')),
            'tipo': lambda: bad(lambda f: f['contador'].update(tipo='regex')),
            'url host': lambda: bad(lambda f: f['contador'].update(url='https://otro.org/x')),
            'url https': lambda: bad(lambda f: f['contador'].update(url='http://api.ejemplo.org/x')),
            'unidad': lambda: bad(lambda f: f['contador'].pop('unidad')),
            'ruta bool': lambda: bad(lambda f: f['contador'].update(ruta=['meta', True])),
            'literal short': lambda: bad(lambda f: f.update(contador={'tipo': 'contar', 'url': 'https://ejemplo.org/i',
                                                                     'marca': '<idx', 'literal': 'ab', 'unidad': 'x'})),
            'marca missing': lambda: bad(lambda f: f.update(contador={'tipo': 'contar', 'url': 'https://ejemplo.org/i',
                                                                     'literal': '<entry>', 'unidad': 'x'})),
            'medida': lambda: bad(lambda f: f['contador'].update(medida='suma')),
            'ruta empty without longitud': lambda: bad(lambda f: f['contador'].update(ruta=[])),
            'longitud without registro': lambda: bad(lambda f: f['contador'].update(medida='longitud')),
        }
        for name, run in cases.items():
            with self.subTest(name):
                self.assertTrue(run(), name)
        self.assertTrue(any('repeated' in e for e in sondeo.errores(doc(GOOD, GOOD), 'I')))

    def test_a_source_in_two_files_or_a_broken_file_stops_the_load(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'I.json').write_text(json.dumps(doc(GOOD)))
            (Path(d) / 'J.json').write_text(json.dumps(doc({**GOOD, 'subarea': 'J01'}, familia='J')))
            with self.assertRaises(SystemExit) as e:
                sondeo.cargar(d)
            self.assertIn('more than one file', str(e.exception))
            (Path(d) / 'J.json').write_text('{')
            with self.assertRaises(SystemExit):
                sondeo.cargar(d)


class Leer(unittest.TestCase):
    J = {'tipo': 'json', 'ruta': ['meta', 'count']}

    def test_a_whole_number_at_the_path(self):
        for body, want in ((b'{"meta": {"count": 42}}', 42), (b'{"meta": {"count": "1,234,567"}}', 1234567),
                           (b'{"meta": {"count": "7"}}', 7)):
            self.assertEqual(sondeo.leer(body, self.J), want)
        self.assertEqual(sondeo.leer(b'[{"total": 9}]', {'tipo': 'json', 'ruta': [0, 'total']}), 9)
        self.assertEqual(sondeo.leer(b'[1, 2, {"n": 3}]', {'tipo': 'json', 'ruta': [-1, 'n']}), 3)

    def test_anything_else_is_not_a_count(self):
        for body in (b'{"meta": {"count": true}}', b'{"meta": {"count": -1}}', b'{"meta": {"count": 1.5}}',
                     b'{"meta": {"count": "12a"}}', b'{"meta": {}}', b'{"meta": []}', b'[]'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                sondeo.leer(body, self.J)
        with self.assertRaises(ValueError):
            sondeo.leer(b'[1]', {'tipo': 'json', 'ruta': [5]})

    C = {'tipo': 'contar', 'marca': '<rfc-index', 'literal': '<rfc-entry>'}

    def test_contar_counts_records_only_inside_the_expected_document(self):
        self.assertEqual(sondeo.leer(b'<?xml?><rfc-index><rfc-entry>a</rfc-entry><rfc-entry>b</rfc-entry></rfc-index>', self.C), 2)

    def test_a_page_that_is_not_the_document_or_holds_no_record_is_never_a_measured_zero(self):
        # GPT on bff3bed: a maintenance page or a challenge served with 200 would have published valor 0
        for body in (b'<html><body>Under maintenance</body></html>', b'', b'<rfc-index></rfc-index>',
                     b'<html><p>Example: <rfc-entry>x</rfc-entry></p></html>'):  # the record text, but not the document
            with self.subTest(body=body), self.assertRaises(ValueError):
                sondeo.leer(body, self.C)

    def test_longitud_counts_records_that_carry_the_declared_key(self):
        L = {'tipo': 'json', 'ruta': ['licenses'], 'medida': 'longitud', 'registro': 'licenseId'}
        self.assertEqual(sondeo.leer(b'{"licenses": [{"licenseId": "MIT"}, {"licenseId": "0BSD"}]}', L), 2)
        E = {**L, 'ruta': [], 'registro': 'cik_str'}
        self.assertEqual(sondeo.leer(b'{"0": {"cik_str": 1}, "1": {"cik_str": 2}}', E), 2)
        # GPT on ee5296e: an error object or an empty answer served with 200 is not a count of anything
        for body, c in ((b'{"error": "maintenance"}', E), (b'{}', E), (b'{"0": {"ticker": "X"}}', E),
                        (b'{"licenses": [{"licenseId": "MIT"}, "x"]}', L), (b'{"licenses": []}', L),
                        (b'{"licenses": 5}', L), (b'<html>', L)):
            with self.subTest(body=body), self.assertRaises(ValueError):
                sondeo.leer(body, c)

    def test_zero_is_never_the_size_of_a_source(self):
        with self.assertRaises(ValueError):
            sondeo.leer(b'{"meta": {"count": 0}}', self.J)


class Sondear(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def fetcher(self, answers):
        test = self

        class F:
            def __init__(self, hosts, cap):
                test.calls.append((tuple(hosts), cap)); self.hosts = hosts

            def get(self, url):
                a = answers[url]
                if isinstance(a, Exception):
                    raise a
                return Response(status=a[0], body=a[1], url=url)
        return F

    def run_(self, fuentes, answers):
        return sondeo.sondear(fuentes, self.fetcher(answers), ahora=lambda: '2026-10-30T00:00:00Z')

    def test_each_source_is_measured_with_its_own_hosts_and_cap(self):
        other = {**GOOD, 'source_id': 'int.otro', 'allowed_hosts': ['otro.org'], 'base_url': 'https://otro.org'}
        other.pop('contador')
        res = self.run_([('I', other), ('I', GOOD)], {'https://api.ejemplo.org/obras': (200, b'{"meta": {"count": 5}}'),
                                                      'https://otro.org': (200, b'<html>')})
        self.assertEqual([r['source_id'] for r in res], ['int.ejemplo', 'int.otro'])  # sorted
        self.assertEqual((res[0]['estado'], res[0]['valor'], res[0]['unidad']), ('medido', 5, 'obras'))
        self.assertEqual(res[1]['estado'], 'accesible')
        self.assertNotIn('valor', res[1])  # no count is ever guessed
        self.assertEqual(self.calls, [(('ejemplo.org', 'api.ejemplo.org'), 5_000_000), (('otro.org',), 5_000_000)])

    def test_a_failure_is_that_sources_result_and_never_the_runs(self):
        url = GOOD['contador']['url']
        for answer, estado in (((404, b''), 'http'), ((204, b''), 'http'), (FetchRefused('robots.txt disallows'), 'rechazado'),
                               (OSError('secret-host 10.0.0.1'), 'error'), ((200, b'not json'), 'ilegible'),
                               ((200, b'[' * 100000 + b']' * 100000), 'ilegible')):
            with self.subTest(estado=estado, answer=str(answer)[:30]):
                r = self.run_([('I', GOOD)], {url: answer})[0]
                self.assertEqual(r['estado'], estado)
                if estado == 'error':
                    self.assertEqual(r['error'], 'OSError')  # its kind only

    def test_the_default_fetcher_is_the_catalogs_with_the_sources_hosts(self):
        made = []

        class Rec:
            def __init__(self, hosts, **kw):
                made.append((hosts, kw))

            def get(self, url):
                return Response(status=200, body=b'{"meta": {"count": 1}}', url=url)
        with mock.patch.object(sondeo, 'Fetcher', Rec):
            sondeo.sondear([('I', GOOD), ('I', {**GOOD, 'source_id': 'int.ejemplo2'})])
        self.assertEqual(made[0][0], GOOD['allowed_hosts'])
        self.assertIs(made[0][1]['compartido'], made[1][1]['compartido'])  # one pause per host for the whole run
        self.assertEqual((made[0][1]['budget'], made[0][1]['max_bytes']), (6, 5_000_000))
        self.assertIn('deadline', made[0][1])  # no request of the Fetcher starts past the run's deadline either

    def test_past_the_deadline_nothing_is_asked_and_what_was_measured_is_saved_after_every_source(self):
        # GPT on bff3bed: a run cut by the job's limit lost everything it had measured
        others = [{**GOOD, 'source_id': f'int.ejemplo{i}'} for i in range(3)]
        now, saved = [0.0], []

        def reloj():
            now[0] += 10
            return now[0]
        res = sondeo.sondear([('I', f) for f in others], self.fetcher({GOOD['contador']['url']: (200, b'{"meta": {"count": 1}}')}),
                             ahora=lambda: 't', plazo=15, reloj=reloj, guardar=lambda r: saved.append([x['estado'] for x in r]))
        self.assertEqual([r['estado'] for r in res], ['medido', 'pendiente', 'pendiente'])
        self.assertEqual(saved, [['medido'], ['medido', 'pendiente'], ['medido', 'pendiente', 'pendiente']])
        self.assertEqual(len(self.calls), 1)

    def test_sources_of_one_host_share_its_pause_and_its_robots_txt(self):
        # GPT on ee5296e: a new Fetcher per source forgot the last request to a host shared with the previous source
        from rg.catalog.fetch import Fetcher
        from tests.test_catalog import FakeOpener
        robots = b'User-agent: *\nCrawl-delay: 5\n'
        opener = FakeOpener({'https://ejemplo.org/robots.txt': (200, robots, {}), 'https://ejemplo.org/a': (200, b'a', {}),
                             'https://ejemplo.org/b': (200, b'b', {})})
        slept, shared = [], {}
        mk = lambda: Fetcher(['ejemplo.org'], opener=opener, clock=lambda: 100.0, sleep=slept.append, compartido=shared)
        mk().get('https://ejemplo.org/a')
        mk().get('https://ejemplo.org/b')
        self.assertEqual([u for u, _ in opener.calls].count('https://ejemplo.org/robots.txt'), 1)
        self.assertIn(5.0, slept)  # the second source waited the site's Crawl-delay after the first

    def test_an_empty_registry_never_publishes_a_complete_run(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(SystemExit):
            sondeo.main(['--registro', d, '--out', str(Path(d) / 'out.json')])

    def test_the_command_writes_the_results_and_a_summary(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'I.json').write_text(json.dumps(doc(GOOD)))
            out = Path(d) / 'out.json'
            seen = []

            def fake(f, guardar):
                res = [{'source_id': x['source_id'], 'familia': l, 'estado': 'pendiente'} for l, x in f]
                guardar(res); seen.append(json.loads(out.read_text()))  # on disk after the first source already
                return [{**r, 'estado': 'medido'} for r in res]
            with mock.patch.object(sondeo, 'sondear', fake):
                self.assertEqual(sondeo.main(['--registro', d, '--out', str(out)]), 0)
            self.assertFalse(seen[0]['completo'])
            got = json.loads(out.read_text())
            self.assertTrue(got['completo'])
            self.assertEqual(got['resumen'], {'I': {'fuentes': 1, 'medidas': 1, 'accesibles': 0, 'pendientes': 0, 'fallidas': 0, 'vias': {'?': 1}}})

    def test_every_result_carries_the_sources_fastest_route_and_the_summary_counts_them(self):
        res = sondeo.sondear([('I', GOOD)], self.fetcher({GOOD['contador']['url']: (200, b'{"meta": {"count": 1}}')}))
        self.assertEqual(res[0]['via'], 'api')
        self.assertEqual(sondeo.resumen(res)['I']['vias'], {'api': 1})
        for letra, f in sondeo.cargar(ROOT / 'sources' / 'registro'):
            self.assertIn(f['via'], sondeo.VIAS, f['source_id'])


class Workflow(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / '.github' / 'workflows' / 'sondeo.yml').read_text(encoding='utf-8')
        self.wf = yaml.safe_load(self.text)
        self.job = self.wf['jobs']['sondeo']

    def test_mains_code_only_by_schedule_or_dispatch_with_no_secret(self):
        on = self.wf.get('on') or self.wf[True]
        self.assertEqual(set(on), {'schedule', 'workflow_dispatch'})
        self.assertEqual(self.job['if'], "github.ref == 'refs/heads/main'")
        self.assertEqual((self.wf['permissions'], self.job['permissions']), ({}, {'contents': 'write'}))
        self.assertNotIn('secrets.', self.text)
        checkout = self.job['steps'][0]
        self.assertEqual((checkout['with']['ref'], checkout['with']['persist-credentials']), ('main', False))

    def test_tests_run_first_and_the_token_reaches_only_the_push_to_sondeo(self):
        names = [s.get('name', s.get('run', '')) for s in self.job['steps']]
        self.assertLess(names.index('Tests of the sounding before any source is asked'), names.index('Ask every registered source'))
        holders = [s for s in self.job['steps'] if 'github.token' in json.dumps(s)]
        self.assertEqual([s['name'] for s in holders], ['Commit the result to the data branch'])
        run = holders[0]['run']
        self.assertIn('git push -q origin HEAD:sondeo', run)
        self.assertEqual(run.count('git push'), 1)
        self.assertNotIn('${{', run)
        self.assertEqual(holders[0]['if'], 'always()')  # a run cut short still publishes what it measured
        ask = next(s for s in self.job['steps'] if s.get('name') == 'Ask every registered source')
        self.assertLess(ask['timeout-minutes'] * 60, self.job['timeout-minutes'] * 60)
        self.assertLess(sondeo.PLAZO, ask['timeout-minutes'] * 60)


if __name__ == '__main__':
    unittest.main()
