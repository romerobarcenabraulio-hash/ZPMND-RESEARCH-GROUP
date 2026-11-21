"""rg.recrudo (SECURITY T29): test_investigar's two-host web behind a fake opener, changing, refusing or stalling."""
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
    o = FakeOpener(dict(ROUTES))
    real = o.open
    o.open = lambda req, timeout=None: (before(req.full_url), real(req, timeout))[1]
    return o


class Recrudo(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
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
        seen = []  # the receipt as the second artifact is asked: the first one is already on disk
        problems, warnings, stats = self.gate(opener=opener_with(lambda url: url == CERRADO and seen.append(self.recibo.read_text(encoding='utf-8'))))
        self.assertEqual((problems, warnings, stats['quotes_verified'], stats['citas']), ([], [], 2, {'verificada': 2}))
        self.assertEqual(self.outcomes(), [(A_PAGE, 'sha_coincide', None), (A_CLOSED, 'sha_coincide', None),
                                           ('confirmed[0]', 'verificada', None), ('confirmed[1]', 'verificada', None)])
        self.assertFalse((self.folder / 'raw').exists())  # nothing beside the packet
        self.assertEqual(len(list((self.work / 'raw').rglob('*.bin'))), 2)
        self.assertEqual([w for w in ('a.gob.mx', 'example', 'patrón', 'citable') if w in self.recibo.read_text(encoding='utf-8')], [])
        self.assertEqual({u.split('/')[2] for u, _ in self.opener.calls}, {'a.gob.mx', 'b.example.org'})
        self.assertIn(A_PAGE, seen[0])

    def test_bytes_that_changed_are_sha_distinto_deleted_at_once_and_never_a_pass(self):
        changed = PAGE.replace(b'Norma', b'NORMA')
        _, warnings, stats = self.gate({NOTA: (200, changed, {'Content-Type': 'text/html'})})
        self.assertEqual((stats['citas'], len(warnings)), ({'sha_distinto': 1, 'verificada': 1}, 1))
        self.assertEqual((self.lines[0]['sha256'], self.lines[0]['bytes']), (hashlib.sha256(changed).hexdigest(), len(PAGE)))
        self.assertEqual([f.name for f in self.work.rglob('*') if f.is_file()], [f'{hashlib.sha256(CLOSED_BODY).hexdigest()}.bin'])
        _, _, stats = self.gate({NOTA: (200, PAGE + b'x', {'Content-Type': 'text/html'})})  # cut at its declared size
        self.assertEqual((self.outcomes()[0], stats['citas']), ((A_PAGE, 'sha_distinto', 'mayor'), {'sha_distinto': 1, 'verificada': 1}))
        self.assertEqual([f.name for f in (self.work / 'raw').rglob('*') if f.is_file()], [f'{hashlib.sha256(CLOSED_BODY).hexdigest()}.bin'])

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
        with mock.patch.object(recrudo, 'check', return_value=([], [], {})) as ck:
            self.gate()
        self.assertGreater(ck.call_args.args[3], time.monotonic())  # one plazo for downloads and extraction (GPT on 333a2cc)

    def test_a_server_that_never_finishes_gets_no_second_request_while_its_thread_lives(self):
        release, asked = threading.Event(), []
        self.addCleanup(release.set)
        with mock.patch.object(recrudo, 'PER_ARTIFACT', 0.3):
            start = time.monotonic()
            _, _, stats = self.gate(opener=opener_with(lambda url: asked.append(url) or (url == NOTA and release.wait(10))))
        self.assertLess(time.monotonic() - start, 5)
        self.assertEqual(self.outcomes()[:2], [(A_PAGE, 'no_descargable', 'plazo'), (A_CLOSED, 'no_descargable', 'ocupado')])
        self.assertEqual((stats['citas'], [u for u in asked if 'b.example.org' in u]), ({'no_descargable': 2}, []))
        release.set()
        _, _, stats = self.gate()  # a new run (a new Comun) is not held by the old one's threads
        self.assertEqual(stats['citas'], {'verificada': 2})

    def test_one_comun_carries_the_pause_and_robots_across_the_packets_of_a_head(self):
        t, seen = [0.0], []
        def sleep(s):
            t[0] += s
        o = opener_with(lambda url: seen.append((url, t[0])))
        comun = recrudo.Comun()
        for n in (1, 2):  # the same packet twice stands for two packets of one head citing the same hosts
            recrudo.verificar(self.folder, self.tmp / f'w{n}', None, None, comun, opener=o, clock=lambda: t[0], sleep=sleep)
        robots = [u for u, _ in seen if u.endswith('/robots.txt')]
        self.assertEqual(sorted(robots), sorted(set(robots)))  # robots.txt read once per host in the whole run
        for host in ('a.gob.mx', 'b.example.org'):
            times = [x for u, x in seen if u.split('/')[2] == host]
            self.assertGreater(len(times), 2)
            self.assertTrue(all(b - a >= 1.0 for a, b in zip(times, times[1:])), (host, times))
        _, _, stats = self.gate(opener=opener_with(lambda url: url == NOTA and 1 / 0))
        self.assertEqual((self.outcomes()[0], stats['citas']), ((A_PAGE, 'no_descargable', 'error'), {'no_descargable': 1, 'verificada': 1}))

    def test_a_sealed_copy_from_r2_is_read_instead_of_the_host_and_a_wrong_one_is_not(self):
        uh = hashlib.sha256(NOTA.encode()).hexdigest()  # where abrir_sellados.sh opens R2's copy of this URL's bytes
        f = self.tmp / 'sellados' / 'sha256' / SHA_PAGE[:2] / SHA_PAGE / uh / f'{SHA_PAGE}.html'
        f.parent.mkdir(parents=True)
        f.write_bytes(PAGE)
        f.with_suffix('.url').write_text('https://otro.example.com/copia')  # fetched elsewhere: never this artifact's bytes
        comun, changed = recrudo.Comun(), {NOTA: (200, PAGE.replace(b'Norma', b'NORMA'), {'Content-Type': 'text/html'})}
        comun.sellados = self.tmp / 'sellados'
        _, _, stats = self.gate(changed, comun=comun)
        self.assertEqual(stats['citas'], {'sha_distinto': 1, 'verificada': 1})
        f.with_suffix('.url').write_text(NOTA)
        _, _, stats = self.gate(changed, comun=comun)  # the host now serves other bytes: only the sealed ones verify
        self.assertEqual((stats['citas'], self.lines[0]['origen']), ({'verificada': 2}, 'sellado'))
        self.assertNotIn(NOTA, [u for u, _ in self.opener.calls])
        with mock.patch.object(recrudo, 'MAX_TOTAL', len(PAGE)):  # a sealed copy spends T29's budget like a download
            self.gate(changed, comun=comun)
        self.assertEqual(self.outcomes()[1], (A_CLOSED, 'no_descargable', 'tope'))
        f.write_bytes(PAGE + b'x')  # a copy that is not the declared bytes is never read: the raw is asked again
        _, _, stats = self.gate(changed, comun=comun)
        self.assertEqual((stats['citas'], self.outcomes()[0]), ({'sha_distinto': 1, 'verificada': 1}, (A_PAGE, 'sha_distinto', None)))

    def test_kept_raws_unquoted_artifacts_and_an_invalid_packet_are_never_asked(self):
        kept = inv.assemble(RR, inv.fetch(PLAN, self.tmp / 'k', opener=FakeOpener(dict(ROUTES)), sleep=lambda s: None),
                            answer(), self.tmp / 'k', self.tmp / 'kout', 'm', '2026-10-23T00:00:00Z')
        unquoted, opener = metadata_only_packet(self.tmp / 'u', findings=[FINDING]), FakeOpener(dict(ROUTES))
        self.assertEqual(recrudo.bajar(kept, self.tmp / 'w1', None, float('inf'), opener=opener), {})
        self.assertEqual(recrudo.bajar(unquoted, self.tmp / 'w2', None, float('inf'), opener=opener, sleep=lambda s: None), {A_CLOSED: 'sha_coincide'})
        self.edit(lambda p: p.update(status='VERIFIED'))
        self.assertEqual(recrudo.bajar(self.folder, self.tmp / 'w3', None, float('inf'), opener=opener), {})
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
