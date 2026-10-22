"""Extract the text of every raw file in the store: one status per raw, by construction and checked afterwards.

  python -m rg.text.run --catalog data/mx --raw raw --out data/mx/texto --text texto
                        [--bundles-done unpacked.json] [--workers N] [--timeout S] [--deadline-minutes M]

- Each raw file (sha256/<2>/<sha>.<ext>) is read, hashed and extracted in a process of its own, at most --workers at
  once, killed after --timeout seconds, with its address space capped at MAX_MEMORY: a hostile or broken file can only
  fail itself (status fallo), never hang the run or take it down. --workers is bounded by the machine's memory at
  MAX_MEMORY each, so parsers at their limit together still fit. A file whose bytes do not hash to its name gets no line.
- A raw whose line already carries the current extractor of its format is not redone, unless it is a fallo.
- Texts go to --text by content address, and only those not published yet (named by no line before this run), so
  --text holds exactly what the workflow must upload to the release text-mx.
- Coverage is counted apart from the extraction loop: the manifest is read back from disk, and every raw the catalog
  references and every raw file in the store must have exactly one line, no line may come from an older extractor of
  its format, and every new text must hash to its name. Otherwise exit 3, as in the catalog. A bundle that failed its check (rg.text.bundles) is also exit 3. After a crash
  what was done is still written (exit 1). --deadline-minutes stops starting new files (REGLAS 5).
"""
import argparse
import hashlib
import json
import multiprocessing as mp
import os
import re
import sys
import time
from collections import Counter, deque
from datetime import datetime, timezone
from multiprocessing.connection import wait
from pathlib import Path

from ..catalog.store import row_files
from .extract import FAILED, HEAD, VERSIONS, extract, extractor, failed, too_large
from .store import TextStore, read_manifest, text_sha, write_manifest

MAX_BYTES = 200_000_000  # a raw larger than this is not read whole (extract.too_large)
TIMEOUT = 300  # seconds per raw file; HIPÓTESIS until measured on the whole store
MAX_MEMORY = 2_000_000_000  # bytes of address space per worker; HIPÓTESIS until measured on the whole store
NAME = re.compile(r'^([0-9a-f]{64})\.[a-z0-9]{1,5}$')
RAW_PATH = re.compile(r'^sha256/[0-9a-f]{2}/([0-9a-f]{64})\.[a-z0-9]{1,5}$')
LINE_KEYS = ('raw_sha256', 'bytes', 'format', 'status', 'extractor', 'invisibles_removed')
OPTIONAL_KEYS = ('charset', 'pages', 'pages_without_text', 'error')


def _sha_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def read_and_extract(path, max_bytes=MAX_BYTES):
    size = os.path.getsize(path)
    with open(path, 'rb') as fh:
        if size <= max_bytes:
            body = fh.read()
            return {**extract(body), 'raw_sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)}
        head = fh.read(HEAD)
    return {**too_large(head, max_bytes), 'raw_sha256': _sha_file(path), 'bytes': size}


def _child(path, conn, max_bytes):
    try:
        conn.send(read_and_extract(path, max_bytes))
    finally:
        conn.close()


def _limit_memory(limit):
    """Cap this process's address space: a small file that expands without bound dies here (MemoryError), alone."""
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))


def _limited(target, path, conn, max_bytes, max_memory):
    """Every worker runs its target under the cap; if the cap cannot be set the worker ends without a result (fallo)."""
    _limit_memory(max_memory)
    target(path, conn, max_bytes)


