"""Main's packet gate on the packet folders a PR head changes, read as data (auditor.yml, job packet-gate).

    python scripts/packet_gate.py --base origin/main --sha <40 hex> --data <empty dir> --out packets.json

Runs main's rg.packets, never the PR's. The head's research-packets/<RP>/ trees are listed with git ls-tree and each
blob is written with git cat-file, byte for byte: no checkout, no PR code run, and no archive (git archive applies the
head's own export-subst and export-ignore attributes, so it could hand the gate bytes or a file list that are not the
head's). A folder whose tree holds anything but regular files (a link, a submodule), a blob over MAX_BLOB or a head over
MAX_TOTAL is not written and fails. Every changed folder that still exists gets rg.packets.check; it passes only with no
problem and no warning (--strict). Any error is that folder's failed result, and packets.json is always written: it
names the head and, for each folder, its result and, only when it passed, the path and sha256 of each raw file.
audit-gpt reads it as a TRUSTED section: a raw listed there arrives in the diff as one line instead of its bytes.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # main's rg, from main's checkout

from rg.packets import check  # noqa: E402

SHA = re.compile(r'^[0-9a-f]{40}$')
PACKET = re.compile(r'^RP-[A-Za-z0-9._-]{3,64}$')
REGULAR = ('100644', '100755')
MAX_BLOB = 100_000_000  # bytes of one file of a packet
MAX_TOTAL = 500_000_000  # bytes written for one head, all packets together


def git(*args, repo='.'):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, timeout=300).stdout


def changed(base, sha, repo='.'):
    """Packet folders the head changes against the merge base with base (names checked, sorted)."""
    names = git('diff', '--name-only', '-z', f'{base}...{sha}', '--', 'research-packets/', repo=repo).split(b'\0')
    folders = {n.decode('utf-8', 'replace').split('/')[1] for n in names if n.count(b'/') >= 2}
    return sorted(f for f in folders if PACKET.match(f))


def tree(sha, rp, repo='.'):
    """[(mode, type, object, size, path)] of every entry under research-packets/<rp> in the head, recursively."""
    out = git('ls-tree', '-r', '-l', '-z', '--full-tree', sha, '--', f'research-packets/{rp}', repo=repo)
    rows = []
    for item in filter(None, out.split(b'\0')):
        meta, path = item.split(b'\t', 1)
        mode, kind, obj, size = meta.decode().split()
        rows.append((mode, kind, obj, int(size) if size.isdigit() else -1, path.decode('utf-8', 'replace')))
    return rows


def write_blobs(rows, rp, data, repo='.'):
    """Each blob into data at its path, byte for byte as git stores it (sizes were checked from the tree)."""
    for _, _, obj, _, path in rows:
        parts = PurePosixPath(path).parts
        if parts[:2] != ('research-packets', rp) or '..' in parts:
            raise ValueError(f'{path}: outside its packet folder')
        dest = Path(data).joinpath(*parts)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open('wb') as fh:
            subprocess.run(['git', '-C', str(repo), 'cat-file', 'blob', obj], stdout=fh, check=True, timeout=300)
    return Path(data) / 'research-packets' / rp


def one(sha, rp, data, budget, repo='.'):
    """(result, bytes written) for one changed packet folder; an error is a failed result."""
    try:
        rows = tree(sha, rp, repo)
        if not rows:
            return {'packet': rp, 'status': 'removed'}, 0
        odd = [p for mode, kind, _, _, p in rows if mode not in REGULAR or kind != 'blob']
        big = [p for *_, size, p in rows if not 0 <= size <= MAX_BLOB]
        total = sum(max(size, 0) for *_, size, _ in rows)
        problems = ([f'{p}: not a regular file' for p in odd] + [f'{p}: larger than {MAX_BLOB} bytes' for p in big]
                    + ([f'{total} bytes: over the {budget} left for this head'] if total > budget else []))
        if problems:
            return {'packet': rp, 'status': 'failed', 'problems': problems}, 0
        folder = write_blobs(rows, rp, data, repo)
        problems, warnings, stats = check(folder)
    except Exception as e:  # noqa: BLE001 - whatever breaks, the folder fails and packets.json is still written
        return {'packet': rp, 'status': 'failed', 'problems': [f'the gate did not finish: {type(e).__name__}']}, 0
    ok = not problems and not warnings
    raws = {}
    if ok:
        for f in sorted((folder / 'raw').rglob('*')):
            if f.is_file():
                raws[f'research-packets/{rp}/{f.relative_to(folder).as_posix()}'] = hashlib.sha256(f.read_bytes()).hexdigest()
    return {'packet': rp, 'status': 'passed' if ok else 'failed', 'problems': problems, 'warnings': warnings,
            'stats': stats, 'raws': raws}, total


def gate(base, sha, data, repo='.'):
    results, budget = [], MAX_TOTAL
    for rp in changed(base, sha, repo):
        result, used = one(sha, rp, data, budget, repo)
        results.append(result)
        budget -= used
    return {'head_sha': sha, 'packets': results}


def main(argv=None):
    a = argparse.ArgumentParser(description="main's packet gate on a PR head's packet folders")
    a.add_argument('--base', required=True)
    a.add_argument('--sha', required=True)
    a.add_argument('--data', required=True)
    a.add_argument('--out', required=True)
    a.add_argument('--repo', default='.')
    x = a.parse_args(argv)
    if not SHA.match(x.sha):
        raise SystemExit('bad head sha')
    try:
        result = gate(x.base, x.sha, x.data, x.repo)
    except Exception as e:  # noqa: BLE001 - no result is written as one: no raw is verified, so audit-gpt reads them whole
        result = {'head_sha': x.sha, 'packets': [], 'error': f'the gate did not run: {type(e).__name__}'}
    Path(x.out).write_text(json.dumps(result, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps({p['packet']: p['status'] for p in result['packets']} or result.get('error', {}), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
