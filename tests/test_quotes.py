"""T2/T3: a quote must exist verbatim in the hashed raw of an artifact it cites (catches invented quotes)."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from rg.quotes import check


def packet_with(quote, body=b'It can support more than 100 working languages.\n'):
    sha = hashlib.sha256(body).hexdigest()
    art = {'artifact_id': 'SA-x01', 'sha256': sha, 'media_type': 'text/plain'}
    return {'artifacts': [art], 'findings': {'confirmed': [{'claim': 'c', 'artifact_ids': ['SA-x01'], 'quote': quote}],
                                             'conflicting': []}}, sha, body


class Quotes(unittest.TestCase):
    def _run(self, quote, tamper=False):
        p, sha, body = packet_with(quote)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'sha256' / sha[:2] / f'{sha}.txt'
            path.parent.mkdir(parents=True)
            path.write_bytes(body + (b'x' if tamper else b''))
            return check(p, d)

    def test_verbatim_quote_passes_with_whitespace_folded(self):
        self.assertEqual(self._run('support more than   100 working\nlanguages'), [])

    def test_invented_or_altered_quote_fails(self):
        self.assertTrue(self._run('It can support more than 200 working languages.'))

    def test_tampered_raw_fails(self):
        self.assertTrue(self._run('more than 100 working languages', tamper=True))


if __name__ == '__main__':
    unittest.main()
