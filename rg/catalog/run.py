"""One catalog run for one country: index what is new, fetch raw within budget, reconcile coverage, write everything.

  python -m rg.catalog.run --country mx --out work/catalog --raw work/raw [--budget 3000] [--bundle work/raw-mx.tar]

Exit codes: 0 ok; 3 a coverage reconciliation failed (data is still written, the failure is in the manifest);
4 some entries fail the catalog_entry schema (they are quarantined: listed in the manifest, never written).
Sources with status 'trial' run only when named in --sources (never in the scheduled run).
"""
import argparse
import json
import os
import re
import sys
import tarfile
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import hf_tesis, indicadores, leyesbiblio, normas, ojn, sidof
from .categorize import clean_text, doc_type, dof_doc_type, fold
from .fetch import BudgetExhausted, Fetcher, FetchRefused, FileSink, Response, decode_html
from .store import Catalog, RawStore
from . import tratados
from ..schemas import validate

REPO = Path(__file__).resolve().parents[2]
CDMX = timezone(timedelta(hours=-6))  # central zone has no DST since 2022 (Ley de los Husos Horarios)


def dof_window_start(days, today, forward_days, reread=2):
    """First day to (re)index: the last `reread` days are always read again for notes published late; a first run
    starts `forward_days` back."""
    if not days:
        return today - timedelta(days=forward_days)
    return min(date.fromisoformat(max(days)) + timedelta(days=1), today - timedelta(days=reread))


def recategorize(entries):
    """Derived categories are recomputed every run from the verbatim fields kept in each entry, so an improved fixed
    table applies to the whole catalog, not only to new rows. Source-printed types (OJN) are never recomputed."""
    for e in entries:  # a printed 'no date' (OJN 00-00-0000) converted before 2026-10-20 becomes absent, never a date
        for k, v in list(e.get('dates', {}).items()):
            try:
                date.fromisoformat(v) if isinstance(v, str) else None  # None stays: it fails the schema (quarantine)
            except ValueError:
                del e['dates'][k]
    for e in entries:
        if e['source_id'].endswith('.dof'):
            e['category']['doc_type'] = dof_doc_type(e['title'], e['category'].get('branch'))
        elif e['source_id'].endswith(('leyes-federales', 'reglamentos-federales')):
            e['category']['doc_type'] = doc_type(e['title'])
        elif e['source_id'].endswith('hf-tesis-scjn'):
            e['category']['doc_type'] = hf_tesis.doc_type(e.get('listing', {}).get('type_printed'))


MAX_REREADS = 3  # after this many successful re-reads a still-short day is 'stuck': reported every run, retried spaced
MAX_BACKOFF_DAYS = 30


def short_days(days, entries, source_id, today=None):
    """Days that still owe something. Returns (requeue, stuck); the state is never modified, so a re-read that fails
    leaves the day owed and the next run asks again.

    Trust comes from provenance, not from counts: a day is owed while
    - it is a row from before 2026-10-20 (no 'ids'): read once more under today's code;
    - a note its page listed (independent count, so a note the parser cannot read is listed too) is not in the
      catalog, unless a person marked it 'withdrawn' with evidence;
    - a listed note's date has no 'date_source' (a legacy date, or a legacy row brought back by quarantine).
    A day re-read MAX_REREADS times and still owed is 'stuck': reported every run and re-read only from its
    retry_after date (spaced retries), never abandoned."""
    have = {e['native_id']: e for e in entries if e['source_id'] == source_id}
    requeue, stuck = [], []
    for d, info in sorted(days.items()):
        if 'ids' not in info:
            short = True
        else:
            withdrawn = set(info.get('withdrawn') or [])
            short = any(i not in have or not have[i].get('date_source') for i in info['ids'] if i not in withdrawn)
        if short:
            if info.get('rereads', 0) >= MAX_REREADS:
                stuck.append(d)
                if today is not None and today.isoformat() >= info.get('retry_after', ''):
                    requeue.append(d)
            else:
                requeue.append(d)
    return requeue, stuck


def raw_priority(e):
    """Order for fetching DOF raw texts (highest first): standards first, since their text is what compliance work
    reads, then the newest."""
    return normas.cites_nom(e.get('title') or ''), e['dates'].get('published') or '', e['native_id']


def host_groups(sources):
    """Group sources by the hosts they hit; groups run in parallel, members of a group run in sequence."""
    groups = defaultdict(list)
    for src in sources:
        groups[tuple(sorted(h.lower() for h in src['allowed_hosts']))].append(src)
    return list(groups.values())


