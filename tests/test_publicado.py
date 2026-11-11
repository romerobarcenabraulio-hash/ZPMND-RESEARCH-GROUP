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

import yaml

from rg.catalog import publicado
from rg.catalog.run import _artifact, main as catalog_run

ROOT = Path(__file__).resolve().parents[1]
DOF = {'source_type': 'primary_official', 'publisher': 'DOF', 'license': 'LFDA', 'redistribution': 'allowed'}


def rel_of(body, ext='html'):
    sha = hashlib.sha256(body).hexdigest()
    return sha, f'sha256/{sha[:2]}/{sha}.{ext}'


def row(nid, rel, versions=()):
    """A valid catalog_entry: stored with its artifact when rel is given, metadata_only without a raw when it is None."""
    url = f'https://sidof.segob.gob.mx/notas/{nid}'
    e = {'entry_id': f'mx.dof:{nid}', 'country': 'MX', 'source_id': 'mx.dof', 'native_id': nid, 'title': 'Acuerdo x', 'url': url,
         'first_seen': '2026-10-20T00:00:00Z', 'dates': {'published': '2026-10-20'}, 'raw_status': 'stored' if rel else 'metadata_only',
         'category': {'jurisdiction': 'federal', 'collection': 'DOF', 'doc_type': 'ACUERDO'}}
    if rel:
        e.update(raw_path=rel, artifact=_artifact(DOF, url, (rel.split('/')[-1] + 'a' * 64)[:64], b'x', 'text/html', rel))
    if versions:
        e['versions'] = [{'sha256': r.split('/')[-1][:64], 'retrieved_at': '2026-10-20T00:00:00Z', 'raw_path': r} for r in versions]
    return e


