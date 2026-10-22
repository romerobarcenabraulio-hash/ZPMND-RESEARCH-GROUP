"""Raw bundles of the release raw-mx: which ones to download, checked against their .sha256, unpacked safely.

  python -m rg.text.bundles plan --assets assets.json --done data/mx/texto/bundles.json --mode nuevos|todos
  python -m rg.text.bundles unpack --dir bundles --raw raw --record unpacked.json [--delete]

A bundle is one `<tar>.sha256` asset. Its lines hash either each `<tar>.partNN` asset or the whole `<tar>`, whose bytes
are then `<tar>` itself or its parts in order; raw-mx holds both forms (2026-10-21). Nothing of a bundle is unpacked
unless every hash matches, every part on disk is covered by one and the parts run 00, 01, ... without a gap. Only
regular members named sha256/<2>/<sha>.<ext> are written, at the path rebuilt from that name; links, absolute paths,
'..' and any other member are skipped and counted. A member larger than MAX_MEMBER, or than what is left of the run's
unpack budget (MAX_TOTAL, all bundles together), stops its bundle before a byte of it is written: a hostile tar cannot
fill the disk. A bundle that fails goes to `errors` in the record, and the others go on. A bundle counts as done only
for the extractor versions it was done with, so a version bump reopens it even in mode 'nuevos'.
"""
import argparse
import glob
import hashlib
import io
import json
import re
import shutil
import sys
import tarfile
from collections import defaultdict
from pathlib import Path

from .extract import VERSIONS

ASSET = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$')  # asset names reach `gh release download --pattern`
PART = re.compile(r'^(.+)\.part(\d+)$')
MEMBER = re.compile(r'^(?:\./)?sha256/([0-9a-f]{2})/([0-9a-f]{64})\.([a-z0-9]{1,5})$')
CHUNK = 1 << 20
MAX_MEMBER = 200_000_000  # bytes; a raw is at most the catalog's fetch limit (60 MB), so a larger member is no raw
MAX_TOTAL = 40_000_000_000  # bytes unpacked per run, every bundle together: the runner's freed disk; HIPÓTESIS


def is_done(mark):
    """A bundle is done only for the extractor versions it was done with: a version bump reopens it."""
    return isinstance(mark, dict) and mark.get('extractors') == VERSIONS


def plan(assets, done, mode):
    """Names to download: every bundle not done by the current extractors (all of them with mode 'todos'), its
    .sha256 first."""
    names = sorted(a['name'] for a in assets)
    bad = [n for n in names if not ASSET.match(n)]
    if bad:
        raise ValueError(f'unexpected asset names: {bad[:5]}')
    out = []
    for s in (n for n in names if n.endswith('.sha256')):
        if mode == 'nuevos' and is_done(done.get(s)):
            continue
        tar = s[:-len('.sha256')]
        out += [s] + [n for n in names if n == tar or (PART.match(n) and PART.match(n).group(1) == tar)]
    return out


class _Concat(io.RawIOBase):
    """The files, read one after the other as one stream."""
    def __init__(self, paths):
        self.paths, self.fh = list(paths), None

    def readable(self):
        return True

    def readinto(self, b):
        while True:
            if self.fh is None:
                if not self.paths:
                    return 0
                self.fh = open(self.paths.pop(0), 'rb')
            n = self.fh.readinto(b)
            if n:
                return n
            self.fh.close()
            self.fh = None

    def close(self):
        if self.fh:
            self.fh.close()
        super().close()


def _sha(paths):
    h = hashlib.sha256()
    with io.BufferedReader(_Concat(paths), CHUNK) as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b''):
            h.update(chunk)
    return h.hexdigest()


def _parts(d, tar):
    found = [p for p in d.glob(glob.escape(tar) + '.part*') if PART.match(p.name) and PART.match(p.name).group(1) == tar]
    return sorted(found, key=lambda p: int(PART.match(p.name).group(2)))


