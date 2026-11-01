"""rg/catalog/db.py: the catalog in Postgres, every field of every row in its place, checked against the rows, swapped in
only whole. The database tests run against the Postgres that RG_TEST_DB_URL names (a service container in ci.yml);
ci.yml sets RG_REQUIRE_DB_TESTS so they can never be skipped there.

Built here (CONSTRUIDO): a small catalog folder shaped as store.Catalog writes it (dof/<year>.jsonl, an indicator series,
a state file with listing.state_code, the NOM and treaty views, a run manifest) and sources shaped as sources/mx.json.
"""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from rg.catalog import db

ROOT = Path(__file__).resolve().parents[1]
URL = os.environ.get('RG_TEST_DB_URL', '')
P = f't{os.getpid()}_'  # this process's schemas: mutation runs suites side by side
SOURCES = {'sources': [{'source_id': 'mx.dof', 'status': 'active', 'tier': 1, 'title': 'DOF', 'publisher': 'SEGOB',
                        'license': 'LFDA art. 14 fr. VIII', 'redistribution': 'allowed', 'source_type': 'primary_official'},
                       {'source_id': 'mx.banxico-sie', 'status': 'active', 'tier': 1},
                       {'source_id': 'mx.ojn-estatal', 'status': 'active', 'tier': 1}],
           'secondary_sources': [{'source_id': 'mx.hf-tesis-scjn', 'status': 'active'}]}
ART = {'artifact_id': 'SA-1c98f4a7eebac052b66e8e4e', 'bytes': 28025, 'license': 'LFDA art. 14 fr. VIII (official texts)',
       'media_type': 'text/html', 'publisher': 'SEGOB - DOF', 'redistribution': 'allowed', 'retrieved_at': '2026-10-21T20:30:35Z',
       'sha256': '1c' * 32, 'source_type': 'primary_official', 'stored_at': 'local_corpus',
       'url': 'https://sidof.segob.gob.mx/notas/docFuente/5777757'}


def dof(native, title, published, **extra):
    return {'entry_id': f'mx.dof:{native}', 'country': 'MX', 'source_id': 'mx.dof', 'native_id': str(native), 'title': title,
            'url': f'https://sidof.segob.gob.mx/notas/{native}', 'date_source': 'edition', 'raw_status': 'stored',
            'raw_path': 'sha256/1c/' + '1c' * 32 + '.html', 'first_seen': '2026-10-21T17:43:50Z', 'artifact': ART,
            'category': {'jurisdiction': 'federal', 'collection': 'DOF', 'edition': 'MATUTINA', 'section': 'UNICA SECCION',
                         'branch': 'PODER EJECUTIVO', 'issuer': 'SECRETARIA DE RELACIONES EXTERIORES', 'doc_type': 'DECRETO'},
            'dates': {'published': published}, **extra}


NOTE = dof(5777757, 'Decreto Promulgatorio del Convenio de Ejemplo, hecho en Roma.', '2026-01-02')
NOM = dof(5356770, 'Proyecto de Norma Oficial Mexicana PROY-NOM-000-SAG-FITO/SSA1-2013, Límites máximos de residuos',
          '2014-08-19', versions=[{'sha256': '2d' * 32, 'retrieved_at': '2026-10-22T01:00:00Z',
                                   'raw_path': 'sha256/2d/' + '2d' * 32 + '.html', 'last_modified': None}])
FIX = {'entry_id': 'mx.banxico-sie:SF43718-1991-11-12', 'country': 'MX', 'source_id': 'mx.banxico-sie',
       'native_id': 'SF43718-1991-11-12', 'title': 'Tipo de cambio', 'url': 'https://www.banxico.org.mx/SieAPIRest/service/v1/series/SF43718/datos/<token>',
       'raw_status': 'stored', 'first_seen': '2026-10-22T02:06:00Z', 'category': {'jurisdiction': 'federal', 'collection': 'SIE',
       'doc_type': 'INDICADOR ECONOMICO'}, 'dates': {}, 'observation': {'series_id': 'SF43718', 'date_printed': '12/11/1991',
       'value_printed': '3.0735', 'unit_printed': 'Pesos por Dólar'}}
LEY = {'entry_id': 'mx.ojn-estatal:1-1-1', 'country': 'MX', 'source_id': 'mx.ojn-estatal', 'native_id': '1-1-1',
       'title': 'Ley de Aguas del Estado de Aguascalientes', 'url': 'https://www.ordenjuridico.gob.mx/fichaOrdenamiento.php?idArchivo=1',
       'raw_status': 'stored', 'first_seen': '2026-10-19T00:00:00Z',
       'category': {'jurisdiction': 'estatal', 'collection': 'OJN', 'branch': 'PODER LEGISLATIVO', 'doc_type': 'LEY',
                    'status_printed': 'VIGENTE', 'locality': 'Aguascalientes'},
       'dates': {'original_publication': '2000-01-03', 'last_reform_printed': '2024-05-06'},
       'listing': {'state_code': 1, 'page_order': 3, 'history_urls': [], 'type_printed': 'Ley'}}


