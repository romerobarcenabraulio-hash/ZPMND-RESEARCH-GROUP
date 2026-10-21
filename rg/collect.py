"""Collect sources for a ResearchPacket: fetch each URL with the guarded fetcher, store raw bytes by content address,
and emit one SourceArtifact per URL (url, retrieved_at, sha256, bytes, media type, license as declared).

  python -m rg.collect --hosts huggingface.co --in sources.json --raw work/raw-packets --out artifacts.json

sources.json: [{"artifact_id": "SA-...", "url": "...", "source_type": "...", "publisher": "...", "license": "...",
                "redistribution": "allowed|metadata_only|unknown", "title": "..."}]
A URL that fails or is refused is reported, never silently dropped. Raw stays outside git (stored_at local_corpus).
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .catalog.fetch import Fetcher, FetchRefused
from .catalog.store import RawStore
from .schemas import validate

EXT = {'text/markdown': 'md', 'text/plain': 'txt', 'application/json': 'json', 'text/html': 'html', 'application/pdf': 'pdf'}


def collect(sources, hosts, raw_root, budget=200):
    fetcher, raw = Fetcher(hosts, budget=budget), RawStore(raw_root)
    artifacts, failures = [], []
    for src in sources:
        try:
            r = fetcher.get(src['url'])
        except FetchRefused as exc:
            failures.append({'url': src['url'], 'reason': str(exc)})
            continue
        if r.status != 200 or not r.body:
            failures.append({'url': src['url'], 'reason': f'HTTP {r.status}'})
            continue
        media = (r.headers.get('content-type', '').split(';')[0].strip().lower() or 'application/octet-stream')
        sha, rel = raw.put(r.body, EXT.get(media, 'bin'))
        art = {'artifact_id': src['artifact_id'], 'url': src['url'],
               'retrieved_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'sha256': sha, 'bytes': len(r.body),
               'media_type': media, 'source_type': src['source_type'], 'publisher': src['publisher'],
               'license': src['license'], 'redistribution': src['redistribution'], 'stored_at': 'local_corpus'}
        if src.get('title'):
            art['title'] = src['title']
        errors = validate('source_artifact', art)
        if errors:
            failures.append({'url': src['url'], 'reason': f'invalid artifact: {errors[:2]}'})
            continue
        artifacts.append(art)
    return artifacts, failures


def main(argv=None):
    a = argparse.ArgumentParser(description='Collect raw sources for a ResearchPacket')
    a.add_argument('--hosts', required=True, help='comma-separated allowlist')
    a.add_argument('--in', dest='inp', required=True)
    a.add_argument('--raw', required=True)
    a.add_argument('--out', required=True)
    x = a.parse_args(argv)
    sources = json.loads(Path(x.inp).read_text(encoding='utf-8'))
    artifacts, failures = collect(sources, x.hosts.split(','), x.raw)
    Path(x.out).write_text(json.dumps({'artifacts': artifacts, 'failures': failures}, ensure_ascii=False, indent=1) + '\n',
                           encoding='utf-8')
    print(json.dumps({'collected': len(artifacts), 'failures': failures}, ensure_ascii=False, indent=1))
    return 0 if not failures else 3


if __name__ == '__main__':
    sys.exit(main())
