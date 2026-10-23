"""Text extractor (rg.text): format by first bytes, statuses, isolation, coverage, bundles, quote check, workflow.

Real bytes: the HTML pages already in tests/fixtures, plus two official raws of the catalog, fetched through the
catalog's Fetcher (robots.txt honored) on 2026-10-21; both hash to the sha256 the catalog stored:
- leyesbiblio_reg_lieps_2026-10-21.pdf: https://www.diputados.gob.mx/LeyesBiblio/regley/Reg_LIEPS.pdf
  sha256 cb15a70b51a87cff0f6d329d5e8a97617d71c955e46da65921037a77a83ca5f4, 101,410 bytes, 4 pages.
- ojn_wo82633_2026-10-21.docx: https://www.ordenjuridico.gob.mx/Documentos/Estatal/Oaxaca/wo82633.docx
  sha256 9aff4a9af3b613750836d11abe9ccd89af2e6dfaf2722b22a09a94dd8f8b2880, 22,383 bytes (served as text/plain).
Bytes built here are marked CONSTRUIDO where they are built: first bytes of formats with no fixture, PDFs and DOCX
assembled from the real ones (blank pages, injected XML), tars for the bundle checks.
"""
import contextlib
import hashlib
import io
import json
import os
import re
import sys
import tarfile
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import yaml
from pypdf import PdfReader, PdfWriter, __version__ as PYPDF_VERSION

from rg.catalog import store as catalog_store
from rg.catalog.store import Catalog, RawStore
from rg.quotes import _fold as fold
from rg.schemas import validate
from rg.text import bundles, extract as ex, quote, run as tr
from rg.text.store import TextStore, read_manifest, text_sha, write_manifest

ROOT = Path(__file__).resolve().parents[1]
FX = ROOT / 'tests' / 'fixtures'
PDF_NAME, DOCX_NAME = 'leyesbiblio_reg_lieps_2026-10-21.pdf', 'ojn_wo82633_2026-10-21.docx'
PDF, DOCX = (FX / PDF_NAME).read_bytes(), (FX / DOCX_NAME).read_bytes()
PDF_SHA = 'cb15a70b51a87cff0f6d329d5e8a97617d71c955e46da65921037a77a83ca5f4'
DOCX_SHA = '9aff4a9af3b613750836d11abe9ccd89af2e6dfaf2722b22a09a94dd8f8b2880'
# sha256 of the text each pinned extractor gives for a fixture. A change here means the extractor's output changed:
# bump its version in rg.text.extract.EXTRACTORS (quotes cite name==version) and only then update the hash.
GOLDEN = {
    'sidof_day_2026-10-15_single_edition.html': ('rg-html==1', '830739cd490051ced12501de00f1dfa079a398e12ff8dd31937767c518764105'),
    'ojn_ficha_95983.html': ('rg-html==1', '2be0fc7b450124fb5c8b2f1772c8ebf8c9734ed692d08eb56a3fa56c29f1fa4c'),
    'leyesbiblio_regla_2026-10-19.htm': ('rg-html==1', '41cc7a34340be17f125fcf3ebaf86050792b424846cac159f62b61233676cc0b'),
    DOCX_NAME: ('rg-docx==1', '05f91aa93750a8a2890a5c92d43baf122e0746dd88934070f04dd41678390ef7'),
    PDF_NAME: (f'rg-pdf==1+pypdf.{PYPDF_VERSION}', '75ba41862adc68f4373aa445a45e0531fd8688a0c8fc8155a049e5dab6247a33'),
}


def html(name):
    return (FX / name).read_bytes()


def pdf_of(*pages):
    """CONSTRUIDO: a PDF made of pages of the real one (by index) and blank pages (None), which have no text layer."""
    real, w = PdfReader(io.BytesIO(PDF)), PdfWriter()
    for p in pages:
        if p is None:
            w.add_blank_page(612, 792)
        else:
            w.add_page(real.pages[p])
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def docx_with(body_xml=None, extra=None):
    """CONSTRUIDO from the real DOCX: `body_xml` goes first in its body; `extra` adds or replaces zip entries."""
    src, buf = zipfile.ZipFile(io.BytesIO(DOCX)), io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == 'word/document.xml' and body_xml is not None:
                data = data.replace(b'<w:body>', b'<w:body>' + body_xml.encode('utf-8'), 1)
            if info.filename not in (extra or {}):
                z.writestr(info.filename, data)
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


class Fixtures(unittest.TestCase):
    def test_the_official_files_are_the_catalogs_raws(self):
        self.assertEqual(hashlib.sha256(PDF).hexdigest(), PDF_SHA)
        self.assertEqual(hashlib.sha256(DOCX).hexdigest(), DOCX_SHA)
        self.assertLess(len(PDF), 300_000)


class Sniff(unittest.TestCase):
    def test_the_format_comes_from_the_bytes_never_the_name(self):
        self.assertEqual(ex.sniff(PDF[:4096]), 'pdf')
        self.assertEqual(ex.sniff(DOCX[:4096]), 'zip')
        self.assertEqual(ex.extract(DOCX)['format'], 'docx')
        self.assertEqual(ex.sniff(html('ojn_ficha_95983.html')[:4096]), 'html')
        self.assertEqual(ex.sniff(html('hf_tesis_scjn_sample.json')[:4096]), 'json')
        self.assertEqual(ex.sniff(b'\r\n  ' + PDF[:4096]), 'pdf')  # CONSTRUIDO: junk before the header

    def test_formats_without_extractor_are_named_and_not_supported(self):
        # CONSTRUIDO: the first bytes of each format (there is no fixture of these)
        cases = {'ole2': ex.OLE2 + b'\x00' * 504, 'rtf': b'{\\rtf1\\ansi\\deff0 {\\fonttbl{\\f0 Arial;}} Ley}',
                 'json': b'{"texto": "<p>Art\\u00edculo 1</p>"}', 'otro': b'Ley de Ingresos, texto plano\n'}
        for fmt, body in cases.items():
            r = ex.extract(body)
            self.assertEqual((r['format'], r['status'], r['extractor'], r['text']), (fmt, ex.UNSUPPORTED, ex.SNIFF, None), fmt)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:  # CONSTRUIDO: a zip that is not a DOCX
            z.writestr('content.xml', '<office:document/>')
        r = ex.extract(buf.getvalue())
        self.assertEqual((r['format'], r['status'], r['text']), ('zip', ex.UNSUPPORTED, None))