class Catalog:
    def __init__(self, test, rows=None, noms=None, treaties=None, coverage=None):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.mx = self.root / 'mx'
        files = rows if rows is not None else {'dof/2026.jsonl': [NOTE], 'dof/2014.jsonl': [NOM],
                                               'banxico-sie/SF43718.jsonl': [FIX], 'ojn-estatal/01.jsonl': [LEY]}
        for rel, entries in files.items():
            (self.mx / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.mx / rel).write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in entries), encoding='utf-8')
        (self.mx / 'normas').mkdir(parents=True)  # parents: a catalog may have no row file at all
        (self.mx / 'normas' / 'nom.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in (noms if noms is not None else [
            {'lineage': 'NOM-000-SAG-FITO/SSA1', 'editions': [2013], 'notes': [
                {'entry_id': NOM['entry_id'], 'stage': 'proyecto', 'edition': 2013, 'code_printed': 'PROY-NOM-000-SAG-FITO/SSA1-2013',
                 'project': True, 'published': '2014-08-19', 'title': NOM['title']}],
             'relations': [{'entry_id': NOM['entry_id'], 'type': 'menciona', 'to': 'NOM-002-CNA-1995', 'to_lineage': 'NOM-002-CNA',
                            'to_edition': 1995, 'published': '2014-08-19'}]}])), encoding='utf-8')
        (self.mx / 'tratados').mkdir()
        (self.mx / 'tratados' / 'tratados.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in (treaties if treaties is not None else [
            {'instrument': 'CONVENIO DE EJEMPLO', 'notes': [{'entry_id': NOTE['entry_id'], 'published': '2026-01-02',
                                                            'stage': 'promulgacion', 'title': NOTE['title']}]}])), encoding='utf-8')
        (self.mx / 'runs').mkdir()
        (self.mx / 'runs' / '2026-10-29T055004Z.json').write_text(json.dumps({'started_at': '2026-10-29T05:50:04Z',
            'finished_at': '2026-10-29T06:20:35Z', 'coverage': coverage if coverage is not None else [
                {'source_id': 'mx.dof', 'scope': '2026-10-28', 'expected': 69, 'extracted': 69, 'ok': True}]}), encoding='utf-8')

    def build(self, conn):
        return db.build(conn, self.root, 'mx', SOURCES, prefix=P, reader=READER)


READER = P + 'lector'
PASSWORD = 'a1' * 20
REMOTE = 'postgresql://postgres.abcdefghijklmnop@aws-0-us-east-1.pooler.supabase.com:5432/postgres'  # no password: test_no_secrets


class Connection(unittest.TestCase):
    """GPT on 358b5d8: a remote connection always verifies the server; no URI can turn that off."""

    def test_a_remote_host_is_verified_by_name_against_the_pinned_ca(self):
        self.assertEqual(db.tls(REMOTE), {'sslmode': 'verify-full', 'sslrootcert': str(db.CA)})
        import hashlib
        self.assertEqual(hashlib.sha256(db.CA.read_bytes()).hexdigest(), db.CA_SHA256)
        with mock.patch('psycopg.connect') as c:
            db.connect(REMOTE)
        self.assertEqual((c.call_args.kwargs['sslmode'], c.call_args.kwargs['sslrootcert']), ('verify-full', str(db.CA)))

    def test_only_a_local_host_connects_as_its_uri_says(self):
        for uri in ('postgresql://postgres:postgres@localhost:5432/postgres', 'postgresql://u@127.0.0.1/db',
                    'postgresql://u@[::1]/db', 'postgresql:///db?host=/var/run/postgresql'):
            with self.subTest(uri=uri):
                self.assertEqual(db.tls(uri), {})
        for uri in (REMOTE, 'postgresql://u@localhost.evil.com/db', 'postgresql://u@localhost,db.example.com/db'):
            with self.subTest(uri=uri):
                self.assertEqual(db.tls(uri)['sslmode'], 'verify-full')

    def test_a_uri_that_sets_its_own_tls_or_address_is_refused_without_echoing_it(self):
        for extra in ('sslmode=disable', 'sslmode=require', 'sslrootcert=/tmp/x.crt', 'sslmode=verify-full&sslrootcert=system',
                      'hostaddr=1.2.3.4', 'gssencmode=disable'):
            uri = f'{REMOTE}?{extra}'
            with self.subTest(extra=extra):
                with self.assertRaises(ValueError):
                    db.tls(uri)
                with mock.patch.dict('os.environ', {'RG_DB_URL': uri}, clear=True), \
                        mock.patch.object(db, 'connect', side_effect=AssertionError('no call')), self.assertRaises(SystemExit) as e:
                    db.main(['ping'])
                self.assertIn('sets options RG sets or refuses', str(e.exception))
                self.assertNotIn('pooler.supabase.com', str(e.exception))  # the URI is never echoed

    def test_the_reader_logs_in_as_the_pooler_names_it(self):
        self.assertEqual(db.reader_user(REMOTE), 'zppmnd_lectura.abcdefghijklmnop')
        self.assertEqual(db.reader_user('postgresql://postgres:x@localhost/postgres', 'r'), 'r')

    def test_a_ca_that_is_not_the_pinned_one_is_refused(self):
        with mock.patch.object(db, 'CA_SHA256', '0' * 64), self.assertRaises(ValueError):
            db.tls(REMOTE)

    def test_the_role_password_reaches_the_server_only_as_its_scram_verifier(self):
        import base64
        import hashlib
        import hmac
        v = db.scram(PASSWORD, salt=b'\x01' * 16)
        head, keys = v.split('$')[1:]
        iterations, salt = head.split(':')
        stored, server = (base64.b64decode(k) for k in keys.split(':'))
        salted = hashlib.pbkdf2_hmac('sha256', PASSWORD.encode(), base64.b64decode(salt), int(iterations))
        self.assertEqual(stored, hashlib.sha256(hmac.new(salted, b'Client Key', 'sha256').digest()).digest())
        self.assertEqual(server, hmac.new(salted, b'Server Key', 'sha256').digest())
        self.assertNotIn(PASSWORD, v)
        self.assertNotEqual(db.scram(PASSWORD), db.scram(PASSWORD))  # a fresh salt each time


