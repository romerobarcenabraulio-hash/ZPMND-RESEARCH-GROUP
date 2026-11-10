"""Every raw a catalog row points to must be published (SECURITY.md T30).

2026-11-09: 1,166 rows of mx (698 DOF notes, 318 federal laws, 150 regulations) said raw_status 'stored' while no raw-mx
bundle held their bytes. The runs of 2026-10-19/20 were made by hand on one disk; earlier test attempts had left those
files there, the store did not count them as new, and the bundle held only the files new to that run. The catalog
was committed with the rows; the bytes stayed on that disk. Nothing compared the rows with what was published.

Published means one of:
- a line in <country>/texto/*.jsonl: texto-mx writes one per member of every bundle it read (one status per raw);
- a sha256 in <country>/raw/publicados.txt: the members of each bundle catalog-mx uploads, written at upload time,
  before texto-mx has read that bundle.

    python -m rg.catalog.publicado --catalog data/mx                 # exit 5 if a row points to an unpublished raw
    python -m rg.catalog.publicado --catalog data/mx --anotar raw    # add the raw files under raw to the ledger

A bundle is made of what the rows point to and is not published yet (`por_publicar`), never of what one process
remembers writing: a disk kept between runs (a worker, a manual run) holds files that are not new and still unpublished.
"""
import argparse
import json
import re
import sys
import tarfile
from pathlib import Path

from .store import row_files

RAW_PATH = re.compile(r'^sha256/([0-9a-f]{2})/([0-9a-f]{64})\.[a-z0-9]{1,5}$')
SHA = re.compile(r'^[0-9a-f]{64}$')
LEDGER = Path('raw') / 'publicados.txt'
SAMPLE = 20  # rels named in a report; the count is always whole


def referencias(country_dir):
    """{sha256: raw_path} of every raw a row points to: its raw_path and every version's raw_path."""
    refs = {}
    d = Path(country_dir)
    if not d.is_dir():
        return refs
    for f in row_files(d):
        for line in f.read_text(encoding='utf-8').splitlines():
            if line.strip():
                e = json.loads(line)
                for rp in [e.get('raw_path')] + [v.get('raw_path') for v in e.get('versions', [])]:
                    m = RAW_PATH.match(rp or '')
                    if m and m.group(1) == m.group(2)[:2]:
                        refs.setdefault(m.group(2), rp)
    return refs


def publicados(country_dir):
    """sha256 of every published raw: texto lines and the ledger. A malformed sha in either stops the check."""
    d, out = Path(country_dir), set()
    for f in sorted((d / 'texto').glob('*.jsonl')):
        for n, line in enumerate(f.read_text(encoding='utf-8').splitlines(), 1):
            if line.strip():
                sha = json.loads(line).get('raw_sha256')
                if not (isinstance(sha, str) and SHA.match(sha)):
                    raise ValueError(f'{f.name}:{n}: raw_sha256 is not a sha256')
                out.add(sha)
    ledger = d / LEDGER
    if ledger.exists():
        for n, line in enumerate(ledger.read_text(encoding='utf-8').splitlines(), 1):
            if not SHA.match(line):
                raise ValueError(f'{LEDGER}:{n}: not a sha256')
            out.add(line)
    return out


def faltan(country_dir, raw_root=None):
    """{'por_publicar': [raw_path on disk, not published], 'perdidos': [raw_path neither published nor on disk]}."""
    pub = publicados(country_dir)
    por_publicar, perdidos = [], []
    for sha, rp in sorted(referencias(country_dir).items()):
        if sha in pub:
            continue
        on_disk = raw_root is not None and (Path(raw_root) / rp).is_file()
        (por_publicar if on_disk else perdidos).append(rp)
    return {'por_publicar': por_publicar, 'perdidos': perdidos}


def empaquetar(bundle, raw_root, rels):
    """Write the tar of `rels` (faltan(...)['por_publicar']: on disk, pointed to, not published) under raw_root."""
    with tarfile.open(bundle, 'w') as tar:
        for rel in rels:
            tar.add(Path(raw_root) / rel, arcname=rel)


def anotar(country_dir, raw_root):
    """Add to the ledger the sha256 of every raw file under raw_root (the members of the bundle just uploaded)."""
    new = set()
    for p in Path(raw_root).glob('sha256/*/*'):
        m = RAW_PATH.match(f'sha256/{p.parent.name}/{p.name}')
        if m and p.is_file() and m.group(1) == m.group(2)[:2]:
            new.add(m.group(2))
    ledger = Path(country_dir) / LEDGER
    old = set(ledger.read_text(encoding='utf-8').splitlines()) if ledger.exists() else set()
    if new - old:
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(''.join(f'{s}\n' for s in sorted(old | new)), encoding='utf-8')
    return len(new - old)


def main(argv=None):
    a = argparse.ArgumentParser(description='every raw a catalog row points to is published')
    a.add_argument('--catalog', required=True, help='country folder of the data branch, e.g. data/mx')
    a.add_argument('--anotar', metavar='RAW', help='add the raw files under RAW to the ledger, then check')
    x = a.parse_args(argv)
    if x.anotar:
        print(json.dumps({'anotados': anotar(x.catalog, x.anotar)}))
    r = faltan(x.catalog)
    print(json.dumps({'perdidos': len(r['perdidos']), 'muestra': r['perdidos'][:SAMPLE]}))
    return 5 if r['perdidos'] else 0


if __name__ == '__main__':
    sys.exit(main())
