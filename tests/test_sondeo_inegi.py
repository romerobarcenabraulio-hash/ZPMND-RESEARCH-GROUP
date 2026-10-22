"""scripts/sondear_inegi.py: every documented request shape is tried, and the token never reaches the output."""
import importlib.util
import unittest
from pathlib import Path
from urllib.parse import quote

import yaml

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('sondear_inegi', ROOT / 'scripts' / 'sondear_inegi.py')
sondeo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sondeo)
TOKEN = 'tok-0123456789abcdef'


class FakeFetcher:
    def __init__(self):
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        from rg.catalog.fetch import Response
        return Response(400, f'["ErrorInfo:No se encontraron resultados {TOKEN}"]'.encode(), url)


class Probe(unittest.TestCase):
    def test_every_documented_shape_is_tried_and_the_token_never_printed(self):
        lines, fake = [], FakeFetcher()
        sondeo.probe(['628194'], TOKEN, fetcher=fake, out=lines.append)
        self.assertEqual(len(fake.urls), 8)  # 3 areas x 2 fuentes for INDICATOR, 2 fuentes for CL_INDICATOR
        self.assertTrue(any('/628194/es/0700/false/BIE/' in u for u in fake.urls))
        self.assertTrue(any('/CL_INDICATOR/628194/es/BISE/' in u for u in fake.urls))
        self.assertTrue(all(u.startswith('https://www.inegi.org.mx/') and TOKEN in u for u in fake.urls))
        self.assertTrue(lines and not any(TOKEN in line for line in lines))
        self.assertTrue(all('<token>' in line for line in lines))

    def test_a_token_cut_by_the_length_limit_is_never_printed(self):
        # GPT review of #23: redacting after cutting at 400 bytes could print the start of a reflected token.
        class Straddle(FakeFetcher):
            def get(self, url):
                from rg.catalog.fetch import Response
                return Response(400, (' ' * 390 + TOKEN + ' ' * 10).encode(), url)
        lines = []
        sondeo.probe(['628194'], TOKEN, fetcher=Straddle(), out=lines.append)
        self.assertFalse(any(TOKEN[:8] in line for line in lines))

    def test_a_refusal_that_names_the_url_never_prints_the_token(self):
        # GPT review of #23 (c236293): no fake raised FetchRefused, so dropping the redaction of its message went unseen.
        class Refuses(FakeFetcher):
            def get(self, url):
                from rg.catalog.fetch import FetchRefused
                raise FetchRefused(f'{url} is disallowed by robots.txt')  # the token sits inside the 160 characters shown
        lines = []
        sondeo.probe(['628194'], TOKEN, fetcher=Refuses(), out=lines.append)
        self.assertTrue(lines and all(line.startswith('refused ') for line in lines))
        self.assertFalse(any(TOKEN in line for line in lines))

    def test_a_token_reflected_url_encoded_is_never_printed(self):
        # GPT review of #23 (c236293): TOKEN reads the same quoted, so dropping the quoted form went unseen.
        odd = 'tok/+ =0123456789'
        self.assertNotEqual(quote(odd, safe=''), odd)

        class Encoded(FakeFetcher):
            def get(self, url):
                from rg.catalog.fetch import Response
                return Response(400, f'no results for {quote(odd, safe="")}'.encode(), url)
        lines = []
        sondeo.probe(['628194'], odd, fetcher=Encoded(), out=lines.append)
        self.assertFalse(any(quote(odd, safe='') in line or odd in line for line in lines))

    def test_the_real_fetcher_binds_the_token_to_inegi_only(self):
        f = sondeo.make_fetcher(TOKEN, 8)
        self.assertEqual(f.allowed_hosts, {'www.inegi.org.mx'})
        self.assertEqual(f.secrets, {TOKEN: 'www.inegi.org.mx'})

    def test_no_token_stops_before_any_request(self):
        fake = FakeFetcher()
        with self.assertRaises(SystemExit):
            sondeo.probe(['628194'], '', fetcher=fake, out=lambda _: None)
        self.assertEqual(fake.urls, [])


class Workflow(unittest.TestCase):
    def test_read_only_and_the_ids_are_validated(self):
        doc = yaml.safe_load((ROOT / '.github' / 'workflows' / 'sondeo-inegi.yml').read_text(encoding='utf-8'))
        self.assertEqual(doc['permissions'], {'contents': 'read'})
        steps = doc['jobs']['probe']['steps']
        with_token = [s for s in steps if 'INEGI_TOKEN' in str(s.get('env', ''))]
        self.assertEqual(len(with_token), 1)
        self.assertIn('[[ "$SERIES" =~ ^[0-9]+( [0-9]+){0,4}$ ]]', with_token[0]['run'])


if __name__ == '__main__':
    unittest.main()
