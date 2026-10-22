"""SCJN tesis from the Hugging Face dataset (secondary source): parser, verbatim mapping, download guards, coverage.

Fixtures are real: tests/fixtures/hf_tesis_scjn_sample.json holds five points copied byte for byte from the dataset
file at revision f233341 (byte ranges in its "rg_fixture" key), and hf_tesis_scjn_api_2026-10-21.json is the Hub API
answer of that day. No network: a fake opener plays huggingface.co and its CDN.
"""
import hashlib
import http.client
import io
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import yaml

from rg.catalog import hf_tesis
from rg.catalog.fetch import Fetcher, FetchRefused, FileSink
from rg.catalog.run import Run, quarantine, recategorize
from rg.catalog.store import Catalog
from rg.schemas import validate
from tests.test_catalog import FIX, FakeOpener, FakeResp

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = (FIX / 'hf_tesis_scjn_sample.json').read_bytes()
API_FIX = json.loads((FIX / 'hf_tesis_scjn_api_2026-10-21.json').read_bytes())
SID = 'mx.hf-tesis-scjn'
DATASET, FILE = 'ayaxrojo/tesis_scjn_v5_complete', 'tesis_scjn_v5_complete.json'
REV = API_FIX['sha']
HF, CDN = 'https://huggingface.co', 'https://us.aws.cdn.hf.co'
API = hf_tesis.API_URL.format(dataset=DATASET)
RESOLVE = hf_tesis.RESOLVE_URL.format(dataset=DATASET, revision=REV, file=FILE)
SIGNED = CDN + '/xet-bridge-us/abc?X-Amz-Signature=SECRETSIG&Key-Pair-Id=K1'
ROBOTS_HF = (200, b'User-agent: *\nAllow: /\n\nSitemap: https://huggingface.co/sitemap.xml\n', {})  # 2026-10-21
ROBOTS_CDN = (404, b'', {})  # us.aws.cdn.hf.co, 2026-10-21: no robots.txt = allowed
CLOUDFRONT_403 = (403, b'<?xml version="1.0" encoding="UTF-8"?><Error><Code>MissingKey</Code><Message>Missing '
                       b'Key-Pair-Id query parameter or cookie value</Message></Error>', {})  # cas-bridge.xethub.hf.co


def consistent(raw=SAMPLE):
    """The excerpt with total_points set to its own number of points (the file's own value is 59678)."""
    return raw.replace(b'"total_points": 59678', b'"total_points": 5', 1)


def api_body(file_bytes, license_='cc-by-4.0', sha=None):
    """The real API answer, with sha256 and size of the file the fake CDN serves."""
    meta = json.loads(json.dumps(API_FIX))
    lfs = next(s for s in meta['siblings'] if s['rfilename'] == FILE)['lfs']
    lfs['sha256'], lfs['size'] = sha or hashlib.sha256(file_bytes).hexdigest(), len(file_bytes)
    meta['cardData']['license'] = license_
    return json.dumps(meta).encode()


def points():
    return json.loads(SAMPLE)['points']


def construido(point, **metadata):
    """CONSTRUIDO: a copy of a real point with some metadata fields replaced (e.g. the rubro blanked), for the rows of
    run 39691250207 that print no rubro or no registro digital (the excerpt has none)."""
    p = json.loads(json.dumps(point))
    p['payload']['metadata'].update(metadata)
    return p


def body_of(ps):
    return json.dumps({'total_points': len(ps), 'points': ps}, ensure_ascii=False).encode('utf-8')


