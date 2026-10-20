"""DOF catalog invariants under any sequence of page reads and runs (no network).

Three audit rounds each found a new way to lose or misdate a note by combining reads that every single-case test
passed. So this file states the composed property and searches for a counterexample: real main() runs over a catalog
kept on disk, a DOF calendar (weekday editions, weekend mirrors), dates that advance so days close, a start from the
legacy catalog (count-only rows, Friday notes dated Sunday), random reads per day (good, no dates, no PDF links,
malformed date, a note the parser misses, a note withdrawn, empty, failed) and small budgets. After every run:
  I1 nothing crashes;
  I2 exit 0 => every listed note carries the official date of its edition (a weekend page: its Friday);
  I3 exit 0 => every listed note is in the catalog (nothing owed goes unreported);
  I4 a day once read never leaves the state.
After good runs (the site recovers): I5 every listed note is catalogued with its official date.
"""
import contextlib
import io
import os
import random
import re
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

from rg.catalog import sidof
from rg.catalog.run import MAX_REREADS, Run, quarantine, recategorize
from rg.schemas import validate
from tests.test_catalog import FIX, SAT, SIDOF, FakeOpener
from rg.catalog.fetch import Fetcher
from rg.catalog.store import Catalog

FRI = (FIX / 'sidof_day_2026-10-16_two_editions.html').read_text(encoding='utf-8')
MIRROR = (FIX / SAT).read_text(encoding='utf-8')
IDS = {i['native_id'] for i in sidof.parse_day(FRI)}
OFFICIAL = '2026-10-16'
DAYS = [date(2026, 10, 16), date(2026, 10, 17), date(2026, 10, 18)]


def strip(page, inputs=('pdfMat', 'pdfVes', 'pdfExt', 'fechaPub')):
    return re.sub(r'(<input[^>]*id="(?:%s)"[^>]*value=")[^"]*"' % '|'.join(inputs), r'\1"', page)


def drop_one(page):  # the parser skips a note with an empty title; the independent count still sees it
    return re.sub(r'(<a[^>]*class="sumario-nota"[^>]*>)(.*?)(</a>)', r'\1\3', page, count=1, flags=re.S)


OK = lambda p: (200, p.encode('utf-8'), {})  # noqa: E731
VARIANTS = {
    'friday': {'own': OK(FRI), 'drop_one': OK(drop_one(FRI)), 'no_dates': OK(strip(FRI)), 'fail': (503, b'', {}),
               'empty': OK('<html><body>Alta demanda</body></html>')},
    'mirror': {'mirror': OK(MIRROR), 'no_pdf': OK(strip(MIRROR, ('pdfMat', 'pdfVes', 'pdfExt'))),
               'no_dates': OK(strip(MIRROR)), 'fail': (503, b'', {}), 'empty': OK('<html></html>')},
}
GOOD = {DAYS[0]: VARIANTS['friday']['own'], DAYS[1]: VARIANTS['mirror']['mirror'], DAYS[2]: VARIANTS['mirror']['mirror']}


class World:
    def __init__(self, tmp):
        self.run = Run('MX', tmp + '/out', tmp + '/raw', None, DAYS[-1], 2, 0)  # the 3 days are always re-read
        self.src = next(s for s in self.run.registry['sources'] if s['source_id'] == 'mx.dof')

    def one_run(self, pages):
        routes = {SIDOF + '/robots.txt': (200, b'User-agent: *\nDisallow: /notas/docFuente/\n', {})}
        routes.update({sidof.day_url(SIDOF, d): r for d, r in pages.items()})
        f = Fetcher(['sidof.segob.gob.mx'], opener=FakeOpener(routes), clock=lambda: 0.0, sleep=lambda s: None, retries=0)
        run = self.run
        run._fetcher = lambda s: f
        run.manifest.update({'coverage': [], 'errors': []})
        run.run_sidof(self.src)  # I1: an exception fails the test
        entries = run.catalog.entries
        recategorize(entries.values())
        invalid = {eid: errs for eid, e in entries.items() if (errs := validate('catalog_entry', e))}
        quarantine(run.catalog, invalid)
        bad = [c for c in run.manifest['coverage'] if not c['ok']]
        return 4 if invalid else (3 if bad else 0)

    def dof(self):
        return {e['native_id']: e for e in self.run.catalog.snapshot('mx.dof')}