class Organization(unittest.TestCase):
    def test_every_field_the_entry_schema_allows_has_a_place(self):
        schema = json.loads((ROOT / 'schemas' / 'catalog_entry.schema.json').read_text(encoding='utf-8'))
        self.assertEqual(set(schema['properties']), set(db.COLUMNS) | set(db.NESTED) | set(db.AS_JSON) | set(db.ELSEWHERE))
        for key in ('category', 'dates'):
            self.assertEqual(set(schema['properties'][key]['properties']), set(db.NESTED[key]), key)
        artifact = json.loads((ROOT / 'schemas' / 'source_artifact.schema.json').read_text(encoding='utf-8'))
        self.assertEqual(set(artifact['properties']), set(db.NESTED['artifact']))

    def test_a_field_with_no_column_stops_the_build(self):
        for bad in ({**NOTE, 'nuevo': 1}, {**NOTE, 'category': {**NOTE['category'], 'nueva': 'x'}},
                    {**NOTE, 'artifact': {**ART, 'otra': 'x'}}):
            with self.subTest(bad=sorted(set(bad) ^ set(NOTE)) or 'nested'), self.assertRaises(ValueError):
                db._doc(bad)

    def test_the_lines_of_a_file_are_counted_one_by_one(self):
        c = Catalog(self, rows={'dof/2026.jsonl': [NOTE, dof(5777758, 'Aviso de prueba.', '2026-01-02')], 'dof/2014.jsonl': [NOM]})
        self.assertEqual(db.lines_per_source(c.mx), {'mx.dof': 3})


class Command(unittest.TestCase):
    def test_a_value_that_is_not_a_connection_uri_stops_before_any_connection(self):
        for value in ('', 'https://xyz.supabase.co', 'eyJhbGciOiJIUzI1NiJ9.secreto'):
            with self.subTest(value=value[:8]), mock.patch.dict('os.environ', {'RG_DB_URL': value}, clear=True), \
                    mock.patch.object(db, 'connect', side_effect=AssertionError('no call')), self.assertRaises(SystemExit) as e:
                db.main(['ping'])
            self.assertIn('is not a postgresql:// connection URI', str(e.exception))
            if value:
                self.assertNotIn(value, str(e.exception))  # the value is never echoed

    def test_an_empty_checkout_is_refused_before_any_statement_and_the_command_exits_3(self):
        # GPT on 358b5d8: with no rows every check passes, and the live catalog would be swapped for an empty one
        conn = mock.MagicMock()
        conn.execute.side_effect = AssertionError('no statement')
        for c in (Catalog(self, rows={}, noms=[], treaties=[]), Catalog(self, rows={'dof/2026.jsonl': []}, noms=[], treaties=[])):
            with self.subTest(root=c.root), self.assertRaises(db.Empty):
                db.build(conn, c.root, 'mx', SOURCES)
        with self.assertRaises(db.Empty):
            db.build(conn, c.root / 'nada', 'mx', SOURCES)
        sources = c.root / 'mx.json'
        sources.write_text(json.dumps(SOURCES), encoding='utf-8')
        with mock.patch.dict('os.environ', {'RG_DB_URL': 'postgresql://u:p@localhost/db'}, clear=True), \
                mock.patch.object(db, 'connect', return_value=conn), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(db.main(['cargar', '--catalog', str(c.root), '--sources', str(sources)]), 3)
        self.assertIn('no rows', json.loads(out.getvalue())['empty'])

    def test_the_role_command_needs_a_strong_password_and_fails_when_its_test_fails(self):
        env = {'RG_DB_URL': 'postgresql://u:p@localhost/db'}
        for bad in ('', 'corta', 'x' * 31, 'con espacio ' * 4, 'ñ' * 40):
            with self.subTest(bad=bad[:6]), mock.patch.dict('os.environ', {**env, 'RG_LECTURA_PASSWORD': bad}, clear=True), \
                    mock.patch.object(db, 'connect', side_effect=AssertionError('no call')), self.assertRaises(SystemExit) as e:
                db.main(['lector'])
            self.assertIn('RG_LECTURA_PASSWORD must be', str(e.exception))
        for ok, code in ((True, 0), (False, 3)):
            with self.subTest(ok=ok), mock.patch.dict('os.environ', {**env, 'RG_LECTURA_PASSWORD': PASSWORD}, clear=True), \
                    mock.patch.object(db, 'connect'), mock.patch.object(db, 'reader_role') as role, \
                    mock.patch.object(db, 'reader_probe', return_value={'ok': ok}), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(db.main(['lector']), code)
            self.assertEqual(role.call_args.args[1], PASSWORD)

    def test_the_role_logs_in_only_after_its_test_and_its_login_pass(self):
        for probe, login, disabled in (({'ok': True}, 'ok', False), ({'ok': True}, 'refused (OperationalError)', True),
                                       ({'ok': False}, 'ok', True), (RuntimeError('x'), 'ok', True)):
            kw = {'side_effect': probe} if isinstance(probe, Exception) else {'return_value': dict(probe)}
            with self.subTest(probe=probe, login=login), mock.patch.object(db, 'reader_role'), \
                    mock.patch.object(db, 'reader_probe', **kw), mock.patch.object(db, 'reader_enable', return_value=login) as on, \
                    mock.patch.object(db, 'reader_disable') as off:
                try:
                    report = db.lector('conn', 'url', PASSWORD, role='r')
                    self.assertEqual(report['ok'], not disabled)
                except RuntimeError:
                    pass
                self.assertEqual(off.call_args_list, [mock.call('conn', 'r')] if disabled else [])
                self.assertEqual(on.called, probe == {'ok': True})  # LOGIN is never given before the test passes

    def test_a_failed_connection_says_its_kind_and_never_the_uri(self):
        uri = 'postgresql://usuario-secreto:clave-secreta@127.0.0.1:9/nada'
        with mock.patch.dict('os.environ', {'RG_DB_URL': uri}, clear=True), \
                mock.patch.object(db, 'connect', side_effect=OSError(f'cannot reach {uri}')), self.assertRaises(SystemExit) as e:
            db.main(['ping'])
        self.assertEqual(str(e.exception), 'no connection to the database: OSError')


