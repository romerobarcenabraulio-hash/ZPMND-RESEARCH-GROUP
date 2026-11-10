"""rg/catalog/publicado.py (SECURITY.md T30): replays the 2026-11-09 incident and the guard's edges."""
import contextlib
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from rg.catalog import publicado
from rg.catalog.run import Run, _artifact, main

ROOT = Path(__file__).resolve().parents[1]


def rel_of(body, ext='html'):
    sha = hashlib.sha256(body).hexdigest()
    return sha, f'sha256/{sha[:2]}/{sha}.{ext}'


def row(nid, rel, versions=()):
    vs = {'versions': [{'sha256': r.split('/')[2][:64], 'retrieved_at': '2026-10-20T00:00:00Z', 'raw_path': r} for r in versions]}
    return {'entry_id': f'mx.dof:{nid}', 'source_id': 'mx.dof', 'native_id': nid, 'raw_path': rel, 'raw_status': 'stored', **(vs if versions else {})}


class Ledger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mx, self.raw = Path(self.tmp.name, 'mx'), Path(self.tmp.name, 'raw')
        (self.mx / 'dof').mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def rows(self, *entries):
        (self.mx / 'dof' / '2026.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in entries), encoding='utf-8')

    def put(self, body, ext='html'):
        sha, rel = rel_of(body, ext)
        (self.raw / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.raw / rel).write_bytes(body)
        return sha, rel

    def test_texto_lines_and_the_ledger_both_count_as_published(self):
        a, ra = rel_of(b'a')
        b, rb = rel_of(b'b', 'pdf')
        c, rc = rel_of(b'c')
        self.rows(row('1', ra), row('2', rb), row('3', rc))
        (self.mx / 'texto').mkdir()
        (self.mx / 'texto' / 'dof.jsonl').write_text(json.dumps({'raw_sha256': a}) + '\n', encoding='utf-8')
        (self.mx / 'raw').mkdir()
        (self.mx / 'raw' / 'publicados.txt').write_text(b + '\n', encoding='utf-8')
        self.assertEqual(publicado.faltan(self.mx), {'por_publicar': [], 'perdidos': [rc]})

    def test_a_raw_on_disk_is_to_publish_and_one_nowhere_is_lost(self):
        _, here = self.put(b'here')
        _, gone = rel_of(b'gone')
        self.rows(row('1', here), row('2', gone))
        self.assertEqual(publicado.faltan(self.mx, self.raw), {'por_publicar': [here], 'perdidos': [gone]})
        self.assertEqual(publicado.faltan(self.mx), {'por_publicar': [], 'perdidos': sorted([here, gone], key=lambda r: r.split('/')[2])})

    def test_every_version_a_row_keeps_is_pointed_to(self):
        _, new = rel_of(b'new')
        _, old = rel_of(b'old', 'pdf')
        sha, _ = rel_of(b'misplaced')
        wrong = f"sha256/{'00' if sha[:2] != '00' else '01'}/{sha}.html"  # a path that is not its content address
        self.rows(row('1', new, versions=[old, new]), row('2', wrong))
        refs, bad = publicado.referencias(self.mx)
        self.assertEqual(sorted(refs.values()), sorted([new, old]))
        self.assertEqual(len(bad), 1)
        self.assertIn(wrong, bad[0])

    def test_a_malformed_reference_now_or_in_a_version_is_lost_never_skipped(self):
        sha, _ = rel_of(b'x')
        misplaced = f"sha256/{'00' if sha[:2] != '00' else '01'}/{sha}.html"
        for current, versions in ((misplaced, ()), ('raw/x.pdf', ()), (None, ['sha256/zz/nope.pdf'])):
            with self.subTest(current=current, versions=versions):
                e = {'entry_id': 'mx.dof:1', 'source_id': 'mx.dof', 'native_id': '1', 'raw_status': 'stored', 'raw_path': current}
                if versions:
                    e['versions'] = [{'sha256': 'a' * 64, 'retrieved_at': '2026-10-20T00:00:00Z', 'raw_path': v} for v in versions]
                self.rows(e)
                self.assertEqual(len(publicado.faltan(self.mx, self.raw)['perdidos']), 1)
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(publicado.main(['--catalog', str(self.mx)]), 5)
        self.rows({'entry_id': 'mx.dof:2', 'source_id': 'mx.dof', 'native_id': '2', 'raw_status': 'metadata_only', 'raw_path': ''})
        self.assertEqual(publicado.faltan(self.mx), {'por_publicar': [], 'perdidos': []})  # no raw: nothing to check

    def test_a_linked_raw_or_a_linked_folder_is_never_on_disk_nor_in_the_ledger(self):
        body = b'<html>enlazado</html>'
        sha, rel = rel_of(body)
        real = Path(self.tmp.name, 'fuera'); real.mkdir()
        (real / f'{sha}.html').write_bytes(body)
        (self.raw / 'sha256' / sha[:2]).mkdir(parents=True)
        (self.raw / rel).symlink_to(real / f'{sha}.html')  # the file is a link
        self.rows(row('1', rel))
        self.assertEqual(publicado.faltan(self.mx, self.raw), {'por_publicar': [], 'perdidos': [rel]})
        self.assertEqual(publicado.anotar(self.mx, self.raw), 0)
        with self.assertRaises(OSError):  # O_NOFOLLOW: a link is refused, not followed
            publicado.empaquetar(Path(self.tmp.name, 'b.tar'), self.raw, [rel])
        (self.raw / rel).unlink(); (self.raw / 'sha256' / sha[:2]).rmdir()
        (self.raw / 'sha256' / sha[:2]).symlink_to(real, target_is_directory=True)  # the folder is a link
        self.assertEqual(publicado.faltan(self.mx, self.raw)['por_publicar'], [])
        self.assertEqual(publicado.anotar(self.mx, self.raw), 0)
        with self.assertRaisesRegex(ValueError, 'without links'):
            publicado.empaquetar(Path(self.tmp.name, 'b.tar'), self.raw, [rel])

    def test_a_raw_whose_bytes_do_not_match_its_name_is_never_bundled(self):
        _, rel = rel_of(b'what the name says')
        (self.raw / rel).parent.mkdir(parents=True)
        (self.raw / rel).write_bytes(b'other bytes')
        with self.assertRaisesRegex(ValueError, 'hash to'):
            publicado.empaquetar(Path(self.tmp.name, 'b.tar'), self.raw, [rel])
        (self.raw.parent / 'fuera.html').write_bytes(b'x')
        with self.assertRaisesRegex(ValueError, 'content address'):  # never a path outside the store
            publicado.empaquetar(Path(self.tmp.name, 'b.tar'), self.raw, ['../fuera.html'])

    def test_a_malformed_sha_in_texto_or_in_the_ledger_stops_the_check(self):
        (self.mx / 'texto').mkdir()
        (self.mx / 'texto' / 'dof.jsonl').write_text(json.dumps({'raw_sha256': 'A' * 64}) + '\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'dof.jsonl:1'):
            publicado.publicados(self.mx)
        (self.mx / 'texto' / 'dof.jsonl').write_text('', encoding='utf-8')
        (self.mx / 'raw').mkdir()
        (self.mx / 'raw' / 'publicados.txt').write_text('a' * 64 + '\n../x\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'publicados.txt:2'):
            publicado.publicados(self.mx)

    def test_anotar_adds_each_member_once_and_ignores_what_is_not_a_raw(self):
        a, _ = self.put(b'a')
        b, _ = self.put(b'b', 'pdf')
        c, _ = rel_of(b'c')
        wrong = '00' if c[:2] != '00' else '01'
        (self.raw / 'sha256' / wrong).mkdir(exist_ok=True)
        (self.raw / 'sha256' / wrong / (c + '.html')).write_bytes(b'c')  # in a folder that is not its prefix
        (self.raw / 'sha256' / a[:2] / (a + '.html.123.part')).write_bytes(b'x')  # a write cut short
        self.assertEqual(publicado.anotar(self.mx, self.raw), 2)
        self.assertEqual(publicado.anotar(self.mx, self.raw), 0)
        self.assertEqual((self.mx / 'raw' / 'publicados.txt').read_text(encoding='utf-8'), ''.join(f'{s}\n' for s in sorted([a, b])))

    def test_main_refuses_with_5_until_the_raw_is_in_the_ledger(self):
        _, rel = self.put(b'only on this disk')
        self.rows(row('1', rel))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(publicado.main(['--catalog', str(self.mx)]), 5)
            self.assertEqual(publicado.main(['--catalog', str(self.mx), '--anotar', str(self.raw)]), 0)
        self.assertIn(rel, out.getvalue().splitlines()[0])

    def test_the_module_runs_as_the_workflow_calls_it(self):
        _, rel = rel_of(b'x')
        self.rows(row('1', rel))
        p = subprocess.run([sys.executable, '-m', 'rg.catalog.publicado', '--catalog', str(self.mx)], cwd=ROOT,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 5, p.stderr)


class Incident(unittest.TestCase):
    """The run itself: its bundle holds what the rows point to and is unpublished, never only what it wrote now."""

    def run_main(self, tmp, body, on_disk_before, *extra):
        out, raw = Path(tmp, 'o'), Path(tmp, 'r')
        sha, rel = rel_of(body)
        if on_disk_before:  # left by an earlier attempt on the same disk
            (raw / rel).parent.mkdir(parents=True)
            (raw / rel).write_bytes(body)

        def runner(self_, src):
            dof = next(s for s in self_.registry['sources'] if s['source_id'] == 'mx.dof')
            url = 'https://sidof.segob.gob.mx/notas/5799706'
            got_sha, got_rel = (self_.raw.put(body, 'html') if on_disk_before else (sha, rel))
            cat = {'jurisdiction': 'federal', 'collection': 'DOF', 'doc_type': 'ACUERDO'}
            self_.catalog.upsert({'entry_id': 'mx.dof:5799706', 'country': 'MX', 'source_id': 'mx.dof', 'native_id': '5799706', 'title': 'Acuerdo x', 'url': url, 'first_seen': '2026-10-20T00:00:00Z', 'category': cat, 'dates': {'published': '2026-10-20'}, 'raw_status': 'stored', 'raw_path': got_rel, 'artifact': _artifact(dof, url, got_sha, body, 'text/html', got_rel)})
            return {}
        log = io.StringIO()
        with mock.patch.object(Run, 'run_indicadores', runner), contextlib.redirect_stdout(log):
            rc = main(['--country', 'mx', '--out', str(out), '--raw', str(raw), '--sources', 'mx.inegi-bie', *extra])
        manifest = json.loads(next((out / 'mx' / 'runs').glob('*.json')).read_text(encoding='utf-8'))
        return rc, rel, manifest

    def test_a_file_an_earlier_attempt_left_on_the_disk_goes_in_the_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp, 'b.tar')
            rc, rel, manifest = self.run_main(tmp, b'<html>nota</html>', True, '--bundle', str(bundle))
            with tarfile.open(bundle) as tar:
                self.assertEqual(tar.getnames(), [rel])
        self.assertEqual(manifest['raw_bundle_members'], 1)
        self.assertEqual(rc, 0)
        self.assertTrue(next(c for c in manifest['coverage'] if c['source_id'] == 'raw')['ok'])

    def test_a_row_whose_bytes_are_nowhere_fails_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, rel, manifest = self.run_main(tmp, b'<html>perdida</html>', False, '--bundle', str(Path(tmp, 'b.tar')))
            self.assertFalse(Path(tmp, 'b.tar').exists())
        check = next(c for c in manifest['coverage'] if c['source_id'] == 'raw')
        self.assertEqual((check['ok'], check['extracted'], check['entries']), (False, 1, [rel]))
        self.assertEqual(rc, 3)


class Workflow(unittest.TestCase):
    def test_the_ledger_is_written_before_the_upload_and_the_gate_runs_before_the_commit(self):
        steps = yaml.safe_load((ROOT / '.github' / 'workflows' / 'catalog-mx.yml').read_text(encoding='utf-8'))['jobs']['run']['steps']
        names = [s.get('name', '') for s in steps]
        up = steps[next(i for i, n in enumerate(names) if n.startswith('Upload raw bundle'))]['run']
        self.assertLess(up.index('python -m rg.catalog.publicado --catalog data/mx --anotar raw'), up.index('rm -rf raw'))
        gate = names.index('Every raw a row points to is published, or nothing is committed')
        self.assertEqual(steps[gate]['run'], 'python -m rg.catalog.publicado --catalog data/mx')
        self.assertNotIn('if', steps[gate])
        self.assertLess(names.index(next(n for n in names if n.startswith('Upload raw bundle'))), gate)
        self.assertLess(gate, names.index('Commit catalog to the data branch'))


if __name__ == '__main__':
    unittest.main()
