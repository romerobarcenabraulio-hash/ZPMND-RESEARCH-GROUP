"""scripts/mutar.py split in shards: the shards partition the mutant list, and CI ties them to its matrix."""
import importlib.util
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('mutar', ROOT / 'scripts' / 'mutar.py')
mutar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mutar)


class Shards(unittest.TestCase):
    def test_shards_partition_the_list(self):
        items = list('abcdefghijk')
        for n in range(1, 6):
            parts = [mutar.shard(items, f'{k}/{n}') for k in range(n)]
            seen = [i for p in parts for i, _ in p]
            self.assertEqual(sorted(seen), list(range(1, len(items) + 1)), n)   # each mutant exactly once
            self.assertTrue(all(items[i - 1] == m for p in parts for i, m in p))

    def test_a_bad_shard_spec_stops_the_run(self):
        for spec in ('4/4', '-1/4', '1/0', 'x', '1'):
            with self.assertRaises(ValueError, msg=spec):
                mutar.shard(['a'], spec)

    def test_ci_derives_the_shard_from_the_matrix(self):
        job = yaml.safe_load((ROOT / '.github' / 'workflows' / 'ci.yml').read_text(encoding='utf-8'))['jobs']['mutation']
        env = next(s['env'] for s in job['steps'] if 'mutar.py' in s.get('run', ''))
        self.assertEqual(env['RG_SHARD'], '${{ strategy.job-index }}/${{ strategy.job-total }}')
        self.assertFalse(job['strategy']['fail-fast'])


if __name__ == '__main__':
    unittest.main()