class Views(unittest.TestCase):
    def test_a_checkout_missing_a_view_is_refused_before_the_database_is_touched(self):
        # GPT on 03e6751: read as empty, an absent NOM, treaty or run view would let the swap erase its live tables
        for gone in db.VIEWS:
            with self.subTest(gone=gone):
                c = Catalog(self)
                target = c.mx / gone
                if target.is_dir():
                    for f in target.iterdir():
                        f.unlink()
                    target.rmdir()
                else:
                    target.unlink()
                conn = mock.Mock()
                with self.assertRaises(db.Empty) as e:
                    c.build(conn)
                self.assertIn(gone, str(e.exception))
                conn.execute.assert_not_called()

    def test_an_empty_view_is_a_view(self):
        c = Catalog(self, noms=[], treaties=[])
        self.assertEqual(db._views(c.mx)[3]['nom'], 0)


class Required(unittest.TestCase):
    def test_where_the_database_tests_are_required_they_have_a_database(self):
        if os.environ.get('RG_REQUIRE_DB_TESTS'):
            self.assertTrue(URL, 'RG_REQUIRE_DB_TESTS is set and RG_TEST_DB_URL is not: the database tests would be skipped')


@unittest.skipUnless(URL, 'needs RG_TEST_DB_URL (a Postgres; ci.yml has one)')
class Database(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(URL)
        self.addCleanup(self.conn.close)
        self.addCleanup(self.drop)

    def drop(self):
        self.conn.rollback()
        for s in (db.LIVE, db.NEXT, db.REJECTED, 'sonda', 'extra'):
            self.conn.execute(f'DROP SCHEMA IF EXISTS "{P}{s}" CASCADE')
        for r in (READER, P + 'otro'):
            if self.conn.execute('SELECT 1 FROM pg_roles WHERE rolname = %s', (r,)).fetchone():
                self.conn.execute(f'DROP OWNED BY "{r}"')
                self.conn.execute(f'DROP ROLE "{r}"')
        self.conn.commit()

    def rows(self, query, schema=db.LIVE):
        return self.conn.execute(query.replace('{s}', f'"{P}{schema}"')).fetchall()

    def test_a_catalog_becomes_its_tables_and_the_report_says_it_holds_every_row(self):
        report = Catalog(self).build(self.conn)
        self.assertTrue(report['ok'], report)
        self.assertEqual((report['rows'], report['lines']), ({'mx.dof': 2, 'mx.banxico-sie': 1, 'mx.ojn-estatal': 1},) * 2)
        self.assertEqual(self.rows("SELECT ambito, estado, poder, tipo, n FROM {s}.arbol WHERE ambito = 'estatal'"),
                         [('estatal', 'Aguascalientes', 'PODER LEGISLATIVO', 'LEY', 1)])
        self.assertEqual(self.rows('SELECT value_printed, unit_printed FROM {s}.observacion'), [('3.0735', 'Pesos por Dólar')])
        self.assertEqual(self.rows('SELECT lineage, stage, project FROM {s}.nom_nota'), [('NOM-000-SAG-FITO/SSA1', 'proyecto', True)])
        self.assertEqual(self.rows('SELECT type, "to" FROM {s}.nom_relacion'), [('menciona', 'NOM-002-CNA-1995')])
        self.assertEqual(self.rows('SELECT instrument, stage FROM {s}.tratado_nota'), [('CONVENIO DE EJEMPLO', 'promulgacion')])
        self.assertEqual(self.rows('SELECT source_id, expected, extracted, ok FROM {s}.cobertura'), [('mx.dof', 69, 69, True)])
        self.assertEqual(self.rows("SELECT secondary FROM {s}.fuente WHERE source_id = 'mx.hf-tesis-scjn'"), [(True,)])
        self.assertEqual(self.rows('SELECT sha256 FROM {s}.version'), [('2d' * 32,)])
        # titles are searched with accents folded: 'limites maximos' finds 'Límites máximos'
        self.assertEqual(self.rows("SELECT entry_id FROM {s}.documento WHERE to_tsvector('simple', titulo_busqueda) "
                                   "@@ plainto_tsquery('simple', 'limites maximos')"), [(NOM['entry_id'],)])
        self.assertEqual(json.loads(dict(self.rows('SELECT key, value FROM {s}.meta'))['report'])['ok'], True)
        self.assertEqual(self.conn.execute('SELECT nspname FROM pg_namespace WHERE nspname LIKE %s ORDER BY 1', (P + '%',)).fetchall(),
                         [(P + db.LIVE,)])  # the loading schema became the live one; nothing else is left

    def test_the_database_gives_back_every_row_as_it_was_written(self):
        Catalog(self).build(self.conn)
        for e in (NOTE, NOM, FIX, LEY):
            with self.subTest(e['entry_id']):
                self.assertEqual(db.entry(self.conn, e['entry_id'], P + db.LIVE), db._bare(e))
        self.assertIsNone(db.entry(self.conn, 'mx.dof:0', P + db.LIVE))

    def assertRejectedAndLiveKept(self, report):
        self.assertFalse(report['ok'])
        self.assertTrue(json.loads(dict(self.rows('SELECT key, value FROM {s}.meta'))['report'])['ok'])  # live kept
        self.assertTrue(self.rows('SELECT 1 FROM {s}.documento', db.REJECTED))  # the rejected one is kept to look at

    def test_a_row_on_disk_the_database_lacks_is_reported(self):
        # the Claude auditor on 358b5d8: only missing_or_extra sees a line that never became a row
        c = Catalog(self)
        c.build(self.conn)
        with open(c.mx / 'dof' / '2026.jsonl', 'a', encoding='utf-8') as f:
            f.write(json.dumps(dof(5777759, 'Aviso que no llegó.', '2026-01-03')) + '\n')
        report = db.check(self.conn, c.mx, P + db.LIVE, db._views(c.mx)[3])
        self.assertEqual((report['missing_or_extra'], report['ok']), (['mx.dof'], False))

    def test_an_empty_or_smaller_load_never_replaces_the_live_catalog(self):
        # GPT on 358b5d8: publish, then try to load an empty catalog and one that lost rows; live stays whole
        Catalog(self).build(self.conn)
        with self.assertRaises(db.Empty):
            Catalog(self, rows={}, noms=[], treaties=[]).build(self.conn)
        self.assertEqual(self.rows('SELECT count(*) FROM {s}.documento'), [(4,)])
        report = Catalog(self, rows={'dof/2026.jsonl': [NOTE], 'banxico-sie/SF43718.jsonl': [FIX],
                                     'ojn-estatal/01.jsonl': [LEY]}, noms=[]).build(self.conn)
        self.assertEqual(report['shrunk'], {'mx.dof': {'live': 2, 'new': 1}})
        self.assertRejectedAndLiveKept(report)
        self.assertEqual(self.rows('SELECT count(*) FROM {s}.documento'), [(4,)])

    def test_the_reader_reads_the_live_catalog_after_every_load_and_nothing_else(self):
        # GPT on 358b5d8 (rights lost on the swap) and ZPPMND's acceptance test (2026-10-29)
        import psycopg
        sent = []
        real = type(self.conn).execute

        def spy(conn, query, *a, **k):
            sent.append(query)
            return real(conn, query, *a, **k)
        with mock.patch.object(type(self.conn), 'execute', spy):
            db.reader_role(self.conn, PASSWORD, role=READER, live=P + db.LIVE)
        text = ' '.join(q.as_string(self.conn) if hasattr(q, 'as_string') else str(q) for q in sent)
        self.assertNotIn(PASSWORD, text)
        self.assertIn('SCRAM-SHA-256$4096:', text)
        for n in (1, 2):  # two loads in a row: the second one's swap must not take the reader's rights away
            report = Catalog(self).build(self.conn)
            self.assertEqual((report['ok'], report['readers']), (True, [READER]), n)
        Catalog(self, rows={'dof/2026.jsonl': [NOTE, NOTE]}, noms=[], treaties=[]).build(self.conn)  # rejected
        privilege = lambda kind, obj, what: self.conn.execute(f'SELECT has_{kind}_privilege(%s, %s, %s)', (READER, obj, what)).fetchone()[0]
        self.assertFalse(privilege('schema', P + db.REJECTED, 'USAGE'))
        for table in ('documento', 'fuente', 'version', 'meta'):
            for what in ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'):
                self.assertFalse(privilege('table', f'"{P}{db.LIVE}".{table}', what), (table, what))
        self.assertTrue(db.lector(self.conn, URL, PASSWORD, role=READER, live=P + db.LIVE)['ok'])  # LOGIN once accepted
        with db.connect(URL, user=READER, password=PASSWORD, autocommit=True) as c:
            self.assertEqual(c.execute('SHOW default_transaction_read_only').fetchone(), ('on',))
            self.assertEqual(c.execute(f'SELECT count(*) FROM "{P}{db.LIVE}".documento').fetchone(), (4,))
            with self.assertRaises(psycopg.Error):
                c.execute('CREATE TABLE intruso(x int)')
        report = db.reader_probe(self.conn, role=READER, live=P + db.LIVE, other=P + 'sonda')
        self.assertTrue(report['ok'], report)
        self.assertEqual(report['select_catalogo'], 'ok')
        self.assertTrue(report['insert_catalogo'].startswith('refused') and report['select_otro_schema'].startswith('refused'))

    def test_a_load_that_swaps_a_published_document_or_version_for_another_never_goes_live(self):
        # GPT on 2f0c5b3: with A and B published, B and C keep the count; A must not disappear, nor a version
        Catalog(self).build(self.conn)
        report = Catalog(self, rows={'dof/2026.jsonl': [NOTE, dof(5777760, 'Aviso nuevo.', '2026-01-04')],
                                     'banxico-sie/SF43718.jsonl': [FIX], 'ojn-estatal/01.jsonl': [LEY]}, noms=[]).build(self.conn)
        # the swapped-out document goes with its version: both are reported
        self.assertEqual((report['shrunk'], report['perdidos']), ({}, {'documento': [[NOM['entry_id']]], 'version': [[NOM['entry_id'], '2d' * 32]]}))
        self.assertRejectedAndLiveKept(report)
        bare = {k: v for k, v in NOM.items() if k != 'versions'}
        report = Catalog(self, rows={'dof/2026.jsonl': [NOTE], 'dof/2014.jsonl': [bare], 'banxico-sie/SF43718.jsonl': [FIX],
                                     'ojn-estatal/01.jsonl': [LEY]}).build(self.conn)
        self.assertEqual(report['perdidos'], {'version': [[NOM['entry_id'], '2d' * 32]]})
        self.assertRejectedAndLiveKept(report)

    def test_a_source_that_loses_a_row_to_another_never_goes_live(self):
        # GPT on 6dcedcf: the entry keeps its entry_id and moves to another source's file; counts and identities agree
        Catalog(self).build(self.conn)
        report = Catalog(self, rows={'dof/2014.jsonl': [NOM], 'banxico-sie/SF43718.jsonl': [FIX],
                                     'ojn-estatal/01.jsonl': [LEY, dict(NOTE, source_id='mx.ojn-estatal')]}).build(self.conn)
        self.assertEqual(report['shrunk'], {'mx.dof': {'live': 2, 'new': 1}})
        clean = ('missing_or_extra', 'duplicated', 'round_trip_differs', 'derived', 'dangling', 'unregistered_sources',
                 'perdidos')
        self.assertEqual({k: report[k] for k in clean}, {'missing_or_extra': [], 'duplicated': [], 'round_trip_differs': 0,
                                                         'derived': {}, 'dangling': {}, 'unregistered_sources': [],
                                                         'perdidos': {}})  # only the shrink can refuse it
        self.assertRejectedAndLiveKept(report)

    def test_a_reader_whose_test_fails_or_breaks_cannot_log_in(self):
        # GPT on 6dcedcf: the role was enabled before its acceptance; a red test left it able to log in
        import psycopg
        Catalog(self).build(self.conn)
        db.reader_role(self.conn, PASSWORD, role=READER, live=P + db.LIVE)  # GPT on f6c1e87: the run dies right here
        with self.assertRaises(psycopg.Error):
            db.connect(URL, user=READER, password=PASSWORD).close()  # configured, never accepted: no login at all
        self.conn.execute(f'GRANT UPDATE (title) ON "{P}{db.LIVE}".documento TO PUBLIC'); self.conn.commit()
        report = db.lector(self.conn, URL, PASSWORD, role=READER, live=P + db.LIVE)
        self.assertFalse(report['ok'])
        with self.assertRaises(psycopg.Error):
            db.connect(URL, user=READER, password=PASSWORD).close()
        self.conn.execute(f'REVOKE UPDATE (title) ON "{P}{db.LIVE}".documento FROM PUBLIC'); self.conn.commit()
        self.assertTrue(db.lector(self.conn, URL, PASSWORD, role=READER, live=P + db.LIVE)['ok'])  # accepted: it logs in
        db.connect(URL, user=READER, password=PASSWORD).close()
        with mock.patch.object(db, 'reader_probe', side_effect=RuntimeError('broken')), self.assertRaises(RuntimeError):
            db.lector(self.conn, URL, PASSWORD, role=READER, live=P + db.LIVE)
        with self.assertRaises(psycopg.Error):
            db.connect(URL, user=READER, password=PASSWORD).close()

    def test_updating_the_reader_drops_every_privilege_and_membership_it_had(self):
        Catalog(self).build(self.conn)
        db.reader_role(self.conn, PASSWORD, role=READER, live=P + db.LIVE)
        self.conn.execute(f'CREATE ROLE "{P}otro"')
        self.conn.execute(f'GRANT "{P}otro" TO "{READER}"')
        self.conn.execute(f'GRANT INSERT ON "{P}{db.LIVE}".fuente TO "{READER}"')
        self.conn.commit()
        db.reader_role(self.conn, PASSWORD, role=READER, live=P + db.LIVE)
        self.assertFalse(self.conn.execute('SELECT 1 FROM pg_auth_members m JOIN pg_roles u ON u.oid = m.member WHERE u.rolname = %s',
                                           (READER,)).fetchall())
        self.assertFalse(self.conn.execute('SELECT has_table_privilege(%s, %s, %s)', (READER, f'"{P}{db.LIVE}".fuente', 'INSERT')).fetchone()[0])
        self.assertTrue(db.reader_probe(self.conn, role=READER, live=P + db.LIVE, other=P + 'sonda')['ok'])

    def test_the_probe_reads_privileges_not_only_behavior(self):
        # GPT on 2f0c5b3: a read-only session default hid a granted INSERT; the probe now writes inside READ WRITE and
        # reads, from the catalogs, any write privilege, any SELECT outside the live schema and any membership
        Catalog(self).build(self.conn)
        probe = lambda: db.reader_probe(self.conn, role=READER, live=P + db.LIVE, other=P + 'sonda')
        db.reader_role(self.conn, PASSWORD, role=READER, live=P + db.LIVE)
        self.conn.execute(f'GRANT INSERT ON "{P}{db.LIVE}".fuente TO "{READER}"'); self.conn.commit()
        r = probe()
        self.assertEqual((r['insert_catalogo'], r['ok']), ('ok', False))  # the write went through: privileges, not the default
        db.reader_role(self.conn, PASSWORD, role=READER, live=P + db.LIVE)
        self.conn.execute(f'GRANT UPDATE ON "{P}{db.LIVE}".documento TO "{READER}"'); self.conn.commit()
        r = probe()
        self.assertEqual((r['escritura'], r['ok']), ([f'{P}{db.LIVE}.documento'], False))  # regclass quotes only when needed
        db.reader_role(self.conn, PASSWORD, role=READER, live=P + db.LIVE)
        self.conn.execute(f'CREATE SCHEMA "{P}extra"'); self.conn.execute(f'CREATE TABLE "{P}extra".t(x int)')
        self.conn.execute(f'GRANT SELECT ON "{P}extra".t TO "{READER}"'); self.conn.commit()
        r = probe()
        self.assertEqual((r['lectura_fuera'], r['ok']), ([f'{P}extra.t'], False))
        db.reader_role(self.conn, PASSWORD, role=READER, live=P + db.LIVE)
        self.conn.execute(f'CREATE ROLE "{P}otro"'); self.conn.execute(f'GRANT "{P}otro" TO "{READER}"'); self.conn.commit()
        r = probe()
        self.assertEqual((r['membresias'], r['ok']), ([P + 'otro'], False))
        # GPT on d974ef0: a SECURITY DEFINER function it may run, or a schema where it may create, is a way to write
        db.reader_role(self.conn, PASSWORD, role=READER, live=P + db.LIVE)
        self.conn.execute(f'GRANT USAGE ON SCHEMA "{P}extra" TO "{READER}"')
        self.conn.execute(f'CREATE FUNCTION "{P}extra".f() RETURNS int LANGUAGE sql SECURITY DEFINER AS $$ SELECT 1 $$')
        self.conn.execute(f'REVOKE EXECUTE ON FUNCTION "{P}extra".f() FROM PUBLIC')
        self.conn.execute(f'GRANT EXECUTE ON FUNCTION "{P}extra".f() TO "{READER}"'); self.conn.commit()
        r = probe()
        self.assertEqual((r['funciones'], r['ok']), ([f'{P}extra.f()'], False))
        db.reader_role(self.conn, PASSWORD, role=READER, live=P + db.LIVE)
        self.conn.execute(f'GRANT CREATE ON SCHEMA "{P}extra" TO "{READER}"'); self.conn.commit()
        r = probe()
        self.assertEqual((r['crear'], r['ok']), ([f'{P}extra'], False))
        # GPT on 03e6751: a sequence it may use through PUBLIC changes state with nextval() even in a read-only catalog
        db.reader_role(self.conn, PASSWORD, role=READER, live=P + db.LIVE)
        self.conn.execute(f'CREATE SEQUENCE "{P}extra".s')
        self.conn.execute(f'GRANT USAGE ON SEQUENCE "{P}extra".s TO PUBLIC'); self.conn.commit()
        r = probe()
        self.assertEqual((r['secuencias'], r['ok']), ([f'{P}extra.s'], False))
        self.conn.execute(f'REVOKE USAGE ON SEQUENCE "{P}extra".s FROM PUBLIC'); self.conn.commit()
        # GPT on 6dcedcf: a privilege on one column, even to PUBLIC, survives DROP OWNED BY and still writes or reads
        db.reader_role(self.conn, PASSWORD, role=READER, live=P + db.LIVE)
        self.conn.execute(f'GRANT UPDATE (title) ON "{P}{db.LIVE}".documento TO PUBLIC'); self.conn.commit()
        r = probe()
        self.assertEqual((r['escritura'], r['ok']), ([f'{P}{db.LIVE}.documento'], False))
        self.conn.execute(f'REVOKE UPDATE (title) ON "{P}{db.LIVE}".documento FROM PUBLIC')
        self.conn.execute(f'GRANT SELECT (x) ON "{P}extra".t TO PUBLIC'); self.conn.commit()
        r = probe()
        self.assertEqual((r['lectura_fuera'], r['ok']), ([f'{P}extra.t'], False))

    def test_the_probe_fails_when_the_reader_cannot_read(self):
        db.reader_role(self.conn, PASSWORD, role=READER, live=P + db.LIVE)  # no live schema yet: nothing to read
        report = db.reader_probe(self.conn, role=READER, live=P + db.LIVE, other=P + 'sonda')
        self.assertFalse(report['ok'])
        self.assertTrue(report['select_catalogo'].startswith('refused'))

    def test_a_row_twice_is_reported_and_never_goes_live(self):
        Catalog(self).build(self.conn)
        report = Catalog(self, rows={'dof/2026.jsonl': [NOTE], 'dof/2014.jsonl': [NOTE]}, noms=[], treaties=[]).build(self.conn)
        self.assertEqual(report['duplicated'], [NOTE['entry_id']])
        self.assertRejectedAndLiveKept(report)

    def test_a_row_the_database_gives_back_differently_is_reported(self):
        Catalog(self).build(self.conn)
        real = db._doc
        # the same catalog, so nothing is lost and only the round trip can see the value the database dropped (m130)
        with mock.patch.object(db, '_doc', lambda e: [None if col == 'issuer' else v for col, v in zip(db.DOC_COLUMNS, real(e))]):
            report = Catalog(self).build(self.conn)
        self.assertEqual(report['perdidos'], {})
        self.assertEqual((report['round_trip_differs'], set(report['round_trip_examples'])), (2, {NOTE['entry_id'], NOM['entry_id']}))
        self.assertRejectedAndLiveKept(report)

    def test_a_view_naming_a_document_the_database_lacks_is_reported(self):
        report = Catalog(self, rows={'dof/2026.jsonl': [NOTE]}, treaties=[]).build(self.conn)  # the NOM view names mx.dof:5356770
        self.assertEqual(report['dangling'], {'nom_nota': [NOM['entry_id']], 'nom_relacion': [NOM['entry_id']]})
        self.assertFalse(report['ok'])

    def test_a_source_not_registered_in_a_row_or_a_coverage_check_is_reported(self):
        stray = {**LEY, 'entry_id': 'mx.ojn-municipal:1-1-1', 'source_id': 'mx.ojn-municipal'}
        for c, want in ((Catalog(self, rows={'ojn-municipal/01.jsonl': [stray]}, noms=[], treaties=[]), ['mx.ojn-municipal']),
                        (Catalog(self, coverage=[{'source_id': 'mx.inexistente', 'expected': 1, 'extracted': 1, 'ok': True}]),
                         ['mx.inexistente']),  # GPT on cdf5056: a coverage check names a source too
                        (Catalog(self, coverage=[{'scope': 'sin fuente', 'expected': 1, 'extracted': 1, 'ok': True}]),
                         ['(sin fuente)'])):
            with self.subTest(want=want):
                report = c.build(self.conn)
                self.assertEqual((report['ok'], report['unregistered_sources']), (False, want))

    def test_a_derived_table_that_lost_rows_is_reported(self):
        # GPT on cdf5056: the NOM, treaty and coverage tables are counted against their views too
        c = Catalog(self)
        c.build(self.conn)
        want = db._views(c.mx)[3]
        for table in want:
            with self.subTest(table):
                report = db.check(self.conn, c.mx, P + db.LIVE, {**want, table: want[table] + 1})
                self.assertEqual((report['ok'], report['derived']), (False, {table: {'want': want[table] + 1, 'got': want[table]}}))

    def test_the_command_loads_pings_and_exits_3_when_the_database_would_not_hold_every_row(self):
        real = db.build
        for rows, code in (({'dof/2026.jsonl': [NOTE]}, 0), ({'dof/2026.jsonl': [NOTE], 'dof/2014.jsonl': [NOTE]}, 3)):
            with self.subTest(code=code):
                c = Catalog(self, rows=rows, noms=[], treaties=[])
                sources = c.root / 'mx.json'
                sources.write_text(json.dumps(SOURCES), encoding='utf-8')
                with mock.patch.dict('os.environ', {'RG_DB_URL': URL}), contextlib.redirect_stdout(io.StringIO()) as out, \
                        mock.patch.object(db, 'build', lambda conn, *a: real(conn, *a, prefix=P)):
                    got = db.main(['cargar', '--catalog', str(c.root), '--sources', str(sources)])
                self.assertEqual((got, json.loads(out.getvalue())['ok']), (code, code == 0))
        with mock.patch.dict('os.environ', {'RG_DB_URL': URL}), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(db.main(['ping']), 0)
        self.assertTrue(json.loads(out.getvalue())['connected'])


if __name__ == '__main__':
    unittest.main()