def workers_for(requested, max_memory, total=None):
    """At most `requested` workers, and no more than the machine's memory holds at max_memory each with one share left
    for the parent: several parsers at their limit at once must not take the runner down."""
    if total is None:
        total = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')
    return max(1, min(requested, total // max_memory - 1))


def _lost(path, why):
    """The result for a raw whose process did not answer: fallo, by its first bytes, hashed here (no parsing)."""
    with open(path, 'rb') as fh:
        head = fh.read(HEAD)
    return {**failed(head, why), 'raw_sha256': _sha_file(path), 'bytes': os.path.getsize(path)}


def _context():
    if 'forkserver' in mp.get_all_start_methods():  # forked from a clean server: no parent threads or state copied
        ctx = mp.get_context('forkserver')
        ctx.set_forkserver_preload(['rg.text.extract'])  # pypdf imported once, not per raw
        return ctx
    return mp.get_context('spawn')


def extract_all(paths, workers=1, timeout=TIMEOUT, deadline=None, max_bytes=MAX_BYTES, target=_child,
                max_memory=MAX_MEMORY):
    """Yield (path, result) for each path, each in its own process under a `max_memory` address-space cap, at most
    `workers` at once, each killed after `timeout` seconds. Once time.monotonic() passes `deadline`, no new path is
    started (those are not yielded)."""
    ctx, todo, running = _context(), deque(paths), {}
    while todo or running:
        while todo and len(running) < workers and (deadline is None or time.monotonic() < deadline):
            path = todo.popleft()
            recv, send = ctx.Pipe(duplex=False)
            proc = ctx.Process(target=_limited, args=(target, str(path), send, max_bytes, max_memory), daemon=True)
            proc.start()
            send.close()
            running[recv] = (path, proc, time.monotonic() + timeout)
        if not running:
            return
        soonest = min(until for _, _, until in running.values())
        for conn in wait(list(running), timeout=max(0.0, soonest - time.monotonic())):
            path, proc, _ = running.pop(conn)
            try:
                result = conn.recv()
            except (EOFError, OSError):
                result = None
            conn.close()
            proc.join(10)
            if proc.is_alive():
                proc.kill()
                proc.join()
            yield path, result if result is not None else _lost(path, f'process ended without a result (exit {proc.exitcode})')
        now = time.monotonic()
        for conn, (path, proc, until) in list(running.items()):
            if now >= until:
                proc.kill()
                proc.join()
                conn.close()
                del running[conn]
                yield path, _lost(path, f'timeout ({timeout} s)')


def referenced(catalog):
    """sha256 of every raw a catalog row points to (raw_path and every version's raw_path); derived views excluded."""
    refs = set()
    if not Path(catalog).is_dir():
        return refs
    for f in row_files(catalog):
        for line in f.read_text(encoding='utf-8').splitlines():
            if line.strip():
                e = json.loads(line)
                for rp in [e.get('raw_path')] + [v.get('raw_path') for v in e.get('versions', [])]:
                    m = RAW_PATH.match(rp or '')
                    if m:
                        refs.add(m.group(1))
    return refs


def stored(raw):
    """{sha: path} of the raw files in the store, by name only: the count the extraction loop is checked against."""
    out = {}
    for p in sorted(Path(raw).glob('sha256/*/*')):
        m = NAME.match(p.name)
        if m and p.is_file() and p.parent.name == m.group(1)[:2]:
            out.setdefault(m.group(1), p)
    return out


def current(line):
    """The line was made by the current extractor of its format and is not a fallo: nothing to redo."""
    return bool(line) and line['status'] != FAILED and not stale(line)


def stale(line):
    """The line was made by an older extractor of its format: its raw still owes an extraction."""
    return line['extractor'] != extractor(line['format'])


def make_line(res):
    line = {k: res[k] for k in LINE_KEYS}
    line.update({k: res[k] for k in OPTIONAL_KEYS if res.get(k) is not None})
    text = res.get('text')
    line['text_sha256'] = text_sha(text) if text is not None else None
    line['chars'] = len(text) if text is not None else 0
    return line


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def run(catalog, raw, out, text, bundles_done=None, workers=1, timeout=TIMEOUT, deadline=None, max_bytes=MAX_BYTES,
        target=_child, max_memory=MAX_MEMORY):
    out, texts = Path(out), TextStore(text)
    started = now_iso()
    report = {'run_id': started.replace(':', ''), 'started_at': started, 'extractors': {}, 'errors': [],
              'workers': workers, 'timeout_s': timeout, 'max_memory_bytes': max_memory}
    previous = read_manifest(out)
    lines = {line['raw_sha256']: line for line in previous}
    published = {line['text_sha256'] for line in previous if line.get('text_sha256')}
    store = stored(raw)
    todo = [p for sha, p in sorted(store.items()) if not current(lines.get(sha))]
    report['to_extract'], report['already_current'] = len(todo), len(store) - len(todo)
    new_texts, mismatched, crashed = set(), [], None
    try:
        for n, (path, res) in enumerate(extract_all(todo, workers, timeout, deadline, max_bytes, target, max_memory), 1):
            sha = NAME.match(path.name).group(1)
            if res['raw_sha256'] != sha:  # the bytes are not the raw the name promises: no line for either
                mismatched.append(sha)
                continue
            line = make_line(res)
            if line['text_sha256'] and line['text_sha256'] not in published:
                texts.put(res['text'])
                new_texts.add(line['text_sha256'])
            lines[sha] = line
            report['extractors'][line['format']] = line['extractor']
            if n % 1000 == 0:
                print(f'{n}/{len(todo)} raws', flush=True)
    except Exception as exc:  # never lose what was done: write it, record the crash, exit 1
        crashed = f'{type(exc).__name__}: {exc}'
        report['errors'].append(f'run crashed: {crashed}')
    write_manifest(out, lines)

    on_disk = read_manifest(out)  # coverage trusts the disk, not the loop
    count = Counter(line['raw_sha256'] for line in on_disk)
    refs = referenced(catalog)
    missing_refs = sorted(refs - count.keys())
    missing_store = sorted(store.keys() - count.keys())
    repeated = sorted(s for s, k in count.items() if k > 1)
    old = sorted(line['raw_sha256'] for line in on_disk if stale(line))  # e.g. a version bump cut by the deadline
    bad_texts = sorted(s for s in new_texts if texts.get(s) is None)
    report['status'] = dict(sorted(Counter(line['status'] for line in on_disk).items()))
    report['status_referenced'] = dict(sorted(Counter(line['status'] for line in on_disk if line['raw_sha256'] in refs).items()))
    report['format'] = dict(sorted(Counter(line['format'] for line in on_disk).items()))
    report['new_texts'] = len(new_texts)
    report['coverage'] = {
        'referenced': len(refs), 'in_store': len(store), 'lines': len(on_disk),
        'referenced_without_status': len(missing_refs), 'stored_without_status': len(missing_store),
        'repeated_lines': len(repeated), 'name_mismatch': len(mismatched), 'texts_not_matching': len(bad_texts),
        'stale_extractor': len(old),
        'first': {'referenced_without_status': missing_refs[:20], 'stored_without_status': missing_store[:20],
                  'repeated_lines': repeated[:20], 'name_mismatch': mismatched[:20], 'texts_not_matching': bad_texts[:20],
                  'stale_extractor': old[:20]},
    }
    report['coverage']['ok'] = not (missing_refs or missing_store or repeated or mismatched or bad_texts or old)

    if bundles_done and Path(bundles_done).exists():
        record = json.loads(Path(bundles_done).read_text(encoding='utf-8'))
        done_path = out / 'bundles.json'
        done = json.loads(done_path.read_text(encoding='utf-8')) if done_path.exists() else {}
        fresh = {line['raw_sha256'] for line in on_disk if not stale(line)}
        for name, b in record.get('bundles', {}).items():
            if set(b['raws']) <= fresh:  # done only when every raw of the bundle has a line by the current extractor
                done[name] = {'tars': b['tars'], 'raws': len(b['raws']), 'run_id': report['run_id'],
                              'extractors': dict(VERSIONS)}  # a later version bump reopens it (bundles.is_done)
            else:
                done.pop(name, None)  # unpacked again and not whole: an older mark no longer holds
        done_path.write_text(json.dumps(done, indent=1, sort_keys=True) + '\n', encoding='utf-8')
        report['bundle_errors'] = record.get('errors', [])
    report['finished_at'] = now_iso()
    runs = out / 'runs'
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{report['run_id']}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True) + '\n',
                                                   encoding='utf-8')
    if crashed:
        return 1, report
    return (0 if report['coverage']['ok'] and not report.get('bundle_errors') else 3), report


