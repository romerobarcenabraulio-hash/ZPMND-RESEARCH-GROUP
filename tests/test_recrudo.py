"""rg.recrudo: the gate downloads again the raws a packet cites and does not keep, checks their sha256 and reads the
quotes there (docs/NORTE.md hueco 3, SECURITY T29). Built here (CONSTRUIDO): tests/test_investigar.py's two-host web
behind a fake opener, a metadata_only packet rg.investigar builds from it, then that web changing, refusing or stalling.
"""
import hashlib
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from rg import investigar as inv
from rg import packets, recrudo
from tests.test_catalog import FakeOpener
from tests.test_investigar import A_CLOSED, A_PAGE, CLOSED, CLOSED_BODY, PAGE, PLAN, ROUTES, RR, SHA_PAGE, answer

NOTA, CERRADO = 'https://a.gob.mx/nota', 'https://b.example.org/cerrado.json'
SOURCES = [{**PLAN['sources'][0], 'redistribution': 'metadata_only'}, {**CLOSED, 'role': 'primary'}]
FINDING = {'claim': 'El dataset es cerrado.', 'artifact_ids': [A_CLOSED], 'quote': '"cerrado": true, "detalle": "solo citable"',
           'locator': 'raíz'}


def metadata_only_packet(tmp, findings=None):
    rows = inv.fetch({**PLAN, 'sources': SOURCES}, tmp / 'run', opener=FakeOpener(dict(ROUTES)), sleep=lambda s: None)
    ans = answer()
    ans['findings']['confirmed'] = findings or [ans['findings']['confirmed'][0], FINDING]
    return inv.assemble(RR, rows, ans, tmp / 'run', tmp / 'out', 'm', '2026-10-23T00:00:00Z')


def opener_with(before):
    """The fake web, running `before(url)` first: a stall, a crash, a look at the receipt."""
    o = FakeOpener(dict(ROUTES))
    real = o.open
    o.open = lambda req, timeout=None: (before(req.full_url), real(req, timeout))[1]
    return o