class Parser(unittest.TestCase):
    def test_real_excerpt_reads_like_json_loads(self):
        header = {}
        got = list(hf_tesis.iter_points(io.BytesIO(SAMPLE), header, chunk=4096))
        doc = json.loads(SAMPLE)
        self.assertEqual(got, doc['points'])
        self.assertEqual({k: header[k] for k in ('collection', 'total_points')}, {'collection': 'tesis_scjn_v5', 'total_points': 59678})
        self.assertEqual(header['rg_fixture']['revision'], REV)

    def test_a_number_cut_by_a_chunk_boundary_is_never_taken_short(self):
        body = b'{"total_points": 59678, "points": [{"id": 1}, 2.5e-05], "after": 12345}'
        for chunk in range(1, len(body) + 1):
            header = {}
            self.assertEqual(list(hf_tesis.iter_points(io.BytesIO(body), header, chunk=chunk)), [{'id': 1}, 2.5e-05], chunk)
            self.assertEqual((header['total_points'], header['after']), (59678, 12345), chunk)

    def test_one_value_larger_than_the_cap_stops_the_read(self):
        with self.assertRaises(ValueError):
            list(hf_tesis.iter_points(io.BytesIO(SAMPLE), {}, chunk=4096, max_value=10_000))

    def test_malformed_cut_or_trailing_data_is_an_error(self):
        for body in (b'{"points": [1, }', b'{"points": []} x', SAMPLE[:200_000], b'[1, 2]', b'{1: 2}'):
            with self.subTest(body=body[:20]), self.assertRaises(ValueError):
                list(hf_tesis.iter_points(io.BytesIO(body), {}, chunk=1000))