class Html(unittest.TestCase):
    def test_script_and_style_are_dropped(self):
        body = html('sidof_day_2026-10-15_single_edition.html')
        self.assertIn(b'function gtag', body)
        text = ex.extract(body)['text']
        self.assertNotIn('gtag', text)
        self.assertNotIn('dataLayer', text)
        self.assertIn('1.- Acuerdo por el que se modifica la delimitación', text)

    def test_blocks_break_lines_and_cells_never_glue_words(self):
        text = ex.extract(html('ojn_ficha_95983.html'))['text']
        self.assertIn('Fecha de Publicación:\n09 de Abril de 2015', text)
        # CONSTRUIDO: cells and paragraphs with no whitespace between the tags
        t = ex.extract(b'<html><body><table><tr><td>Art\xc3\xadculo</td><td>5</td></tr></table><p>uno</p><p>dos</p></body></html>')
        self.assertEqual(t['text'], 'Artículo\t5\n\nuno\n\ndos')

    def test_charset_bom_then_valid_utf8_then_declared_then_windows_1252(self):
        ojn = html('ojn_ficha_95983.html')
        r = ex.extract(ojn)
        self.assertEqual(r['charset'], 'iso-8859-1')  # declared; decode_html reads it as windows-1252
        self.assertIn('Ficha técnica del Ordenamiento', r['text'])
        r = ex.extract(html('leyesbiblio_regla_2026-10-19.htm'))  # says utf-8, is not
        self.assertEqual(r['charset'], 'windows-1252')
        self.assertIn('Más de la Constitución', r['text'])
        self.assertEqual(ex.extract(html('sidof_day_1994-06-02_historic.html'))['charset'], 'utf-8')
        # CONSTRUIDO: the OJN page re-encoded as UTF-8 with its iso-8859-1 declaration kept: valid UTF-8 wins
        utf8 = ex.extract(ojn.decode('cp1252').encode('utf-8'))
        self.assertEqual((utf8['charset'], utf8['text']), ('utf-8', ex.extract(ojn)['text']))
        # CONSTRUIDO: a UTF-8 BOM wins even when a byte after it is not UTF-8
        bom = ex.extract(b'\xef\xbb\xbf<html><body><p>Art\xc3\xadculo \xff</p></body></html>')
        self.assertEqual((bom['charset'], bom['text']), ('utf-8', 'Artículo \ufffd'))

    def test_invisible_characters_are_removed_and_counted(self):
        r = ex.extract(html('sidof_day_2026-10-15_single_edition.html'))
        self.assertEqual(r['invisibles_removed'], 1)  # one U+FEFF in the page
        self.assertNotIn('\ufeff', r['text'])


class Finish(unittest.TestCase):
    def test_only_whitespace_and_invisibles_change(self):
        text, removed = ex._finish('  Ley \r\n\n\n\n del\u200b ISR \n\n')
        self.assertEqual((text, removed), ('Ley\n\ndel ISR', 2))
        self.assertEqual(fold(text), 'Ley del ISR')

    def test_nfc(self):
        self.assertEqual(ex._finish('Arti\u0301culo')[0], 'Artículo')


class Docx(unittest.TestCase):
    def test_real_docx(self):
        r = ex.extract(DOCX)
        self.assertEqual((r['format'], r['status'], r['extractor']), ('docx', ex.OK, 'rg-docx==1'))
        self.assertTrue(r['text'].startswith('LEY DE AMNISTIA PARA EL ESTADO DE OAXACA\n\nÚLTIMA REFORMA'))
        self.assertIn('LIC. JOSE MURAT, GOBERNADOR', r['text'])  # two runs split inside a word, joined

    def test_what_is_not_reading_text_is_skipped(self):
        body = ('<w:p><w:r><w:t xml:space="preserve">INICIO </w:t></w:r>'
                '<w:del w:id="91" w:author="x"><w:r><w:delText>TEXTO BORRADO</w:delText></w:r></w:del>'
                '<w:moveFrom w:id="92" w:author="x"><w:r><w:t>TEXTO MOVIDO</w:t></w:r></w:moveFrom>'
                '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
                '<w:r><mc:AlternateContent><mc:Choice Requires="wps"><w:t xml:space="preserve">CAJA UNICA </w:t></mc:Choice>'
                '<mc:Fallback><w:t xml:space="preserve">CAJA UNICA </w:t></mc:Fallback></mc:AlternateContent></w:r>'
                '<w:r><w:t>A</w:t><w:tab/><w:t>B</w:t><w:br/><w:t>C</w:t><w:noBreakHyphen/><w:t>D</w:t></w:r></w:p>')
        text = ex.extract(docx_with(body))['text']  # CONSTRUIDO
        self.assertTrue(text.startswith('INICIO CAJA UNICA A\tB\nC-D\nLEY DE AMNISTIA'), text[:80])
        for gone in ('TEXTO BORRADO', 'TEXTO MOVIDO', 'PAGE'):
            self.assertNotIn(gone, text)

    def test_footnotes_and_endnotes_follow_the_body(self):
        ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
        notes = {'word/footnotes.xml': f'<w:footnotes {ns}><w:footnote w:id="1"><w:p><w:r><w:t>(REFORMADO, P.O. 1 DE ENERO DE 2001)</w:t></w:r></w:p></w:footnote></w:footnotes>'}
        text = ex.extract(docx_with(extra=notes))['text']  # CONSTRUIDO
        self.assertTrue(text.endswith('(REFORMADO, P.O. 1 DE ENERO DE 2001)'))

    def test_images_without_text_need_ocr(self):
        empty = docx_with(extra={'word/document.xml': DOCX_EMPTY})  # CONSTRUIDO
        self.assertEqual(ex.extract(empty)['status'], ex.OK)
        scanned = docx_with(extra={'word/document.xml': DOCX_EMPTY, 'word/media/image1.png': b'\x89PNG\r\n\x1a\n'})
        r = ex.extract(scanned)
        self.assertEqual((r['format'], r['status'], r['text']), ('docx', ex.OCR, ''))

    def test_a_part_too_large_is_a_fallo(self):
        with mock.patch.object(ex, 'MAX_PART', 1000):
            r = ex.extract(DOCX)
        self.assertEqual((r['format'], r['status'], r['extractor']), ('docx', ex.FAILED, 'rg-docx==1'))
        self.assertIn('larger than 1000 bytes', r['error'])


DOCX_EMPTY = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p/>'
              '</w:body></w:document>')


