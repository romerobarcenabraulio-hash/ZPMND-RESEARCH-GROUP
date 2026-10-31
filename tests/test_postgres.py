"""The throwaway Postgres that ci.yml (checks and mutation) and the auditor's evidence job give the database tests: where
RG_REQUIRE_DB_TESTS is set a missing database fails instead of skipping, and the database there answers a real query.
The Claude auditor on 04f6d73: a service with no test that uses it is false assurance; this file is that test."""
import os
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
URL = os.environ.get('RG_TEST_DB_URL', '')
ENV = {'RG_TEST_DB_URL': 'postgresql://postgres:postgres@localhost:5432/postgres', 'RG_REQUIRE_DB_TESTS': '1'}


class Required(unittest.TestCase):
    def test_where_the_database_is_required_it_is_there(self):
        if os.environ.get('RG_REQUIRE_DB_TESTS'):
            self.assertTrue(URL, 'RG_REQUIRE_DB_TESTS is set and RG_TEST_DB_URL is not: the database tests would be skipped')


@unittest.skipUnless(URL, 'needs RG_TEST_DB_URL (ci.yml and the auditor evidence job set it)')
class Answers(unittest.TestCase):
    def test_the_database_answers_a_query(self):
        import psycopg
        with psycopg.connect(URL, connect_timeout=30) as conn:
            self.assertEqual(conn.execute('SELECT 1').fetchone(), (1,))


class Jobs(unittest.TestCase):
    def test_every_job_that_runs_the_suite_has_the_database_and_requires_it(self):
        for wf, name in (('ci.yml', 'checks'), ('ci.yml', 'mutation'), ('auditor.yml', 'evidence')):
            with self.subTest(job=f'{wf} {name}'):
                job = yaml.safe_load((ROOT / '.github' / 'workflows' / wf).read_text(encoding='utf-8'))['jobs'][name]
                self.assertEqual(job['services']['postgres']['image'], 'postgres:16-alpine')
                self.assertEqual({k: job.get('env', {}).get(k) for k in ENV}, ENV)


if __name__ == '__main__':
    unittest.main()
