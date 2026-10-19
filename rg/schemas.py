"""Validate RG artifacts against schemas/ (JSON Schema 2020-12) plus the checks a schema cannot express.

The ZPMND airlock must run its own validation; passing here makes a packet well-formed, never true.
Usage: python -m rg.schemas <kind> <file.json>   kinds: research_request, research_packet, source_artifact, knowledge_demand, catalog_entry
"""
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

SCHEMAS = Path(__file__).resolve().parent.parent / 'schemas'
KINDS = ('research_request', 'research_packet', 'source_artifact', 'knowledge_demand', 'catalog_entry')
MAX_BYTES = 512 * 1024


def _registry():
    resources = []
    for path in SCHEMAS.glob('*.schema.json'):
        schema = json.loads(path.read_text(encoding='utf-8'))
        resource = Resource.from_contents(schema)
        resources += [(schema['$id'], resource), (path.name, resource)]
    return Registry().with_resources(resources)


def _schema(kind):
    return json.loads((SCHEMAS / f'{kind}.schema.json').read_text(encoding='utf-8'))


def _packet_references(packet):
    errors = []
    ids = [a.get('artifact_id') for a in packet.get('artifacts', [])]
    known = set(ids)
    if len(known) != len(ids):
        errors.append('artifacts: duplicate artifact_id')
    sources = packet.get('sources', {})
    for group in ('primary', 'secondary'):
        for ref in sources.get(group, []):
            if ref not in known:
                errors.append(f'sources.{group}: unknown artifact {ref}')
    findings = packet.get('findings', {})
    for group in ('confirmed', 'conflicting'):
        for i, finding in enumerate(findings.get(group, [])):
            for ref in finding.get('artifact_ids', []):
                if ref not in known:
                    errors.append(f'findings.{group}[{i}]: unknown artifact {ref}')
    if findings.get('confirmed') and not sources.get('primary'):
        errors.append('findings.confirmed requires at least one primary source')
    return errors


def validate(kind, obj):
    """Return a list of error strings; empty means well-formed."""
    if kind not in KINDS:
        return [f'unknown kind {kind}']
    if len(json.dumps(obj, ensure_ascii=False).encode('utf-8')) > MAX_BYTES:
        return [f'document larger than {MAX_BYTES} bytes']
    validator = Draft202012Validator(_schema(kind), registry=_registry())
    errors = [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in validator.iter_errors(obj)]
    if not errors and kind == 'research_packet':
        errors += _packet_references(obj)
    return errors


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[-1]); return 2
    errors = validate(argv[0], json.loads(Path(argv[1]).read_text(encoding='utf-8')))
    for e in errors:
        print('INVALID', e)
    print('VALID' if not errors else f'{len(errors)} error(s)')
    return 0 if not errors else 1


if __name__ == '__main__':
    sys.exit(main())