class Pdf(unittest.TestCase):
    def test_real_pdf_with_page_offsets(self):
        r = ex.extract(PDF)
        self.assertEqual((r['format'], r['status'], r['pages_without_text']), ('pdf', ex.OK, []))
        text, pages = r['text'], r['pages']
        self.assertEqual(len(pages), 4)
        self.assertEqual(pages[0][0], 0)
        self.assertEqual(pages[-1][1], len(text))
        self.assertTrue(all(a[1] == b[0] for a, b in zip(pages, pages[1:])))  # contiguous, nothing between pages
        self.assertTrue(text.startswith('REGLAMENTO DE LA LEY DEL IMPUESTO ESPECIAL SOBRE PRODUCCIÓN Y SERVICIOS'))
        self.assertIn('PRIMERO. El presente Reglamento entrará en vigor', text[pages[3][0]:pages[3][1]])
        self.assertIn('4 de 4', text[pages[3][0]:pages[3][1]])

    def test_extractor_names_the_pinned_pypdf(self):
        pin = re.search(r'^pypdf==(\S+)$', (ROOT / 'requirements-dev.txt').read_text(encoding='utf-8'), re.M).group(1)
        self.assertEqual(PYPDF_VERSION, pin)
        self.assertEqual(ex.EXTRACTORS['pdf'], f'rg-pdf==1+pypdf.{pin}')
        for name in ex.EXTRACTORS.values():  # the evidence field of the contract accepts every extractor id
            ev = {'raw_sha256': 'a' * 64, 'extractor': name, 'quote': 'REGLAMENTO DE LA LEY'}
            rel = {'type': 'cita', 'from': {'entry_id': 'mx.dof:1'}, 'to': {'entry_id': 'mx.dof:2'}, 'evidence': ev, 'status': 'CANDIDATE'}
            self.assertEqual(validate('relation', rel), [], name)

    def test_no_text_layer_needs_ocr_and_keeps_no_text(self):
        r = ex.extract(pdf_of(None, None))  # CONSTRUIDO
        self.assertEqual((r['status'], r['text'], r['pages_without_text']), (ex.OCR, None, [1, 2]))

    def test_mostly_text_is_ok_and_mixed_needs_ocr_with_its_text(self):
        r = ex.extract(pdf_of(0, 1, 2, 3, 0, 1, 2, 3, 0, 1, None))  # CONSTRUIDO: 10 of 11 pages with text
        self.assertEqual((r['status'], r['pages_without_text']), (ex.OK, [11]))
        r = ex.extract(pdf_of(0, 1, 2, 3, None))  # CONSTRUIDO: 4 of 5
        self.assertEqual((r['status'], r['pages_without_text']), (ex.OCR, [5]))
        self.assertIn('PRIMERO. El presente Reglamento', r['text'])

    def test_encrypted(self):
        def enc(user):
            w = PdfWriter(clone_from=PdfReader(io.BytesIO(PDF)))
            w.encrypt(user_password=user, owner_password='propietario', algorithm='RC4-128')
            buf = io.BytesIO()
            w.write(buf)
            return buf.getvalue()
        r = ex.extract(enc('clave'))  # CONSTRUIDO
        self.assertEqual((r['status'], r['error']), (ex.FAILED, 'encrypted: needs a password'))
        self.assertEqual(ex.extract(enc(''))['text'], ex.extract(PDF)['text'])  # owner password only: readable

    def test_text_that_cannot_be_utf8_is_a_fallo_in_the_child(self):
        # Audit of #21 (05412eb): a lone surrogate in extracted text passed the child and raised UnicodeEncodeError in
        # the parent's text_sha, which stopped every run on the same raw.
        with mock.patch.object(ex, '_html', lambda body: ex._result('html', ex.OK, text='antes\ud800despues')):
            r = ex.extract(html('ojn_ficha_95983.html'))
        self.assertEqual((r['format'], r['status'], r['text']), ('html', ex.FAILED, None))
        self.assertIn('surrogates not allowed', r['error'])
        r['error'].encode('utf-8')  # the error itself never carries the surrogate

    def test_a_broken_file_is_a_fallo_not_a_crash(self):
        r = ex.extract(b'%PDF-1.4\n1 0 obj << /Type /Catalog')  # CONSTRUIDO
        self.assertEqual((r['format'], r['status'], r['extractor']), ('pdf', ex.FAILED, ex.EXTRACTORS['pdf']))
        self.assertTrue(r['error'])


class Golden(unittest.TestCase):
    def test_each_extractor_gives_the_same_text_as_when_its_version_was_fixed(self):
        for name, (extractor, sha) in GOLDEN.items():
            r = ex.extract((FX / name).read_bytes())
            self.assertEqual((r['extractor'], text_sha(r['text'])), (extractor, sha),
                             f'{name}: the output changed; bump the version in EXTRACTORS, then update GOLDEN')


def _sleeps(path, conn, max_bytes):  # a child that never answers
    time.sleep(20)


def _dies(path, conn, max_bytes):  # a child whose process dies without a word
    os._exit(7)


def _reports_limit(path, conn, max_bytes):  # a child that answers with the address-space cap it runs under
    import resource
    conn.send({'as_limit': resource.getrlimit(resource.RLIMIT_AS)[0]})


def _hogs(path, conn, max_bytes):  # a parser that blows up on 'hog.bin': far more memory than a small file needs
    if Path(path).name == 'hog.bin':
        bytearray(1_500_000_000)
    tr._child(path, conn, max_bytes)


LINUX = sys.platform.startswith('linux')  # RLIMIT_AS is enforced on Linux, where texto-mx runs


class Isolation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / f'{PDF_SHA}.bin'
        self.path.write_bytes(PDF)

    def test_each_file_runs_alone_and_returns_its_hash(self):
        [(path, r)] = list(tr.extract_all([self.path], timeout=60))
        self.assertEqual((path, r['status'], r['raw_sha256'], r['bytes']), (self.path, ex.OK, PDF_SHA, len(PDF)))

    def test_a_file_that_hangs_is_killed_at_the_time_limit(self):
        t0 = time.monotonic()
        [(_, r)] = list(tr.extract_all([self.path], timeout=1, target=_sleeps))
        self.assertLess(time.monotonic() - t0, 15)
        self.assertEqual((r['status'], r['format'], r['raw_sha256']), (ex.FAILED, 'pdf', PDF_SHA))
        self.assertTrue(r['error'].startswith('timeout'))

    def test_a_process_that_dies_is_a_fallo(self):
        [(_, r)] = list(tr.extract_all([self.path], timeout=60, target=_dies))
        self.assertEqual((r['status'], r['error']), (ex.FAILED, 'process ended without a result (exit 7)'))

    @unittest.skipUnless(LINUX, 'RLIMIT_AS is enforced on Linux, where the workflow runs')
    def test_each_worker_runs_under_its_memory_cap(self):
        # GPT review of #21 (4c71c28): a process and a size limit do not bound the parser's memory.
        [(_, r)] = list(tr.extract_all([self.path], timeout=60, max_memory=700_000_000, target=_reports_limit))
        self.assertEqual(r, {'as_limit': 700_000_000})

    @unittest.skipUnless(LINUX, 'RLIMIT_AS is enforced on Linux, where the workflow runs')
    def test_a_parser_that_outgrows_its_memory_is_a_fallo_and_the_others_are_kept(self):
        hog = Path(self.tmp.name) / 'hog.bin'
        hog.write_bytes(PDF)
        got = dict(tr.extract_all([hog, self.path], workers=2, timeout=60, max_memory=700_000_000, target=_hogs))
        self.assertEqual(got[hog]['status'], ex.FAILED)
        self.assertTrue(got[hog]['error'].startswith('process ended without a result'), got[hog]['error'])
        self.assertEqual((got[self.path]['status'], got[self.path]['raw_sha256']), (ex.OK, PDF_SHA))

    def test_workers_are_bounded_by_the_memory_they_may_take(self):
        g = 1_000_000_000
        self.assertEqual(tr.workers_for(8, 2 * g, total=7 * g), 2)    # 3 shares fit, one is left for the parent
        self.assertEqual(tr.workers_for(4, 2 * g, total=16 * g), 4)   # the request is the lower bound
        self.assertEqual(tr.workers_for(4, 2 * g, total=3 * g), 1)    # always at least one

    def test_nothing_starts_after_the_deadline(self):
        self.assertEqual(list(tr.extract_all([self.path], deadline=time.monotonic() - 1)), [])

    def test_a_raw_over_the_size_limit_is_not_read_whole(self):
        self.assertEqual(tr.read_and_extract(self.path, max_bytes=1000)['error'], 'larger than 1000 bytes')
        j = Path(self.tmp.name) / 'x.json'
        j.write_bytes(html('hf_tesis_scjn_sample.json'))
        r = tr.read_and_extract(j, max_bytes=1000)
        self.assertEqual((r['status'], r['raw_sha256']), (ex.UNSUPPORTED, hashlib.sha256(j.read_bytes()).hexdigest()))


