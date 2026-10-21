"""Contract of the full-text front: ChangeEvent and Relation candidates (schemas/change_event, schemas/relation).

Each guard has a case that fails without it. Required fields are listed here by hand, not read from the schema, so
dropping one from the schema's `required` makes a test fail.
"""
import copy
import unittest

from rg.schemas import validate

OLD, NEW = 'a' * 64, 'b' * 64
EVIDENCE = {'raw_sha256': NEW, 'extractor': 'pypdf==6.19.0',
            'quote': 'PRIMERO.- El presente Decreto entrará en vigor el 1o. de enero de 2027.'}
CHANGE = {
    'source_id': 'mx.leyes-federales', 'entry_id': 'mx.leyes-federales:CPEUM', 'before_ref': OLD, 'after_ref': NEW,
    'published_at': '2026-10-07', 'effective_at': None,
    'provenance': {'url': 'https://www.diputados.gob.mx/LeyesBiblio/pdf/CPEUM.pdf', 'sha256': NEW,
                   'retrieved_at': '2026-10-21T03:00:00Z'},
    'status': 'CANDIDATE',
}
CHANGE_DATED = {**copy.deepcopy(CHANGE), 'effective_at': '2027-01-01', 'effective_at_evidence': EVIDENCE}
RELATION = {
    'type': 'reglamenta', 'from': {'entry_id': 'mx.reglamentos-federales:RLISR'}, 'to': {'entry_id': 'mx.leyes-federales:LISR'},
    'evidence': {'raw_sha256': OLD, 'extractor': 'pypdf==6.19.0', 'quote': 'REGLAMENTO DE LA LEY DEL IMPUESTO SOBRE LA RENTA'},
    'status': 'CANDIDATE',
}
RELATION_PRINTED = {
    'type': 'reforma', 'from': {'entry_id': 'mx.dof:5770001'}, 'to': {'printed': 'Ley Federal del Trabajo'},
    'evidence': {'raw_sha256': NEW, 'extractor': 'rg-html==1',
                 'quote': 'ÚNICO.- Se reforma el artículo 132 de la Ley Federal del Trabajo, para quedar como sigue:'},
    'status': 'CANDIDATE',
}
TYPES = ('reglamenta', 'reforma', 'adiciona', 'deroga', 'abroga', 'cancela', 'cita')


def mutate(base, fn):
    obj = copy.deepcopy(base)
    fn(obj)
    return obj


class Baselines(unittest.TestCase):
    def test_valid_documents_pass(self):
        self.assertEqual(validate('change_event', CHANGE), [])
        self.assertEqual(validate('change_event', CHANGE_DATED), [])
        self.assertEqual(validate('relation', RELATION), [])
        self.assertEqual(validate('relation', RELATION_PRINTED), [])

    def test_published_at_may_be_absent_in_the_source(self):
        self.assertEqual(validate('change_event', mutate(CHANGE, lambda e: e.update(published_at=None))), [])

    def test_every_relation_type_of_the_fixed_list_passes(self):
        for t in TYPES:
            self.assertEqual(validate('relation', mutate(RELATION, lambda r: r.update(type=t))), [], t)


class Required(unittest.TestCase):
    def _each_missing(self, kind, base, fields, at=lambda d: d):
        for field in fields:
            with self.subTest(kind=kind, field=field):
                self.assertTrue(validate(kind, mutate(base, lambda d: at(d).pop(field))))

    def test_change_event_fields(self):
        self._each_missing('change_event', CHANGE, ('source_id', 'entry_id', 'before_ref', 'after_ref', 'published_at',
                                                    'effective_at', 'provenance', 'status'))
        self._each_missing('change_event', CHANGE, ('url', 'sha256', 'retrieved_at'), at=lambda d: d['provenance'])
        self._each_missing('change_event', CHANGE_DATED, ('raw_sha256', 'extractor', 'quote'),
                           at=lambda d: d['effective_at_evidence'])

    def test_relation_fields(self):
        self._each_missing('relation', RELATION, ('type', 'from', 'to', 'evidence', 'status'))
        self._each_missing('relation', RELATION, ('raw_sha256', 'extractor', 'quote'), at=lambda d: d['evidence'])


class Enums(unittest.TestCase):
    def test_status_is_always_candidate(self):
        for status in ('VERIFIED', 'CANONICAL', 'ACTIVE', 'PROMOTED', 'candidate', None):
            self.assertTrue(validate('change_event', mutate(CHANGE, lambda e: e.update(status=status))), status)
            self.assertTrue(validate('relation', mutate(RELATION, lambda r: r.update(status=status))), status)

    def test_relation_type_outside_the_fixed_list_rejected(self):
        for t in ('modifica', 'REFORMA', 'deroga_parcial', 'implica', 'afecta', ''):
            self.assertTrue(validate('relation', mutate(RELATION, lambda r: r.update(type=t))), t)


class NoExtraFields(unittest.TestCase):
    def test_semantic_delta_is_not_rgs(self):
        bad = mutate(CHANGE, lambda e: e.update(semantic_delta='La reforma amplía la obligación de retención.'))
        self.assertTrue(validate('change_event', bad))

    def test_unknown_fields_rejected_at_every_level(self):
        cases = [
            ('change_event', CHANGE, lambda e: e.update(impact='high')),
            ('change_event', CHANGE, lambda e: e.update(verified=True)),
            ('change_event', CHANGE, lambda e: e['provenance'].update(trusted=True)),
            ('change_event', CHANGE_DATED, lambda e: e['effective_at_evidence'].update(confidence=0.9)),
            ('relation', RELATION, lambda r: r.update(weight=1)),
            ('relation', RELATION, lambda r: r['evidence'].update(page=3)),
            ('relation', RELATION, lambda r: r['to'].update(title='Ley del ISR')),
        ]
        for kind, base, fn in cases:
            self.assertTrue(validate(kind, mutate(base, fn)))