class Mapping(unittest.TestCase):
    def setUp(self):
        reg = json.loads((ROOT / 'sources' / 'mx.json').read_text(encoding='utf-8'))
        self.src = next(s for s in reg['sources'] if s['source_id'] == SID)
        self.art = {'artifact_id': 'SA-' + 'a' * 24, 'url': RESOLVE, 'retrieved_at': '2026-10-21T00:00:00Z', 'sha256': 'a' * 64,
                    'bytes': 1, 'media_type': 'application/json', 'source_type': self.src['source_type'],
                    'publisher': self.src['publisher'], 'license': self.src['license'],
                    'redistribution': self.src['redistribution'], 'stored_at': 'local_corpus'}

    def entries(self):
        return [hf_tesis.to_entry(self.src, 'MX', p, i, self.art, 'sha256/aa/' + 'a' * 64 + '.json', '2026-10-21T00:00:00Z')
                for i, p in enumerate(points(), 1)]

    def test_fields_are_copied_verbatim_and_valid(self):
        es = {e['native_id']: e for e in self.entries()}
        self.assertEqual(list(es), ['160971', '160972', '2006839', '2021168', '2009327'])
        for e in es.values():
            self.assertEqual(validate('catalog_entry', e), [], e['native_id'])
        a, j = es['160971'], es['2021168']
        self.assertTrue(a['title'].startswith('VISITAS DOMICILIARIAS. LA FACULTAD DEL DIRECTOR DE AUDITORÍA FISCAL'))
        self.assertEqual(a['url'], 'https://sjf2.scjn.gob.mx/detalle/tesis/160971')
        self.assertEqual((a['category']['edition'], a['category']['section'], a['category']['issuer'], a['category']['doc_type']),
                         ('Novena Época', 'Administrativa', 'Tribunales Colegiados de Circuito', 'TESIS AISLADA'))
        self.assertEqual((a['listing']['list_marker'], a['listing']['type_printed']), ('III.4o.(III Región) 53 A', 'Aislada'))
        self.assertEqual(a['dates'], {})  # 'fuente' prints "Septiembre de 2011": month and year only, never a date
        self.assertNotIn('branch', a['category'])  # the row does not print the branch: "(sin dato en la fuente)"
        self.assertEqual((j['category']['issuer'], j['category']['doc_type'], j['dates']),
                         ('Plenos de Circuito', 'JURISPRUDENCIA', {'published': '2019-11-29'}))
        self.assertEqual(es['2006839']['dates'], {'published': '2014-06-27'})
        self.assertIn('Libro 72, Noviembre de 2019', j['listing']['listing_text'])

    def test_doc_type_comes_from_a_fixed_table_over_the_printed_type(self):
        self.assertEqual([hf_tesis.doc_type(t) for t in ('Aislada', ' JURISPRUDENCIA ', 'jurisprudencia', 'Precedente', None)],
                         ['TESIS AISLADA', 'JURISPRUDENCIA', 'JURISPRUDENCIA', 'OTRO', 'OTRO'])

    def test_only_a_real_printed_publication_date_becomes_a_date(self):
        p = hf_tesis.published
        self.assertEqual(p('Esta tesis se publicó el viernes 05 de junio de 2015 a las 09:30 horas en el Semanario'), '2015-06-05')
        self.assertEqual(p('Esta tesis se publicó el lunes 5 de junio de 2017 a las 10:00 horas'), '2017-06-05')
        self.assertIsNone(p('Esta tesis se publicó el viernes 31 de febrero de 2014 a las 09:30 horas'))
        self.assertIsNone(p('Esta tesis se publicó el viernes 27 de juniembre de 2014'))
        self.assertIsNone(p('Semanario Judicial de la Federación y su Gaceta. Tomo XXXIV, Septiembre de 2011'))
        self.assertIsNone(p(''))

    def entry(self, point):
        return hf_tesis.to_entry(self.src, 'MX', point, 1, self.art, 'sha256/aa/' + 'a' * 64 + '.json', '2026-10-21T00:00:00Z')

    def test_only_a_row_without_rubro_or_registro_is_uncitable(self):
        self.assertEqual([hf_tesis.uncitable(e) for e in self.entries()], [None] * 5)
        p = points()[0]
        cases = [(construido(p, rubro=''), 'without_rubro'),                     # CONSTRUIDO: rubro blanked
                 (construido(p, rubro=' \n\t '), 'without_rubro'),               # CONSTRUIDO: blank after normalising
                 (construido(p, registro_digital=''), 'without_registro'),       # CONSTRUIDO: registro blanked
                 (construido(p, registro_digital='', rubro=''), 'without_registro'),  # CONSTRUIDO: counted once
                 (construido(p, registro_digital='1000'), None)]                 # CONSTRUIDO: a small registro stays
        self.assertEqual([hf_tesis.uncitable(self.entry(q)) for q, _ in cases], [why for _, why in cases])
        small = self.entry(cases[-1][0])
        self.assertEqual((small['entry_id'], validate('catalog_entry', small)), (f'{SID}:1000', []))

    def test_only_a_qdrant_id_names_an_uncatalogued_row(self):
        ps = points()
        self.assertEqual([hf_tesis.point_id(p) for p in ps[:3]], [160971, 160972, '07e52232-7046-4331-8512-f74b3c96cbcf'])
        rubro = ps[0]['payload']['metadata']['rubro']
        for odd in ({'id': rubro}, {'id': True}, {'id': -1}, {'id': None}, {}, 'x', None, {'id': ps[2]['id'].upper()}):
            self.assertIsNone(hf_tesis.point_id(odd), odd if not isinstance(odd, dict) else str(odd)[:40])

    def test_recategorize_recomputes_the_type_from_the_printed_one(self):
        e = self.entries()[3]
        e['category']['doc_type'] = 'OTRO'
        recategorize([e])
        self.assertEqual(e['category']['doc_type'], 'JURISPRUDENCIA')

    def test_sixty_thousand_rows_are_split_below_the_github_file_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            cat = Catalog(tmp, 'MX')
            for e in self.entries():
                cat.upsert(e)
            cat.write()
            files = sorted(p.relative_to(Path(tmp) / 'mx').as_posix() for p in (Path(tmp) / 'mx').rglob('*.jsonl'))
            self.assertEqual(files, ['hf-tesis-scjn/0016.jsonl', 'hf-tesis-scjn/0200.jsonl', 'hf-tesis-scjn/0202.jsonl'])
            # the parts are catalog rows (not a derived view): the next run loads exactly what was written
            self.assertEqual(Catalog(tmp, 'MX').entries, cat.entries)