class Invariants(unittest.TestCase):
    def check(self, world, code, seen_days, label):
        notes = world.dof()
        wrong = {i: e['dates'].get('published') for i, e in notes.items() if e['dates'].get('published') != OFFICIAL}
        self.assertEqual(wrong, {}, f'I2 {label}')
        if IDS - set(notes):
            self.assertNotEqual(code, 0, f'I3 {label}: {len(IDS - set(notes))} notes missing, exit 0')
        self.assertTrue(seen_days <= set(world.run.catalog.state['mx.dof']['days']), f'I4 {label}')

    def test_degraded_mirror_after_its_owner_keeps_the_official_date(self):
        # Audit of #6 round 2, blocking: Friday then a Saturday mirror without inputs set all 57 notes to None.
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            code = world.one_run({DAYS[0]: VARIANTS['friday']['own'], DAYS[1]: VARIANTS['mirror']['no_dates'],
                                  DAYS[2]: VARIANTS['mirror']['fail']})
            self.assertEqual({e['dates']['published'] for e in world.dof().values()}, {OFFICIAL})
            self.assertEqual(code, 3)  # the mirror's 'fecha oficial' check still fails

    def test_undated_and_dated_pending_notes_together_do_not_crash(self):
        # Audit of #6 round 2, blocking: the pending sort compared None with a date and aborted the run.
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.run.catalog.entries['mx.dof:1'] = {'entry_id': 'mx.dof:1', 'source_id': 'mx.dof', 'native_id': '1', 'title': 'Nota',
                                                    'category': {}, 'dates': {'published': '2026-10-10'}, 'raw_status': 'pending'}
            world.one_run({DAYS[0]: VARIANTS['friday']['no_dates'], DAYS[1]: VARIANTS['mirror']['fail'],
                           DAYS[2]: VARIANTS['mirror']['fail']})

    def test_a_note_the_parser_misses_keeps_its_day_owed(self):
        # Audit of #6 round 2: 'notes' ignored the independent count, so the day closed with 56 of 57.
        from rg.catalog.run import short_days
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.one_run({DAYS[0]: VARIANTS['friday']['drop_one'], DAYS[1]: VARIANTS['mirror']['fail'],
                           DAYS[2]: VARIANTS['mirror']['fail']})
            days = world.run.catalog.state['mx.dof']['days']
            self.assertEqual(days['2026-10-16']['notes'], 57)
            self.assertIn('2026-10-16', short_days(days, world.run.catalog.snapshot('mx.dof'), 'mx.dof')[0])

    def test_stuck_day_fails_the_run_and_is_retried_later(self):
        # Round 2: a stuck day was only logged (exit 0) and, after the cap, never read again.
        from rg.catalog.run import short_days
        days = {'2026-10-01': {'ids': ['9'], 'notes': 1, 'rereads': MAX_REREADS, 'retry_after': '2026-10-25'}}
        self.assertEqual(short_days(days, [], 'mx.dof', date(2026, 10, 24)), ([], ['2026-10-01']))
        self.assertEqual(short_days(days, [], 'mx.dof', date(2026, 10, 25)), (['2026-10-01'], ['2026-10-01']))
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.run.catalog.state['mx.dof'] = {'days': {'2026-10-01': dict(days['2026-10-01'])}}
            code = world.one_run(GOOD)
            self.assertEqual(code, 3)
            self.assertTrue(any('pendientes al cerrar' in c['scope'] for c in world.run.manifest['coverage'] if not c['ok']))


def official(d):
    """The DOF publishes on weekdays; a weekend page shows the Friday edition."""
    return d if d.weekday() < 5 else d - timedelta(days=d.weekday() - 4)


_PAGES = {}


def page_for(d):
    """What SIDOF serves for day d: that day's own edition (57 notes), or the Friday it mirrors."""
    o = official(d)
    if o not in _PAGES:
        p = FRI.replace('16-10-2026', f'{o:%d-%m-%Y}')
        _PAGES[o] = re.sub(r'/notas/(\d+)', lambda m: f'/notas/{o:%m%d}{m.group(1)}', p)
    return _PAGES[o]


def ids_for(d):
    return {i['native_id'] for i in sidof.parse_day(page_for(d))}


