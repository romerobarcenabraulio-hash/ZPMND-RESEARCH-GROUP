"""One catalog run for one country: index what is new, fetch raw within budget, reconcile coverage, write everything.

  python -m rg.catalog.run --country mx --out work/catalog --raw work/raw [--budget 3000] [--bundle work/raw-mx.tar]

Exit codes: 0 ok; 3 a coverage reconciliation failed (data is still written, the failure is in the manifest);
4 an entry fails the catalog_entry schema (nothing is written).
"""
import argparse
import json
import re
import sys
import tarfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import leyesbiblio, ojn, sidof
from .categorize import doc_type, fold
from .fetch import BudgetExhausted, Fetcher, FetchRefused, decode_html
from .store import Catalog, RawStore
from ..schemas import validate

REPO = Path(__file__).resolve().parents[2]
CDMX = timezone(timedelta(hours=-6))  # central zone has no DST since 2022 (Ley de los Husos Horarios)


def dof_window_start(days, today, forward_days, reread=2):
    """First day to (re)index: the last `reread` days are always read again for notes published late; a first run
    starts `forward_days` back."""
    if not days:
        return today - timedelta(days=forward_days)
    return min(date.fromisoformat(max(days)) + timedelta(days=1), today - timedelta(days=reread))


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _media_type(resp, fallback):
    mt = resp.headers.get('content-type', '').split(';')[0].strip().lower()
    return mt if re.fullmatch(r'[a-z0-9.+-]+/[a-z0-9.+-]+', mt or '') else fallback


def _artifact(src, url, sha, body, media_type, rel):
    return {'artifact_id': f'SA-{sha[:24]}', 'url': url, 'retrieved_at': now_iso(), 'sha256': sha, 'bytes': len(body),
            'media_type': media_type, 'source_type': src['source_type'], 'publisher': src['publisher'],
            'license': src['license'], 'redistribution': src['redistribution'], 'stored_at': 'local_corpus'}


