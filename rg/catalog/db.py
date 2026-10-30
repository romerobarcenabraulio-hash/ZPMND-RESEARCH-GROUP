"""The catalog in Postgres (Supabase; docs/CATALOGO.md, "Base de datos"): every row of <root>/<cc>/ in tables, rebuilt
whole in a schema of its own and swapped in for the live one only when its checks say it holds every row. The rows on
the catalog branch stay the record; the database is a view of them (like store.DERIVED) that agents and apps query.

Organization (schema `catalogo`):
  fuente                  one row per registered source (sources/<cc>.json): status, tier, publisher, license
  documento               one row per official document, note or tesis: where it sits (país → ámbito → estado →
                          municipio → poder → dependencia → tipo), its printed dates and status, its url and raw file
  version                 every text version of a document ever retrieved (append-only in the rows)
  observacion             one indicator value exactly as the API served it (text, never a number)
  nom, nom_nota, nom_relacion   NOM lineages (mx/normas/nom.jsonl), their notes by stage, cancela/menciona
  tratado, tratado_nota   treaties (mx/tratados/tratados.jsonl) and their decrees by stage
  corrida, cobertura      each run's manifest and its coverage checks
  arbol                   counts per level, a view; documento.titulo_busqueda feeds full-text search (accents folded)
Readers: the role READER (ZPPMND, 2026-10-29) may log in and SELECT the live schema, nothing else; its rights are given to
each new schema before the swap, so a load never takes them away (GPT on 358b5d8). Remote connections verify the server
against Supabase's root CA, pinned here by sha256; only a local host (the tests' Postgres) connects as its URI says.
Nothing is computed, inferred or classified: every column is copied from a row, a view or a manifest, except
titulo_busqueda, the title folded for search, which is never read back as data.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

from rg.catalog import store
from rg.catalog.categorize import fold

SCHEMA_VERSION = 2
LIVE, NEXT, REJECTED = 'catalogo', 'catalogo_nuevo', 'catalogo_rechazado'
READER = 'zppmnd_lectura'
# Supabase Root 2021 CA (prod-ca-2021.crt, Supabase's SSL download; it verified three session poolers by name, 2026-10-30)
CA = Path(__file__).with_name('supabase-prod-ca-2021.crt')
CA_SHA256 = '700723581420dd1ac98fd7e9ac529f0ef210eadcaf87fc868a3ad7d114c2f3b7'
LOCAL = ('localhost', '127.0.0.1', '::1')
# every field of schemas/catalog_entry.schema.json has a place (tests.test_db pins it): a new field is never dropped
COLUMNS = {'entry_id': 'entry_id', 'country': 'country', 'source_id': 'source_id', 'native_id': 'native_id',
           'title': 'title', 'url': 'url', 'date_source': 'date_source', 'raw_status': 'raw_status',
           'raw_path': 'raw_path', 'first_seen': 'first_seen'}
NESTED = {'category': ('jurisdiction', 'collection', 'edition', 'section', 'branch', 'issuer', 'doc_type',
                       'status_printed', 'locality', 'municipality'),
          'dates': ('published', 'original_publication', 'last_reform_printed'),
          'artifact': ('artifact_id', 'url', 'title', 'version', 'published_at', 'retrieved_at', 'sha256', 'bytes',
                       'media_type', 'source_type', 'publisher', 'license', 'redistribution', 'stored_at')}
AS_JSON = ('listing',)  # kept whole: its lists (history, related urls) have no fixed width
ELSEWHERE = ('observation', 'versions')  # tables of their own
DOC_COLUMNS = (list(COLUMNS.values()) + [f if k != 'artifact' else f'artifact_{f}' for k, fs in NESTED.items() for f in fs]
               + list(AS_JSON))
_TEXT = ' text'
TABLES = '''
CREATE TABLE {s}.meta(key text PRIMARY KEY, value text NOT NULL);
CREATE TABLE {s}.fuente(source_id text PRIMARY KEY, status text, tier integer, title text, publisher text, license text,
  redistribution text, source_type text, secondary boolean NOT NULL);
CREATE TABLE {s}.documento(''' + ', '.join(f'{c}{" bigint" if c == "artifact_bytes" else " jsonb" if c == "listing" else _TEXT}'
                                           for c in DOC_COLUMNS) + ''', titulo_busqueda text NOT NULL, ord bigint NOT NULL);
CREATE TABLE {s}.version(entry_id text NOT NULL, ord integer NOT NULL, sha256 text NOT NULL, retrieved_at text NOT NULL,
  raw_path text NOT NULL, last_modified text);
CREATE TABLE {s}.observacion(entry_id text NOT NULL, series_id text NOT NULL, date_printed text NOT NULL,
  value_printed text, unit_printed text);
CREATE TABLE {s}.nom(lineage text PRIMARY KEY, editions jsonb NOT NULL);
CREATE TABLE {s}.nom_nota(lineage text NOT NULL, entry_id text NOT NULL, stage text, edition integer, code_printed text,
  project boolean, published text);
CREATE TABLE {s}.nom_relacion(lineage text NOT NULL, entry_id text NOT NULL, type text NOT NULL, "to" text NOT NULL,
  to_lineage text, to_edition integer, published text);
CREATE TABLE {s}.tratado(instrument text PRIMARY KEY);
CREATE TABLE {s}.tratado_nota(instrument text NOT NULL, entry_id text NOT NULL, stage text, published text);
CREATE TABLE {s}.corrida(run_id text PRIMARY KEY, started_at text, finished_at text, manifest jsonb NOT NULL);
CREATE TABLE {s}.cobertura(run_id text NOT NULL, source_id text, scope text, expected bigint, extracted bigint, ok boolean);
'''
INDEXES = '''
CREATE INDEX ON {s}.documento(country, jurisdiction, locality, municipality, branch, issuer, doc_type);
CREATE INDEX ON {s}.documento(source_id, published);
CREATE INDEX ON {s}.documento USING gin (to_tsvector('simple', titulo_busqueda));
CREATE INDEX ON {s}.version(entry_id);
CREATE INDEX ON {s}.observacion(entry_id);
CREATE INDEX ON {s}.nom_nota(entry_id);
CREATE INDEX ON {s}.tratado_nota(entry_id);
CREATE VIEW {s}.arbol AS SELECT country AS pais, jurisdiction AS ambito, locality AS estado, municipality AS municipio,
  branch AS poder, issuer AS dependencia, doc_type AS tipo, count(*) AS n FROM {s}.documento GROUP BY 1, 2, 3, 4, 5, 6, 7;
'''


def _doc(e):
    """The documento values of one catalog entry, every one copied; a field with no column stops the build."""
    unknown = set(e) - set(COLUMNS) - set(NESTED) - set(AS_JSON) - set(ELSEWHERE)
    unknown |= {f'{k}.{f}' for k in NESTED for f in set(e.get(k) or {}) - set(NESTED[k])}
    if unknown:
        raise ValueError(f"{e.get('entry_id')}: fields with no column: {sorted(unknown)}")
    row = [e.get(key) for key in COLUMNS]
    row += [(e.get(k) or {}).get(f) for k, fs in NESTED.items() for f in fs]
    row.append(json.dumps(e['listing'], ensure_ascii=False, sort_keys=True) if 'listing' in e else None)
    return row


def _bare(x):
    """x without its empty values: a field absent and a field null say the same (no data in the source)."""
    if isinstance(x, dict):
        out = {k: _bare(v) for k, v in x.items()}
        return {k: v for k, v in out.items() if v is not None and v != {} and v != []}
    if isinstance(x, list):
        return [_bare(v) for v in x]
    return x


def _digest(e):
    return hashlib.sha256(json.dumps(_bare(e), ensure_ascii=False, sort_keys=True).encode('utf-8')).digest()


REBUILD = '''SELECT {cols},
  (SELECT json_agg(json_build_object('sha256', v.sha256, 'retrieved_at', v.retrieved_at, 'raw_path', v.raw_path,
                                     'last_modified', v.last_modified) ORDER BY v.ord)
     FROM {s}.version v WHERE v.entry_id = d.entry_id),
  o.series_id, o.date_printed, o.value_printed, o.unit_printed
FROM {s}.documento d LEFT JOIN {s}.observacion o ON o.entry_id = d.entry_id'''


def _rebuild(row):
    """The catalog entry the database gives back, from one REBUILD row, as _bare would write it."""
    vals = dict(zip(DOC_COLUMNS, row[:len(DOC_COLUMNS)]))
    versions, series_id, date_printed, value_printed, unit_printed = row[len(DOC_COLUMNS):]
    e = {key: vals[col] for key, col in COLUMNS.items()}
    for k, fs in NESTED.items():
        e[k] = {f: vals[f if k != 'artifact' else f'artifact_{f}'] for f in fs}
    if vals['listing'] is not None:
        e['listing'] = vals['listing']
    if versions:
        e['versions'] = versions
    if series_id is not None:
        e['observation'] = {'series_id': series_id, 'date_printed': date_printed, 'value_printed': value_printed,
                            'unit_printed': unit_printed}
    return _bare(e)


def entry(conn, entry_id, schema=LIVE):
    """One catalog entry as the database holds it, or None."""
    from psycopg import sql
    q = sql.SQL(REBUILD + ' WHERE d.entry_id = %s').format(cols=sql.SQL(', ').join(sql.SQL('d.') + sql.Identifier(c) for c in DOC_COLUMNS),
                                                           s=sql.Identifier(schema))
    row = conn.execute(q, (entry_id,)).fetchone()
    return _rebuild(row) if row else None


def _lines(path):
    with open(path, encoding='utf-8') as f:
        return [line for line in f if line.strip()]


def lines_per_source(cc_dir):
    """The independent count: non-empty lines of every row file, by the source its path names (dof/1993.jsonl is
    <cc>.dof), read without parsing a single row."""
    out = Counter()
    for f in store.row_files(cc_dir):
        out[f'{cc_dir.name}.{f.relative_to(cc_dir).parts[0].removesuffix(".jsonl")}'] += len(_lines(f))
    return out


def _views(cc_dir):
    """The NOM and treaty views and the run manifests as written, and how many rows each table must get from them."""
    noms = [json.loads(line) for line in (_lines(cc_dir / 'normas' / 'nom.jsonl') if (cc_dir / 'normas' / 'nom.jsonl').exists() else [])]
    treaties = [json.loads(line) for line in (_lines(cc_dir / 'tratados' / 'tratados.jsonl')
                                              if (cc_dir / 'tratados' / 'tratados.jsonl').exists() else [])]
    runs = []
    for f in sorted((cc_dir / 'runs').glob('*.json')):
        with open(f, encoding='utf-8') as fh:
            runs.append((f.stem, json.load(fh)))
    want = {'nom': len(noms), 'nom_nota': sum(len(r['notes']) for r in noms),
            'nom_relacion': sum(len(r.get('relations', [])) for r in noms), 'tratado': len(treaties),
            'tratado_nota': sum(len(r['notes']) for r in treaties), 'corrida': len(runs),
            'cobertura': sum(len(m.get('coverage', [])) for _, m in runs)}
    return noms, treaties, runs, want


class Empty(Exception):
    """A load with no rows: refused before the database is touched."""


def build(conn, root, country, sources, prefix='', reader=READER):
    """Loads <root>/<country>/ into schema next_, checks it, and swaps it in as live only if every check passes (one
    transaction: readers never see half a catalog); otherwise it is kept as rejected for inspection and live stays.
    prefix and reader only name the schemas and the role apart in tests that run side by side."""
    from psycopg import sql
    live, next_, rejected = prefix + LIVE, prefix + NEXT, prefix + REJECTED
    from psycopg.types.json import Jsonb
    cc_dir = Path(root) / country.lower()
    if not (cc_dir.is_dir() and sum(lines_per_source(cc_dir).values())):  # GPT on 358b5d8: an empty load passes every check
        raise Empty(f'{country}: the catalog checkout has no rows; nothing was loaded and the live catalog stays')
    S = sql.Identifier(next_)
    ddl = lambda text: conn.execute(sql.SQL(text).format(s=S))
    conn.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(S))
    conn.execute(sql.SQL('CREATE SCHEMA {}').format(S))
    for stmt in filter(str.strip, TABLES.split(';')):
        ddl(stmt)
    with conn.cursor() as cur:
        with cur.copy(sql.SQL('COPY {}.fuente FROM STDIN').format(S)) as cp:
            for secondary, key in ((False, 'sources'), (True, 'secondary_sources')):
                for s in sources.get(key, []):
                    cp.write_row((s['source_id'], s.get('status'), s.get('tier'), s.get('title'), s.get('publisher'),
                                  s.get('license'), s.get('redistribution'), s.get('source_type'), secondary))
        ord_ = 0
        cols = sql.SQL(', ').join(sql.Identifier(c) for c in DOC_COLUMNS + ['titulo_busqueda', 'ord'])
        for f in store.row_files(cc_dir):
            entries = [json.loads(line) for line in _lines(f)]
            with cur.copy(sql.SQL('COPY {}.documento ({}) FROM STDIN').format(S, cols)) as cp:
                for e in entries:
                    ord_ += 1
                    cp.write_row(_doc(e) + [fold(e['title']), ord_])
            with cur.copy(sql.SQL('COPY {}.version FROM STDIN').format(S)) as cp:
                for e in entries:
                    for i, v in enumerate(e.get('versions', [])):
                        cp.write_row((e['entry_id'], i, v['sha256'], v['retrieved_at'], v['raw_path'], v.get('last_modified')))
            with cur.copy(sql.SQL('COPY {}.observacion FROM STDIN').format(S)) as cp:
                for e in entries:
                    if 'observation' in e:
                        o = e['observation']
                        cp.write_row((e['entry_id'], o['series_id'], o['date_printed'], o.get('value_printed'), o.get('unit_printed')))
        noms, treaties, runs, want = _views(cc_dir)
        for r in noms:
            cur.execute(sql.SQL('INSERT INTO {}.nom VALUES (%s, %s)').format(S), (r['lineage'], Jsonb(r.get('editions', []))))
            cur.executemany(sql.SQL('INSERT INTO {}.nom_nota VALUES (%s, %s, %s, %s, %s, %s, %s)').format(S),
                            [(r['lineage'], n['entry_id'], n.get('stage'), n.get('edition'), n.get('code_printed'),
                              n.get('project'), n.get('published')) for n in r['notes']])
            cur.executemany(sql.SQL('INSERT INTO {}.nom_relacion VALUES (%s, %s, %s, %s, %s, %s, %s)').format(S),
                            [(r['lineage'], x['entry_id'], x['type'], x['to'], x.get('to_lineage'), x.get('to_edition'),
                              x.get('published')) for x in r.get('relations', [])])
        for r in treaties:
            cur.execute(sql.SQL('INSERT INTO {}.tratado VALUES (%s)').format(S), (r['instrument'],))
            cur.executemany(sql.SQL('INSERT INTO {}.tratado_nota VALUES (%s, %s, %s, %s)').format(S),
                            [(r['instrument'], n['entry_id'], n.get('stage'), n.get('published')) for n in r['notes']])
        for run_id, m in runs:
            cur.execute(sql.SQL('INSERT INTO {}.corrida VALUES (%s, %s, %s, %s)').format(S),
                        (run_id, m.get('started_at'), m.get('finished_at'), Jsonb(m)))
            cur.executemany(sql.SQL('INSERT INTO {}.cobertura VALUES (%s, %s, %s, %s, %s, %s)').format(S),
                            [(run_id, c.get('source_id'), c.get('scope'), c.get('expected'), c.get('extracted'), c.get('ok'))
                             for c in m.get('coverage', [])])
    for stmt in filter(str.strip, INDEXES.split(';')):
        ddl(stmt)
    report = check(conn, cc_dir, next_, want, live)
    report['readers'] = []
    if report['ok']:  # the reader's rights go on the new schema before the swap; a rejected load never gets them
        for (role,) in conn.execute('SELECT rolname FROM pg_roles WHERE rolname = %s', (reader,)).fetchall():
            conn.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(S, sql.Identifier(role)))
            conn.execute(sql.SQL('GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}').format(S, sql.Identifier(role)))
            report['readers'].append(role)
    conn.execute(sql.SQL('INSERT INTO {}.meta VALUES (%s, %s), (%s, %s)').format(S),
                 ('schema_version', str(SCHEMA_VERSION), 'report', json.dumps(report, ensure_ascii=False, sort_keys=True)))
    target = live if report['ok'] else rejected
    conn.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(target)))
    conn.execute(sql.SQL('ALTER SCHEMA {} RENAME TO {}').format(S, sql.Identifier(target)))
    conn.commit()  # the swap: drop, load, check and rename are one transaction
    return report


def check(conn, cc_dir, schema, want, live=None):
    """Rows per source against lines per source on disk, every row read back against its line (by digest), each
    derived table against its view's own count, no reference to a missing document, no unregistered source, and, when
    a live schema exists, no source with fewer rows than it has there: the catalog rows only grow (a partial checkout,
    a truncated file)."""
    from psycopg import sql
    S = sql.Identifier(schema)
    q = lambda text, *a: conn.execute(sql.SQL(text).format(s=S), a).fetchall()
    in_db = dict(q('SELECT source_id, count(*) FROM {s}.documento GROUP BY source_id'))
    before = {}
    if live and conn.execute('SELECT 1 FROM pg_namespace WHERE nspname = %s', (live,)).fetchone():
        before = dict(conn.execute(sql.SQL('SELECT source_id, count(*) FROM {}.documento GROUP BY source_id')
                                   .format(sql.Identifier(live))).fetchall())
    on_disk = lines_per_source(cc_dir)
    duplicated = [r[0] for r in q('SELECT entry_id FROM {s}.documento GROUP BY entry_id HAVING count(*) > 1 LIMIT 20')]
    digests = {}
    for f in store.row_files(cc_dir):
        for line in _lines(f):
            e = json.loads(line)
            digests[e['entry_id']] = _digest(e)
    differ = []
    cols = sql.SQL(', ').join(sql.SQL('d.') + sql.Identifier(c) for c in DOC_COLUMNS)
    with conn.cursor(name='ida_y_vuelta') as cur:
        cur.itersize = 10000
        cur.execute(sql.SQL(REBUILD + ' ORDER BY d.ord').format(cols=cols, s=S))
        for row in cur:
            e = _rebuild(row)
            if digests.get(e['entry_id']) != hashlib.sha256(json.dumps(e, ensure_ascii=False, sort_keys=True).encode('utf-8')).digest():
                differ.append(e['entry_id'])
    got = {t: q(f'SELECT count(*) FROM {{s}}.{t}')[0][0] for t in want}
    derived = {t: {'want': want[t], 'got': got[t]} for t in want if got[t] != want[t]}
    dangling = {t: [r[0] for r in q(f'SELECT DISTINCT x.entry_id FROM {{s}}.{t} x LEFT JOIN {{s}}.documento d '
                                    f'USING (entry_id) WHERE d.entry_id IS NULL LIMIT 20')]
                for t in ('version', 'observacion', 'nom_nota', 'nom_relacion', 'tratado_nota')}
    unregistered = sorted({r[0] or '(sin fuente)' for r in q(
        'SELECT DISTINCT source_id FROM {s}.documento WHERE source_id IS NULL OR source_id NOT IN (SELECT source_id FROM {s}.fuente) '
        'UNION SELECT DISTINCT source_id FROM {s}.cobertura WHERE source_id IS NULL OR source_id NOT IN (SELECT source_id FROM {s}.fuente)')})
    report = {'schema_version': SCHEMA_VERSION, 'rows': in_db, 'lines': dict(on_disk), 'duplicated': duplicated,
              'missing_or_extra': sorted(s for s in set(in_db) | set(on_disk) if in_db.get(s) != on_disk.get(s)),
              'round_trip_differs': len(differ), 'round_trip_examples': differ[:20], 'derived': derived,
              'dangling': {t: ids for t, ids in dangling.items() if ids}, 'unregistered_sources': unregistered,
              'shrunk': {s: {'live': n, 'new': in_db.get(s, 0)} for s, n in sorted(before.items()) if in_db.get(s, 0) < n}}
    report['ok'] = not (report['missing_or_extra'] or duplicated or differ or derived or report['dangling'] or unregistered
                        or report['shrunk'])
    return report


def tls(url):
    """The TLS options RG imposes: verify-full against the pinned CA for any host but a local one. A URI that sets its own
    TLS options is refused, so none can weaken this (GPT on 358b5d8)."""
    from psycopg.conninfo import conninfo_to_dict
    params = conninfo_to_dict(url)
    own = sorted(k for k in params if k.startswith('ssl') or k in ('requiressl', 'gssencmode', 'hostaddr'))
    if own:  # hostaddr too: with it a host named local could connect anywhere without TLS
        raise ValueError(f'the connection URI sets options RG sets or refuses ({", ".join(own)})')
    hosts = str(params.get('host') or 'localhost').split(',')
    if all(h in LOCAL or h.startswith('/') for h in hosts):
        return {}
    if hashlib.sha256(CA.read_bytes()).hexdigest() != CA_SHA256:
        raise ValueError(f'{CA.name} is not the pinned Supabase root CA')
    return {'sslmode': 'verify-full', 'sslrootcert': str(CA)}


def connect(url, **kw):
    import psycopg
    return psycopg.connect(url, prepare_threshold=None, connect_timeout=30, **tls(url), **kw)  # the pooler's session mode


def scram(password, salt=None, iterations=4096):
    """The SCRAM-SHA-256 verifier Postgres stores (RFC 7677), made here so the password itself never reaches the server
    or its logs. password is ASCII (checked by its caller), so SASLprep leaves it as it is."""
    salt = salt or os.urandom(16)
    salted = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, iterations)
    stored = hashlib.sha256(hmac.new(salted, b'Client Key', 'sha256').digest()).digest()
    server = hmac.new(salted, b'Server Key', 'sha256').digest()
    b64 = lambda x: base64.b64encode(x).decode()
    return f'SCRAM-SHA-256${iterations}:{b64(salt)}${b64(stored)}:{b64(server)}'


def reader_role(conn, password, role=READER, live=LIVE):
    """Creates or updates the read-only role: it logs in and SELECTs the live schema; it owns nothing, creates nothing,
    belongs to no role, its sessions start read-only with a 60 s statement limit, at most 5 at once."""
    from psycopg import sql
    exists = conn.execute('SELECT 1 FROM pg_roles WHERE rolname = %s', (role,)).fetchone()
    R = sql.Identifier(role)
    conn.execute(sql.SQL(('ALTER' if exists else 'CREATE') + ' ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
                         'NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 5 PASSWORD {}').format(R, sql.Literal(scram(password))))
    for setting, value in (('default_transaction_read_only', 'on'), ('statement_timeout', '60s'), ('search_path', live)):
        conn.execute(sql.SQL('ALTER ROLE {} SET {} = {}').format(R, sql.Identifier(setting), sql.Literal(value)))
    if conn.execute('SELECT 1 FROM pg_namespace WHERE nspname = %s', (live,)).fetchone():
        conn.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(sql.Identifier(live), R))
        conn.execute(sql.SQL('GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}').format(sql.Identifier(live), R))
    conn.commit()


def reader_user(url, role=READER):
    """The reader's login: Supabase's pooler names users <role>.<project>, so it takes the project from RG_DB_URL's user."""
    from psycopg.conninfo import conninfo_to_dict
    user = str(conninfo_to_dict(url).get('user') or '')
    return role + user[user.index('.'):] if '.' in user else role