def normalize_strings(obj, counter):
    """Apply clean_text to every string in an entry, counting removed invisible characters."""
    if isinstance(obj, dict):
        return {k: normalize_strings(v, counter) for k, v in obj.items()}
    if isinstance(obj, list):
        return [normalize_strings(v, counter) for v in obj]
    if isinstance(obj, str):
        clean, removed = clean_text(obj)
        counter[0] += removed
        return clean
    return obj


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
    def __init__(self, country, out, raw, budget, today, forward_days, index_days, parallel=True):
        self.registry = json.loads((REPO / 'sources' / f'{country.lower()}.json').read_text(encoding='utf-8'))
        self.country = self.registry['country']
        self.catalog = Catalog(out, self.country)
        self.raw = RawStore(raw)
        self.budget, self.today = budget, today
        self.forward_days, self.index_days = forward_days, index_days
        self.used = 0
        self.parallel = parallel
        self.deadline = None  # time.monotonic() value; set by --deadline-minutes
        self._lock = threading.Lock()
        self.manifest = {'run_id': now_iso().replace(':', ''), 'country': self.country, 'started_at': now_iso(),
                         'sources': {}, 'coverage': [], 'errors': [], 'robots': {}}

    def _fetcher(self, src, secrets=None):
        # Per-source budget: --budget when given, else the source's max_requests from the registry. The final robots.txt
        # URL of every origin goes to the manifest; `secrets` binds each credential to its one host.
        return Fetcher(src['allowed_hosts'], budget=self.budget if self.budget is not None else src.get('max_requests', 1500),
                       robots_log=self.manifest['robots'], secrets=secrets,
                       deadline=self.deadline)

    def _get(self, f, url, **kw):
        """Fetch one URL; a guard refusal (robots, host, size) skips only that URL and is recorded. Budget ends the run."""
        try:
            return f.get(url, **kw)
        except BudgetExhausted:
            raise
        except FetchRefused as exc:
            self.manifest['errors'].append(f'refused {url}: {exc}')
            return Response(0, b'', url, {'x-rg-refused': str(exc)[:200]})

    def _cover(self, source_id, scope, expected, got):
        ok = expected == got
        self.manifest['coverage'].append({'source_id': source_id, 'scope': scope, 'expected': expected, 'extracted': got, 'ok': ok})
        return ok

    # ---- DOF via SIDOF ----------------------------------------------------------------------------
    def run_sidof(self, src):
        f = self._fetcher(src)
        st = self.catalog.state.setdefault(src['source_id'], {'days': {}})
        days = st['days']
        requeued, stuck = short_days(days, self.catalog.snapshot(src['source_id']), src['source_id'], self.today)
        floor = date.fromisoformat(src['backfill_floor'])
        start = dof_window_start(days, self.today, self.forward_days)
        forward = [start + timedelta(days=i) for i in range((self.today - start).days + 1)]
        oldest = date.fromisoformat(min(days)) if days else start
        backfill = [oldest - timedelta(days=i) for i in range(1, self.index_days + 1) if oldest - timedelta(days=i) >= floor]
        stats = {'days_requeued': len(requeued), 'days_short_unresolved': len(stuck), 'days_indexed': 0, 'notes_new': 0,
                 'notes_dated_by_page': 0, 'raw_stored': 0, 'raw_skipped_metadata_only': 0, 'raw_robots_disallowed': 0,
                 'raw_failed': 0}
        try:
            again = set(requeued)
            # Days inside the indexed range that are missing (a page that failed) are read again, with the requeued.
            gaps = [date.fromisoformat(min(days)) + timedelta(days=i) for i in range((self.today - date.fromisoformat(min(days))).days)] if days else []
            for day in dict.fromkeys([date.fromisoformat(d) for d in requeued] + [g for g in gaps if g.isoformat() not in days]
                                     + forward + backfill):  # each day once
                key = day.isoformat()
                if key in days and key not in again and day < self.today - timedelta(days=2):
                    continue  # closed day already indexed and whole; the last 3 days are re-read for late notes
                r = self._get(f, sidof.day_url(src['base_url'], day))
                if r.status != 200:
                    self.manifest['errors'].append(f'{src["source_id"]} {key}: HTTP {r.status}')
                    self._cover(src['source_id'], key, None, 0)  # page not read: the run is not whole (exit 3)
                    continue
                page = r.text()
                items = sidof.parse_day(page)
                if not items:  # no real DOF day lists 0 notes (0 of 392 indexed): a soft error page, read again
                    self.manifest['errors'].append(f'{src["source_id"]} {key}: page lists no notes')
                    self._cover(src['source_id'], key, None, 0)
                    continue
                self._cover(src['source_id'], key, sidof.count_listed(page), len(items))
                self._cover(src['source_id'], f'{key} fecha oficial', len(items), sum(1 for it in items if it['published']))
                stats['notes_dated_by_page'] += sum(1 for it in items if it['published'] and not it['edition_date'])
                for it in items:
                    branch = it['branch'] or ''
                    meta_only = fold(branch) in {fold(b) for b in src.get('metadata_only_branches', [])}
                    entry_id = f"{src['source_id']}:{it['native_id']}"
                    old = self.catalog.entries.get(entry_id)
                    # The official date and where it came from: the edition's own PDF link, else the page's own date,
                    # else the date an earlier read under this code already took from one of those. A date with no
                    # provenance is never reused: None fails the schema (quarantine) and the day stays owed.
                    published = it['published']
                    source = 'edition' if it['edition_date'] else ('page' if published else None)
                    if not published and old and old.get('date_source'):
                        published, source = old['dates'].get('published'), old['date_source']
                    entry = {
                        'entry_id': entry_id, 'country': self.country, 'source_id': src['source_id'],
                        'native_id': it['native_id'], 'title': it['title'],
                        'url': sidof.note_url(src['base_url'], it['native_id']),
                        'category': {**src['category'], 'edition': it['edition'], 'section': it['section'],
                                     'branch': it['branch'], 'issuer': it['issuer'], 'doc_type': dof_doc_type(it['title'], it['branch'])},
                        'dates': {'published': published},
                        'raw_status': old['raw_status'] if old else ('metadata_only' if meta_only else 'pending'),
                        'first_seen': now_iso(),
                    }
                    if source:
                        entry['date_source'] = source
                    for k in ('artifact', 'raw_path'):
                        if old and k in old:
                            entry[k] = old[k]
                    stats['notes_new'] += self.catalog.upsert(entry)
                prev = days.get(key, {})
                # once listed, always owed; the independent list also names notes the parser could not read
                ids = list(dict.fromkeys(prev.get('ids', []) + sidof.listed_ids(page) + [it['native_id'] for it in items]))
                days[key] = {'ids': ids, 'notes': len(ids), 'indexed_at': now_iso(),
                             'rereads': prev.get('rereads', 0) + 1 if key in again else 0}
                if prev.get('withdrawn'):  # set only by a person, with evidence that the source no longer lists them
                    days[key]['withdrawn'] = prev['withdrawn']
                if days[key]['rereads'] >= MAX_REREADS:  # spaced retries: 3, 6, 12, 24, 30, 30... days
                    wait = min(MAX_BACKOFF_DAYS, 3 * 2 ** (days[key]['rereads'] - MAX_REREADS))
                    days[key]['retry_after'] = (self.today + timedelta(days=wait)).isoformat()
                stats['days_indexed'] += 1
            # robots_disallowed is checked again against today's robots.txt (cached: no request per note).
            pending = sorted((e for e in self.catalog.snapshot(src['source_id']) if e['raw_status'] in ('pending', 'failed', 'robots_disallowed')),
                             key=raw_priority, reverse=True)
            for e in pending:
                url = sidof.raw_url(src['base_url'], e['native_id'])
                try:
                    if not f.allowed(url):
                        e['raw_status'] = 'robots_disallowed' if f.disallowed_by_rule(url) else 'failed'
                        stats['raw_robots_disallowed' if e['raw_status'] == 'robots_disallowed' else 'raw_failed'] += 1
                        continue
                    r = self._get(f, url)
                except FetchRefused as exc:
                    if isinstance(exc, BudgetExhausted):
                        raise
                    e['raw_status'] = 'robots_disallowed' if f.disallowed_by_rule(url) else 'failed'
                    stats['raw_robots_disallowed' if e['raw_status'] == 'robots_disallowed' else 'raw_failed'] += 1
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
        # Exit 0 only when nothing is owed: every day whose notes or official date are still missing at the end of
        # the run (failed, degraded, unread for lack of budget, or stuck) fails the run, every run, until resolved.
        owed, stuck = short_days(days, self.catalog.snapshot(src['source_id']), src['source_id'])
        for d in sorted(set(owed) | set(stuck)):
            self._cover(src['source_id'], f'{d} notas o fecha oficial pendientes al cerrar', days[d].get('notes', 0), None)
        stats['days_owed_at_end'] = len(set(owed) | set(stuck))
        stats['raw_skipped_metadata_only'] = sum(1 for e in self.catalog.snapshot(src['source_id']) if e['raw_status'] == 'metadata_only')
        stats['requests'] = f.used
        with self._lock:
            self.used += f.used
        return stats

    # ---- Laws and regulations (LeyesBiblio) -------------------------------------------------------
    def run_leyesbiblio(self, src):
        f = self._fetcher(src)
        st = self.catalog.state.setdefault(src['source_id'], {'etags': {}})
        stats = {'listed': 0, 'new_instruments': 0, 'new_versions': 0, 'unchanged': 0, 'raw_failed': 0}
        try:
            r = self._get(f, src['base_url'] + src['listing'])
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
                resp = self._get(f, row['raw_url'], etag=cached.get('etag'), last_modified=cached.get('last_modified'))
                if resp.status == 304 and not entry.get('raw_path'):  # validators cached but no bytes kept: fetch again
                    resp = self._get(f, row['raw_url'])
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
        with self._lock:
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
                    r = self._get(f, ojn.list_url(src['base_url'], edo, power, src['liberado']))
                    if r.status != 200:
                        self.manifest['errors'].append(f"{src['source_id']} edo {edo} poder {power}: HTTP {r.status}")
                        continue
                    page = decode_html(r.body, r.charset if 'charset' in r.headers.get('content-type', '').lower() else 'iso-8859-1')
                    items, state = ojn.parse_list(page), ojn.state_name(page)
                    total, rows = ojn.printed_total(page), ojn.count_rows(page)
                    # The printed total counts rows; the source repeats some rows verbatim (same idArchivo), so the
                    # accounting is: printed == rows read, and rows == unique + repeated-in-source.
                    self._cover(src['source_id'], f'edo {edo} poder {power} (filas leídas vs total impreso)', -1 if total is None else total, rows)
                    self._cover(src['source_id'], f'edo {edo} poder {power} (fichas distintas en la página vs catalogadas)',
                                ojn.count_ids(page), len({it['native_id'] for it in items}))
                    stats['listings'] += 1
                    stats['listed'] += len(items)
                    stats['source_repeated_rows'] = stats.get('source_repeated_rows', 0) + rows - len(items)
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
            self._ojn_fetch_pending(src, f, st, stats)
        except BudgetExhausted:
            self.manifest['errors'].append(f"{src['source_id']}: request budget reached (continues next run)")
        stats['requests'] = f.used
        with self._lock:
            self.used += f.used
        return stats

    def _ojn_fetch_pending(self, src, f, st, stats):
        """Record sheet + document for every pending entry of an OJN source, laws first. BudgetExhausted propagates."""
        pending = sorted((e for e in self.catalog.snapshot(src['source_id']) if e['raw_status'] in ('pending', 'failed')),
                         key=lambda e: (not e['category']['doc_type'].startswith(self.PRIORITY), e['listing']['state_code'], int(e['native_id'])))
        for e in pending:
            r = self._get(f, e['url'])
            if r.status != 200:
                e['raw_status'] = 'failed'
                stats['raw_failed'] += 1
                continue
            sheet = ojn.parse_ficha(decode_html(r.body, 'iso-8859-1'), src['base_url'])
            if sheet['status_printed']:
                e['category']['status_printed'] = sheet['status_printed'].upper()
            if sheet['locality'] and e['category']['jurisdiction'] == 'estatal':
                e['category']['locality'] = sheet['locality']
            if not sheet['doc_url']:
                e['raw_status'] = 'no_text_link'
                stats['no_document_link'] += 1
                continue
            cached = st['etags'].get(sheet['doc_url'], {})
            d = self._get(f, sheet['doc_url'], etag=cached.get('etag'), last_modified=cached.get('last_modified'))
            if d.status == 304 and not e.get('raw_path'):  # validators cached but no bytes kept: fetch again
                d = self._get(f, sheet['doc_url'])
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

    def run_ojn_municipal(self, src):
        """Municipal instruments per municipality, from each state's own selector. Listings refresh every
        src['relist_days'] days (about 2,500 municipalities, rarely changing); pending documents are fetched every run."""
        f = self._fetcher(src)
        st = self.catalog.state.setdefault(src['source_id'], {'etags': {}, 'listed_at': {}})
        stats = {'states': 0, 'municipalities_listed': 0, 'listed': 0, 'new_instruments': 0, 'raw_stored': 0,
                 'raw_unchanged': 0, 'raw_failed': 0, 'no_document_link': 0}
        try:
            for edo in src['states']:
                last = st['listed_at'].get(str(edo))
                if last and (self.today - date.fromisoformat(last)).days < src.get('relist_days', 30):
                    continue
                r = self._get(f, ojn.state_page_url(src['base_url'], edo, src['liberado']))
                if r.status != 200:
                    self.manifest['errors'].append(f"{src['source_id']} edo {edo}: state page HTTP {r.status}")
                    continue
                state_page = decode_html(r.body, 'iso-8859-1')
                state = ojn.state_name(state_page)
                stats['states'] += 1
                incomplete = False
                for mun_id, mun_name in ojn.parse_municipalities(state_page):
                    pr = self._get(f, ojn.municipal_url(src['base_url'], edo, mun_id))
                    if pr.status != 200:
                        self.manifest['errors'].append(f"{src['source_id']} edo {edo} mun {mun_id}: HTTP {pr.status}")
                        incomplete = True
                        continue
                    page = decode_html(pr.body, 'iso-8859-1')
                    state = state or ojn.state_name(page)
                    items, total = ojn.parse_list(page), ojn.printed_total(page)
                    self._cover(src['source_id'], f'edo {edo} mun {mun_id} (filas leídas vs total impreso)',
                                -1 if total is None else total, ojn.count_rows(page))
                    self._cover(src['source_id'], f'edo {edo} mun {mun_id} (fichas distintas en la página vs catalogadas)',
                                ojn.count_ids(page), len({it['native_id'] for it in items}))
                    stats['municipalities_listed'] += 1
                    stats['listed'] += len(items)
                    for order, it in enumerate(items, 1):
                        entry_id = f"{src['source_id']}:{it['native_id']}"
                        old = self.catalog.entries.get(entry_id)
                        entry = {
                            'entry_id': entry_id, 'country': self.country, 'source_id': src['source_id'],
                            'native_id': it['native_id'], 'title': it['title'],
                            'url': ojn.ficha_url(src['base_url'], it['native_id'], it['ambito']),
                            'category': {**src['category'], 'locality': state, 'municipality': mun_name,
                                         'doc_type': fold(it['type_printed']) or 'OTRO'},
                            'dates': {}, 'listing': {'state_code': edo, 'page_order': order,
                                                     'listing_text': ' | '.join((it['title'], it['type_printed']))},
                            'raw_status': old['raw_status'] if old else 'pending',
                            'versions': old.get('versions', []) if old else [], 'first_seen': now_iso(),
                        }
                        if old and old['category'].get('status_printed'):
                            entry['category']['status_printed'] = old['category']['status_printed']
                        for k in ('artifact', 'raw_path'):
                            if old and k in old:
                                entry[k] = old[k]
                        stats['new_instruments'] += self.catalog.upsert(entry)
                if not incomplete:  # a state with a failed municipality is listed again next run, not in 30 days
                    st['listed_at'][str(edo)] = self.today.isoformat()
            self._ojn_fetch_pending(src, f, st, stats)
        except BudgetExhausted:
            self.manifest['errors'].append(f"{src['source_id']}: request budget reached (continues next run)")
        stats['requests'] = f.used
        with self._lock:
            self.used += f.used
        return stats

    # ---- SCJN tesis, SECONDARY source: Hugging Face dataset (hf_tesis.py) --------------------------
    def run_hf_tesis(self, src):
        """One 3.6 GB file, downloaded only when its sha256 changed or rows it produced are missing from the catalog.
        Coverage: the file's own total_points == rows read, and distinct registros digitales == entries catalogued."""
        f = self._fetcher(src)
        st = self.catalog.state.setdefault(src['source_id'], {})
        stats = {'downloaded': False, 'rows_read': 0, 'distinct': 0, 'source_repeated_rows': 0, 'new_entries': 0}
        try:
            self._hf_tesis(src, f, st, stats)
        except BudgetExhausted:
            self.manifest['errors'].append(f"{src['source_id']}: request budget reached (continues next run)")
            self._cover(src['source_id'], src['file'], None, 0)
        stats['requests'] = f.used
        with self._lock:
            self.used += f.used
        return stats

    def _hf_tesis(self, src, f, st, stats):
        sid = src['source_id']
        r = self._get(f, hf_tesis.API_URL.format(dataset=src['dataset']))  # public metadata: sent without the token
        try:
            if r.status != 200:
                raise ValueError(f'Hub API HTTP {r.status}')
            meta = hf_tesis.parse_meta(r.body, src['file'], src['license_id'])
        except ValueError as exc:
            self.manifest['errors'].append(f'{sid}: {exc}')
            self._cover(sid, src['file'], None, 0)
            return
        scope = f"{src['file']} @ {meta['revision'][:12]}"

        def catalogued():
            return sum(1 for e in self.catalog.snapshot(sid) if (e.get('artifact') or {}).get('sha256') == meta['sha256'])
        if st.get('sha256') == meta['sha256'] and st.get('distinct') == catalogued():
            # Same file and every row it produced is still catalogued: nothing to download. The receipts of the run
            # that read it are checked again every run, so a file that did not reconcile keeps failing.
            self._cover(sid, f'{scope} (total_points declarado vs filas leídas)', st['total_points'], st['rows_read'])
            self._cover(sid, f'{scope} (registros digitales distintos vs catalogados)', st['distinct'], catalogued())
            return
        token = os.environ.get(src['token_env'], '')
        if not token:
            self.manifest['errors'].append(f"{sid}: {src['token_env']} is not set; the gated file is not requested")
            self._cover(sid, scope, None, 0)
            return
        url = hf_tesis.RESOLVE_URL.format(dataset=src['dataset'], revision=meta['revision'], file=src['file'])
        sink = FileSink(self.raw.root / f'.{sid}.{os.getpid()}.part', meta['size'])
        try:
            try:
                d = f.get(url, auth=f'Bearer {token}', sink=sink)
            except BudgetExhausted:
                raise
            except FetchRefused as exc:
                d = Response(0, b'', url, {'x-rg-refused': hf_tesis.redact(str(exc))[:300]})
            if d.status != 200 or sink.bytes != meta['size'] or sink.sha256 != meta['sha256']:
                self.manifest['errors'].append(
                    f"{sid}: {scope}: HTTP {d.status} {d.headers.get('x-rg-refused', '')} {sink.bytes} of {meta['size']} "
                    f"bytes, sha256 {'ok' if sink.sha256 == meta['sha256'] else 'differs from the Hub metadata'}")
                self._cover(sid, scope, None, 0)
                return
            rel = self.raw.put_file(sink.path, meta['sha256'], 'json')
        finally:
            sink.path.unlink(missing_ok=True)
        stats['downloaded'] = True
        artifact = {**_artifact(src, url, meta['sha256'], b'', 'application/json', rel), 'bytes': meta['size']}
        header, seen, now, complete = {}, set(), now_iso(), True
        with open(self.raw.root / rel, 'rb') as fh:
            try:
                for order, point in enumerate(hf_tesis.iter_points(fh, header), 1):
                    stats['rows_read'] += 1
                    entry = hf_tesis.to_entry(src, self.country, point, order, artifact, rel, now)
                    if entry['native_id'] in seen:  # repeated in the source: the first row stays, repeats are counted
                        stats['source_repeated_rows'] += 1
                        continue
                    seen.add(entry['native_id'])
                    stats['new_entries'] += self.catalog.upsert(entry)
            except ValueError as exc:  # malformed file: what was read is kept, the run is not whole
                complete = False
                self.manifest['errors'].append(f'{sid}: {scope}: {exc}')
        declared = header.get('total_points')
        stats['distinct'] = len(seen)
        self._cover(sid, f'{scope} (total_points declarado vs filas leídas)',
                    declared if isinstance(declared, int) else None, stats['rows_read'] if complete else None)
        self._cover(sid, f'{scope} (registros digitales distintos vs catalogados)', len(seen), catalogued())
        if complete:  # a file read only in part is downloaded again next run
            st.update(revision=meta['revision'], sha256=meta['sha256'], total_points=declared,
                      rows_read=stats['rows_read'], distinct=len(seen))

    # ---- Calculation indicators: Banxico SIE and INEGI BIE (indicadores.py) -----------------------
    def run_indicadores(self, src):
        """The whole history of each registered series, every run. Raw responses are kept byte-exact; one entry per
        observation as served; per series, observations served == entries stored (exit 3 otherwise). The token goes
        only to its own host and is never recorded: every recorded URL carries '<token>'."""
        sid = src['source_id']
        stats = {'series': len(src['series']), 'observations_served': 0, 'entries_new': 0, 'entries_changed': 0,
                 'raw_stored': 0, 'raw': {}}
        done = set()
        token = os.environ.get(src['token_env'], '')
        if not indicadores.valid_token(token):
            self.manifest['errors'].append(f"{sid}: {src['token_env']} is not set or not a valid token; nothing is requested")
        else:
            f = self._fetcher(src, secrets={token: src['token_host']})
            try:
                if src['adapter'] == 'banxico-sie':
                    self._banxico(src, f, token, stats, done)
                else:
                    self._inegi(src, f, token, stats, done)
            except BudgetExhausted:
                self.manifest['errors'].append(f'{sid}: request budget reached (continues next run)')
            stats['requests'] = f.used
            with self._lock:
                self.used += f.used
        for s in src['series']:
            if s['id'] not in done:  # not read this run (no token, budget): the run is not whole
                self._cover(sid, f"{s['id']} (serie no leída)", None, 0)
        return stats

    def _ind_error(self, sid, text, token):
        self.manifest['errors'].append(indicadores.redact(f'{sid}: {text}', token)[:400])

    def _ind_get(self, f, sid, url, shown, token, **kw):
        """Like _get, but what is recorded names `shown` (the URL with '<token>'), never the URL that was sent."""
        try:
            r = f.get(url, **kw)
        except BudgetExhausted:
            raise
        except FetchRefused as exc:
            self._ind_error(sid, f'refused {shown}: {exc}', token)
            return Response(0, b'', shown, {})
        if r.status != 200:
            self._ind_error(sid, f'{shown}: HTTP {r.status} {r.body[:200].decode("utf-8", "replace")}', token)
        return r

    def _ind_store(self, sid, r, token, stats, key):
        """Raw bytes exactly as served, unless they echo the credential: then nothing is kept."""
        if r.status != 200:
            return None
        if token.encode() in r.body:
            self._ind_error(sid, f'{key}: the response contains the credential; it is not stored', token)
            return None
        sha, rel = self.raw.put(r.body, 'json')
        stats['raw'][key] = rel
        stats['raw_stored'] += 1
        return sha, rel

    def _ind_catalog(self, src, series_id, scope, r, stored, shown, token, title, unit, observations, date_key, stats):
        sid = src['source_id']
        served = indicadores.served_count(r.body, date_key) if stored else 0
        stats['observations_served'] += served
        if not stored or not served or not title or unit is None:
            missing = [k for k, v in (('raw', stored), ('observaciones', served), ('título', title), ('unidad', unit)) if not v]
            self._ind_error(sid, f'{series_id}: not catalogued, missing {", ".join(missing)}', token)
            self._cover(sid, scope, served or None, 0)
            return
        sha, rel = stored
        artifact, now = _artifact(src, shown, sha, r.body, 'application/json', rel), now_iso()
        for order, (date_printed, value) in enumerate(observations, 1):
            e = indicadores.entry(src, self.country, series_id, title, unit, order, date_printed, value, shown,
                                  artifact, rel, now)
            if e['native_id'] is None:
                self._ind_error(sid, f'{series_id}: observation {order} has no usable date', token)
                continue
            old = self.catalog.entries.get(e['entry_id'])
            if old and all(old.get(k) == e[k] for k in ('observation', 'title', 'listing')):
                continue  # unchanged: the row keeps the raw that first served it
            stats['entries_changed' if old else 'entries_new'] += 1
            self.catalog.upsert(e)
        stored_n = sum(1 for e in self.catalog.snapshot(sid) if (e.get('observation') or {}).get('series_id') == series_id)
        self._cover(sid, scope, served, stored_n)

    def _banxico(self, src, f, token, stats, done):
        sid, auth, end = src['source_id'], (src['token_header'], token), self.today.isoformat()
        series = [s for s in src['series'] if indicadores.valid_series(s['id'])]
        meta_url = indicadores.BANXICO_META.format(series=','.join(s['id'] for s in series))
        m = self._ind_get(f, sid, meta_url, meta_url, token, auth=auth)
        meta = {}
        if self._ind_store(sid, m, token, stats, 'metadatos'):
            try:
                meta = indicadores.parse_banxico_meta(m.body)
            except ValueError as exc:
                self._ind_error(sid, f'metadatos: {exc}', token)
        for s in series:
            url = indicadores.BANXICO_DATOS.format(series=s['id'], start=s['start'], end=end)
            r = self._ind_get(f, sid, url, url, token, auth=auth)
            stored = self._ind_store(sid, r, token, stats, s['id'])
            title, observations = None, []
            if stored:
                try:
                    title, observations = indicadores.parse_banxico_datos(r.body, s['id'])
                except ValueError as exc:
                    self._ind_error(sid, f"{s['id']}: {exc}", token)
            info = meta.get(s['id'], {})
            self._ind_catalog(src, s['id'], f"{s['id']} {s['start']}..{end} (observaciones servidas vs catalogadas)", r,
                              stored, url, token, title or info.get('titulo'), info.get('unidad'), observations, 'fecha', stats)
            done.add(s['id'])

    def _inegi(self, src, f, token, stats, done):
        sid = src['source_id']
        for s in src['series']:
            if not indicadores.valid_series(s['id']):
                continue
            (url, shown), (cat_url, cat_shown) = indicadores.inegi_urls(src, s['id'], token)
            c = self._ind_get(f, sid, cat_url, cat_shown, token)
            title = None
            if self._ind_store(sid, c, token, stats, f"{s['id']} CL_INDICATOR"):
                try:
                    title = indicadores.parse_inegi_catalog(c.body, s['id'])
                except ValueError as exc:
                    self._ind_error(sid, f"{s['id']} CL_INDICATOR: {exc}", token)
            r = self._ind_get(f, sid, url, shown, token)
            stored = self._ind_store(sid, r, token, stats, s['id'])
            unit, observations = None, []
            if stored:
                try:
                    unit, observations = indicadores.parse_inegi_indicator(r.body, s['id'])
                except ValueError as exc:
                    self._ind_error(sid, f"{s['id']}: {exc}", token)
            self._ind_catalog(src, s['id'], f"{s['id']} serie histórica completa (observaciones servidas vs catalogadas)",
                              r, stored, shown, token, title, unit, observations, 'TIME_PERIOD', stats)
            done.add(s['id'])

    def execute(self, only=None):
        # 'trial' sources (new, formats still HIPÓTESIS) run only when named; the scheduled run never reaches them.
        active = [s for s in self.registry['sources'] if (not only or s['source_id'] in only)
                  and (s['status'] == 'active' or (s['status'] == 'trial' and only))]
        runners = {'sidof': self.run_sidof, 'leyesbiblio': self.run_leyesbiblio, 'ojn': self.run_ojn,
                   'ojn-municipal': self.run_ojn_municipal, 'hf-tesis': self.run_hf_tesis,
                   'banxico-sie': self.run_indicadores, 'inegi-bie': self.run_indicadores}
        def run_group(srcs):  # sources sharing a host run one after another: politeness is per host
            for src in srcs:
                self.manifest['sources'][src['source_id']] = runners[src['adapter']](src)
        groups = host_groups(active)
        if self.parallel and len(groups) > 1:
            with ThreadPoolExecutor(max_workers=len(groups)) as pool:
                list(pool.map(run_group, groups))
        else:
            for g in groups:
                run_group(g)
        self.manifest['planned_sources'] = {s['source_id']: s.get('blocked_by') for s in self.registry['sources']
                                            if s['status'] not in ('active', 'trial')}
        self.manifest['requests_total'] = self.used
        self.manifest['raw_new_files'] = len(self.raw.new_files)
        self.manifest['finished_at'] = now_iso()
        return self.manifest


