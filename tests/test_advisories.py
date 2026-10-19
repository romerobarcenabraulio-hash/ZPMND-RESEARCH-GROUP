"""T5: the pinned OpenClaw is never affected by a published advisory, and unknown ranges fail closed."""
import json
import tempfile
import unittest
from pathlib import Path

from rg.advisories import affects, evaluate, main, parse_version as v

LOCK = Path(__file__).resolve().parent.parent / 'substrate' / 'openclaw.lock.json'


def adv(rng, pkg='openclaw', ghsa='GHSA-test'):
    return {'ghsa_id': ghsa, 'severity': 'high', 'published_at': '2026-09-01T00:00:00Z',
            'vulns': [{'pkg': pkg, 'vulnerable': rng, 'patched': 'x'}]}


class Ranges(unittest.TestCase):
    def test_space_separated_bounds_are_both_applied(self):
        # Counterexample found while building this gate: '>= A < B' was read as '>= A' and flagged every newer version.
        self.assertFalse(affects(v('2026.10.5'), '>= 2026.2.26 < 2026.7.1'))
        self.assertTrue(affects(v('2026.5.1'), '>= 2026.2.26 < 2026.7.1'))
        self.assertFalse(affects(v('2026.10.5'), '>=2026.1.21, <2026.2.18'))

    def test_disjunctions(self):
        self.assertFalse(affects(v('2026.10.5'), '<=2026.2.21 || =2026.2.21-1 || =2026.2.21-2'))
        self.assertTrue(affects(v('2026.2.21-1'), '<=2026.2.21 || =2026.2.21-1'))

    def test_prerelease_and_correction_ordering(self):
        self.assertTrue(v('2026.2.14-beta.1') < v('2026.2.14') < v('2026.2.14-1') < v('2026.2.15'))
        self.assertTrue(affects(v('2026.1.30'), '>=2026.1.29-beta.1 <2026.2.14'))

    def test_unparseable_is_unknown_not_safe(self):
        for rng in ('', '   ', 'all versions', '< latest', '>= 2026.1 < 2026.2', '>= 2026.1.1 garbage'):
            self.assertIsNone(affects(v('2026.10.5'), rng), rng)


class Gate(unittest.TestCase):
    def test_other_packages_ignored_empty_name_counted(self):
        affected, unparsed = evaluate([adv('< 2027.1.1', pkg='@openclaw/feishu'), adv('< 2027.1.1', pkg='')], '2026.10.5', ['openclaw'])
        self.assertEqual(len(affected), 1)

    def _run(self, rows):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'adv.jsonl'
            f.write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
            return main(['--lock', str(LOCK), '--file', str(f)])

    def test_exit_codes(self):
        self.assertEqual(self._run([adv('< 2026.8.1')]), 0)
        self.assertEqual(self._run([adv('< 2026.8.1'), adv('< 2027.1.1')]), 1)
        self.assertEqual(self._run([adv('< 2026.8.1'), adv('every version')]), 2)


if __name__ == '__main__':
    unittest.main()