class EffectiveAt(unittest.TestCase):
    def test_a_date_needs_its_transitorio_quote(self):
        self.assertTrue(validate('change_event', mutate(CHANGE_DATED, lambda e: e.pop('effective_at_evidence'))))

    def test_a_quote_without_a_date_rejected(self):
        self.assertTrue(validate('change_event', mutate(CHANGE_DATED, lambda e: e.update(effective_at=None))))

    def test_only_a_calendar_date_is_accepted(self):
        for value in ('al día siguiente de su publicación', '2027-13-01', '01/01/2027', '2027-01-01T00:00:00Z'):
            self.assertTrue(validate('change_event', mutate(CHANGE_DATED, lambda e: e.update(effective_at=value))), value)

    def test_transitorio_is_quoted_from_the_new_text(self):
        bad = mutate(CHANGE_DATED, lambda e: e['effective_at_evidence'].update(raw_sha256='c' * 64))
        self.assertTrue(any('effective_at_evidence' in m for m in validate('change_event', bad)))


class Consistency(unittest.TestCase):
    """Cross-field checks in rg.schemas (a JSON Schema cannot compare two fields)."""
    def test_unchanged_raw_is_not_a_change(self):
        bad = mutate(CHANGE, lambda e: e.update(before_ref=NEW))
        self.assertTrue(any('equals before_ref' in m for m in validate('change_event', bad)))

    def test_provenance_is_the_new_version(self):
        bad = mutate(CHANGE, lambda e: e['provenance'].update(sha256=OLD))
        self.assertTrue(any('provenance.sha256' in m for m in validate('change_event', bad)))

    def test_entry_belongs_to_its_source(self):
        bad = mutate(CHANGE, lambda e: e.update(source_id='mx.reglamentos-federales'))
        self.assertTrue(any('belong' in m for m in validate('change_event', bad)))

    def test_self_edge_rejected(self):
        bad = mutate(RELATION, lambda r: r.update(to=dict(r['from'])))
        self.assertTrue(any('same instrument' in m for m in validate('relation', bad)))

    def test_printed_identifier_must_be_in_the_quote(self):
        bad = mutate(RELATION_PRINTED, lambda r: r['to'].update(printed='Ley Federal de Trabajo'))
        self.assertTrue(any('to.printed' in m for m in validate('relation', bad)))
        bad = mutate(RELATION_PRINTED, lambda r: r.update(**{'from': {'printed': 'Decreto por el que se reforma'}}))
        self.assertTrue(any('from.printed' in m for m in validate('relation', bad)))

    def test_printed_identifier_matches_with_whitespace_folded(self):
        ok = mutate(RELATION_PRINTED, lambda r: r['to'].update(printed='Ley Federal\n del  Trabajo'))
        self.assertEqual(validate('relation', ok), [])

    def test_endpoint_is_exactly_one_of_entry_id_or_printed(self):
        both = mutate(RELATION_PRINTED, lambda r: r['to'].update(entry_id='mx.leyes-federales:LFT'))
        self.assertTrue(validate('relation', both))
        self.assertTrue(validate('relation', mutate(RELATION, lambda r: r.update(to={}))))


class TextAndIdentity(unittest.TestCase):
    def test_long_or_hidden_quote_rejected(self):
        self.assertTrue(validate('relation', mutate(RELATION, lambda r: r['evidence'].update(quote='x' * 301))))
        for ch in ('​', '‮', '﻿', '\x00'):
            bad = mutate(RELATION, lambda r: r['evidence'].update(quote=f'REGLAMENTO{ch} DE LA LEY'))
            self.assertTrue(validate('relation', bad), repr(ch))

    def test_extractor_is_pinned(self):
        for value in ('pypdf', 'pypdf>=6', 'pypdf==', '==6.19.0', 'PyPDF==6.19.0', 'pypdf==6.19.0; rm -rf /'):
            self.assertTrue(validate('relation', mutate(RELATION, lambda r: r['evidence'].update(extractor=value))), value)

    def test_hashes_ids_and_urls_are_checked(self):
        cases = [
            ('change_event', CHANGE, lambda e: e.update(after_ref='xyz')),
            ('change_event', CHANGE, lambda e: e.update(entry_id='CPEUM')),
            ('change_event', CHANGE, lambda e: e.update(published_at='2026-10-21T00:00:00Z')),
            ('change_event', CHANGE, lambda e: e['provenance'].update(url='javascript:alert(1)')),
            ('change_event', CHANGE, lambda e: e['provenance'].update(retrieved_at='2026-10-21')),
            ('relation', RELATION, lambda r: r['evidence'].update(raw_sha256='A' * 64)),
            ('relation', RELATION, lambda r: r['from'].update(entry_id='reglamento del ISR')),
        ]
        for kind, base, fn in cases:
            self.assertTrue(validate(kind, mutate(base, fn)))


if __name__ == '__main__':
    unittest.main()
