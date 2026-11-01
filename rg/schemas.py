"""Validate RG artifacts against schemas/ (JSON Schema 2020-12) plus the checks a schema cannot express.

The ZPMND airlock must run its own validation; passing here makes a packet well-formed, never true.
Usage: python -m rg.schemas <kind> <file.json>   kinds: research_request, research_packet, source_artifact, knowledge_demand, catalog_entry, change_event, relation, adquisicion
"""
import json
import sys
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from rg.quotes import _fold as fold

SCHEMAS = Path(__file__).resolve().parent.parent / 'schemas'
KINDS = ('research_request', 'research_packet', 'source_artifact', 'knowledge_demand', 'catalog_entry', 'change_event',
         'relation', 'adquisicion')
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


@lru_cache(maxsize=None)
def _validator(kind):
    """Schemas are read once per process (a catalog run validates ~60,000 entries)."""
    return Draft202012Validator(_schema(kind), registry=_registry())


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
    primary = set(sources.get('primary', []))
    for i, finding in enumerate(findings.get('confirmed', [])):  # T2 per finding (GPT, REVISE of #51)
        if not primary & set(finding.get('artifact_ids', [])):
            errors.append(f'findings.confirmed[{i}]: cites no primary source')
    return errors


def _change_event_checks(ev):
    errors = []
    if ev['before_ref'] == ev['after_ref']:
        errors.append('after_ref equals before_ref: an unchanged raw is not a change')
    if ev['provenance']['sha256'] != ev['after_ref']:
        errors.append('provenance.sha256 must be after_ref: provenance is the retrieval of the new version')
    if ev['entry_id'].split(':', 1)[0] != ev['source_id']:
        errors.append('entry_id does not belong to source_id')
    evid = ev.get('effective_at_evidence')
    if evid and evid['raw_sha256'] != ev['after_ref']:
        errors.append('effective_at_evidence.raw_sha256 must be after_ref: the transitorio is quoted from the new text')
    return errors


def _relation_checks(rel):
    errors = []
    if rel['from'] == rel['to']:
        errors.append('from and to are the same instrument')
    quote = fold(rel['evidence']['quote'])
    for end in ('from', 'to'):
        printed = rel[end].get('printed')
        if printed is not None and fold(printed) not in quote:
            errors.append(f'{end}.printed does not appear verbatim in evidence.quote')
    return errors


CHECKS = {'research_packet': _packet_references, 'change_event': _change_event_checks, 'relation': _relation_checks}


def validate(kind, obj):
    """Return a list of error strings; empty means well-formed."""
    if kind not in KINDS:
        return [f'unknown kind {kind}']
    if len(json.dumps(obj, ensure_ascii=False).encode('utf-8')) > MAX_BYTES:
        return [f'document larger than {MAX_BYTES} bytes']
    validator = _validator(kind)
    errors = [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in validator.iter_errors(obj)]
    if not errors and kind in CHECKS:  # cross-field checks run only on a schema-valid document
        errors += CHECKS[kind](obj)
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
