"""Every raw a catalog row points to is published: a texto line or a ledger sha (SECURITY.md T30, the 1,166 rows of
2026-10-19/20). `--catalog data/mx` exits 5 on a lost raw; `--publicar RAW` writes RAW's verified tar to stdout."""
import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tarfile
from pathlib import Path

from ..schemas import validate
from .store import row_files

RAW_PATH = re.compile(r'^sha256/([0-9a-f]{2})/([0-9a-f]{64})\.[a-z0-9]{1,5}$')
SHA = re.compile(r'^[0-9a-f]{64}$')
LEDGER = Path('raw') / 'publicados.txt'
SAMPLE = 20  # rels named in a report; the count is always whole


def referencias(country_dir):
    """({sha256: raw_path}, [lost], rows): only a valid catalog_entry with content-address raw_paths counts (GPT, 5521f27)."""
    refs, bad, n = {}, [], 0
    d = Path(country_dir)
    if not d.is_dir():  # a wrong path is never a catalog with nothing to check (GPT on 2c55288)
        raise ValueError(f'{d}: not a catalog folder')
    for f in row_files(d):
        for k, line in enumerate(f.read_text(encoding='utf-8').splitlines(), 1):
            if line.strip():
                e, n = json.loads(line), n + 1
                if errs := validate('catalog_entry', e):
                    bad.append(f'{f.name}:{k}: {errs[0][:200]}')
                    continue
                for rp in filter(None, [e.get('raw_path')] + [v['raw_path'] for v in e.get('versions', [])]):  # the schema: stored has one
                    m = RAW_PATH.fullmatch(rp)
                    if m and m.group(1) == m.group(2)[:2]:
                        refs.setdefault(m.group(2), rp)
                    else:
                        bad.append(f'{f.name}: {str(rp)[:200]!r}')
    return refs, bad, n


def _crudo(raw_root, rel):
    """A regular file reached through no symbolic link at all: tar keeps a link, not its bytes (GPT on 2d88340)."""
    p = Path(raw_root)
    if os.path.islink(p):  # the root itself too (GPT on 2c55288)
        return False
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
                if not (isinstance(sha, str) and SHA.fullmatch(sha)):
                    raise ValueError(f'{f.name}:{n}: raw_sha256 is not a sha256')
                out.add(sha)
    ledger = d / LEDGER
    if ledger.exists():
        for n, line in enumerate(ledger.read_text(encoding='utf-8').splitlines(), 1):
            if not SHA.fullmatch(line):
                raise ValueError(f'{LEDGER}:{n}: not a sha256')
            out.add(line)
    return out


def faltan(country_dir, raw_root=None):
    """{'por_publicar': [raw_path on disk, not published], 'perdidos': [raw_path neither published nor on disk]}."""
    pub = publicados(country_dir)
    refs, malformadas, _ = referencias(country_dir)
    por_publicar, perdidos = [], list(malformadas)
    for sha, rp in sorted(refs.items()):
        if sha in pub:
            continue
        on_disk = raw_root is not None and _crudo(raw_root, rp)
        (por_publicar if on_disk else perdidos).append(rp)
    return {'por_publicar': por_publicar, 'perdidos': perdidos}


class _Leido:
    """The bytes tarfile copies, hashed as they pass: what is written is what is checked (GPT on e100e9c)."""
    def __init__(self, fh):
        self.fh, self.h = fh, hashlib.sha256()

    def read(self, n=-1):
        self.h.update(b := self.fh.read(n))
        return b


def crudos(raw_root):
    """Content addresses under raw_root that are regular files reached without links, sorted."""
    rels = (f'sha256/{p.parent.name}/{p.name}' for p in Path(raw_root).glob('sha256/*/*'))
    return sorted(r for r in rels if (m := RAW_PATH.fullmatch(r)) and m.group(1) == m.group(2)[:2] and _crudo(raw_root, r))


def empaquetar(destino, raw_root, rels):
    """Tar of rels to destino (path or stream), each a linkless regular file whose bytes, hashed as written, are its name."""
    shas = []
    with (tarfile.open(destino, 'w') if isinstance(destino, (str, Path)) else tarfile.open(fileobj=destino, mode='w|')) as tar:
        for rel in rels:
            m = RAW_PATH.fullmatch(rel)
            if not (m and m.group(1) == m.group(2)[:2]):
                raise ValueError(f'{rel!r} is not a content address')
            fd = os.open(Path(raw_root) / rel, os.O_RDONLY | os.O_NOFOLLOW)  # a link is refused here, not followed
            with os.fdopen(fd, 'rb') as fh:
                st = os.fstat(fh.fileno())
                if not (stat.S_ISREG(st.st_mode) and _crudo(raw_root, rel)):
                    raise ValueError(f'{rel}: not a regular file reached without links')
                info, src = tarfile.TarInfo(rel), _Leido(fh)
                info.size, info.mode, info.mtime = st.st_size, 0o644, int(st.st_mtime)
                tar.addfile(info, src)
                if src.h.hexdigest() != m.group(2):
                    raise ValueError(f'{rel}: its bytes hash to {src.h.hexdigest()}')
            shas.append(m.group(2))
    return shas


def anotar(country_dir, shas):
    """Add shas (the members of a bundle empaquetar wrote) to the ledger; returns how many were new."""
    ledger = Path(country_dir) / LEDGER
    old = set(ledger.read_text(encoding='utf-8').splitlines()) if ledger.exists() else set()
    if set(shas) - old:
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(''.join(f'{s}\n' for s in sorted(old | set(shas))), encoding='utf-8')
    return len(set(shas) - old)


def main(argv=None):
    a = argparse.ArgumentParser(description='every raw a catalog row points to is published')
    a.add_argument('--catalog', required=True, help='country folder of the data branch, e.g. data/mx')
    a.add_argument('--publicar', metavar='RAW', help='write the verified tar of RAW to stdout and add it to the ledger')
    x = a.parse_args(argv)
    if not (Path(x.catalog).is_dir() and referencias(x.catalog)[2]):
        print(f'{x.catalog}: no catalog rows there', file=sys.stderr)  # a wrong path, no files, empty files (GPT on 65b74f5)
        return 2
    if x.publicar:  # only publishes: a loss found elsewhere never stops this upload; the gate step decides the commit
        shas = empaquetar(sys.stdout.buffer, x.publicar, crudos(x.publicar))
        print(json.dumps({'publicados': len(shas), 'nuevos': anotar(x.catalog, shas)}), file=sys.stderr)
        return 0
    r = faltan(x.catalog)
    print(json.dumps({'perdidos': len(r['perdidos']), 'muestra': r['perdidos'][:SAMPLE]}))
    return 5 if r['perdidos'] else 0


if __name__ == '__main__':
    sys.exit(main())