class Run:
    def __init__(self, country, out, raw, budget, today, forward_days, index_days):
        self.registry = json.loads((REPO / 'sources' / f'{country.lower()}.json').read_text(encoding='utf-8'))
        self.country = self.registry['country']
        self.catalog = Catalog(out, self.country)
        self.raw = RawStore(raw)
        self.budget, self.today = budget, today
        self.forward_days, self.index_days = forward_days, index_days
        self.used = 0
        self.manifest = {'run_id': now_iso().replace(':', ''), 'country': self.country, 'started_at': now_iso(),
                         'sources': {}, 'coverage': [], 'errors': []}

    def _fetcher(self, src):
        remaining = max(self.budget - self.used, 0)
        return Fetcher(src['allowed_hosts'], budget=min(remaining, src.get('max_requests', remaining)))

    def _cover(self, source_id, scope, expected, got):
        ok = expected == got
        self.manifest['coverage'].append({'source_id': source_id, 'scope': scope, 'expected': expected, 'extracted': got, 'ok': ok})
        return ok

    # ---- DOF via SIDOF ----------------------------------------------------------------------------
    def run_sidof(self, src):
        f = self._fetcher(src)
        st = self.catalog.state.setdefault(src['source_id'], {'days': {}})
        days = st['days']
        floor = date.fromisoformat(src['backfill_floor'])
        start = dof_window_start(days, self.today, self.forward_days)
        forward = [start + timedelta(days=i) for i in range((self.today - start).days + 1)]
        oldest = date.fromisoformat(min(days)) if days else start
        backfill = [oldest - timedelta(days=i) for i in range(1, self.index_days + 1) if oldest - timedelta(days=i) >= floor]
        stats = {'days_indexed': 0, 'notes_new': 0, 'raw_stored': 0, 'raw_skipped_metadata_only': 0,
                 'raw_robots_disallowed': 0, 'raw_failed': 0}
        try:
            for day in forward + backfill:
                key = day.isoformat()
                if key in days and day < self.today - timedelta(days=2):
                    continue  # closed day already indexed; the last 3 days are re-read for late notes
                r = f.get(sidof.day_url(src['base_url'], day))
                if r.status != 200:
                    self.manifest['errors'].append(f'{src["source_id"]} {key}: HTTP {r.status}')
                    continue
                page = r.text()
                items = sidof.parse_day(page)
                self._cover(src['source_id'], key, sidof.count_listed(page), len(items))
                for it in items:
                    branch = it['branch'] or ''
                    meta_only = branch in src.get('metadata_only_branches', [])
                    entry_id = f"{src['source_id']}:{it['native_id']}"
                    old = self.catalog.entries.get(entry_id)
                    entry = {
                        'entry_id': entry_id, 'country': self.country, 'source_id': src['source_id'],
                        'native_id': it['native_id'], 'title': it['title'],
                        'url': sidof.note_url(src['base_url'], it['native_id']),
                        'category': {**src['category'], 'edition': it['edition'], 'section': it['section'],
                                     'branch': it['branch'], 'issuer': it['issuer'], 'doc_type': doc_type(it['title'])},
                        'dates': {'published': key},
                        'raw_status': old['raw_status'] if old else ('metadata_only' if meta_only else 'pending'),
                        'first_seen': now_iso(),
                    }
                    for k in ('artifact', 'raw_path'):
                        if old and k in old:
                            entry[k] = old[k]
                    stats['notes_new'] += self.catalog.upsert(entry)
                days[key] = {'notes': len(items), 'indexed_at': now_iso()}
                stats['days_indexed'] += 1
            pending = sorted((e for e in self.catalog.entries.values()
                              if e['source_id'] == src['source_id'] and e['raw_status'] in ('pending', 'failed')),
                             key=lambda e: (e['dates']['published'], e['native_id']), reverse=True)
            for e in pending:
                url = sidof.raw_url(src['base_url'], e['native_id'])
                try:
                    if not f.allowed(url):
                        e['raw_status'] = 'robots_disallowed'
                        stats['raw_robots_disallowed'] += 1
                        continue
                    r = f.get(url)
                except FetchRefused as exc:
                    if isinstance(exc, BudgetExhausted):
                        raise
                    e['raw_status'] = 'robots_disallowed' if 'robots' in str(exc) else 'failed'
                    continue
                if r.status != 200 or not r.body:
                    e['raw_status'] = 'failed'
                    stats['raw_failed'] += 1
                    continue
                sha, rel = self.raw.put(r.body, 'html')
                e['artifact'] = _artifact(src, url, sha, r.body, _media_type(r, 'text/html'), rel)
                e['raw_path'] = rel
                e['raw_status'] = 'stored'
                stats['raw_stored'] += 1
        except BudgetExhausted:
            self.manifest['errors'].append(f'{src["source_id"]}: request budget reached (continues next run)')
        stats['raw_skipped_metadata_only'] = sum(1 for e in self.catalog.entries.values()
                                                 if e['source_id'] == src['source_id'] and e['raw_status'] == 'metadata_only')
        stats['requests'] = f.used
        self.used += f.used
        return stats

    # ---- Laws and regulations (LeyesBiblio) -------------------------------------------------------
    def run_leyesbiblio(self, src):
        f = self._fetcher(src)
        st = self.catalog.state.setdefault(src['source_id'], {'etags': {}})
        stats = {'listed': 0, 'new_instruments': 0, 'new_versions': 0, 'unchanged': 0, 'raw_failed': 0}
        try:
            r = f.get(src['base_url'] + src['listing'])
            if r.status != 200:
                self.manifest['errors'].append(f"{src['source_id']}: listing HTTP {r.status}")
                return stats
            page = r.text()
            rows = leyesbiblio.parse_listing(page, src['base_url'])
            self._cover(src['source_id'], src['listing'] + ' (every PDF on the page accounted for)',
                        leyesbiblio.count_text_pdfs(page), len(leyesbiblio.accounted_pdfs(rows, src['base_url'])))
            stats['listed'] = len(rows)
            for row in rows:
                entry_id = f"{src['source_id']}:{row['native_id']}"
                old = self.catalog.entries.get(entry_id)
                entry = {
                    'entry_id': entry_id, 'country': self.country, 'source_id': src['source_id'],
                    'native_id': row['native_id'], 'title': row['title'], 'url': row['raw_url'] or src['base_url'] + src['listing'],
                    'category': {**src['category'], 'doc_type': doc_type(row['title']), 'status_printed': row['status_printed']},
                    'dates': {k: row[k] for k in ('original_publication', 'last_reform_printed') if row[k]},
                    'listing': {k: row[k] for k in ('list_marker', 'page_order', 'listing_text', 'history_urls', 'related_urls')},
                    'raw_status': 'no_text_link' if not row['raw_url'] else (old['raw_status'] if old else 'pending'),
                    'versions': old['versions'] if old else [], 'first_seen': now_iso(),
                }
                for k in ('artifact', 'raw_path'):
                    if old and k in old:
                        entry[k] = old[k]
                stats['new_instruments'] += self.catalog.upsert(entry)
                if not row['raw_url']:
                    continue
                cached = st['etags'].get(row['raw_url'], {})
                resp = f.get(row['raw_url'], etag=cached.get('etag'), last_modified=cached.get('last_modified'))
                if resp.status == 304:
                    stats['unchanged'] += 1
                    continue
                if resp.status != 200 or not resp.body:
                    entry['raw_status'] = 'failed'
                    stats['raw_failed'] += 1
                    continue
                sha, rel = self.raw.put(resp.body, 'pdf')
                st['etags'][row['raw_url']] = {'etag': resp.headers.get('etag'), 'last_modified': resp.headers.get('last-modified')}
                if not any(v['sha256'] == sha for v in entry['versions']):
                    entry['versions'] = entry['versions'] + [{'sha256': sha, 'retrieved_at': now_iso(), 'raw_path': rel,
                                                              'last_modified': resp.headers.get('last-modified')}]
                    stats['new_versions'] += 1
                entry['artifact'] = _artifact(src, row['raw_url'], sha, resp.body, _media_type(resp, 'application/pdf'), rel)
                entry['raw_path'], entry['raw_status'] = rel, 'stored'
        except BudgetExhausted:
            self.manifest['errors'].append(f"{src['source_id']}: request budget reached (continues next run)")
        stats['requests'] = f.used
        self.used += f.used
        return stats


    # ---- State legislation (Orden Jurídico Nacional) ----------------------------------------------
    PRIORITY = ('CONSTITUCION', 'LEY', 'CODIGO', 'REGLAMENTO', 'ESTATUTO')

    def run_ojn(self, src):
        f = self._fetcher(src)
        st = self.catalog.state.setdefault(src['source_id'], {'etags': {}})
        stats = {'listings': 0, 'listed': 0, 'new_instruments': 0, 'reform_changed': 0, 'raw_stored': 0,
                 'raw_unchanged': 0, 'raw_failed': 0, 'no_document_link': 0}
        try:
            for edo in src['states']:
                for power in src['powers']:
                    r = f.get(ojn.list_url(src['base_url'], edo, power, src['liberado']))
                    if r.status != 200:
                        self.manifest['errors'].append(f"{src['source_id']} edo {edo} poder {power}: HTTP {r.status}")
                        continue
                    page = decode_html(r.body, r.charset if 'charset' in r.headers.get('content-type', '').lower() else 'iso-8859-1')
                    items, state = ojn.parse_list(page), ojn.state_name(page)
                    total = ojn.printed_total(page)
                    self._cover(src['source_id'], f'edo {edo} poder {power} (total impreso)', -1 if total is None else total, len(items))
                    stats['listings'] += 1
                    stats['listed'] += len(items)
                    for order, it in enumerate(items, 1):
                        entry_id = f"{src['source_id']}:{it['native_id']}"
                        old = self.catalog.entries.get(entry_id)
                        dates = {k: v for k, v in (('published', it['published']), ('last_reform_printed', it['last_reform'])) if v}
                        reform_changed = bool(old) and old['dates'].get('last_reform_printed') != dates.get('last_reform_printed')
                        entry = {
                            'entry_id': entry_id, 'country': self.country, 'source_id': src['source_id'],
                            'native_id': it['native_id'], 'title': it['title'], 'url': ojn.ficha_url(src['base_url'], it['native_id']),
                            'category': {**src['category'], 'locality': state, 'branch': ojn.POWERS[power],
                                         'doc_type': fold(it['type_printed']) or 'OTRO',
                                         'status_printed': (old or {}).get('category', {}).get('status_printed')},
                            'dates': dates,
                            'listing': {'state_code': edo, 'page_order': order,
                                        'listing_text': ' | '.join((it['title'], it['published_printed'], it['last_reform_printed'], it['type_printed']))},
                            'raw_status': 'pending' if (not old or reform_changed) else old['raw_status'],
                            'versions': old.get('versions', []) if old else [], 'first_seen': now_iso(),
                        }
                        if entry['category']['status_printed'] is None:
                            entry['category'].pop('status_printed')
                        for k in ('artifact', 'raw_path'):
                            if old and k in old:
                                entry[k] = old[k]
                        stats['reform_changed'] += reform_changed
                        stats['new_instruments'] += self.catalog.upsert(entry)
            pending = sorted((e for e in self.catalog.entries.values()
                              if e['source_id'] == src['source_id'] and e['raw_status'] in ('pending', 'failed')),
                             key=lambda e: (not e['category']['doc_type'].startswith(self.PRIORITY), e['listing']['state_code'], int(e['native_id'])))
            for e in pending:
                r = f.get(e['url'])
                if r.status != 200:
                    e['raw_status'] = 'failed'
                    stats['raw_failed'] += 1
                    continue
                sheet = ojn.parse_ficha(decode_html(r.body, 'iso-8859-1'), src['base_url'])
                if sheet['status_printed']:
                    e['category']['status_printed'] = sheet['status_printed'].upper()
                if sheet['locality']:
                    e['category']['locality'] = sheet['locality']
                if not sheet['doc_url']:
                    e['raw_status'] = 'no_text_link'
                    stats['no_document_link'] += 1
                    continue
                cached = st['etags'].get(sheet['doc_url'], {})
                d = f.get(sheet['doc_url'], etag=cached.get('etag'), last_modified=cached.get('last_modified'))
                if d.status == 304 and e.get('raw_path'):
                    e['raw_status'] = 'stored'
                    stats['raw_unchanged'] += 1
                    continue
                if d.status != 200 or not d.body:
                    e['raw_status'] = 'failed'
                    stats['raw_failed'] += 1
                    continue
                ext = sheet['doc_url'].rsplit('.', 1)[-1].lower()
                ext = ext if ext in ('doc', 'docx', 'pdf', 'htm', 'html', 'rtf') else 'bin'
                sha, rel = self.raw.put(d.body, ext)
                st['etags'][sheet['doc_url']] = {'etag': d.headers.get('etag'), 'last_modified': d.headers.get('last-modified')}
                if not any(v['sha256'] == sha for v in e['versions']):
                    e['versions'] = e['versions'] + [{'sha256': sha, 'retrieved_at': now_iso(), 'raw_path': rel,
                                                      'last_modified': d.headers.get('last-modified')}]
                e['artifact'] = _artifact(src, sheet['doc_url'], sha, d.body, _media_type(d, 'application/octet-stream'), rel)
                e['raw_path'], e['raw_status'] = rel, 'stored'
                stats['raw_stored'] += 1
        except BudgetExhausted:
            self.manifest['errors'].append(f"{src['source_id']}: request budget reached (continues next run)")
        stats['requests'] = f.used
        self.used += f.used
        return stats

    def execute(self, only=None):
        active = [s for s in self.registry['sources'] if s['status'] == 'active' and (not only or s['source_id'] in only)]
        for src in sorted(active, key=lambda s: s['adapter'] == 'sidof'):  # bounded sources first, the DOF takes the rest
            runner = {'sidof': self.run_sidof, 'leyesbiblio': self.run_leyesbiblio, 'ojn': self.run_ojn}[src['adapter']]
            self.manifest['sources'][src['source_id']] = runner(src)
        self.manifest['planned_sources'] = {s['source_id']: s.get('blocked_by') for s in self.registry['sources'] if s['status'] != 'active'}
        self.manifest['requests_total'] = self.used
        self.manifest['raw_new_files'] = len(self.raw.new_files)
        self.manifest['finished_at'] = now_iso()
        return self.manifest