def main(argv=None):
    a = argparse.ArgumentParser(description='RESEARCH GROUP text extraction over the raw store')
    a.add_argument('--catalog', required=True, help='country folder of the catalog (data branch), e.g. data/mx')
    a.add_argument('--raw', required=True, help='raw store root (sha256/<2>/<sha>.<ext>)')
    a.add_argument('--out', required=True, help='manifest folder, e.g. data/mx/texto')
    a.add_argument('--text', required=True, help='text store root; receives the texts not yet published')
    a.add_argument('--bundles-done', help='record written by `rg.text.bundles unpack`')
    a.add_argument('--workers', type=int, default=os.cpu_count() or 1)
    a.add_argument('--timeout', type=float, default=TIMEOUT, help='seconds per raw file')
    a.add_argument('--deadline-minutes', type=float, help='start no new raw file after this many minutes')
    x = a.parse_args(argv)
    deadline = time.monotonic() + 60 * x.deadline_minutes if x.deadline_minutes is not None else None
    workers = workers_for(max(1, x.workers), MAX_MEMORY)
    rc, report = run(x.catalog, x.raw, x.out, x.text, x.bundles_done, workers, x.timeout, deadline)
    print(json.dumps({k: report[k] for k in ('run_id', 'to_extract', 'already_current', 'status', 'status_referenced',
                                              'format', 'new_texts', 'coverage', 'errors')} | {'bundle_errors': report.get('bundle_errors', [])},
                     ensure_ascii=False, indent=1))
    return rc


if __name__ == '__main__':
    sys.exit(main())