def reader_probe(admin, url, password, role=READER, live=LIVE, other='rg_sonda'):
    """The acceptance test of the role (ZPPMND, 2026-10-29), as the role itself: a SELECT of the live catalog works, an
    INSERT into it fails, a SELECT of another schema fails. Every result is printed; all three as expected or it fails."""
    import psycopg
    from psycopg import sql
    for stmt in ('DROP SCHEMA IF EXISTS {o} CASCADE', 'CREATE SCHEMA {o}', 'CREATE TABLE {o}.t(x int)', 'INSERT INTO {o}.t VALUES (1)'):
        admin.execute(sql.SQL(stmt).format(o=sql.Identifier(other)))
    admin.commit()
    got = {}
    try:
        with connect(url, user=reader_user(url, role), password=password, autocommit=True) as c:
            for name, schema, stmt in (('select_catalogo', live, 'SELECT count(*) FROM {}.documento'),
                                       ('insert_catalogo', live, "INSERT INTO {}.fuente(source_id, secondary) VALUES ('x', false)"),
                                       ('select_otro_schema', other, 'SELECT x FROM {}.t')):
                try:
                    c.execute(sql.SQL(stmt).format(sql.Identifier(schema)))
                    got[name] = 'ok'
                except psycopg.Error as e:
                    got[name] = f'refused ({type(e).__name__})'
    finally:
        admin.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(other)))
        admin.commit()
    ok = got.get('select_catalogo') == 'ok' and all(got.get(k, '').startswith('refused') for k in ('insert_catalogo', 'select_otro_schema'))
    return {'role': role, **got, 'ok': ok}