READS = {
    'good': lambda d: OK(page_for(d)),
    'no_dates': lambda d: OK(strip(page_for(d))),
    'no_pdf': lambda d: OK(strip(page_for(d), ('pdfMat', 'pdfVes', 'pdfExt'))),
    'malformed': lambda d: OK(page_for(d).replace(f'{official(d):%d-%m-%Y}', '00-00-0000')),
    'drop_one': lambda d: OK(drop_one(page_for(d))),
    'withdrawn': lambda d: OK(re.sub(r'<a[^>]*class="sumario-nota"[^>]*>.*?</a>', '', page_for(d), count=1, flags=re.S)),
    'empty': lambda d: OK('<html><body>Alta demanda</body></html>'),
    'fail': lambda d: (503, b'', {}),
}


class Persistent:
    """Each run is a real main() over the catalog on disk: state, quarantine and its restore persist between runs."""

    def __init__(self, root):
        self.out, self.raw = root + '/out', root + '/raw'

    def run(self, today, read, budget=None, forward=3):
        from rg.catalog import run as runmod
        routes = {SIDOF + '/robots.txt': (200, b'User-agent: *\nDisallow: /notas/docFuente/\n', {})}
        d = date(2026, 10, 1)
        while d <= today:
            routes[sidof.day_url(SIDOF, d)] = read(d)
            d += timedelta(days=1)
        opener, real = FakeOpener(routes), runmod.Fetcher
        fetcher = lambda hosts, **kw: real(hosts, **{**kw, 'opener': opener, 'sleep': lambda s: None, 'clock': lambda: 0.0, 'retries': 0})  # noqa: E731
        argv = ['--country', 'mx', '--out', self.out, '--raw', self.raw, '--sources', 'mx.dof', '--sequential',
                '--today', today.isoformat(), '--forward-days', str(forward), '--index-days', '0']
        if budget:
            argv += ['--budget', str(budget)]
        with mock.patch.object(runmod, 'Fetcher', fetcher), contextlib.redirect_stdout(io.StringIO()):
            return runmod.main(argv)

    def catalog(self):
        return Catalog(self.out, 'MX')


LEGACY = None


def legacy_world(root):
    """The catalog as published in a1c7fbd: count-only day rows, and each note dated with the last day requested
    (a Friday's 57 notes dated Sunday). Built once with good pages, then rewritten to that format."""
    global LEGACY
    if LEGACY is None:
        LEGACY = tempfile.mkdtemp()
        w = Persistent(LEGACY)
        assert w.run(date(2026, 10, 18), READS['good'], forward=6) == 0
        cat = w.catalog()
        days = cat.state['mx.dof']['days']
        for e in cat.snapshot('mx.dof'):
            listing = [k for k in sorted(days) if e['native_id'] in days[k]['ids']]
            e['dates']['published'] = listing[-1]
        cat.state['mx.dof']['days'] = {k: {'notes': v['notes'], 'indexed_at': v['indexed_at']} for k, v in days.items()}
        cat.write()
    shutil.copytree(LEGACY, root, dirs_exist_ok=True)
    return Persistent(root)


