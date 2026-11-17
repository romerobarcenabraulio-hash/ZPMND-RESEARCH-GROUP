"""RESEARCH_CONTRACT.md §7: the contract version a consumer pins is the sha256 of each schema it validates against
(directive of 2026-11-17, transition to ZPMND-FINAL: "Versiona cualquier cambio de contrato"). A schema that changes
without its row, or a schema the request or the packet reaches by $ref that the table leaves out, fails here."""
import hashlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROW = re.compile(r'^\| `(schemas/[a-z_]+\.schema\.json)` \| `([0-9a-f]{64})` \|$')


def table():
    text = (ROOT / 'RESEARCH_CONTRACT.md').read_text(encoding='utf-8')
    section = text[text.index('## 7. Contract version'):]
    return {m.group(1): m.group(2) for m in map(ROW.match, section.splitlines()) if m}


def reached(name, seen=None):
    """Every schema file that schemas/<name> reaches through $ref, itself included."""
    seen = set() if seen is None else seen
    if name in seen:
        return seen
    seen.add(name)
    refs = re.findall(r'"\$ref":\s*"([a-z_]+\.schema\.json)', (ROOT / 'schemas' / name).read_text(encoding='utf-8'))
    for ref in refs:
        reached(ref, seen)
    return seen


class ContractVersion(unittest.TestCase):
    def test_every_pinned_schema_has_the_sha256_of_its_file(self):
        rows = table()
        self.assertTrue(rows)
        for path, digest in rows.items():
            with self.subTest(path):
                self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), digest)

    def test_the_table_pins_exactly_what_a_request_and_a_packet_reach(self):
        need = reached('research_request.schema.json') | reached('research_packet.schema.json')
        self.assertEqual(set(table()), {f'schemas/{n}' for n in need})
        self.assertIn('`rg-contrato-1`', (ROOT / 'RESEARCH_CONTRACT.md').read_text(encoding='utf-8'))
        for n in need:  # each one parses: a table of digests of broken files pins nothing
            json.loads((ROOT / 'schemas' / n).read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