class Ledger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mx, self.raw = Path(self.tmp.name, 'mx'), Path(self.tmp.name, 'raw')
        (self.mx / 'dof').mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        (self.mx / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.mx / rel).write_text(text, encoding='utf-8')

    def rows(self, *entries):
        self.write('dof/2026.jsonl', ''.join(json.dumps(e) + '\n' for e in entries))

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
        self.write('texto/dof.jsonl', json.dumps({'raw_sha256': a}) + '\n')
        self.write('raw/publicados.txt', b + '\n')
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
        self.rows(row('1', new, versions=[old, new]))
        refs, bad, _ = publicado.referencias(self.mx)
        self.assertEqual((sorted(refs.values()), bad), (sorted([new, old]), []))

    def test_a_row_that_is_not_a_valid_entry_or_points_badly_is_lost_never_skipped(self):
        misplaced = f"sha256/{'00' if (sha := rel_of(b'x')[0])[:2] != '00' else '01'}/{sha}.html"
        stored = row('1', misplaced)
        self.write('raw/publicados.txt', sha + '\n')  # its sha is published: only the address check makes it lost
        for e in (stored, row('1', 'raw/x.pdf'), row('1', None, ['sha256/zz/nope.pdf']), {}, {**stored, 'raw_path': None},
                  {**stored, 'raw_path': ''}, {k: v for k, v in stored.items() if k != 'raw_path'}):  # GPT on 2d88340, 5521f27
            with self.subTest(e=e):
                self.rows(e)
                self.assertEqual(len(publicado.faltan(self.mx, self.raw)['perdidos']), 1)
                self.assertEqual(self.publicar().returncode, 5)
        self.rows(row('2', None))  # metadata_only, no raw: a valid row with nothing to check
        self.assertEqual(publicado.faltan(self.mx), {'por_publicar': [], 'perdidos': []})
        (self.mx / 'dof' / '2026.jsonl').write_text('no es json\n', encoding='utf-8')
        with self.assertRaises(ValueError):  # fails closed
            publicado.faltan(self.mx)

    def test_a_linked_raw_or_a_linked_folder_is_never_on_disk_nor_in_the_ledger(self):
        body = b'<html>enlazado</html>'
        sha, rel = rel_of(body)
        real = Path(self.tmp.name, 'fuera'); real.mkdir()
        (real / f'{sha}.html').write_bytes(body)
        (self.raw / 'sha256' / sha[:2]).mkdir(parents=True)
        (self.raw / rel).symlink_to(real / f'{sha}.html')  # the file is a link
        self.rows(row('1', rel))
        self.assertEqual(publicado.faltan(self.mx, self.raw), {'por_publicar': [], 'perdidos': [rel]})
        self.assertEqual(publicado.crudos(self.raw), [])
        with self.assertRaises(OSError):  # O_NOFOLLOW: a link is refused, not followed
            publicado.empaquetar(Path(self.tmp.name, 'b.tar'), self.raw, [rel])
        (self.raw / rel).unlink(); (self.raw / 'sha256' / sha[:2]).rmdir()
        (self.raw / 'sha256' / sha[:2]).symlink_to(real, target_is_directory=True)  # the folder is a link
        self.assertEqual(publicado.faltan(self.mx, self.raw)['por_publicar'], [])
        self.assertEqual(publicado.crudos(self.raw), [])
        with self.assertRaisesRegex(ValueError, 'without links'):
            publicado.empaquetar(Path(self.tmp.name, 'b.tar'), self.raw, [rel])
        plain = Path(self.tmp.name, 'plano'); (plain / rel).parent.mkdir(parents=True); (plain / rel).write_bytes(body)
        link = Path(self.tmp.name, 'enlace'); link.symlink_to(plain, target_is_directory=True)  # the root is a link
        self.assertEqual((publicado.crudos(plain), publicado.crudos(link)), ([rel], []))

    def test_a_malformed_sha_in_texto_or_in_the_ledger_stops_the_check(self):
        self.write('texto/dof.jsonl', json.dumps({'raw_sha256': 'A' * 64}) + '\n')
        with self.assertRaisesRegex(ValueError, 'dof.jsonl:1'):
            publicado.publicados(self.mx)
        self.write('texto/dof.jsonl', '')
        self.write('raw/publicados.txt', 'a' * 64 + '\n../x\n')
        with self.assertRaisesRegex(ValueError, 'publicados.txt:2'):
            publicado.publicados(self.mx)

    def test_anotar_adds_each_member_once_and_ignores_what_is_not_a_raw(self):
        a, _ = self.put(b'a')
        b, _ = self.put(b'b', 'pdf')
        c, _ = rel_of(b'c')
        (self.raw / 'sha256' / ('00' if c[:2] != '00' else '01')).mkdir(exist_ok=True)
        (self.raw / 'sha256' / ('00' if c[:2] != '00' else '01') / (c + '.html')).write_bytes(b'c')  # in a folder not its prefix
        (self.raw / 'sha256' / a[:2] / (a + '.html.123.part')).write_bytes(b'x')  # a write cut short
        self.assertEqual([r.split('/')[2][:64] for r in publicado.crudos(self.raw)], sorted([a, b]))
        self.assertEqual((publicado.anotar(self.mx, [a, b]), publicado.anotar(self.mx, [b])), (2, 0))
        self.assertEqual((self.mx / 'raw' / 'publicados.txt').read_text(encoding='utf-8'), ''.join(f'{s}\n' for s in sorted([a, b])))

    def publicar(self, *extra, cat=None):
        return subprocess.run([sys.executable, '-m', 'rg.catalog.publicado', '--catalog', cat or str(self.mx), *extra], cwd=ROOT,
                              capture_output=True, timeout=60)

    def test_as_the_workflow_calls_it_the_tar_on_stdout_and_the_ledger_are_the_same_verified_members(self):
        a, ra = self.put(b'only on this disk')
        self.rows(row('1', ra))
        self.assertEqual(self.publicar().returncode, 5)
        p = self.publicar('--publicar', str(self.raw))
        self.assertEqual(p.returncode, 0, p.stderr)
        with tarfile.open(fileobj=io.BytesIO(p.stdout)) as tar:
            self.assertEqual([(m.name, tar.extractfile(m).read()) for m in tar], [(ra, b'only on this disk')])
        self.assertEqual((self.mx / 'raw' / 'publicados.txt').read_text(encoding='utf-8'), a + '\n')
        self.assertEqual(self.publicar().returncode, 0)

    def test_a_loss_never_stops_the_upload_and_the_gate_still_stops_the_commit(self):
        a, ra = self.put(b'new this run')
        _, gone = rel_of(b'lost before')
        self.rows(row('1', ra), row('2', gone))
        p = self.publicar('--publicar', str(self.raw))
        self.assertEqual(p.returncode, 0, p.stderr)  # the new raw is uploaded all the same (auditor on 2c55288)
        with tarfile.open(fileobj=io.BytesIO(p.stdout)) as tar:
            self.assertEqual(tar.getnames(), [ra])
        self.assertEqual(self.publicar().returncode, 5)  # the gate step: no commit while a row's raw is lost

    def test_a_catalog_run_has_no_bundle_of_its_own(self):
        # its --bundle packed the files new to that process and left 1,166 rows without bytes: one bundler reads the rows
        with contextlib.redirect_stderr(err := io.StringIO()), self.assertRaises(SystemExit) as cm:
            catalog_run(['--country', 'mx', '--out', self.tmp.name, '--raw', str(self.raw), '--bundle', 'x.tar'])
        self.assertEqual((cm.exception.code, 'unrecognized arguments: --bundle x.tar' in err.getvalue()), (2, True))

    def test_a_missing_or_empty_catalog_never_passes_and_writes_no_ledger(self):
        for cat, text in ((self.tmp.name + '/nada', None), (str(self.mx), None), (str(self.mx), ''), (str(self.mx), ' \n\t\n')):
            _ = text is None or (self.mx / 'dof' / '2026.jsonl').write_text(text, encoding='utf-8')  # a file of no rows (GPT, 65b74f5)
            p, q = self.publicar(cat=cat), self.publicar('--publicar', str(self.raw), cat=cat)
            self.assertEqual((p.returncode, q.returncode, q.stdout), (2, 2, b''))
        self.assertFalse((self.mx / 'raw').exists())
        with self.assertRaisesRegex(ValueError, 'not a catalog folder'):
            publicado.faltan(Path(self.tmp.name, 'nada'))

    def test_a_raw_whose_name_is_not_its_bytes_stops_the_publication_and_the_ledger(self):
        _, rel = rel_of(b'what the name says')
        (self.raw / rel).parent.mkdir(parents=True)
        (self.raw / rel).write_bytes(b'other bytes')
        self.rows(row('1', rel))
        p = self.publicar('--publicar', str(self.raw))
        self.assertNotEqual(p.returncode, 0)  # the pipe fails, the step fails, nothing is committed
        self.assertIn(b'hash to', p.stderr)
        self.assertFalse((self.mx / 'raw' / 'publicados.txt').exists())
        (self.raw.parent / 'fuera.html').write_bytes(b'x')
        with self.assertRaisesRegex(ValueError, 'content address'):  # never a path outside the store
            publicado.empaquetar(Path(self.tmp.name, 'b.tar'), self.raw, ['../fuera.html'])

    def test_a_trailing_newline_never_makes_a_reference_or_a_ledger_line(self):
        sha, rel = rel_of(b'x')
        self.rows(row('1', rel + '\n'))
        self.write('raw/publicados.txt', sha + '\n')
        self.assertEqual(len(publicado.faltan(self.mx)['perdidos']), 1)  # malformed, so lost even with its sha published


class Workflow(unittest.TestCase):
    def test_the_ledger_is_written_before_the_upload_and_the_gate_runs_before_the_commit(self):
        steps = yaml.safe_load((ROOT / '.github' / 'workflows' / 'catalog-mx.yml').read_text(encoding='utf-8'))['jobs']['run']['steps']
        names = [s.get('name', '') for s in steps]
        up = steps[next(i for i, n in enumerate(names) if n.startswith('Upload raw bundle'))]['run']
        self.assertLess(up.index('python -m rg.catalog.publicado --catalog data/mx --publicar raw | split -b 1900m'), up.index('rm -rf raw'))
        self.assertIn('set -euo pipefail', up)  # a publicado that fails fails the pipe
        gate = names.index('Every raw a row points to is published, or nothing is committed')
        self.assertEqual(steps[gate]['run'], 'python -m rg.catalog.publicado --catalog data/mx')
        self.assertNotIn('if', steps[gate])
        self.assertLess(names.index(next(n for n in names if n.startswith('Upload raw bundle'))), gate)
        self.assertLess(gate, names.index('Commit catalog to the data branch'))


if __name__ == '__main__':
    unittest.main()