class Run(unittest.TestCase):
    """A store of real raws under the extensions their sources gave (a PDF as .bin, a DOCX as .doc), plus CONSTRUIDO
    Word 97 first bytes and a PDF without text layer; the catalog references each one."""
    RAWS = ((PDF_NAME, 'bin'), (DOCX_NAME, 'doc'), ('ojn_ficha_95983.html', 'html'),
            ('sidof_day_2026-10-15_single_edition.html', 'html'), ('hf_tesis_scjn_sample.json', 'json'))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        self.raw, self.cat, self.text = d / 'raw', d / 'data' / 'mx', d / 'texto'
        self.out = self.cat / 'texto'
        store, rows = RawStore(self.raw), []
        bodies = [(FX / n).read_bytes() for n, _ in self.RAWS] + [ex.OLE2 + b'\x00' * 504, pdf_of(None)]
        for i, (body, ext) in enumerate(zip(bodies, [e for _, e in self.RAWS] + ['doc', 'pdf'])):
            sha, rel = store.put(body, ext)
            rows.append({'entry_id': f'mx.ojn-estatal:{i}', 'raw_path': rel,
                         'versions': [{'sha256': sha, 'raw_path': rel, 'retrieved_at': '2026-10-21T00:00:00Z'}]})
        self.shas = [r['versions'][0]['sha256'] for r in rows]
        (self.cat / 'ojn-estatal').mkdir(parents=True)
        (self.cat / 'ojn-estatal' / '01.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')

    def go(self, **kw):
        return tr.run(self.cat, self.raw, self.out, self.text, workers=kw.pop('workers', 2), timeout=60, **kw)

    def lines(self):
        return {line['raw_sha256']: line for line in read_manifest(self.out)}

    def test_every_raw_gets_exactly_one_status(self):
        rc, rep = self.go()
        self.assertEqual(rc, 0, rep['coverage'])
        lines = self.lines()
        self.assertEqual(sorted(lines), sorted(self.shas))
        self.assertEqual(rep['status'], {'formato_no_soportado': 2, 'necesita_ocr': 1, 'ok': 4})
        self.assertEqual(rep['status_referenced'], rep['status'])
        self.assertEqual(rep['format'], {'docx': 1, 'html': 2, 'json': 1, 'ole2': 1, 'pdf': 2})
        self.assertEqual((rep['coverage']['referenced'], rep['coverage']['in_store'], rep['coverage']['lines']), (7, 7, 7))
        pdf = lines[PDF_SHA]
        self.assertEqual((pdf['format'], pdf['status'], pdf['extractor'], pdf['bytes']), ('pdf', 'ok', ex.EXTRACTORS['pdf'], len(PDF)))
        self.assertEqual(TextStore(self.text).get(pdf['text_sha256']), ex.extract(PDF)['text'])
        self.assertEqual(pdf['chars'], len(ex.extract(PDF)['text']))
        self.assertEqual(rep['new_texts'], 4)
        self.assertEqual(sorted(line['status'] for line in lines.values() if line['text_sha256']), ['ok'] * 4)
        self.assertTrue((self.out / 'runs' / f"{rep['run_id']}.json").exists())

    def test_a_second_run_redoes_nothing(self):
        self.go()
        before = {p.name: p.read_bytes() for p in self.out.glob('*.jsonl')}
        rc, rep = self.go()
        self.assertEqual((rc, rep['to_extract'], rep['already_current'], rep['new_texts']), (0, 0, 7, 0))
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.out.glob('*.jsonl')})

    def test_a_fallo_or_an_older_extractor_is_redone(self):
        self.go()
        lines = self.lines()
        lines[PDF_SHA] = {**lines[PDF_SHA], 'status': 'fallo', 'error': 'timeout (300 s)'}
        lines[DOCX_SHA] = {**lines[DOCX_SHA], 'extractor': 'rg-docx==0'}
        write_manifest(self.out, lines)
        rc, rep = self.go()
        self.assertEqual((rc, rep['to_extract']), (0, 2))
        self.assertEqual(self.lines()[PDF_SHA]['status'], 'ok')
        self.assertEqual(self.lines()[DOCX_SHA]['extractor'], 'rg-docx==1')

    def test_a_published_text_is_not_written_again(self):
        self.go()
        lines = self.lines()
        lines[DOCX_SHA] = {**lines[DOCX_SHA], 'extractor': 'rg-docx==0'}  # redone, same text: already on text-mx
        write_manifest(self.out, lines)
        self.text.rename(self.text.with_name('texto-subido'))
        rc, rep = self.go()
        self.assertEqual((rc, rep['new_texts']), (0, 0))
        self.assertFalse(self.text.exists() and any(self.text.rglob('*.txt')))

    def test_a_referenced_raw_missing_from_the_store_fails_coverage(self):
        rows = self.cat / 'ojn-estatal' / '01.jsonl'
        extra = [{'entry_id': 'mx.ojn-estatal:x', 'raw_path': f"sha256/ee/{'e' * 64}.pdf"},
                 {'entry_id': 'mx.ojn-estatal:y', 'raw_path': f'sha256/{PDF_SHA[:2]}/{PDF_SHA}.bin',  # an older version
                  'versions': [{'sha256': 'd' * 64, 'raw_path': f"sha256/dd/{'d' * 64}.pdf", 'retrieved_at': '2026-10-19T00:00:00Z'}]}]
        rows.write_text(rows.read_text(encoding='utf-8') + ''.join(json.dumps(r) + '\n' for r in extra), encoding='utf-8')
        rc, rep = self.go()
        self.assertEqual((rc, rep['coverage']['referenced_without_status']), (3, 2))
        self.assertEqual(rep['coverage']['first']['referenced_without_status'], ['d' * 64, 'e' * 64])

    def test_bytes_that_do_not_match_their_name_get_no_line(self):
        fake = self.raw / 'sha256' / 'aa' / f"{'a' * 64}.html"
        fake.parent.mkdir(parents=True)
        fake.write_bytes(html('ojn_ficha_95983.html'))
        rc, rep = self.go()
        self.assertEqual((rc, rep['coverage']['name_mismatch'], rep['coverage']['stored_without_status']), (3, 1, 1))
        self.assertNotIn('a' * 64, self.lines())

    def test_coverage_counts_what_is_on_disk_not_what_the_loop_believes(self):
        def drops_one(d, lines):
            write_manifest(d, dict(sorted(lines.items())[1:]))
        with mock.patch.object(tr, 'write_manifest', drops_one):
            rc, rep = self.go()
        self.assertEqual((rc, rep['coverage']['stored_without_status'], rep['coverage']['lines']), (3, 1, 6))

    def test_a_raw_with_two_lines_fails_coverage(self):
        def twice(d, lines):
            write_manifest(d, lines)
            first = sorted(Path(d).glob('*.jsonl'))[0]
            first.write_text(first.read_text(encoding='utf-8') * 2, encoding='utf-8')
        with mock.patch.object(tr, 'write_manifest', twice):
            rc, rep = self.go()
        self.assertEqual(rc, 3)
        self.assertGreaterEqual(rep['coverage']['repeated_lines'], 1)

    def test_every_new_text_must_hash_to_its_name(self):
        real_put = TextStore.put

        def corrupt(self_, text):
            sha = real_put(self_, text)
            self_.path(sha).write_bytes(b'otro texto')
            return sha
        with mock.patch.object(TextStore, 'put', corrupt):
            rc, rep = self.go()
        self.assertEqual((rc, rep['coverage']['texts_not_matching']), (3, 4))

    def test_past_the_deadline_nothing_new_starts_and_what_exists_is_written(self):
        rc, rep = self.go(deadline=time.monotonic() - 1)
        self.assertEqual((rc, rep['coverage']['stored_without_status']), (3, 7))
        self.assertTrue((self.out / 'runs' / f"{rep['run_id']}.json").exists())

    def test_a_crash_still_writes_what_was_done(self):
        real = tr.extract_all

        def one_then_crash(paths, *a, **k):
            yield next(real(paths, *a, **k))
            raise RuntimeError('boom')
        with mock.patch.object(tr, 'extract_all', one_then_crash):
            rc, rep = self.go(workers=1)
        self.assertEqual(rc, 1)
        self.assertEqual(len(self.lines()), 1)
        self.assertIn('run crashed: RuntimeError: boom', rep['errors'])

    def test_lines_of_an_older_extractor_fail_coverage_and_keep_their_bundle_open(self):
        # GPT review of #21 (4c71c28): after a version bump cut by the deadline, coverage counted the old lines as
        # present (exit 0) and their bundle was marked done, so a later 'nuevos' run never redid them.
        self.go()
        lines = self.lines()
        lines[DOCX_SHA] = {**lines[DOCX_SHA], 'extractor': 'rg-docx==0'}
        write_manifest(self.out, lines)
        record = Path(self.tmp.name) / 'unpacked.json'
        record.write_text(json.dumps({'bundles': {'a.tar.sha256': {'tars': ['a.tar'], 'raws': [DOCX_SHA, PDF_SHA]}},
                                      'errors': []}), encoding='utf-8')
        done = self.out / 'bundles.json'
        rc, rep = self.go(deadline=time.monotonic() - 1, bundles_done=record)
        self.assertEqual((rc, rep['coverage']['stale_extractor'], rep['coverage']['first']['stale_extractor']),
                         (3, 1, [DOCX_SHA]))
        self.assertNotIn('a.tar.sha256', json.loads(done.read_text(encoding='utf-8')))
        assets = [{'name': 'a.tar.sha256'}, {'name': 'a.tar'}]
        self.assertEqual(bundles.plan(assets, json.loads(done.read_text(encoding='utf-8')), 'nuevos'), ['a.tar.sha256', 'a.tar'])
        rc, rep = self.go(bundles_done=record)  # the next run redoes it: whole again, and the bundle is done
        self.assertEqual((rc, rep['coverage']['stale_extractor']), (0, 0))
        self.assertIn('a.tar.sha256', json.loads(done.read_text(encoding='utf-8')))
        self.assertEqual(bundles.plan(assets, json.loads(done.read_text(encoding='utf-8')), 'nuevos'), [])

    def test_a_line_removed_from_the_manifest_leaves_the_disk(self):
        # Audit of #21 (125f1e3): write_manifest rewrote only the part files that still had rows, so a part whose
        # rows were all removed kept its old lines on disk and coverage counted them.
        a, b = {'raw_sha256': 'a' * 64}, {'raw_sha256': 'b' * 64}
        d = Path(self.tmp.name) / 'm'
        write_manifest(d, {'a' * 64: a, 'b' * 64: b})
        write_manifest(d, {'a' * 64: a})
        self.assertEqual(read_manifest(d), [a])
        self.assertEqual(sorted(p.name for p in d.iterdir()), ['a.jsonl'])

    def test_a_reprocessed_bundle_left_incomplete_loses_its_mark(self):
        # GPT review of #21 (5c164de): a bundle marked done earlier kept its mark when a later run unpacked it again
        # and could not finish it, so a 'nuevos' run never took it again.
        self.go()
        lines = self.lines()
        del lines[DOCX_SHA]
        write_manifest(self.out, lines)
        done = self.out / 'bundles.json'
        done.write_text(json.dumps({'a.tar.sha256': {'tars': ['a.tar'], 'raws': 2, 'run_id': 'antes',
                                                     'extractors': dict(ex.VERSIONS)}}), encoding='utf-8')
        record = Path(self.tmp.name) / 'unpacked.json'
        record.write_text(json.dumps({'bundles': {'a.tar.sha256': {'tars': ['a.tar'], 'raws': [DOCX_SHA, PDF_SHA]}},
                                      'errors': []}), encoding='utf-8')
        rc, _ = self.go(deadline=time.monotonic() - 1, bundles_done=record)
        self.assertEqual(rc, 3)
        self.assertNotIn('a.tar.sha256', json.loads(done.read_text(encoding='utf-8')))

    def test_the_cli_bounds_its_workers_by_memory(self):
        with contextlib.redirect_stdout(io.StringIO()):
            rc = tr.main(['--catalog', str(self.cat), '--raw', str(self.raw), '--out', str(self.out), '--text',
                          str(self.text), '--workers', '100000'])
        [report] = [json.loads(p.read_text(encoding='utf-8')) for p in (self.out / 'runs').glob('*.json')]
        self.assertEqual(rc, 0)
        self.assertEqual(report['workers'], tr.workers_for(100000, tr.MAX_MEMORY))
        self.assertLess(report['workers'], 100000)

    def test_a_bundle_is_done_only_when_all_its_raws_have_a_line(self):
        record = Path(self.tmp.name) / 'unpacked.json'
        record.write_text(json.dumps({'bundles': {'a.tar.sha256': {'tars': ['a.tar'], 'raws': self.shas[:3]},
                                                  'b.tar.sha256': {'tars': ['b.tar'], 'raws': [self.shas[0], 'f' * 64]}},
                                      'errors': []}), encoding='utf-8')
        rc, rep = self.go(bundles_done=record)
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(json.loads((self.out / 'bundles.json').read_text(encoding='utf-8'))), ['a.tar.sha256'])
        record.write_text(json.dumps({'bundles': {}, 'errors': ['c.tar.sha256: ValueError: c.tar: does not match its sha256']}),
                          encoding='utf-8')
        rc, rep = self.go(bundles_done=record)
        self.assertEqual(rc, 3)

    def test_the_catalog_never_reads_the_text_manifest_as_rows(self):
        self.go()
        self.assertTrue(list(self.out.glob('*.jsonl')))
        self.assertIn('texto', catalog_store.DERIVED)
        cat = Catalog(self.cat.parent, 'MX')  # without 'texto' in DERIVED: KeyError 'entry_id'
        self.assertEqual(len(cat.entries), 7)
        self.assertEqual(tr.referenced(self.cat), set(self.shas))