class Recrudo(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.folder, self.recibo, self.n = metadata_only_packet(self.tmp), self.tmp / 'citas.jsonl', 0

    def edit(self, fn):
        packet = json.loads((self.folder / 'packet.json').read_text(encoding='utf-8'))
        fn(packet)
        (self.folder / 'packet.json').write_text(json.dumps(packet), encoding='utf-8')

    def gate(self, routes=None, opener=None, **kw):
        self.n += 1
        self.work, self.opener = self.tmp / f'work{self.n}', opener or FakeOpener({**ROUTES, **(routes or {})})
        with open(self.recibo, 'w', encoding='utf-8') as fh:
            got = recrudo.verificar(self.folder, self.work, fh, opener=self.opener, sleep=lambda s: None, **kw)
        self.lines = [json.loads(x) for x in self.recibo.read_text(encoding='utf-8').splitlines()]
        return got

    def outcomes(self):
        return [(x.get('artefacto') or x['cita'], x['estado'], x.get('motivo')) for x in self.lines]

    def test_every_quote_is_read_in_its_raw_downloaded_again_and_the_receipt_holds_no_url_or_text(self):
        problems, warnings, stats = self.gate()
        self.assertEqual((problems, warnings, stats['quotes_verified'], stats['citas']), ([], [], 2, {'verificada': 2}))
        self.assertEqual(self.outcomes(), [(A_PAGE, 'sha_coincide', None), (A_CLOSED, 'sha_coincide', None),
                                           ('confirmed[0]', 'verificada', None), ('confirmed[1]', 'verificada', None)])
        self.assertFalse((self.folder / 'raw').exists())  # nothing beside the packet
        self.assertEqual(len(list((self.work / 'raw').rglob('*.bin'))), 2)
        for leak in ('a.gob.mx', 'example', 'patrón', 'citable'):
            self.assertNotIn(leak, self.recibo.read_text(encoding='utf-8'))
        self.assertEqual({u.split('/')[2] for u, _ in self.opener.calls}, {'a.gob.mx', 'b.example.org'})

    def test_bytes_that_changed_are_sha_distinto_deleted_at_once_and_never_a_pass(self):
        changed = PAGE.replace(b'Norma', b'NORMA')
        _, warnings, stats = self.gate({NOTA: (200, changed, {'Content-Type': 'text/html'})})
        self.assertEqual((stats['citas'], len(warnings)), ({'sha_distinto': 1, 'verificada': 1}, 1))
        self.assertEqual((self.lines[0]['sha256'], self.lines[0]['bytes']), (hashlib.sha256(changed).hexdigest(), len(PAGE)))
        self.assertEqual([f.name for f in self.work.rglob('*') if f.is_file()], [f'{hashlib.sha256(CLOSED_BODY).hexdigest()}.bin'])
        _, _, stats = self.gate({NOTA: (200, PAGE + b'x', {'Content-Type': 'text/html'})})  # cut at its declared size
        self.assertEqual((self.outcomes()[0], stats['citas']), ((A_PAGE, 'sha_distinto', 'mayor'), {'sha_distinto': 1, 'verificada': 1}))

    def test_what_the_fetcher_refuses_is_no_descargable_with_its_reason(self):
        for routes, motivo in (({'https://a.gob.mx/robots.txt': (200, b'User-agent: *\nDisallow: /nota\n', {})}, 'rechazada'),
                               ({NOTA: (302, b'', {'Location': 'https://c.example.com/x'})}, 'rechazada'),  # outside the hosts
                               ({NOTA: (404, b'', {})}, 'http')):
            with self.subTest(motivo):
                _, warnings, stats = self.gate(routes)
                self.assertEqual((self.outcomes()[0], stats['citas']), ((A_PAGE, 'no_descargable', motivo),
                                                                        {'no_descargable': 1, 'verificada': 1}))
        self.edit(lambda p: p['artifacts'][0].update(url='http://a.gob.mx/nota'))
        self.gate()
        self.assertEqual(self.outcomes()[0], (A_PAGE, 'no_descargable', 'rechazada'))

    def test_rights_limits_and_the_deadline_are_decided_before_any_request(self):
        for patch, want in ((('MAX_ARTIFACTS', 0), 'tope'), (('MAX_BYTES', 10), 'tope'), (('MAX_TOTAL', 10), 'tope'),
                            (('PLAZO', 0), 'plazo')):
            with self.subTest(patch), mock.patch.object(recrudo, *patch):
                self.gate()
                self.assertEqual([x[1:] for x in self.outcomes()[:2]], [('no_descargable', want)] * 2)
                self.assertEqual((self.opener.calls, self.work.exists()), ([], False))  # not even a thread or a file
        with mock.patch.object(recrudo, 'MAX_TOTAL', len(PAGE)):  # the first one spends what is left
            self.gate()
            self.assertEqual([x[1:] for x in self.outcomes()[:2]], [('sha_coincide', None), ('no_descargable', 'tope')])
        self.edit(lambda p: p['artifacts'][0].update(redistribution='unknown'))
        self.gate()
        self.assertEqual((self.outcomes()[0], {u.split('/')[2] for u, _ in self.opener.calls}),
                         ((A_PAGE, 'no_descargable', 'derechos'), {'b.example.org'}))

    def test_a_server_that_never_finishes_or_breaks_costs_only_its_own_artifact(self):
        release = threading.Event()
        self.addCleanup(release.set)
        with mock.patch.object(recrudo, 'PER_ARTIFACT', 0.3):
            start = time.monotonic()
            _, _, stats = self.gate(opener=opener_with(lambda url: url == NOTA and release.wait(10)))
        self.assertLess(time.monotonic() - start, 5)
        self.assertEqual((self.outcomes()[0], stats['citas']), ((A_PAGE, 'no_descargable', 'plazo'), {'no_descargable': 1, 'verificada': 1}))
        _, _, stats = self.gate(opener=opener_with(lambda url: url == NOTA and 1 / 0))
        self.assertEqual((self.outcomes()[0], stats['citas']), ((A_PAGE, 'no_descargable', 'error'), {'no_descargable': 1, 'verificada': 1}))

    def test_each_artifact_is_in_the_receipt_before_the_next_one_is_asked(self):
        seen = []
        self.gate(opener=opener_with(lambda url: url == CERRADO and seen.append(self.recibo.read_text(encoding='utf-8'))))
        self.assertIn(A_PAGE, seen[0])

    def test_kept_raws_unquoted_artifacts_and_an_invalid_packet_are_never_asked(self):
        kept = inv.assemble(RR, inv.fetch(PLAN, self.tmp / 'k', opener=FakeOpener(dict(ROUTES)), sleep=lambda s: None),
                            answer(), self.tmp / 'k', self.tmp / 'kout', 'm', '2026-10-23T00:00:00Z')
        unquoted, opener = metadata_only_packet(self.tmp / 'u', findings=[FINDING]), FakeOpener(dict(ROUTES))
        self.assertEqual(recrudo.bajar(kept, self.tmp / 'w1', opener=opener), {})
        self.assertEqual(recrudo.bajar(unquoted, self.tmp / 'w2', opener=opener, sleep=lambda s: None), {A_CLOSED: 'sha_coincide'})
        self.edit(lambda p: p.update(status='VERIFIED'))
        self.assertEqual(recrudo.bajar(self.folder, self.tmp / 'w3', opener=opener), {})
        self.assertEqual({u.split('/')[2] for u, _ in opener.calls}, {'b.example.org'})

    def test_a_quote_its_raw_does_not_hold_is_cita_ausente_and_no_extraction_starts_after_the_deadline(self):
        self.edit(lambda p: p['findings']['confirmed'][1].update(quote='una cita que no está en el crudo'))
        problems, _, stats = self.gate()
        self.assertEqual((len(problems), stats['citas']), (1, {'verificada': 1, 'cita_ausente': 1}))
        citas = {}
        packets.check(self.folder, [self.work / 'raw'], citas, deadline=0.0)
        self.assertEqual(citas, {'confirmed[0]': 'sin_texto', 'confirmed[1]': 'sin_texto'})
        self.assertTrue((self.work / 'raw' / 'sha256' / SHA_PAGE[:2] / f'{SHA_PAGE}.bin').is_file())


if __name__ == '__main__':
    unittest.main()
