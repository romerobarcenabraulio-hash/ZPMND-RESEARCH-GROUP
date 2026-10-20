"""DOF catalog invariants under any sequence of page reads (no network).

Two audit rounds each found a new way to lose or misdate a note by combining reads that every single-case test
passed. So this file states the composed property and searches for a counterexample: random sequences of real,
mirrored, degraded, empty, failed and incomplete pages over several runs, each followed by the run's own schema
quarantine. After every run:
  I1 nothing crashes;
  I2 every catalogued note carries the official date of its edition (2026-10-16), never another;
  I3 a listed note missing from the catalog never goes unreported: the run's exit code is not 0;
  I4 a day once read never leaves the state.
After good runs (the site recovers): I5 every listed note is catalogued with its official date.
"""
import random
import re
import tempfile
import unittest
from datetime import date

from rg.catalog import sidof
from rg.catalog.run import MAX_REREADS, Run, quarantine, recategorize
from rg.schemas import validate
from tests.test_catalog import FIX, SAT, SIDOF, FakeOpener
from rg.catalog.fetch import Fetcher

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

    def test_no_sequence_of_reads_loses_or_misdates_a_note(self):
        rng = random.Random(20261020)
        for scenario in range(int(__import__("os").environ.get("RG_PROPERTY_SCENARIOS", "40"))):
            with tempfile.TemporaryDirectory() as tmp:
                world, seen, label = World(tmp), set(), []
                for _ in range(rng.randint(1, 5)):
                    pages = {DAYS[0]: rng.choice(list(VARIANTS['friday'].values()))}
                    pages.update({d: rng.choice(list(VARIANTS['mirror'].values())) for d in DAYS[1:]})
                    label.append([k for d, r in pages.items() for k, v in {**VARIANTS['friday'], **VARIANTS['mirror']}.items() if v is r][:3])
                    code = world.one_run(pages)
                    seen |= {d.isoformat() for d, r in pages.items() if r[0] == 200 and b'sumario-nota' in r[1]}
                    self.check(world, code, seen, f'scenario {scenario} {label}')
                for _ in range(MAX_REREADS + 1):  # the site recovers
                    code = world.one_run(GOOD)
                    self.check(world, code, seen | {d.isoformat() for d in DAYS}, f'scenario {scenario} recovery')
                notes = world.dof()
                self.assertEqual(set(notes) & IDS, IDS, f'I5 scenario {scenario} {label}')
                self.assertEqual(code, 0, f'I5 scenario {scenario}: still not whole after recovery')

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
            self.assertTrue(any('notas debidas' in c['scope'] for c in world.run.manifest['coverage'] if not c['ok']))


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
