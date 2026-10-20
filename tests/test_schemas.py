"""Every interface guard has a case that fails without it (SECURITY.md, threats T1-T4)."""
import copy
import unittest

from rg.schemas import validate

SHA = 'a' * 64
ARTIFACT = {
    'artifact_id': 'SA-0001', 'url': 'https://example.org/report', 'retrieved_at': '2026-10-19T16:00:00Z',
    'sha256': SHA, 'bytes': 1024, 'media_type': 'text/html', 'source_type': 'primary_official',
    'publisher': 'Example Standards Body', 'license': 'unknown', 'redistribution': 'unknown', 'stored_at': 'none',
}
PACKET = {
    'research_id': 'RP-0001', 'request_id': 'RR-0001', 'status': 'CANDIDATE', 'produced_at': '2026-10-19T17:00:00Z',
    'question': 'Which primary sources define prompt-injection controls for tool-using agents?',
    'why_zpmnd_needs_it': 'To compare candidate controls with existing guards.', 'scope': 'Public standards, 2024-2026.',
    'sources': {'primary': ['SA-0001'], 'secondary': []},
    'artifacts': [ARTIFACT],
    'findings': {'confirmed': [{'claim': 'The source lists tool allowlisting as a control.', 'artifact_ids': ['SA-0001']}],
                 'conflicting': [], 'unknown': ['Effectiveness data is not reported.']},
    'candidate_tests': ['Describe: an injected page asks the agent to call a denied tool; expect refusal.'],
    'limitations': ['Single source.'],
    'researcher_agents': [{'agent': 'researcher-1', 'model': 'claude', 'substrate': 'openclaw 2026.10.5'}],
}
REQUEST = {
    'request_id': 'RR-0001', 'issued_by': 'OWNER', 'issued_at': '2026-10-19T15:00:00Z',
    'question': 'Strongest current primary sources on agentic AI security.', 'why_needed': 'Seed the demand map.',
    'affected_component': 'governance', 'desired_evidence': ['standards', 'attack evidence'], 'priority': 'P1',
    'risk_if_wrong': 'Controls based on weak sources.', 'privacy_class': 'PUBLIC',
}
DEMAND = {
    'id': 'KD-0001', 'origin': 'RG_PROPOSED', 'domain': 'ai_security', 'question': 'What are current memory-poisoning attacks?',
    'why_needed': 'Memory is a persistent attack surface.', 'affected_zpmnd_capabilities': ['memory'],
    'known_sources': [], 'knowledge_status': 'UNKNOWN', 'research_priority': 'P2',
    'risk_if_wrong': 'Undetected poisoning.', 'current_evidence': [],
}


def mutate(base, fn):
    obj = copy.deepcopy(base)
    fn(obj)
    return obj


class Baselines(unittest.TestCase):
    def test_valid_documents_pass(self):
        self.assertEqual(validate('research_packet', PACKET), [])
        self.assertEqual(validate('research_request', REQUEST), [])
        self.assertEqual(validate('source_artifact', ARTIFACT), [])
        self.assertEqual(validate('knowledge_demand', DEMAND), [])


class NoAuthority(unittest.TestCase):
    """T1: a packet can never claim truth, canon or authority."""
    def test_status_other_than_candidate_rejected(self):
        for status in ('VERIFIED', 'CANONICAL', 'PROMOTED', 'FACT', 'POLICY'):
            self.assertTrue(validate('research_packet', mutate(PACKET, lambda p: p.update(status=status))), status)

    def test_unknown_fields_rejected_at_every_level(self):
        cases = [
            lambda p: p.update(authority='grant'),
            lambda p: p.update(promote_to_canon=True),
            lambda p: p['findings']['confirmed'][0].update(verified=True),
            lambda p: p['artifacts'][0].update(trusted=True),
            lambda p: p['researcher_agents'][0].update(permissions=['admin']),
            lambda p: p['sources'].update(canonical=['SA-0001']),
        ]
        for fn in cases:
            self.assertTrue(validate('research_packet', mutate(PACKET, fn)))

    def test_demand_cannot_mark_knowledge_verified(self):
        self.assertTrue(validate('knowledge_demand', mutate(DEMAND, lambda d: d.update(knowledge_status='VERIFIED'))))