class FetcherCredentialsAndSink(unittest.TestCase):
    def fetcher(self, routes, **kw):
        self.opener = FakeOpener(routes)
        return Fetcher(['huggingface.co', 'us.aws.cdn.hf.co'], opener=self.opener, clock=lambda: 0.0, sleep=lambda s: None, **kw)

    def auth_of(self, url):
        return [dict((k.lower(), v) for k, v in h.items()).get('authorization') for u, h in self.opener.calls if u == url]

    def test_the_credential_never_follows_a_redirect_to_another_host(self):
        f = self.fetcher({HF + '/robots.txt': ROBOTS_HF, CDN + '/robots.txt': ROBOTS_CDN,
                          HF + '/same': (302, b'', {'Location': HF + '/here'}), HF + '/here': (302, b'', {'Location': SIGNED}),
                          SIGNED: (200, b'bytes', {})})
        self.assertEqual(f.get(HF + '/same', auth='Bearer t0k').body, b'bytes')
        self.assertEqual(self.auth_of(HF + '/same') + self.auth_of(HF + '/here'), ['Bearer t0k', 'Bearer t0k'])
        self.assertEqual(self.auth_of(SIGNED) + self.auth_of(HF + '/robots.txt') + self.auth_of(CDN + '/robots.txt'), [None, None, None])

    def test_body_streams_to_disk_with_its_hash_and_its_own_cap(self):
        body = b'x' * 3_000_000  # over max_bytes: only the sink may hold it
        f = self.fetcher({HF + '/robots.txt': ROBOTS_HF, HF + '/big': (200, body, {})}, max_bytes=1000)
        with tempfile.TemporaryDirectory() as tmp:
            sink = FileSink(Path(tmp) / 'f.part', len(body))
            r = f.get(HF + '/big', sink=sink)
            self.assertEqual((r.status, r.body, sink.bytes, sink.sha256), (200, b'', len(body), hashlib.sha256(body).hexdigest()))
            self.assertEqual(sink.path.read_bytes(), body)
            with self.assertRaises(FetchRefused):
                f.get(HF + '/big', sink=FileSink(Path(tmp) / 'g.part', len(body) - 1))

    def test_a_cut_body_is_downloaded_again_from_zero(self):
        body = b'0123456789' * 300_000

        class CutOnce(FakeOpener):
            cut = True

            def open(self, req, timeout=None):
                if req.full_url == HF + '/big' and CutOnce.cut:
                    CutOnce.cut = False
                    self.calls.append((req.full_url, {}))
                    resp = FakeResp(200, body[:1_500_000])
                    real = resp.read

                    def read(n=-1):
                        data = real(n)
                        if not data:
                            raise http.client.IncompleteRead(b'')
                        return data
                    resp.read = read
                    return resp
                return super().open(req, timeout)
        f = Fetcher(['huggingface.co'], opener=CutOnce({HF + '/robots.txt': ROBOTS_HF, HF + '/big': (200, body, {})}),
                    clock=lambda: 0.0, sleep=lambda s: None, retries=1)
        with tempfile.TemporaryDirectory() as tmp:
            sink = FileSink(Path(tmp) / 'f.part', len(body))
            self.assertEqual(f.get(HF + '/big', sink=sink).status, 200)
            self.assertEqual((sink.bytes, sink.sha256), (len(body), hashlib.sha256(body).hexdigest()))
            self.assertEqual(sink.path.read_bytes(), body)


