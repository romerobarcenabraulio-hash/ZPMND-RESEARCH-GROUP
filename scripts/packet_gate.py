"""Main's packet gate on the packet folders a PR head changes, read as data (auditor.yml, job packet-gate).

    python scripts/packet_gate.py --base origin/main --sha <40 hex> --data <empty dir> --out packets.json

Runs main's rg.packets, never the PR's. The head's research-packets/<RP>/ trees are listed with git ls-tree and each
blob is written with git cat-file, byte for byte: no checkout, no PR code run, and no archive (git archive applies the
head's own export-subst and export-ignore attributes, so it could hand the gate bytes or a file list that are not the
head's). A folder whose tree holds anything but regular files (a link, a submodule), a blob over MAX_BLOB or a head over
MAX_TOTAL is not written and fails. Every changed folder that still exists gets rg.packets.check; it passes only with no
problem and no warning (--strict). Any error is that folder's failed result, and packets.json is always written: it
names the head and, for each folder, its result and, only when it passed, the path and sha256 of each raw file.

    python scripts/packet_gate.py --attest packets.json --base origin/main --sha <40 hex> --data <empty dir> --repo-name <owner/repo>

That result was made where hostile raws were parsed, so it is never relayed as it is: on a clean runner, --attest
lists the changed folders again and settles each from the head's git objects against the investigar runs'
attestations (settle), keeping of packet-read only its failures. The file it writes is what audit-gpt reads as a TRUSTED section: a raw listed there arrives in the diff as
one line instead of its bytes.
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
REPO = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')
PACKET = re.compile(r'^RP-[A-Za-z0-9._-]{3,64}$')
REGULAR = ('100644', '100755')
MAX_BLOB = 100_000_000  # bytes of one file of a packet
MAX_TOTAL = 500_000_000  # bytes written for one head, all packets together
UNCHECKED = 'no raw at hand for its artifacts; quote not checked'  # rg.packets: a metadata_only packet keeps no raw
SIGNER = '.github/workflows/investigar.yml'  # the only workflow whose attestation vouches for a packet's quotes


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
    """(result, bytes reserved) for one changed packet folder; an error is a failed result. The folder's bytes are
    reserved before the first one is written, so an error after that still counts them against the head's budget."""
    reserved = 0
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
        reserved = total
        folder = write_blobs(rows, rp, data, repo)
        problems, warnings, stats = check(folder)
        ok = not problems and not warnings
        raws = {}
        if ok:
            for f in sorted((folder / 'raw').rglob('*')):
                if f.is_file():
                    raws[f'research-packets/{rp}/{f.relative_to(folder).as_posix()}'] = hashlib.sha256(f.read_bytes()).hexdigest()
        # Nothing wrong but quotes this gate cannot check: a metadata_only packet keeps no raw. They were checked by the
        # gate of the investigar run that built it, which attests every file; attest() verifies that, with a token.
        unverifiable = bool(warnings) and not problems and all(w.endswith(UNCHECKED) for w in warnings)
        files = {f'research-packets/{rp}/{f.relative_to(folder).as_posix()}': hashlib.sha256(f.read_bytes()).hexdigest()
                 for f in sorted(folder.rglob('*')) if f.is_file()} if unverifiable else {}
    except Exception as e:  # noqa: BLE001 - whatever breaks, the folder fails and packets.json is still written
        return {'packet': rp, 'status': 'failed', 'problems': [f'the gate did not finish: {type(e).__name__}']}, reserved
    status = 'passed' if ok else 'needs_attestation' if unverifiable else 'failed'
    return {'packet': rp, 'status': status, 'problems': problems, 'warnings': warnings, 'stats': stats, 'raws': raws,
            'files': files}, reserved


def verify_gh(path, repo_name):
    """The in-toto statements GitHub holds for the file's sha256 that verify as signed by investigar.yml of repo_name,
    run from main on a GitHub-hosted runner (gh attestation verify: Sigstore bundle, certificate identity, transparency
    log, SLSA provenance); [] when none does or gh's answer is not the documented one (fail closed)."""
    r = subprocess.run(['gh', 'attestation', 'verify', str(path), '--repo', repo_name, '--signer-workflow',
                        f'{repo_name}/{SIGNER}', '--source-ref', 'refs/heads/main', '--deny-self-hosted-runners',
                        '--format', 'json'], capture_output=True, timeout=120)
    if r.returncode != 0:
        return []
    try:
        return [v['verificationResult']['statement'] for v in json.loads(r.stdout)]
    except (ValueError, KeyError, TypeError):
        return []


def subjects(statement):
    """{name: sha256} of a statement's subjects, or None when they are not distinct names with a sha256 each."""
    try:
        named = {s['name']: s['digest']['sha256'] for s in statement['subject']}
    except (KeyError, TypeError):
        return None
    return named if len(named) == len(statement['subject']) else None


def _words(said, cap=50, width=500):
    """packet-read's problems or warnings, kept only as short strings: its words, never a grant."""
    return [w[:width] for w in said if isinstance(w, str)][:cap] if isinstance(said, list) else []