def secrets_in_env(registry):
    """Every credential a source of the registry reads from the environment (to keep them out of what is written)."""
    return [v for s in registry['sources'] if s.get('token_env') and len(v := os.environ.get(s['token_env'], '')) >= 16]


def redact_secrets(obj, secrets):
    if isinstance(obj, dict):
        return {k: redact_secrets(v, secrets) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_secrets(v, secrets) for v in obj]
    if isinstance(obj, str):
        for s in secrets:
            obj = indicadores.redact(obj, s)
    return obj


def quarantine(catalog, invalid):
    """Entries failing the schema are never written as they are. Each keeps its last valid row on disk (and so its
    versions history), if it had one; a new invalid entry is dropped. Both are listed in the manifest by the caller."""
    previous = catalog.previous(invalid)
    for eid in invalid:
        if eid in previous and not validate('catalog_entry', previous[eid]):
            # the new text was fetched but is not kept: forget its validators, or the next run gets 304 and never adds it
            etags = catalog.state.get(previous[eid]['source_id'], {}).get('etags', {})
            for row in (catalog.entries[eid], previous[eid]):
                etags.pop((row.get('artifact') or {}).get('url'), None)
            catalog.entries[eid] = previous[eid]
        else:
            del catalog.entries[eid]


def main(argv=None):
    a = argparse.ArgumentParser(description='RESEARCH GROUP country catalog run')
    a.add_argument('--country', required=True)
    a.add_argument('--out', required=True, help='catalog root (data branch checkout)')
    a.add_argument('--raw', required=True, help='raw corpus root (never committed)')
    a.add_argument('--budget', type=int, help='max HTTP requests per source this run (default: each source max_requests)')
    a.add_argument('--sequential', action='store_true', help='run host groups one after another')
    a.add_argument('--today', help='YYYY-MM-DD (default: today in Mexico City)')
    a.add_argument('--forward-days', type=int, default=30, help='first run: days back from today to index')
    a.add_argument('--index-days', type=int, default=120, help='older days to index per run, toward the floor')
    a.add_argument('--sources', help='comma-separated source ids (default: all active)')
    a.add_argument('--bundle', help='write a tar of the raw files new in this run')
    a.add_argument('--deadline-minutes', type=float, help='stop sending requests after this many minutes (job time limit)')
    x = a.parse_args(argv)
    today = date.fromisoformat(x.today) if x.today else datetime.now(CDMX).date()
    run = Run(x.country, x.out, x.raw, x.budget, today, x.forward_days, x.index_days, parallel=not x.sequential)
    if x.deadline_minutes is not None:
        run.deadline = time.monotonic() + 60 * x.deadline_minutes
    crashed = None
    try:
        manifest = run.execute(set(x.sources.split(',')) if x.sources else None)
    except Exception as exc:  # never lose what was gathered: write it, record the crash, exit 1
        crashed = f'{type(exc).__name__}: {exc}'
        manifest = run.manifest
        manifest['errors'].append(f'run crashed: {crashed}')
        manifest['requests_total'], manifest['raw_new_files'] = run.used, len(run.raw.new_files)
        manifest['finished_at'] = now_iso()
    if x.bundle and run.raw.new_files:
        with tarfile.open(x.bundle, 'w') as tar:
            for rel in sorted(run.raw.new_files):
                tar.add(Path(x.raw) / rel, arcname=rel)
        manifest['raw_bundle'] = Path(x.bundle).name
    recategorize(run.catalog.entries.values())
    removed = [0]
    run.catalog.entries = {eid: normalize_strings(e, removed) for eid, e in run.catalog.entries.items()}
    manifest['invisible_chars_removed'] = removed[0]
    invalid = {eid: errs[:3] for eid, e in run.catalog.entries.items() if (errs := validate('catalog_entry', e))}
    quarantine(run.catalog, invalid)
    manifest['quarantined'] = invalid
    if invalid:
        manifest['errors'].append(f'{len(invalid)} entries quarantined (fail the catalog_entry schema), see quarantined')
    manifest = redact_secrets(manifest, secrets_in_env(run.registry))  # the manifest and the log never hold a token
    run.catalog.write()
    if x.country.lower() == 'mx':  # NOM lineages come from the DOF; no other country has them
        dof = run.catalog.snapshot('mx.dof')
        manifest['nom_lineages'] = normas.write(run.catalog.dir, dof)
        missed = normas.unparsed(dof)  # a title that seems to name a NOM must yield a code, or the run is not whole
        manifest['coverage'].append({'source_id': 'mx.normas', 'scope': 'titulos con NOM sin codigo leido',
                                     'expected': 0, 'extracted': len(missed), 'ok': not missed, 'entries': missed[:20]})
    tratados.derive(run.catalog.dir, run.catalog.snapshot(), manifest)  # derived view + its independent check
    run.catalog.write_run(manifest)
    bad = [c for c in manifest['coverage'] if not c['ok']]
    if invalid:
        print(json.dumps({'quarantined': dict(list(invalid.items())[:5])}, ensure_ascii=False, indent=1))
    print(json.dumps({'run_id': manifest['run_id'], 'sources': manifest['sources'], 'coverage_checks': len(manifest['coverage']),
                      'coverage_failures': bad, 'errors': manifest['errors'][:10], 'requests': manifest['requests_total'],
                      'raw_new_files': manifest['raw_new_files'], 'catalog_total': len(run.catalog.entries)}, ensure_ascii=False, indent=1))
    if crashed:
        return 1
    return 4 if invalid else (3 if bad else 0)


if __name__ == '__main__':
    sys.exit(main())