def main(argv=None):
    a = argparse.ArgumentParser(description='RESEARCH GROUP country catalog run')
    a.add_argument('--country', required=True)
    a.add_argument('--out', required=True, help='catalog root (data branch checkout)')
    a.add_argument('--raw', required=True, help='raw corpus root (never committed)')
    a.add_argument('--budget', type=int, default=3000, help='max HTTP requests this run')
    a.add_argument('--today', help='YYYY-MM-DD (default: today in Mexico City)')
    a.add_argument('--forward-days', type=int, default=30, help='first run: days back from today to index')
    a.add_argument('--index-days', type=int, default=120, help='older days to index per run, toward the floor')
    a.add_argument('--sources', help='comma-separated source ids (default: all active)')
    a.add_argument('--bundle', help='write a tar of the raw files new in this run')
    x = a.parse_args(argv)
    today = date.fromisoformat(x.today) if x.today else datetime.now(CDMX).date()
    run = Run(x.country, x.out, x.raw, x.budget, today, x.forward_days, x.index_days)
    manifest = run.execute(set(x.sources.split(',')) if x.sources else None)
    if x.bundle and run.raw.new_files:
        with tarfile.open(x.bundle, 'w') as tar:
            for rel in sorted(run.raw.new_files):
                tar.add(Path(x.raw) / rel, arcname=rel)
        manifest['raw_bundle'] = Path(x.bundle).name
    invalid = {eid: errs[:3] for eid, e in run.catalog.entries.items() if (errs := validate('catalog_entry', e))}
    manifest['invalid_entries'] = len(invalid)
    if invalid:
        manifest['errors'].append(f'{len(invalid)} entries fail the catalog_entry schema; nothing written')
        print(json.dumps(dict(list(invalid.items())[:5]), ensure_ascii=False, indent=1))
        return 4
    run.catalog.write()
    run.catalog.write_run(manifest)
    bad = [c for c in manifest['coverage'] if not c['ok']]
    print(json.dumps({'run_id': manifest['run_id'], 'sources': manifest['sources'], 'coverage_checks': len(manifest['coverage']),
                      'coverage_failures': bad, 'errors': manifest['errors'][:10], 'requests': manifest['requests_total'],
                      'raw_new_files': manifest['raw_new_files'], 'catalog_total': len(run.catalog.entries)}, ensure_ascii=False, indent=1))
    return 3 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
