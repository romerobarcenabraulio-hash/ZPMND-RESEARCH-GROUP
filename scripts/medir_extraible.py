"""Measure how much of the raw store has extractable text (read-only, no network). Prints JSON to stdout.

    python scripts/medir_extraible.py work/raw --catalog work/catalog/mx [--sample 300] [--seed 20261021]

Every file: count by extension and by magic bytes. HTML: visible characters (tags, script and style removed).
PDF: a fixed-seed random sample, each read with pypdf; a page "has text" when its text layer gives at least
MIN_CHARS non-blank characters, and the text is "legible" when at least MIN_LEGIBLE of those characters are
Latin letters, digits or common punctuation (a garbled font map gives text that is not). Needs pypdf (pinned in
requirements-dev.txt for rg.text); this is a measurement, not a guard. Same store, sample size and seed = same output.
Files that iCloud evicted from the disk (macOS "dataless" flag) are counted apart and never opened: opening one
starts a download, and this measurement runs without network.
"""
import argparse
import json
import math
import os
import random
import re
import sys
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path

MIN_CHARS = 30
MIN_LEGIBLE = 0.9
MAX_PAGES = 40  # pages read per PDF, evenly spaced; enough to tell text from scan, bounded time (REGLAS 13)
LEGIBLE = re.compile(r"[A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ.,;:()\-\"'/%$°ºª¿?¡!]")
DATALESS = 0x40000000  # macOS SF_DATALESS: the bytes are not on this disk
MAGIC = ((b'%PDF', 'pdf'), (b'\xd0\xcf\x11\xe0', 'ole2 (doc)'), (b'PK\x03\x04', 'zip (docx)'), (b'{\\rtf', 'rtf'))


def magic(path):
    with path.open('rb') as fh:
        head = fh.read(1024)
    for sig, name in MAGIC:
        if head.lstrip()[:len(sig)] == sig:
            return name
    return 'html' if re.search(rb'<(!doctype|html|head|body|p|div|table)\b', head, re.I) else 'otro'


class _Visible(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip, self.n = 0, 0

    def handle_starttag(self, tag, attrs):
        self.skip += tag in ('script', 'style')

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.n += len(''.join(data.split()))


def html_visible_chars(path):
    p = _Visible()
    body = path.read_bytes()
    try:
        text = body.decode('utf-8')
    except UnicodeDecodeError:
        text = body.decode('cp1252', errors='replace')
    p.feed(text)
    return p.n


def pdf_class(path, PdfReader):
    try:
        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted and not reader.decrypt(''):
            return {'clase': 'cifrado', 'paginas': 0, 'paginas_sin_texto_estimadas': 0}
        total = len(reader.pages)
        if not total:
            return {'clase': 'error', 'paginas': 0, 'paginas_sin_texto_estimadas': 0}
        idx = sorted({round(i * (total - 1) / max(1, MAX_PAGES - 1)) for i in range(min(total, MAX_PAGES))})
        with_text, chars, legible = 0, 0, 0
        for i in idx:
            text = ''.join((reader.pages[i].extract_text() or '').split())
            if len(text) >= MIN_CHARS:
                with_text += 1
            chars += len(text)
            legible += len(LEGIBLE.findall(text))
    except Exception as e:  # a broken file is a measured outcome, not a crash
        return {'clase': 'error', 'error': type(e).__name__, 'paginas': 0, 'paginas_sin_texto_estimadas': 0}
    share = with_text / len(idx)
    if share >= 0.9:
        cls = 'texto' if chars and legible / chars >= MIN_LEGIBLE else 'texto_ilegible'
    elif share <= 0.1:
        cls = 'escaneado'
    else:
        cls = 'mixto'
    return {'clase': cls, 'paginas': total, 'paginas_sin_texto_estimadas': round(total * (1 - share))}


def wilson(k, n, z=1.96):
    if not n:
        return [0.0, 0.0]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def source_by_sha(catalog):
    out = {}
    if not catalog:
        return out
    for f in sorted(Path(catalog).rglob('*.jsonl')):
        for line in f.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            for rp in [e.get('raw_path')] + [v.get('raw_path') for v in e.get('versions', [])]:
                if rp:
                    out.setdefault(Path(rp).stem, e['source_id'])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('raw')
    ap.add_argument('--catalog')
    ap.add_argument('--sample', type=int, default=300)
    ap.add_argument('--seed', type=int, default=20261021)
    x = ap.parse_args(argv)
    from pypdf import PdfReader, __version__ as pypdf_version
    every = sorted(p for p in Path(x.raw).glob('sha256/*/*') if p.is_file() and not p.name.endswith('.part'))
    evicted = {p for p in every if getattr(p.stat(), 'st_flags', 0) & DATALESS}
    files = [p for p in every if p not in evicted]
    src = source_by_sha(x.catalog)
    by_ext = Counter(p.suffix.lstrip('.') for p in files)
    ext_vs_magic = Counter(f'{p.suffix.lstrip(".")} -> {magic(p)}' for p in files)
    pdfs = [p for p in files if p.suffix == '.pdf']
    pdf_by_source = Counter(src.get(p.stem, '(sin fila en el catálogo)') for p in pdfs)
    html = [p for p in files if p.suffix in ('.html', '.htm')]
    vis = sorted(html_visible_chars(p) for p in html)
    sample = sorted(random.Random(x.seed).sample(pdfs, min(x.sample, len(pdfs))))
    per_class, per_source, pages, untexted, errors = Counter(), defaultdict(Counter), Counter(), Counter(), Counter()
    for p in sample:
        r = pdf_class(p, PdfReader)
        per_class[r['clase']] += 1
        per_source[src.get(p.stem, '(sin fila en el catálogo)')][r['clase']] += 1
        pages[r['clase']] += r['paginas']
        untexted[r['clase']] += r['paginas_sin_texto_estimadas']
        if 'error' in r:
            errors[r['error']] += 1
    n = len(sample)
    need_ocr = per_class['escaneado'] + per_class['mixto'] + per_class['texto_ilegible']
    print(json.dumps({
        'archivos': len(every),
        'no_en_disco_icloud': dict(Counter(p.suffix.lstrip('.') for p in evicted).most_common()),
        'por_extension_en_disco': dict(by_ext.most_common()),
        'extension_vs_bytes_iniciales': dict(sorted(ext_vs_magic.items())),
        'html': {'archivos': len(html), 'con_menos_de_200_caracteres_visibles': sum(v < 200 for v in vis),
                 'mediana_caracteres_visibles': vis[len(vis) // 2] if vis else 0},
        'pdf': {
            'archivos': len(pdfs), 'por_fuente': dict(pdf_by_source.most_common()),
            'muestra': {'tamano': n, 'semilla': x.seed, 'pypdf': pypdf_version, 'min_caracteres_por_pagina': MIN_CHARS,
                        'min_legible': MIN_LEGIBLE, 'max_paginas_leidas': MAX_PAGES,
                        'por_clase': dict(per_class.most_common()), 'errores': dict(errors.most_common()),
                        'por_fuente': {s: dict(c.most_common()) for s, c in sorted(per_source.items())},
                        'paginas_por_clase': dict(pages.most_common()),
                        'paginas_sin_texto_estimadas': sum(untexted.values()),
                        'paginas_sin_texto_extrapoladas': round(sum(untexted.values()) * len(pdfs) / n) if n else 0,
                        'necesitan_ocr': need_ocr, 'necesitan_ocr_ic95': wilson(need_ocr, n)},
        },
    }, ensure_ascii=False, indent=1, sort_keys=False))


if __name__ == '__main__':
    sys.exit(main())