class PersistentInvariants(unittest.TestCase):
    def check(self, w, rc, seen, label):
        self.assertNotEqual(rc, 1, f'I1 crash {label}')
        cat = w.catalog()
        days = cat.state['mx.dof']['days']
        self.assertTrue(seen <= set(days), f'I4 {label}')
        if rc != 0:
            return
        notes = {e['native_id']: e for e in cat.snapshot('mx.dof')}
        for d, info in days.items():  # exit 0 => nothing owed: every listed note present, with its official date
            want = set(info['ids']) - set(info.get('withdrawn', [])) if 'ids' in info else ids_for(date.fromisoformat(d))
            self.assertEqual(want - set(notes), set(), f'I3 {label} {d}')
            wrong = {i: notes[i]['dates'].get('published') for i in want
                     if notes[i]['dates'].get('published') != official(date.fromisoformat(d)).isoformat()}
            self.assertEqual(wrong, {}, f'I2 {label} {d}')

    def test_legacy_wrong_date_then_degraded_reread_is_never_laundered(self):
        # Audit of #6 round 3, blocking: legacy Sunday-dated notes, a degraded re-read, and every later run exit 0.
        with tempfile.TemporaryDirectory() as tmp:
            w = legacy_world(tmp)
            degraded = lambda d: READS['no_dates'](d) if d >= date(2026, 10, 16) else READS['good'](d)  # noqa: E731
            rc = w.run(date(2026, 10, 19), degraded)
            self.assertNotEqual(rc, 0)
            self.check(w, rc, set(), 'degraded')
            today, rcs = date(2026, 10, 22), []
            for _ in range(4):
                rcs.append(w.run(today, READS['good']))
                self.check(w, rcs[-1], set(), f'good {today}')
                today += timedelta(days=3)
            self.assertEqual(rcs[-1], 0)
            fri = {e['dates']['published'] for e in w.catalog().snapshot('mx.dof') if e['native_id'] in ids_for(date(2026, 10, 16))}
            self.assertEqual(fri, {'2026-10-16'})

    def test_no_sequence_of_reads_and_runs_loses_or_misdates_a_note(self):
        rng = random.Random(20261021)
        names = list(READS)
        for scenario in range(int(os.environ.get('RG_PROPERTY_SCENARIOS', '12'))):
            with tempfile.TemporaryDirectory() as tmp:
                w = legacy_world(tmp) if rng.random() < 0.7 else Persistent(tmp)
                today, seen, log = date(2026, 10, 19), set(), []
                for _ in range(rng.randint(2, 5)):
                    choice = {}
                    read = lambda d: READS[choice.setdefault(d, rng.choice(names))](d)  # noqa: E731
                    budget = rng.choice([None, None, None, 2, 6])
                    rc = w.run(today, read, budget)
                    log.append((today.isoformat(), budget, sorted({v for v in choice.values()})))
                    self.check(w, rc, seen, f'scenario {scenario} {log}')
                    seen = set(w.catalog().state.get('mx.dof', {}).get('days', {}))
                    today += timedelta(days=rng.choice([1, 2, 3, 4]))
                for _ in range(12):  # the site recovers; spaced retries may need weeks
                    rc = w.run(today, READS['good'])
                    self.check(w, rc, seen, f'scenario {scenario} recovery {today} {log}')
                    if rc == 0:
                        break
                    today += timedelta(days=7)
                self.assertEqual(rc, 0, f'I5 scenario {scenario}: never whole again {log}')


class Withdrawn(unittest.TestCase):
    def test_a_note_a_person_marked_withdrawn_is_not_owed_and_stays_marked(self):
        # Round 3, 3a: a quarantined note the source later drops failed every run forever with no way out. A person
        # records it in the day row ('withdrawn', with evidence); the code never sets it on its own.
        from rg.catalog.run import short_days
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            listed = sorted(IDS) + ['X9']
            world.run.catalog.state['mx.dof'] = {'days': {'2026-10-16': {'ids': listed, 'notes': 58, 'withdrawn': ['X9']}}}
            world.one_run({DAYS[0]: VARIANTS['friday']['own'], DAYS[1]: VARIANTS['mirror']['mirror'],
                           DAYS[2]: VARIANTS['mirror']['mirror']})
            days = world.run.catalog.state['mx.dof']['days']
            self.assertEqual(days['2026-10-16']['withdrawn'], ['X9'])
            self.assertEqual(short_days(days, world.run.catalog.snapshot('mx.dof'), 'mx.dof'), ([], []))


class EditionDate(unittest.TestCase):
    def test_the_editions_own_date_wins_over_the_page_date(self):
        # Round 2: no fixture told the edition's PDF date from fechaPub apart.
        page = FRI.replace('id="fechaPub" value="16-10-2026"', 'id="fechaPub" value="17-10-2026"')
        self.assertNotEqual(page, FRI)
        self.assertEqual({i['published'] for i in sidof.parse_day(page)}, {OFFICIAL})
        self.assertEqual({i['published'] for i in sidof.parse_day(strip(page, ('pdfMat', 'pdfVes')))}, {'2026-10-17'})

    def test_printed_edition_only_for_a_single_pane_naming_one_edition(self):
        two = re.sub(r'<a[^>]*href="#resp-tab\d"[^>]*>.*?</a>', '', FRI, flags=re.S)  # no tab navigation, two panes
        two = two.replace('Edici&oacute;n del', 'Edici&oacute;n Matutina del').replace('Edición del', 'Edición Matutina del')
        self.assertEqual({i['edition'] for i in sidof.parse_day(two)}, {None})
        single = (FIX / 'sidof_day_2026-10-15_single_edition.html').read_text(encoding='utf-8')
        both = single.replace('Edici&oacute;n Matutina del', 'Edici&oacute;n Matutina y Vespertina del')
        self.assertEqual({i['edition'] for i in sidof.parse_day(both)}, {None})


if __name__ == '__main__':
    unittest.main()
