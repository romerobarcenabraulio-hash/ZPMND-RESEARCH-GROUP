"""Where extracted texts live: texts by content address, and the manifest that ties each raw to its text.

  <text root>/sha256/<2>/<text sha256>.txt     UTF-8 text; the hash is the path (release text-mx, tar parts)
  <manifest dir>/<first hex of raw sha>.jsonl  one line per raw, sorted by raw sha (data branch, mx/texto/)
  <manifest dir>/bundles.json                  raw-mx bundles already done (rg.text.bundles)
  <manifest dir>/runs/<run_id>.json            report of each run
"""
import hashlib
import json
import os
import re
from pathlib import Path

LINE = re.compile(r'^[0-9a-f]\.jsonl$')


def text_sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class TextStore:
    def __init__(self, root):
        self.root = Path(root)

    def path(self, sha):
        return self.root / 'sha256' / sha[:2] / f'{sha}.txt'

    def put(self, text):
        sha = text_sha(text)
        path = self.path(sha)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f'.txt.{os.getpid()}.part')
            tmp.write_bytes(text.encode('utf-8'))
            tmp.replace(path)
        return sha

    def get(self, sha):
        """The text whose sha256 is `sha`, or None when absent or when its bytes do not hash to it."""
        path = self.path(sha)
        if not path.is_file():
            return None
        body = path.read_bytes()
        return body.decode('utf-8') if hashlib.sha256(body).hexdigest() == sha else None


def read_manifest(d):
    """All lines of the manifest in d, as read from disk, as a list (a repeated raw shows twice)."""
    d = Path(d)
    lines = []
    for f in sorted(p for p in d.glob('*.jsonl') if LINE.match(p.name)):
        lines += [json.loads(line) for line in f.read_text(encoding='utf-8').splitlines() if line.strip()]
    return lines


def write_manifest(d, lines):
    """Rewrite the manifest: one file per first hex digit of the raw sha, lines sorted by raw sha. A part file whose
    rows are all gone is deleted, so the disk holds exactly `lines`."""
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    parts = {}
    for line in lines.values():
        parts.setdefault(line['raw_sha256'][0], []).append(line)
    for key, rows in parts.items():
        rows.sort(key=lambda r: r['raw_sha256'])
        (d / f'{key}.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n' for r in rows),
                                        encoding='utf-8')
    for f in d.glob('*.jsonl'):
        if LINE.match(f.name) and f.name[0] not in parts:
            f.unlink()