def _tar(members):
    """CONSTRUIDO: a tar from (name, bytes or ('symlink', target))."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w') as t:
        for name, data in members:
            info = tarfile.TarInfo(name)
            if isinstance(data, tuple):
                info.type, info.linkname = tarfile.SYMTYPE, data[1]
                t.addfile(info)
            else:
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class Bundles(unittest.TestCase):
    # Asset names as they are on raw-mx (2026-10-21): a whole tar, a tar hashed whole but uploaded as parts, and parts
    # hashed one by one.
    ASSETS = ['raw-mx-2026-10-19-dof.tar', 'raw-mx-2026-10-19-dof.tar.sha256', 'raw-mx-2026-10-19.tar.part00',
              'raw-mx-2026-10-19.tar.sha256', 'raw-mx-2026-10-21-39644985129-1.tar.part00',
              'raw-mx-2026-10-21-39644985129-1.tar.part01', 'raw-mx-2026-10-21-39644985129-1.tar.sha256']

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d, self.raw = Path(self.tmp.name) / 'bundles', Path(self.tmp.name) / 'raw'
        self.d.mkdir()
        self.good = _tar([(f'./sha256/{PDF_SHA[:2]}/{PDF_SHA}.bin', PDF)])  # the names `tar -C raw -cf - .` gives

    def write(self, name, data):
        (self.d / name).write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    def test_plan_takes_the_bundles_not_done_with_their_files(self):
        assets = [{'name': n} for n in self.ASSETS]
        done = {'raw-mx-2026-10-19-dof.tar.sha256': {'extractors': dict(ex.VERSIONS)}}
        self.assertEqual(bundles.plan(assets, done, 'nuevos'),
                         ['raw-mx-2026-10-19.tar.sha256', 'raw-mx-2026-10-19.tar.part00',
                          'raw-mx-2026-10-21-39644985129-1.tar.sha256', 'raw-mx-2026-10-21-39644985129-1.tar.part00',
                          'raw-mx-2026-10-21-39644985129-1.tar.part01'])
        self.assertEqual(len(bundles.plan(assets, done, 'todos')), 7)
        older = {'raw-mx-2026-10-19-dof.tar.sha256': {'extractors': {**ex.VERSIONS, 'pdf': 'rg-pdf==0'}}}
        self.assertEqual(len(bundles.plan(assets, older, 'nuevos')), 7)  # a version bump reopens a done bundle
        self.assertEqual(ex.VERSIONS, {**ex.EXTRACTORS, 'sniff': ex.SNIFF})  # the detector is part of the signature
        sniffed = {'raw-mx-2026-10-19-dof.tar.sha256': {'extractors': {**ex.VERSIONS, 'sniff': 'rg-sniff==0'}}}
        self.assertEqual(len(bundles.plan(assets, sniffed, 'nuevos')), 7)  # so does the format detector's (GPT, #21)
        self.assertEqual(len(bundles.plan(assets, {'raw-mx-2026-10-19-dof.tar.sha256': {}}, 'nuevos')), 7)
        for bad in ('raw mx.tar.sha256', '*.sha256', '-p.sha256', 'a/../b.sha256'):
            with self.assertRaises(ValueError, msg=bad):
                bundles.plan(assets + [{'name': bad}], {}, 'nuevos')

    def test_nothing_to_do_prints_nothing(self):
        # an empty line in the plan would become `gh release download --pattern ""`: every asset of raw-mx
        a, d = Path(self.tmp.name) / 'assets.json', Path(self.tmp.name) / 'bundles.json'
        a.write_text(json.dumps({'assets': [{'name': n} for n in self.ASSETS]}), encoding='utf-8')
        d.write_text(json.dumps({n: {'extractors': dict(ex.VERSIONS)} for n in self.ASSETS if n.endswith('.sha256')}),
                     encoding='utf-8')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(bundles.main(['plan', '--assets', str(a), '--done', str(d), '--mode', 'nuevos']), 0)
        self.assertEqual(out.getvalue(), '')
        dl = yaml.safe_load((ROOT / '.github' / 'workflows' / 'texto-mx.yml').read_text(encoding='utf-8'))
        run = next(s['run'] for s in dl['jobs']['run']['steps'] if s.get('name', '').startswith('Download the raw bundles'))
        self.assertIn('[ -n "$asset" ] || continue', run)

    def test_a_member_over_the_size_limit_stops_its_bundle_before_it_is_written(self):
        # GPT review of #21 (5c164de): the copy had no size limit; a hostile member could fill the disk.
        h = self.write('w.tar', self.good)
        (self.d / 'w.tar.sha256').write_text(f'{h}  w.tar\n', encoding='utf-8')
        with mock.patch.object(bundles, 'MAX_MEMBER', 1000):
            record = bundles.unpack_all(self.d, self.raw)
        self.assertEqual(record['bundles'], {})
        self.assertEqual(len(record['errors']), 1)
        self.assertIn('over the limit', record['errors'][0])
        self.assertFalse(self.raw.exists() and any(p.is_file() for p in self.raw.rglob('*')))

    def test_the_unpack_budget_spans_every_bundle_of_the_run(self):
        h = self.write('a.tar', self.good)
        (self.d / 'a.tar.sha256').write_text(f'{h}  a.tar\n', encoding='utf-8')
        h = self.write('b.tar', _tar([(f'sha256/{DOCX_SHA[:2]}/{DOCX_SHA}.doc', DOCX)]))
        (self.d / 'b.tar.sha256').write_text(f'{h}  b.tar\n', encoding='utf-8')
        record = bundles.unpack_all(self.d, self.raw, max_total=len(PDF) + len(DOCX) // 2)
        self.assertEqual(sorted(record['bundles']), ['a.tar.sha256'])
        self.assertEqual(len(record['errors']), 1)
        self.assertTrue(record['errors'][0].startswith('b.tar.sha256: ValueError:'), record['errors'][0])
        self.assertFalse((self.raw / 'sha256' / DOCX_SHA[:2] / f'{DOCX_SHA}.doc').exists())

    def test_a_checksum_that_names_a_path_outside_the_folder_opens_and_deletes_nothing(self):
        # GPT review of #21 (eae1bdf): verify() used the names listed in a .sha256 as paths, so '../x.tar' was read
        # (and, with --delete, removed) outside --dir.
        outside = self.d.parent / 'fuera.tar'
        outside.write_bytes(self.good)
        (self.d / 'w.tar.sha256').write_text(f'{hashlib.sha256(self.good).hexdigest()}  ../fuera.tar\n', encoding='utf-8')
        record = bundles.unpack_all(self.d, self.raw, delete=True)
        self.assertEqual(record['bundles'], {})
        self.assertIn('not a plain asset name', record['errors'][0])
        self.assertEqual(outside.read_bytes(), self.good)
        self.assertFalse(self.raw.exists())

    def test_the_three_forms_verify_and_unpack(self):
        h = self.write('w.tar', self.good)
        (self.d / 'w.tar.sha256').write_text(f'{h}  w.tar\n', encoding='utf-8')
        cut = len(self.good) // 2
        self.write('p.tar.part00', self.good[:cut])
        self.write('p.tar.part01', self.good[cut:])
        (self.d / 'p.tar.sha256').write_text(f'{hashlib.sha256(self.good).hexdigest()}  p.tar\n', encoding='utf-8')
        h0, h1 = self.write('q.tar.part00', self.good[:cut]), self.write('q.tar.part01', self.good[cut:])
        (self.d / 'q.tar.sha256').write_text(f'{h0}  q.tar.part00\n{h1}  q.tar.part01\n', encoding='utf-8')
        record = bundles.unpack_all(self.d, self.raw, delete=True)
        self.assertEqual(record['errors'], [])
        self.assertEqual(sorted(record['bundles']), ['p.tar.sha256', 'q.tar.sha256', 'w.tar.sha256'])
        self.assertTrue(all(b['raws'] == [PDF_SHA] for b in record['bundles'].values()))
        self.assertEqual((self.raw / 'sha256' / PDF_SHA[:2] / f'{PDF_SHA}.bin').read_bytes(), PDF)
        self.assertEqual(sorted(p.name for p in self.d.iterdir()), ['p.tar.sha256', 'q.tar.sha256', 'w.tar.sha256'])

    def test_nothing_of_a_bundle_that_does_not_verify_is_unpacked(self):
        cut = len(self.good) // 2
        h = hashlib.sha256(self.good).hexdigest()
        cases = {
            'corrupt whole': ([('a.tar', self.good[:-1] + b'x')], f'{h}  a.tar\n'),
            'corrupt part': ([('a.tar.part00', self.good[:cut]), ('a.tar.part01', self.good[cut:-1] + b'x')],
                             f"{hashlib.sha256(self.good[:cut]).hexdigest()}  a.tar.part00\n{hashlib.sha256(self.good[cut:]).hexdigest()}  a.tar.part01\n"),
            'part not listed': ([('a.tar.part00', self.good[:cut]), ('a.tar.part01', self.good[cut:]), ('a.tar.part02', b'')],
                                f"{hashlib.sha256(self.good[:cut]).hexdigest()}  a.tar.part00\n{hashlib.sha256(self.good[cut:]).hexdigest()}  a.tar.part01\n"),
            'gap in parts': ([('a.tar.part00', self.good[:cut]), ('a.tar.part02', self.good[cut:])],
                             f"{hashlib.sha256(self.good[:cut]).hexdigest()}  a.tar.part00\n{hashlib.sha256(self.good[cut:]).hexdigest()}  a.tar.part02\n"),
            'tar and parts': ([('a.tar', self.good), ('a.tar.part00', self.good)], f'{h}  a.tar\n'),
        }
        for case, (files, sums) in cases.items():
            with self.subTest(case), tempfile.TemporaryDirectory() as t:
                d, raw = Path(t) / 'b', Path(t) / 'raw'
                d.mkdir()
                for name, data in files:
                    (d / name).write_bytes(data)
                (d / 'a.tar.sha256').write_text(sums, encoding='utf-8')
                (d / 'z.tar').write_bytes(self.good)  # another bundle, fine: it still goes through
                (d / 'z.tar.sha256').write_text(f'{h}  z.tar\n', encoding='utf-8')
                record = bundles.unpack_all(d, raw)
                self.assertEqual(len(record['errors']), 1, record)
                self.assertTrue(record['errors'][0].startswith('a.tar.sha256: ValueError'), record['errors'])
                self.assertEqual(list(record['bundles']), ['z.tar.sha256'])

    def test_only_content_addressed_regular_files_are_written(self):
        evil = _tar([(f'../sha256/{PDF_SHA[:2]}/{"1" * 64}.pdf', b'x'), (f'/sha256/{PDF_SHA[:2]}/{"2" * 64}.pdf', b'x'),
                     (f'sha256/zz/{"3" * 64}.pdf', b'x'), (f'sha256/44/{"5" * 64}.pdf', b'x'),
                     (f'sha256/66/{"6" * 64}.pdf', ('symlink', '/etc/passwd')), ('README', b'x'),
                     (f'sha256/{PDF_SHA[:2]}/{PDF_SHA}.bin', PDF)])
        self.write('e.tar', evil)
        shas, skipped = bundles.unpack([self.d / 'e.tar'], self.raw)
        self.assertEqual((shas, skipped), ([PDF_SHA], 6))
        written = sorted(p.relative_to(Path(self.tmp.name)).as_posix() for p in Path(self.tmp.name).rglob('*') if p.is_file() or p.is_symlink())
        self.assertEqual(written, ['bundles/e.tar', f'raw/sha256/{PDF_SHA[:2]}/{PDF_SHA}.bin'])


class Quote(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.texts = TextStore(Path(self.tmp.name) / 'texto')
        self.lines = {}
        for body in (PDF, DOCX):
            r = ex.extract(body)
            line = tr.make_line({**r, 'raw_sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)})
            self.texts.put(r['text'])
            self.lines[line['raw_sha256']] = line

    def ev(self, quote, sha=PDF_SHA, extractor=None):
        return {'raw_sha256': sha, 'extractor': extractor or self.lines[sha]['extractor'], 'quote': quote}

    def test_a_relation_quote_is_found_with_its_page(self):
        problems, loc = quote.check(self.ev('I. Ley. La Ley del Impuesto Especial sobre Producción y Servicios, y'),
                                    self.lines, self.texts)
        self.assertEqual(problems, [])
        self.assertEqual((loc['page_start'], loc['page_end'], loc['occurrences']), (1, 1, 1))
        text = self.texts.get(self.lines[PDF_SHA]['text_sha256'])
        self.assertEqual(text[loc['start']:loc['end']], 'I. Ley. La Ley del Impuesto Especial sobre Producción y Servicios, y')

    def test_the_quote_is_of_the_extracted_text_not_of_the_rendered_page(self):
        # pypdf splits "sobre" on page 4; the quote must copy the text the pinned extractor gives (HIPÓTESIS: how
        # often this happens is not measured yet)
        asis = 'SEGUNDO. Se abroga el Reglamento de la Ley del Impuesto Especial s obre Producción y Servicios'
        problems, loc = quote.check(self.ev(asis), self.lines, self.texts)
        self.assertEqual((problems, loc['page_start']), ([], 4))
        problems, loc = quote.check(self.ev(asis.replace('s obre', 'sobre')), self.lines, self.texts)
        self.assertEqual((len(problems), loc), (1, None))
        self.assertIn('quote not found', problems[0])

    def test_whitespace_is_folded_as_the_contract_folds_it_and_pages_can_be_crossed(self):
        loc = quote.find('se  apliquen.\n Capítulo   II\tREGLAMENTO DE LA LEY', self.texts.get(self.lines[PDF_SHA]['text_sha256']),
                         self.lines[PDF_SHA]['pages'])
        self.assertEqual((loc['page_start'], loc['page_end']), (1, 2))
        text = self.texts.get(self.lines[PDF_SHA]['text_sha256'])
        self.assertEqual(fold(text[loc['start']:loc['end']]), 'se apliquen. Capítulo II REGLAMENTO DE LA LEY')
        loc = quote.find('REGLAMENTO DE LA LEY DEL IMPUESTO ESPECIAL', text)
        self.assertEqual((loc['start'], loc['occurrences']), (0, 6))
        self.assertNotIn('page_start', loc)
        self.assertIsNone(quote.find('   ', text))

    def test_a_docx_quote(self):
        problems, loc = quote.check(self.ev('LIC. JOSE MURAT, GOBERNADOR CONSTITUCIONAL', DOCX_SHA), self.lines, self.texts)
        self.assertEqual(problems, [])
        self.assertNotIn('page_start', loc)

    def test_what_makes_a_quote_uncheckable(self):
        q = 'I. Ley. La Ley del Impuesto Especial sobre Producción y Servicios, y'
        cases = {
            'no line': (self.ev(q, sha='c' * 64, extractor='rg-pdf==1'), self.lines),
            'other extractor': (self.ev(q, extractor='pypdf==6.19.0'), self.lines),
            'no text': (self.ev(q), {PDF_SHA: {**self.lines[PDF_SHA], 'status': 'necesita_ocr', 'text_sha256': None}}),
        }
        for case, (evid, lines) in cases.items():
            problems, loc = quote.check(evid, lines, self.texts)
            self.assertEqual((len(problems), loc), (1, None), case)
        self.texts.path(self.lines[PDF_SHA]['text_sha256']).write_text('I. Ley. La Ley del Impuesto Especial sobre Producción y Servicios, y',
                                                                       encoding='utf-8')  # tampered text file
        problems, loc = quote.check(self.ev(q), self.lines, self.texts)
        self.assertIn('not matching its sha256', problems[0])

    def test_cli_validates_the_document_then_checks_its_evidence(self):
        d = Path(self.tmp.name)
        write_manifest(d / 'm', self.lines)
        rel = {'type': 'reglamenta', 'from': {'entry_id': 'mx.reglamentos-federales:Reg_LIEPS'},
               'to': {'entry_id': 'mx.leyes-federales:LIEPS'}, 'status': 'CANDIDATE',
               'evidence': self.ev('I. Ley. La Ley del Impuesto Especial sobre Producción y Servicios, y')}
        (d / 'rel.json').write_text(json.dumps(rel), encoding='utf-8')
        args = ['relation', str(d / 'rel.json'), '--manifest', str(d / 'm'), '--text', str(self.texts.root)]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(quote.main(args), 0)
            rel['evidence']['quote'] = 'Ley del Impuesto al Valor Agregado'
            (d / 'rel.json').write_text(json.dumps(rel), encoding='utf-8')
            self.assertEqual(quote.main(args), 1)
            rel['evidence']['quote'] = 'I. Ley. La Ley del Impuesto Especial sobre Producción y Servicios, y'
            rel['status'] = 'VERIFIED'  # a quote that is found does not make an invalid document pass
            (d / 'rel.json').write_text(json.dumps(rel), encoding='utf-8')
            self.assertEqual(quote.main(args), 1)
        ce = {'source_id': 'mx.reglamentos-federales', 'entry_id': 'mx.reglamentos-federales:Reg_LIEPS', 'before_ref': 'a' * 64,
              'after_ref': PDF_SHA, 'published_at': '2006-12-04', 'effective_at': None, 'status': 'CANDIDATE',
              'provenance': {'url': 'https://www.diputados.gob.mx/LeyesBiblio/regley/Reg_LIEPS.pdf', 'sha256': PDF_SHA,
                             'retrieved_at': '2026-10-21T00:00:00Z'}}
        (d / 'ce.json').write_text(json.dumps(ce), encoding='utf-8')
        with contextlib.redirect_stdout(out):
            self.assertEqual(quote.main(['change_event', str(d / 'ce.json')] + args[2:]), 0)  # no evidence, nothing to find
        self.assertIn('FOUND evidence: {"end": 1063, "occurrences": 1, "page_end": 1, "page_start": 1, "start": 995}', out.getvalue())


class Workflow(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / '.github' / 'workflows' / 'texto-mx.yml').read_text(encoding='utf-8')
        self.doc = yaml.safe_load(self.text)
        self.job = self.doc['jobs']['run']
        self.steps = self.job['steps']

    def step(self, prefix):
        return next(s for s in self.steps if s.get('name', '').startswith(prefix))

    def test_on_demand_with_the_least_permission(self):
        self.assertEqual(set(self.doc.get('on', self.doc.get(True))), {'workflow_dispatch'})
        self.assertEqual(self.doc['permissions'], {'contents': 'read'})
        self.assertEqual(self.job['permissions'], {'contents': 'write'})
        self.assertEqual(self.job['runs-on'], """${{ fromJSON(vars.CATALOG_RUNS_ON || '"ubuntu-24.04"') }}""")

    def test_actions_pinned_and_no_secret_beyond_the_token(self):
        uses = [s['uses'] for s in self.steps if 'uses' in s]
        self.assertTrue(uses)
        self.assertTrue(all(re.fullmatch(r'[\w.-]+/[\w.-]+@[0-9a-f]{40}', u) for u in uses), uses)
        self.assertNotIn('secrets.', self.text)
        self.assertTrue(all(s['with']['persist-credentials'] is False for s in self.steps if 'checkout@' in s.get('uses', '')))

    def test_our_own_runner_is_never_wiped_and_gets_its_own_python(self):
        self.assertEqual(self.step('Free runner disk')['if'], "runner.environment == 'github-hosted'")
        setup = next(s for s in self.steps if s.get('uses', '').startswith('actions/setup-python@'))
        self.assertEqual(setup['if'], "runner.environment == 'github-hosted'")
        self.assertEqual(self.step('Python on our own runner')['if'], "runner.environment != 'github-hosted'")

    def test_no_token_while_raw_files_are_unpacked_or_parsed(self):
        for prefix in ('Verify every bundle', 'Extract text', 'Tests before'):
            self.assertNotIn('env', self.step(prefix), prefix)

    def test_input_is_checked_before_use(self):
        dl = self.step('Download the raw bundles')
        self.assertEqual(dl['env']['BUNDLES'], '${{ inputs.bundles }}')
        self.assertIn('[[ "$BUNDLES" =~ ^(nuevos|todos)$ ]] || {', dl['run'])

    def test_texts_are_uploaded_before_the_manifest_is_committed(self):
        names = [s.get('name', '') for s in self.steps]
        order = [next(i for i, n in enumerate(names) if n.startswith(p)) for p in
                 ('Tests before', 'Download the raw bundles', 'Verify every bundle', 'Extract text', 'Upload new texts', 'Commit the manifest')]
        self.assertEqual(order, sorted(order))
        up = self.step('Upload new texts')['run']
        self.assertIn('split -b 1900m -d - "$name.part"', up)
        self.assertIn('sha256sum "$name".part* > "$name.sha256"', up)
        self.assertIn('gh release upload text-mx', up)
        commit = self.step('Commit the manifest')['run']
        self.assertIn('git add -A mx/texto\n', commit)  # the bot writes only the text manifest on the data branch
        self.assertNotRegex(commit, r'git add -A\s*\n')


if __name__ == '__main__':
    unittest.main()
