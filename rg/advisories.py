"""Fail-closed gate: does any published OpenClaw security advisory affect the pinned version?

Exit 0 = no advisory affects the pin and every relevant range parsed; 1 = affected; 2 = a relevant range could not be
parsed (never assume it is safe). Usage:
  python -m rg.advisories --lock substrate/openclaw.lock.json --fetch          (live, needs gh)
  python -m rg.advisories --lock substrate/openclaw.lock.json --file adv.jsonl
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

_VERSION = r'v?(\d+)\.(\d+)\.(\d+)(?:-(?:(beta|alpha|rc)\.?(\d+)|(\d+)))?'
_CONSTRAINT = re.compile(r'\s*(<=|>=|<|>|=)?\s*(v?\d+\.\d+\.\d+(?:-(?:(?:beta|alpha|rc)\.?\d+|\d+))?)\s*,?')


def parse_version(text):
    m = re.fullmatch(_VERSION, text.strip())
    if not m:
        return None
    major, minor, patch, pre, pre_n, post = m.groups()
    if pre:
        tail = (0, int(pre_n))
    elif post:
        tail = (2, int(post))  # 2026.2.19-2 is a correction AFTER 2026.2.19
    else:
        tail = (1, 0)
    return (int(major), int(minor), int(patch)) + tail


def _conjunction(text):
    """'>= A < B' or '>=A, <B' -> list of (op, version); None if anything is left unparsed."""
    pos, out = 0, []
    while pos < len(text):
        m = _CONSTRAINT.match(text, pos)
        if not m or m.end() == pos:
            return None
        out.append((m.group(1) or '=', parse_version(m.group(2))))
        pos = m.end()
    return out or None


def affects(version, vulnerable_range):
    """True/False, or None when the range is not understood (callers must fail closed)."""
    if not vulnerable_range or not vulnerable_range.strip():
        return None
    results = []
    for part in vulnerable_range.split('||'):
        constraints = _conjunction(part.strip())
        if constraints is None or any(v is None for _, v in constraints):
            return None
        ops = {'<': version.__lt__, '<=': version.__le__, '>': version.__gt__, '>=': version.__ge__, '=': version.__eq__}
        results.append(all(ops[op](v) for op, v in constraints))
    return any(results)


def evaluate(advisories, version_text, packages):
    version = parse_version(version_text)
    if version is None:
        raise ValueError(f'unparseable pinned version {version_text}')
    wanted = {p.lower() for p in packages}
    affected, unparsed = [], []
    for adv in advisories:
        for vuln in adv.get('vulns', []):
            name = (vuln.get('pkg') or '').strip().lower()
            if name not in wanted and name != '':  # an empty package name is ambiguous: treat as ours
                continue
            verdict = affects(version, vuln.get('vulnerable'))
            row = (adv.get('ghsa_id'), adv.get('severity'), vuln.get('vulnerable'), vuln.get('patched'))
            if verdict is None:
                unparsed.append(row)
            elif verdict:
                affected.append(row)
    return affected, unparsed


def fetch(repo):
    jq = ('.[] | {ghsa_id, cve_id, severity, published_at, summary, vulns: [.vulnerabilities[]? | '
          '{pkg: .package.name, vulnerable: .vulnerable_version_range, patched: .patched_versions}]}')
    out = subprocess.run(['gh', 'api', '--paginate', f'repos/{repo}/security-advisories?per_page=100', '--jq', jq],
                         capture_output=True, text=True, check=True).stdout
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def main(argv=None):
    a = argparse.ArgumentParser(description='OpenClaw advisory gate')
    a.add_argument('--lock', required=True)
    src = a.add_mutually_exclusive_group(required=True)
    src.add_argument('--fetch', action='store_true')
    src.add_argument('--file')
    x = a.parse_args(argv)
    lock = json.loads(Path(x.lock).read_text(encoding='utf-8'))
    if x.fetch:
        advisories = fetch(lock['advisory_source'])
    else:
        advisories = [json.loads(l) for l in Path(x.file).read_text(encoding='utf-8').splitlines() if l.strip()]
    affected, unparsed = evaluate(advisories, lock['version'], lock['advisory_packages'])
    latest = max((a.get('published_at') or '' for a in advisories), default='')
    print(f"pinned {lock['version']}: {len(advisories)} advisories, latest published {latest}, "
          f'{len(affected)} affecting, {len(unparsed)} unparsed')
    for row in affected:
        print('AFFECTED', *row)
    for row in unparsed:
        print('UNPARSED', *row)
    if affected:
        return 1
    return 2 if unparsed else 0


if __name__ == '__main__':
    sys.exit(main())