class Download(unittest.TestCase):
    """run_hf_tesis against a fake huggingface.co + CDN."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = mock.patch.dict(os.environ, {'HF_TOKEN': 't0k-secret'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.run_ = Run('MX', self.tmp.name + '/out', self.tmp.name + '/raw', None, date(2026, 10, 22), 0, 0)
        self.src = next(s for s in self.run_.registry['sources'] if s['source_id'] == SID)
        self.calls = []  # every request of every run of this test
        self.serve(consistent())

    def serve(self, file_bytes, api=None, cdn_robots=ROBOTS_CDN):
        self.routes = {HF + '/robots.txt': ROBOTS_HF, CDN + '/robots.txt': cdn_robots,
                       API: (200, api or api_body(file_bytes), {'content-type': 'application/json; charset=utf-8'}),
                       RESOLVE: (302, b'', {'Location': SIGNED}), SIGNED: (200, file_bytes, {})}

    def go(self):
        opener = FakeOpener(self.routes)
        opener.calls = self.calls
        f = Fetcher(self.src['allowed_hosts'], opener=opener, clock=lambda: 0.0, sleep=lambda s: None, retries=0)
        self.run_._fetcher = lambda s: f
        return self.run_.run_hf_tesis(self.src)

    def fetched(self, url):
        return sum(1 for c in self.calls if c[0] == url)

    def failed(self):
        return [c for c in self.run_.manifest['coverage'] if not c['ok']]

    def entries(self):
        return {e['native_id']: e for e in self.run_.catalog.snapshot(SID)}

    def test_every_row_is_catalogued_with_the_file_as_its_raw(self):
        stats = self.go()
        sha = hashlib.sha256(consistent()).hexdigest()
        es = self.entries()
        self.assertEqual(len(es), 5)
        self.assertEqual(self.failed(), [])
        self.assertEqual((stats['rows_read'], stats['distinct'], stats['downloaded']), (5, 5, True))
        e = es['2021168']
        self.assertEqual((e['artifact']['sha256'], e['artifact']['url'], e['artifact']['bytes']), (sha, RESOLVE, len(consistent())))
        self.assertEqual((e['artifact']['license'], e['artifact']['redistribution'], e['artifact']['source_type']),
                         (self.src['license'], 'allowed', 'dataset'))
        self.assertEqual((Path(self.tmp.name) / 'raw' / e['raw_path']).read_bytes(), consistent())
        self.assertEqual(self.run_.raw.new_files, [e['raw_path']])
        self.assertEqual([p.name for p in (Path(self.tmp.name) / 'raw').iterdir()], ['sha256'])  # no .part left behind
        for x in es.values():
            self.assertEqual(validate('catalog_entry', x), [])
        heads = {u: {k.lower(): v for k, v in h.items()} for u, h in self.calls}
        self.assertEqual(heads[RESOLVE].get('authorization'), 'Bearer t0k-secret')
        self.assertNotIn('authorization', heads[SIGNED])  # the CDN gets the signed URL, never the token
        self.assertNotIn('authorization', heads[API])  # public metadata: no credential
        self.assertEqual(self.run_.catalog.state[SID]['sha256'], sha)

    def test_declared_total_points_must_equal_rows_read_every_run(self):
        self.serve(SAMPLE)  # the file's own total_points (59678) against an excerpt of 5 rows
        self.go()
        self.assertEqual([(c['expected'], c['extracted']) for c in self.failed()], [(59678, 5)])
        self.run_.manifest['coverage'] = []
        self.go()  # same file, nothing missing: not downloaded again, but the mismatch still fails the run
        self.assertEqual(self.fetched(SIGNED), 1)
        self.assertEqual([(c['expected'], c['extracted']) for c in self.failed()], [(59678, 5)])

    def test_bytes_that_differ_from_the_hub_sha256_are_not_kept(self):
        self.serve(consistent(), api=api_body(consistent(), sha=hashlib.sha256(b'other').hexdigest()))
        self.go()
        self.assertEqual(self.entries(), {})
        self.assertTrue(self.failed())
        self.assertFalse(list((Path(self.tmp.name) / 'raw').rglob('*.json')))
        self.assertIn('sha256 differs', ' '.join(self.run_.manifest['errors']))

    def test_a_license_change_upstream_stops_before_any_download(self):
        self.serve(consistent(), api=api_body(consistent(), license_='other'))
        self.go()
        self.assertEqual((self.fetched(RESOLVE), self.entries()), (0, {}))
        self.assertTrue(self.failed())

    def test_without_the_token_the_gated_file_is_not_requested(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.go()
        self.assertEqual(self.fetched(RESOLVE), 0)
        self.assertTrue(self.failed())
        self.assertIn('HF_TOKEN is not set', ' '.join(self.run_.manifest['errors']))

    def test_an_unchanged_complete_file_is_not_downloaded_again(self):
        self.go()
        self.go()
        self.assertEqual((self.fetched(RESOLVE), self.fetched(SIGNED), self.fetched(API)), (1, 1, 2))
        self.assertEqual(self.failed(), [])

    def test_a_missing_row_brings_the_file_back(self):
        self.go()
        del self.run_.catalog.entries[f'{SID}:160972']
        self.go()
        self.assertEqual(self.fetched(SIGNED), 2)
        self.assertIn('160972', self.entries())

    def test_a_refused_signed_redirect_is_recorded_without_its_signature(self):
        self.serve(consistent(), cdn_robots=CLOUDFRONT_403)  # the conservative rule: 403 robots = everything disallowed
        self.go()
        self.assertEqual((self.fetched(SIGNED), self.entries()), (0, {}))
        self.assertTrue(self.failed())
        dump = json.dumps(self.run_.manifest)
        self.assertIn('robots.txt disallows', dump)
        self.assertNotIn('SECRETSIG', dump)
        self.assertNotIn('t0k-secret', dump)

    def test_a_file_read_in_part_fails_and_is_downloaded_again(self):
        cut = consistent()[:200_000]
        self.serve(cut)
        self.go()
        self.assertTrue(self.failed())
        self.assertNotIn('sha256', self.run_.catalog.state[SID])
        self.go()
        self.assertEqual(self.fetched(SIGNED), 2)

    def test_a_row_repeated_in_the_source_is_counted_and_the_first_stays(self):
        ps = points()
        again = json.loads(json.dumps(ps[0]))
        again['payload']['metadata']['rubro'] = 'OTRO RUBRO'
        body = json.dumps({'total_points': 6, 'points': ps + [again]}, ensure_ascii=False).encode('utf-8')
        self.serve(body)
        stats = self.go()
        self.assertEqual(self.failed(), [])
        self.assertEqual((stats['rows_read'], stats['distinct'], stats['source_repeated_rows']), (6, 5, 1))
        self.assertTrue(self.entries()['160971']['title'].startswith('VISITAS DOMICILIARIAS'))

    def uncitable_file(self):
        """The real excerpt plus CONSTRUIDO rows like the 2,876 quarantined in run 39691250207: one without rubro placed
        BEFORE the real row of the same registro, one without registro, and one with a small registro and a rubro."""
        ps = points()
        return [construido(ps[1], rubro='')] + ps + [construido(ps[2], registro_digital=''),
                                                     construido(ps[3], registro_digital='1000')]

    def test_rows_without_rubro_or_registro_are_counted_never_catalogued(self):
        rows = self.uncitable_file()
        self.serve(body_of(rows))
        stats = self.go()
        self.assertEqual(self.failed(), [])
        es = self.entries()
        self.assertEqual(sorted(es), ['1000', '160971', '160972', '2006839', '2009327', '2021168'])
        self.assertEqual(es['160972']['title'], ' '.join(points()[1]['payload']['metadata']['rubro'].split()))
        for e in es.values():
            self.assertEqual(validate('catalog_entry', e), [], e['native_id'])
        self.assertEqual({k: stats[k] for k in ('rows_read', 'distinct', 'source_repeated_rows', 'source_rows_without_registro',
                                                'source_rows_without_rubro')},
                         {'rows_read': 8, 'distinct': 6, 'source_repeated_rows': 0, 'source_rows_without_registro': 1,
                          'source_rows_without_rubro': 1})
        self.assertEqual(stats['rows_read'], stats['distinct'] + stats['source_repeated_rows']
                         + stats['source_rows_without_registro'] + stats['source_rows_without_rubro'])
        self.assertEqual((stats['source_rows_without_rubro_point_ids'], stats['source_rows_without_registro_point_ids']),
                         ([160972], ['07e52232-7046-4331-8512-f74b3c96cbcf']))
        dump = json.dumps(self.run_.manifest, ensure_ascii=False)
        for p in (rows[0], rows[-2]):  # nothing of an uncatalogued row reaches the manifest but its point id
            for field in ('rubro', 'texto', 'tesis', 'url'):
                if p['payload']['metadata'].get(field):
                    self.assertNotIn(p['payload']['metadata'][field], dump, field)

    def test_a_file_with_uncatalogued_rows_reconciles_and_is_not_downloaded_again(self):
        # Run 39691250207: such rows failed the schema and were quarantined (dropped), so 'distinct' never matched the
        # catalog again: every run would download the 3.6 GB file again and exit 4.
        self.serve(body_of(self.uncitable_file()))
        self.go()
        invalid = {eid: errs for eid, e in self.run_.catalog.entries.items() if (errs := validate('catalog_entry', e))}
        quarantine(self.run_.catalog, invalid)  # what main() does after the sources ran
        self.run_.manifest['coverage'] = []
        self.go()
        self.assertEqual((invalid, self.fetched(SIGNED), self.failed()), ({}, 1, []))

    def test_at_most_twenty_point_ids_are_kept(self):
        ps = points()
        self.serve(body_of(ps + [construido(ps[0], rubro='')] * 25))  # CONSTRUIDO: 25 rows with the rubro blanked
        stats = self.go()
        self.assertEqual(self.failed(), [])
        self.assertEqual((stats['source_rows_without_rubro'], stats['source_rows_without_rubro_point_ids']), (25, [160971] * 20))


class Wiring(unittest.TestCase):
    def test_registered_active_and_dispatched(self):
        reg = json.loads((ROOT / 'sources' / 'mx.json').read_text(encoding='utf-8'))
        src = next(s for s in reg['sources'] if s['source_id'] == SID)
        self.assertEqual((src['status'], src['role'], src['token_env'], src['license_id']), ('active', 'secondary', 'HF_TOKEN', 'cc-by-4.0'))
        self.assertIn('huggingface.co', src['allowed_hosts'])
        self.assertNotIn(SID, [s['source_id'] for s in reg.get('secondary_sources', [])])
        with tempfile.TemporaryDirectory() as tmp:
            run = Run('MX', tmp + '/out', tmp + '/raw', None, date(2026, 10, 22), 0, 0, parallel=False)
            with mock.patch.object(Run, 'run_hf_tesis', lambda self_, s: {'ran': s['source_id']}):
                manifest = run.execute({SID})
        self.assertEqual(manifest['sources'], {SID: {'ran': SID}})

    def test_the_token_reaches_the_catalog_step_only_as_an_env_var(self):
        wf = yaml.safe_load((ROOT / '.github' / 'workflows' / 'catalog-mx.yml').read_text(encoding='utf-8'))
        steps = wf['jobs']['run']['steps']
        catalog = next(s for s in steps if s.get('id') == 'catalog')
        self.assertEqual(catalog['env']['HF_TOKEN'], '${{ secrets.HF_TOKEN }}')
        self.assertEqual([s.get('name') for s in steps if 'HF_TOKEN' in json.dumps(s.get('env', {}))], [catalog['name']])
        for path in (ROOT / '.github' / 'workflows').glob('*.yml'):
            for job in yaml.safe_load(path.read_text(encoding='utf-8'))['jobs'].values():
                for s in job.get('steps', []):
                    self.assertNotIn('${{', s.get('run', ''), f'{path.name}: {s.get("name")}')  # REGLAS 12


if __name__ == '__main__':
    unittest.main()