class Provenance(unittest.TestCase):
    """T2: every finding traces to a retrieved, hashed artifact."""
    def test_finding_without_artifacts_rejected(self):
        self.assertTrue(validate('research_packet', mutate(PACKET, lambda p: p['findings']['confirmed'][0].update(artifact_ids=[]))))

    def test_finding_citing_unknown_artifact_rejected(self):
        self.assertTrue(validate('research_packet', mutate(PACKET, lambda p: p['findings']['confirmed'][0].update(artifact_ids=['SA-9999']))))

    def test_source_list_citing_unknown_artifact_rejected(self):
        self.assertTrue(validate('research_packet', mutate(PACKET, lambda p: p['sources']['secondary'].append('SA-9999'))))

    def test_confirmed_needs_a_primary_source(self):
        self.assertTrue(validate('research_packet', mutate(PACKET, lambda p: p['sources'].update(primary=[], secondary=['SA-0001']))))

    def test_duplicate_artifact_ids_rejected(self):
        self.assertTrue(validate('research_packet', mutate(PACKET, lambda p: p['artifacts'].append(copy.deepcopy(ARTIFACT)))))

    def test_bad_hash_and_url_rejected(self):
        self.assertTrue(validate('source_artifact', mutate(ARTIFACT, lambda a: a.update(sha256='xyz'))))
        for url in ('javascript:alert(1)', 'file:///etc/passwd', 'ftp://example.org/a'):
            self.assertTrue(validate('source_artifact', mutate(ARTIFACT, lambda a: a.update(url=url))), url)

    def test_packet_needs_a_request(self):
        self.assertTrue(validate('research_packet', mutate(PACKET, lambda p: p.pop('request_id'))))


class HiddenContent(unittest.TestCase):
    """T3: no invisible text that could carry instructions into ZPMND's evaluation."""
    def test_invisible_characters_rejected(self):
        for ch in ('​', '‮', '⁦', '﻿', '\x00', '\x1b', '\x85'):
            bad = mutate(PACKET, lambda p: p['findings']['confirmed'][0].update(claim=f'ok{ch}text'))
            self.assertTrue(validate('research_packet', bad), repr(ch))

    def test_newlines_and_tabs_allowed(self):
        self.assertEqual(validate('research_packet', mutate(PACKET, lambda p: p.update(scope='a\n\tb'))), [])

    def test_long_quotes_rejected(self):
        bad = mutate(PACKET, lambda p: p['findings']['confirmed'][0].update(quote='x' * 301))
        self.assertTrue(validate('research_packet', bad))

    def test_oversize_document_rejected(self):
        bad = mutate(PACKET, lambda p: p.update(candidate_claims=['x' * 4000] * 50, candidate_methods=['y' * 4000] * 50,
                                                candidate_controls=['z' * 4000] * 50))
        self.assertTrue(any('larger than' in e for e in validate('research_packet', bad)))


class PrivacyAndRights(unittest.TestCase):
    """T4: only disclosable requests enter; raw files enter git only with redistribution rights."""
    def test_private_requests_rejected(self):
        for cls in ('PRIVATE', 'RESTRICTED', 'CONFIDENTIAL', 'INTERNAL'):
            self.assertTrue(validate('research_request', mutate(REQUEST, lambda r: r.update(privacy_class=cls))), cls)

    def test_research_group_cannot_issue_requests(self):
        self.assertTrue(validate('research_request', mutate(REQUEST, lambda r: r.update(issued_by='RESEARCH_GROUP'))))

    def test_raw_in_repo_requires_redistribution_rights(self):
        self.assertTrue(validate('source_artifact', mutate(ARTIFACT, lambda a: a.update(stored_at='repo'))))
        self.assertEqual(validate('source_artifact', mutate(ARTIFACT, lambda a: a.update(stored_at='repo', redistribution='allowed'))), [])

    def test_requested_demand_needs_request_id(self):
        self.assertTrue(validate('knowledge_demand', mutate(DEMAND, lambda d: d.update(origin='RESEARCH_REQUEST'))))


if __name__ == '__main__':
    unittest.main()