def verify(sums):
    """[(tar, [files in order])] of one .sha256 file, or ValueError naming what does not match."""
    d = Path(sums).parent
    listed = {}
    for line in Path(sums).read_text(encoding='utf-8').splitlines():
        if line.strip():
            h, name = line.split(None, 1)
            name = name.strip().lstrip('*')
            if not ASSET.fullmatch(name):  # a bare asset name: no '/', no '..', nothing outside --dir is opened
                raise ValueError(f'{Path(sums).name}: lists a name that is not a plain asset name')
            listed[name] = h.lower()
    groups = defaultdict(list)
    for name in listed:
        m = PART.match(name)
        groups[m.group(1) if m else name].append(name)
    out = []
    for tar, names in sorted(groups.items()):
        parts = _parts(d, tar)
        if names == [tar]:  # one hash for the whole tar
            if (d / tar).is_file() and parts:
                raise ValueError(f'{tar}: both the tar and parts of it are on disk')
            files = [d / tar] if (d / tar).is_file() else parts
            if not files or _sha(files) != listed[tar]:
                raise ValueError(f'{tar}: does not match its sha256')
        else:  # one hash per part
            files = sorted((d / n for n in names), key=lambda p: int(PART.match(p.name).group(2)) if PART.match(p.name) else -1)
            if [p.name for p in parts] != [p.name for p in files]:
                raise ValueError(f'{tar}: parts on disk {[p.name for p in parts]} are not the parts listed')
            for f in files:
                if _sha([f]) != listed[f.name]:
                    raise ValueError(f'{f.name}: does not match its sha256')
        numbers = [int(PART.match(f.name).group(2)) for f in files if PART.match(f.name)]
        if numbers and numbers != list(range(len(numbers))):
            raise ValueError(f'{tar}: parts {numbers} do not run from 00 without a gap')
        out.append((tar, files))
    return out


def unpack(files, raw, budget=None):
    """Write the raw files of one tar (its parts in order) under raw/; returns (raw shas, members skipped). `budget`
    ({'left': bytes}) is shared by every bundle of the run; a member over MAX_MEMBER or over what is left raises."""
    raw, shas, skipped = Path(raw), [], 0
    budget = {'left': MAX_TOTAL} if budget is None else budget
    with io.BufferedReader(_Concat(files), CHUNK) as fh, tarfile.open(fileobj=fh, mode='r|') as tar:
        for m in tar:
            if m.isdir():
                continue
            g = MEMBER.match(m.name)
            if not (m.isreg() and g and g.group(1) == g.group(2)[:2]):
                skipped += 1
                continue
            path = raw / 'sha256' / g.group(1) / f'{g.group(2)}.{g.group(3)}'
            if not path.exists():
                if m.size > MAX_MEMBER or m.size > budget['left']:  # checked on the header, before writing anything
                    raise ValueError(f'{m.name}: {m.size} bytes, over the limit '
                                     f'({MAX_MEMBER} per member, {budget["left"]} left in the run)')
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_name(path.name + '.part')
                with tar.extractfile(m) as src, open(tmp, 'wb') as dst:
                    shutil.copyfileobj(src, dst, CHUNK)
                tmp.replace(path)
                budget['left'] -= m.size
            shas.append(g.group(2))
    return shas, skipped


def unpack_all(d, raw, delete=False, max_total=MAX_TOTAL):
    record, budget = {'bundles': {}, 'errors': []}, {'left': max_total}
    for sums in sorted(Path(d).glob('*.sha256')):
        try:
            tars = verify(sums)
            shas, skipped = set(), 0
            for _, files in tars:
                got, n = unpack(files, raw, budget)
                shas.update(got)
                skipped += n
        except (ValueError, OSError, tarfile.TarError) as e:
            record['errors'].append(f'{sums.name}: {type(e).__name__}: {e}')
            continue
        record['bundles'][sums.name] = {'tars': [t for t, _ in tars], 'raws': sorted(shas), 'skipped_members': skipped}
        if delete:
            for _, files in tars:
                for f in files:
                    f.unlink()
    return record


def main(argv=None):
    ap = argparse.ArgumentParser(description='raw-mx bundles: plan the download, verify and unpack')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('plan')
    p.add_argument('--assets', required=True, help='output of `gh release view raw-mx --json assets`')
    p.add_argument('--done', required=True, help='bundles.json of the manifest (absent = none done)')
    p.add_argument('--mode', choices=('nuevos', 'todos'), default='nuevos')
    u = sub.add_parser('unpack')
    u.add_argument('--dir', required=True)
    u.add_argument('--raw', required=True)
    u.add_argument('--record', required=True)
    u.add_argument('--delete', action='store_true', help='delete each bundle once unpacked (disk)')
    x = ap.parse_args(argv)
    if x.cmd == 'plan':
        done = json.loads(Path(x.done).read_text(encoding='utf-8')) if Path(x.done).exists() else {}
        names = plan(json.loads(Path(x.assets).read_text(encoding='utf-8'))['assets'], done, x.mode)
        if names:  # nothing to do prints nothing: an empty line would read as `--pattern ""`, every asset
            print('\n'.join(names))
        return 0
    record = unpack_all(x.dir, x.raw, x.delete)
    Path(x.record).write_text(json.dumps(record, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    for e in record['errors']:
        print('ERROR', e)
    print(json.dumps({b: len(r['raws']) for b, r in record['bundles'].items()}, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
