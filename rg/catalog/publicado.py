"""Every raw a catalog row points to must be published (SECURITY.md T30: the 1,166 mx rows of 2026-10-19/20 said
'stored' while their bytes, left on a manual run's disk by test attempts, were never in a bundle).

Published = a line in <country>/texto/*.jsonl (texto-mx writes one per bundle member it read) or a sha256 in
<country>/raw/publicados.txt (written by catalog-mx when it uploads a bundle). A bundle holds what the rows point to
and is unpublished, never what one process remembers writing.

    python -m rg.catalog.publicado --catalog data/mx [--anotar raw]    # exit 5 if a row points to an unpublished raw
"""
import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tarfile
from pathlib import Path

from .store import row_files

RAW_PATH = re.compile(r'^sha256/([0-9a-f]{2})/([0-9a-f]{64})\.[a-z0-9]{1,5}$')
SHA = re.compile(r'^[0-9a-f]{64}$')
LEDGER = Path('raw') / 'publicados.txt'
SAMPLE = 20  # rels named in a report; the count is always whole


def referencias(country_dir):
    """({sha256: raw_path}, [malformed]) over each row's raw_path and its versions'; malformed counts as lost (GPT, 2d88340)."""
    refs, bad = {}, []
    d = Path(country_dir)
    if not d.is_dir():
        return refs, bad
    for f in row_files(d):
        for line in f.read_text(encoding='utf-8').splitlines():
            if line.strip():
                e = json.loads(line)
                for rp in [e.get('raw_path')] + [v.get('raw_path') for v in e.get('versions', [])]:
                    if rp is None or rp == '':
                        continue
                    m = RAW_PATH.match(rp) if isinstance(rp, str) else None
                    if m and m.group(1) == m.group(2)[:2]:
                        refs.setdefault(m.group(2), rp)
                    else:
                        bad.append(f'{f.name}: {str(rp)[:200]!r}')
    return refs, bad


def _crudo(raw_root, rel):
    """A regular file reached through no symbolic link at all: tar keeps a link, not its bytes (GPT on 2d88340)."""
    p = Path(raw_root)
    for part in Path(rel).parts:
        p = p / part
        try:
            mode = os.lstat(p).st_mode
        except OSError:
            return False
        if stat.S_ISLNK(mode):
            return False
    return stat.S_ISREG(mode)


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
    refs, malformadas = referencias(country_dir)
    por_publicar, perdidos = [], list(malformadas)
    for sha, rp in sorted(refs.items()):
        if sha in pub:
            continue
        on_disk = raw_root is not None and _crudo(raw_root, rp)
        (por_publicar if on_disk else perdidos).append(rp)
    return {'por_publicar': por_publicar, 'perdidos': perdidos}


def empaquetar(bundle, raw_root, rels):
    """Write the tar of `rels` (faltan(...)['por_publicar']: on disk, pointed to, not published) under raw_root."""
    with tarfile.open(bundle, 'w') as tar:
        for rel in rels:
            m = RAW_PATH.match(rel)
            if not (m and m.group(1) == m.group(2)[:2]):
                raise ValueError(f'{rel!r} is not a content address')
            fd = os.open(Path(raw_root) / rel, os.O_RDONLY | os.O_NOFOLLOW)  # a link is refused here, not followed
            with os.fdopen(fd, 'rb') as fh:
                st = os.fstat(fh.fileno())
                if not (stat.S_ISREG(st.st_mode) and _crudo(raw_root, rel)):
                    raise ValueError(f'{rel}: not a regular file reached without links')
                h = hashlib.file_digest(fh, 'sha256')  # streamed, never the whole raw in memory
                if h.hexdigest() != m.group(2):
                    raise ValueError(f'{rel}: its bytes hash to {h.hexdigest()}')
                fh.seek(0)
                info = tarfile.TarInfo(rel)
                info.size, info.mode, info.mtime = st.st_size, 0o644, int(st.st_mtime)
                tar.addfile(info, fh)  # the bytes just hashed, from the same open file


def anotar(country_dir, raw_root):
    """Add to the ledger the sha256 of every raw file under raw_root (the members of the bundle just uploaded)."""
    new = set()
    for p in Path(raw_root).glob('sha256/*/*'):
        rel = f'sha256/{p.parent.name}/{p.name}'
        m = RAW_PATH.match(rel)
        if m and m.group(1) == m.group(2)[:2] and _crudo(raw_root, rel):
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