def main(argv=None):
    a = argparse.ArgumentParser(description='load the catalog rows into the database (RG_DB_URL), or check the connection')
    sub = a.add_subparsers(dest='cmd', required=True)
    load = sub.add_parser('cargar')
    load.add_argument('--catalog', required=True, help='the catalog root (the checkout of branch catalog)')
    load.add_argument('--country', default='mx')
    load.add_argument('--sources', required=True, help='sources/<cc>.json')
    sub.add_parser('ping')
    sub.add_parser('lector', help='create or update the read-only role (password: RG_LECTURA_PASSWORD) and test it as itself')
    x = a.parse_args(argv)
    url = os.environ.get('RG_DB_URL', '')
    if not url.startswith(('postgresql://', 'postgres://')):  # its value is never printed, only whether it has the form
        raise SystemExit('RG_DB_URL is not a postgresql:// connection URI (Supabase: Connect -> Session pooler)')
    try:
        tls(url)
    except ValueError as e:  # names only the options, never their values
        raise SystemExit(f'RG_DB_URL: {e}')
    except Exception as e:  # noqa: BLE001 - a URI the parser rejects; its message can quote the URI
        raise SystemExit(f'RG_DB_URL does not parse: {type(e).__name__}')
    password = os.environ.get('RG_LECTURA_PASSWORD', '')
    if x.cmd == 'lector' and not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', password):
        raise SystemExit('RG_LECTURA_PASSWORD must be 32 to 128 letters, digits, - or _ (openssl rand -hex 32)')
    try:
        conn = connect(url)
    except Exception as e:  # noqa: BLE001 - the message can name the host and user; only its kind is printed
        raise SystemExit(f'no connection to the database: {type(e).__name__}')
    with conn:
        if x.cmd == 'ping':
            version = conn.execute('SHOW server_version').fetchone()[0]
            live = conn.execute('SELECT value FROM catalogo.meta WHERE key = %s', ('report',)).fetchone() \
                if conn.execute('SELECT 1 FROM pg_namespace WHERE nspname = %s', (LIVE,)).fetchone() else None
            print(json.dumps({'connected': True, 'server_version': version,
                              'live_report_ok': json.loads(live[0])['ok'] if live else None}))
            return 0
        if x.cmd == 'lector':
            reader_role(conn, password)
            report = reader_probe(conn, url, password)
            print(json.dumps(report, ensure_ascii=False, indent=1))
            return 0 if report['ok'] else 3
        with open(x.sources, encoding='utf-8') as f:
            try:
                report = build(conn, x.catalog, x.country, json.load(f))
            except Empty as e:
                report = {'ok': False, 'empty': str(e)}
    print(json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True))
    return 0 if report['ok'] else 3  # 3, as a catalog run: live keeps the previous catalog, the rejected one stays


if __name__ == '__main__':
    sys.exit(main())
