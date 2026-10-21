"""Derived views (store.DERIVED) are rewritten every run and never read back as catalog rows, by any reader."""
import json
import tempfile
import unittest
from pathlib import Path

from rg import index
from rg.catalog import store


class DerivedViews(unittest.TestCase):
    def test_no_reader_takes_a_derived_view_for_catalog_rows(self):
        # Audit of #13 (REVISE ef139b6): rg.index read tratados.jsonl as rows and died with KeyError 'entry_id'.
        row = {'entry_id': 'mx.dof:1', 'title': 'Nota'}
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'dof').mkdir()
            (Path(d) / 'dof' / '2026.jsonl').write_text(json.dumps(row) + '\n', encoding='utf-8')
            for name in store.DERIVED:
                (Path(d) / name).mkdir()
                (Path(d) / name / f'{name}.jsonl').write_text('{"derived": true}\n', encoding='utf-8')
            self.assertTrue(store.DERIVED)
            self.assertEqual([f.relative_to(d).parts[0] for f in store.row_files(d)], ['dof'])
            self.assertEqual(index.load_entries([d]), [row])


if __name__ == '__main__':
    unittest.main()