def settle(rp, said, sha, data, repo_name, budget, repo='.', verify=None):
    """(result, bytes reserved) for one changed folder, made on a clean runner where nothing of the folder is parsed.
    packet-read parsed the head's raws, so its result may come from a runner a hostile raw took over (SECURITY T12): of
    it only a failure is kept, with its words. A pass is established here alone: the folder's files are written from the
    head's git objects and hashed, and it passes only when one statement signed by the investigar.yml run on main that
    gated it names exactly those files with those digests, no more and no fewer (the run's attest job signs every file
    of the folder its gate passed as the subjects of one statement). Files of two runs, a file added, removed, renamed
    or changed: no statement matches, and it fails (GPT, REVISEs of #56). Sizes come from the tree and are reserved
    against the head's budget before the first byte is written, as in one(); an error is a failed result."""
    verify = verify or verify_gh
    reserved = 0
    try:
        rows = tree(sha, rp, repo)
        if not rows:  # the head removed it
            return {'packet': rp, 'status': 'removed'}, 0
        if said.get('status') not in ('passed', 'needs_attestation'):
            return {'packet': rp, 'status': 'failed', 'warnings': _words(said.get('warnings')), 'raws': {},
                    'problems': _words(said.get('problems')) or ['packet-read did not pass it']}, 0
        if any(mode not in REGULAR or kind != 'blob' or not 0 <= size <= MAX_BLOB for mode, kind, _, size, _ in rows):
            raise ValueError('a file that is not a regular blob within its size limit')
        total = sum(size for *_, size, _ in rows)
        if total > budget:
            return {'packet': rp, 'status': 'failed', 'warnings': [], 'raws': {},
                    'problems': [f'{total} bytes: over the {budget} left for this head']}, 0
        reserved = total  # before the first byte is written
        folder = write_blobs(rows, rp, data, repo)
        digests = {f'research-packets/{rp}/{f.relative_to(folder).as_posix()}': hashlib.sha256(f.read_bytes()).hexdigest()
                   for f in sorted(folder.rglob('*')) if f.is_file()}
        statements = verify(folder / 'packet.json', repo_name)
    except Exception as e:  # noqa: BLE001 - a timeout, a missing gh, a bad tree: failed, with why
        return {'packet': rp, 'status': 'failed', 'warnings': [], 'raws': {},
                'problems': [f'the attestation check did not finish: {type(e).__name__}']}, reserved
    if any(subjects(st) == digests for st in statements):
        return {'packet': rp, 'status': 'passed', 'problems': [], 'warnings': [],
                'raws': {rel: d for rel, d in digests.items() if rel.startswith(f'research-packets/{rp}/raw/')},
                'attested': {'signer_workflow': f'{repo_name}/{SIGNER}', 'ref': 'refs/heads/main', 'files': len(digests)}}, reserved
    return {'packet': rp, 'status': 'failed', 'warnings': [], 'raws': {},
            'problems': [f'research-packets/{rp}: no statement from {SIGNER} on main names exactly its {len(digests)} files']}, reserved


def attest(result, base, sha, data, repo_name, repo='.', verify=None):
    """The trusted packets.json, from the clean runner alone: the folders the head changes, listed here, each settled
    from the head's git objects (settle) within one budget of MAX_TOTAL bytes for the head; packet-read's result only
    says which of them it failed. A folder it gave no result for, or a result for another head, counts as not passed;
    anything that breaks is a failed result, never a missing one."""
    said = {p.get('packet'): p for p in result.get('packets') or [] if isinstance(p, dict)} \
        if isinstance(result, dict) and result.get('head_sha') == sha else {}
    packets, budget = [], MAX_TOTAL
    for rp in changed(base, sha, repo):
        packet, used = settle(rp, said.get(rp, {}), sha, data, repo_name, budget, repo, verify)
        packets.append(packet)
        budget -= used
    return {'head_sha': sha, 'packets': packets}


def gate(base, sha, data, repo='.'):
    results, budget = [], MAX_TOTAL
    for rp in changed(base, sha, repo):
        result, used = one(sha, rp, data, budget, repo)
        results.append(result)
        budget -= used
    return {'head_sha': sha, 'packets': results}


def main(argv=None):
    a = argparse.ArgumentParser(description="main's packet gate on a PR head's packet folders")
    a.add_argument('--attest', help='packet-read\'s packets.json, replaced by the clean runner\'s result (needs a token)')
    a.add_argument('--repo-name', help='owner/repo whose investigar.yml must have signed')
    a.add_argument('--base')
    a.add_argument('--sha')
    a.add_argument('--data', required=True)
    a.add_argument('--out')
    a.add_argument('--repo', default='.')
    x = a.parse_args(argv)
    if x.attest:
        if not REPO.match(x.repo_name or '') or not SHA.match(x.sha or '') or not x.base:
            raise SystemExit('bad repo name, head sha or base')
        try:
            said = json.loads(Path(x.attest).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            said = {}
        try:
            result = attest(said, x.base, x.sha, x.data, x.repo_name, x.repo)
        except Exception as e:  # noqa: BLE001 - no folder list: nothing passes, and the result says so
            result = {'head_sha': x.sha, 'packets': [], 'error': f'the clean check did not run: {type(e).__name__}'}
        Path(x.attest).write_text(json.dumps(result, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        print(json.dumps({p['packet']: p['status'] for p in result['packets']} or result.get('error', {}), ensure_ascii=False))
        return 0
    if not (x.base and x.sha and x.out):
        raise SystemExit('--base, --sha and --out are required')
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
