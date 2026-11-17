"""RESEARCH_CONTRACT.md §7: the contract version a consumer pins is the sha256 of each schema it validates against
(directive of 2026-11-17, transition to ZPMND-FINAL: "Versiona cualquier cambio de contrato"). A schema that changes
without its row, or a schema the request or the packet reaches by $ref that the table leaves out, fails here."""
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROW = re.compile(r'^\| `(schemas/[a-z_]+\.schema\.json)` \| `([0-9a-f]{64})` \|$')


def table():
    text = (ROOT / 'RESEARCH_CONTRACT.md').read_text(encoding='utf-8')
    section = text[text.index('## 7. Contract version'):]
    return {m.group(1): m.group(2) for m in map(ROW.match, section.splitlines()) if m}


def refs(node):
    """Every $ref value of a parsed schema, at any depth."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from ([v] if k == '$ref' else refs(v))
    elif isinstance(node, list):
        for v in node:
            yield from refs(v)


FILE_REF = re.compile(r'^([a-z_]+\.schema\.json)(#.*)?$')


def reached(name, root=ROOT / 'schemas', seen=None):
    """Every schema file that <root>/<name> reaches through $ref, itself included, walking the parsed JSON (GPT on
    51da4bf: a regex over the raw text missed '"$ref" : ...'). A reference in another form (a URL, an $id) stops it."""
    seen = set() if seen is None else seen
    if name in seen:
        return seen
    seen.add(name)
    for ref in refs(json.loads((root / name).read_text(encoding='utf-8'))):
        if isinstance(ref, str) and ref.startswith('#'):
            continue  # within this same file
        m = FILE_REF.match(ref) if isinstance(ref, str) else None
        if m is None:
            raise ValueError(f'{name}: $ref {ref!r} is neither local nor a schemas/ file')
        reached(m.group(1), root, seen)
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

    def test_a_reference_is_found_however_the_json_is_spaced_and_any_other_form_stops(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / 'raiz.schema.json').write_text('{"properties": {"a": {"$ref" : "extra.schema.json#/$defs/x"}, '
                                                '"b": {"allOf": [{"$ref":"#/$defs/y"}]}}}', encoding='utf-8')
            (d / 'extra.schema.json').write_text('{"$defs": {"x": {}}}', encoding='utf-8')
            need = reached('raiz.schema.json', d)
            self.assertEqual(need, {'raiz.schema.json', 'extra.schema.json'})
            self.assertNotEqual({'raiz.schema.json'}, need)  # a table without extra's row fails the coverage test
            for bad in ('"https://example.org/otro.schema.json"', '"otro.json"', '7'):
                (d / 'raiz.schema.json').write_text('{"$ref": %s}' % bad, encoding='utf-8')
                with self.subTest(bad), self.assertRaises(ValueError):
                    reached('raiz.schema.json', d)


if __name__ == '__main__':
    unittest.main()
