"""Mutation check: every guard of the catalog must have a test that fails without it.

    python scripts/mutar.py            # from the repo root; writes nothing to the repo
    RG_SHARD=1/4 python scripts/mutar.py   # only mutants i with i % 4 == 1 (CI runs the 4 shards in parallel)

Each mutant runs in its own throwaway copy with `git init` and NO remote (a mutant can never be pushed; incident
2026-10-11). The unmutated baseline must pass in such a copy first, or the run stops: a copy that cannot pass makes
every mutant look killed (2026-10-20, REGLAS 16b). The property test runs with fewer scenarios here
(RG_PROPERTY_SCENARIOS) to keep the run short; the full suite runs it in full. A mutant's suite stops at its first
failing test (-f): the verdict is only "some test failed", so stopping there changes no verdict, only the time.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

R = Path(__file__).resolve().parents[1]
PY = sys.executable
# Sorted (file, anchor, replacement) and kept sorted by tests/test_mutar.py: each PR inserts its mutants in place
# instead of appending at the end, so parallel PRs stop colliding on the last line of this list (2026-10-21).
MUT = [
 ('.github/workflows/auditor.yml', '        with: { ref: main, fetch-depth: 0, persist-credentials: false }', "        with: { ref: '${{ needs.gate.outputs.sha }}', fetch-depth: 0, persist-credentials: false }"),
 ('.github/workflows/auditor.yml', "    concurrency: { group: 'auditor-gpt-${{ needs.gate.outputs.pr }}', cancel-in-progress: true }", "    concurrency: { group: 'auditor-gpt-${{ needs.gate.outputs.pr }}', cancel-in-progress: true }\n    env: { OPENAI_API_KEY: '${{ secrets.OPENAI_API_KEY }}' }"),
 ('.github/workflows/auditor.yml', '-f context=auditor-gpt -f description="GPT REVIEW: $verdict"', '-f context=auditor -f description="GPT REVIEW: $verdict"'),
 ('.github/workflows/auditor.yml', '= "GPT REVIEW: $verdict $SHA" ]', '= "AUDIT VERDICT: $verdict $SHA" ]'),
 ('.github/workflows/auditor.yml', """[ "$(grep -ci 'AUDIT VERDICT' verdict.md)" = 0 ] || { echo "the comment names an AUDIT VERDICT: not posted"; exit 1; }""", 'true'),
 ('.github/workflows/auditor.yml', 'if [ "$cross" != false ]; then', 'if false; then'),
 ('.github/workflows/auditor.yml', 'python3 -I scripts/auditor_gpt.py --inputs', 'python3 scripts/auditor_gpt.py --inputs'),
 ('.github/workflows/catalog-mx.yml', '          HF_TOKEN: ${{ secrets.HF_TOKEN }}', '          HF_TOKEN_UNUSED: ${{ secrets.HF_TOKEN }}'),
 ('.github/workflows/indicadores-mx.yml', "          INEGI_TOKEN: ${{ secrets.INEGI_TOKEN }}   # sent only", "          INEGI_TOKEN_UNUSED: ${{ secrets.INEGI_TOKEN }}   # sent only"),
 ('rg/catalog/fetch.py', '                hops += 1\n', '                pass\n'),
 ('rg/catalog/fetch.py', '            rp = _Robots()', '            rp = urllib.robotparser.RobotFileParser()'),
 ('rg/catalog/fetch.py', '        same.rulelines.extend(entry.rulelines)', '        pass'),
 ('rg/catalog/fetch.py', '(secret in url or any(secret in str(v)', '(any(secret in str(v)'),
 ('rg/catalog/fetch.py', 'OSError, ValueError) as e:', 'OSError) as e:'),
 ('rg/catalog/fetch.py', 'ROBOTS_MAX_REDIRECTS = 5  #', 'ROBOTS_MAX_REDIRECTS = 6  #'),
 ('rg/catalog/fetch.py', 'elif r.status in (401, 403, 429):', 'elif r.status in ():'),
 ('rg/catalog/fetch.py', 'if auth and parts.hostname == origin:', 'if auth:'),
 ('rg/catalog/fetch.py', 'if host != bound and (secret in url or any(secret in str(v) for v in headers.values())):', 'if False:'),
 ('rg/catalog/fetch.py', 'if not loc or hops >= ROBOTS_MAX_REDIRECTS:', 'if not loc:'),
 ('rg/catalog/fetch.py', "if parts.scheme != 'https' or", "if parts.scheme not in ('https', 'http') or"),
 ('rg/catalog/fetch.py', 'if self.deadline is not None and self._clock() >= self.deadline:', 'if False:'),
 ('rg/catalog/fetch.py', 'if sink.bytes + len(chunk) > sink.limit:', 'if False:'),
 ('rg/catalog/fetch.py', "loc = r.headers.get('location') if r.status in (301, 302, 303, 307, 308) else None", 'loc = None'),
 ('rg/catalog/fetch.py', "name, value = auth if isinstance(auth, tuple) else ('Authorization', auth)", "name, value = ('Authorization', auth)"),
 ('rg/catalog/fetch.py', "return self._robots_status.get(f'{parts.scheme}://{parts.netloc}') == 200 and not rp.can_fetch(USER_AGENT, url)", 'return not rp.can_fetch(USER_AGENT, url)'),
 ('rg/catalog/fetch.py', "self.robots_log[key] = {'url': url, 'status': r.status, 'redirects': hops}", 'pass'),
 ('rg/catalog/fetch.py', 'sink.reset()  # a retry', 'pass  # a retry'),
 ('rg/catalog/fetch.py', 'url = self._check_url(urljoin(url, loc)).geturl()', 'url = urljoin(url, loc)'),
 ('rg/catalog/hf_tesis.py', '        return date(int(m.group(3)), month, int(m.group(1))).isoformat()', "        return f'{m.group(3)}-{month:02d}-{m.group(1)}'"),
 ('rg/catalog/hf_tesis.py', "    if r.peek() != '':\n        raise", "    if False:\n        raise"),
 ('rg/catalog/hf_tesis.py', "TIPO_TYPES.get(fold(tipo_printed or ''), 'OTRO')", "TIPO_TYPES.get(tipo_printed or '', 'OTRO')"),
 ('rg/catalog/hf_tesis.py', 'if (end < len(self.buf) and self.buf[end] in _DELIMITERS) or self.eof:', 'if end < len(self.buf) or self.eof:'),
 ('rg/catalog/hf_tesis.py', 'if len(self.buf) - self.pos > self.max_value:', 'if False:'),
 ('rg/catalog/hf_tesis.py', 'if license_ != license_id:', 'if False:'),
 ('rg/catalog/hf_tesis.py', "return re.sub(r'\\?\\S*', '?<redacted>', text)", 'return text'),
 ('rg/catalog/indicadores.py', "    if s.get('INDICADOR') != series_id:", '    if False:'),
 ('rg/catalog/indicadores.py', "    if s.get('idSerie') != series_id:", '    if False:'),
 ('rg/catalog/indicadores.py', "_TOKEN = re.compile(r'[A-Za-z0-9-]{16,128}')", "_TOKEN = re.compile(r'.{1,256}')"),
 ('rg/catalog/indicadores.py', "isinstance(c, dict) and c.get('value') == series_id]", 'isinstance(c, dict)]'),
 ('rg/catalog/indicadores.py', 'json.loads(body, parse_float=str, parse_int=str)', 'json.loads(body)'),
 ('rg/catalog/indicadores.py', "rb'\"\\s*:', body))", "rb'', body))"),
 ('rg/catalog/indicadores.py', 'return text.replace(secret, TOKEN_SLOT) if secret else text', 'return text'),
 ('rg/catalog/indicadores.py', 'tpl.format(**kw, token=TOKEN_SLOT)', "tpl.format(**kw, token=quote(token, safe=''))"),
 ('rg/catalog/leyesbiblio.py', "is_regla = 'regley/' in ' '.join(text_links)", "is_regla = 'regley/' in ' '.join(text_links) or not re.fullmatch(r'\\d{3}', cells[0])"),
 ('rg/catalog/normas.py', "        issuer = re.sub(r'\\s+', '', issuer)", '        pass'),
 ('rg/catalog/normas.py', '((?:[A-Z0-9]+\\s*[-/]\\s*)*?[A-Z0-9]+)', '([A-Z0-9]+)'),
 ('rg/catalog/normas.py', '(\\d{2,3}(?:/\\d+)?)\\s*-\\s*(', '(\\d{2,3})-('),
 ('rg/catalog/normas.py', 'best = max((p for p in STAGES if t.startswith(p)), key=len, default=None)', 'best = min((p for p in STAGES if t.startswith(p)), key=len, default=None)'),
 ('rg/catalog/normas.py', "if LOOKS_LIKE.search(fold(e['title'])) and not codes(e['title'])", 'if False'),
 ('rg/catalog/normas.py', 'if lineage == subject and ed == edition:', 'if lineage == subject:'),
 ('rg/catalog/normas.py', "kind = 'cancela' if 'CANCELA' in t[:pos] else 'menciona'", "kind = 'menciona'"),
 ('rg/catalog/normas.py', "{int(head):03d}{'/' + sub if sub else ''}", '{head}'),
 ('rg/catalog/ojn.py', '        return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()', "        return f'{m.group(3)}-{m.group(2)}-{m.group(1)}'"),
 ('rg/catalog/run.py', "                        entry['date_source'] = source\n", '                        pass\n'),
 ('rg/catalog/run.py', "                del e['dates'][k]", '                pass'),
 ('rg/catalog/run.py', '                if not items:  # no real DOF day', '                if False:  # no real DOF day'),
 ('rg/catalog/run.py', "            if s['id'] not in done:", '            if False:'),
 ('rg/catalog/run.py', "        if 'ids' not in info:\n            short = True", "        if 'ids' not in info:\n            short = False"),
 ('rg/catalog/run.py', '        if not token:\n', '        if False:\n'),
 ('rg/catalog/run.py', '        if token.encode() in r.body:', '        if False:'),
 ('rg/catalog/run.py', "        self.manifest['errors'].append(indicadores.redact(f'{sid}: {text}', token)[:400])",
  "        self.manifest['errors'].append(f'{sid}: {text}'[:400])"),
 ('rg/catalog/run.py', '    if x.bundle and run.raw.new_files:', '    if crashed:\n        return 1\n    if x.bundle and run.raw.new_files:'),
 ('rg/catalog/run.py', '    manifest = redact_secrets(manifest, secrets_in_env(run.registry))', '    pass'),
 ('rg/catalog/run.py', "'ok': not missed,", "'ok': True,"),
 ('rg/catalog/run.py', "(s['status'] == 'active' or (s['status'] == 'trial' and only))", "(s['status'] in ('active', 'trial'))"),
 ('rg/catalog/run.py', ',\n                       deadline=self.deadline)', ')'),
 ('rg/catalog/run.py', '[date.fromisoformat(d) for d in requeued] + [g for g', '[] + [g for g'),
 ('rg/catalog/run.py', '[g for g in gaps if g.isoformat() not in days]\n', '[]\n'),
 ('rg/catalog/run.py', "days[key]['retry_after'] = (self.today", '_ = (self.today'),
 ('rg/catalog/run.py', "days[key]['withdrawn'] = prev['withdrawn']", 'pass'),
 ('rg/catalog/run.py', "declared if isinstance(declared, int) else None, stats['rows_read'] if complete else None)", "stats['rows_read'], stats['rows_read'])"),
 ('rg/catalog/run.py', "dict.fromkeys(prev.get('ids', []) + sidof.listed_ids", 'dict.fromkeys(sidof.listed_ids'),
 ('rg/catalog/run.py', "e['category']['doc_type'] = hf_tesis.doc_type(e.get('listing', {}).get('type_printed'))", 'pass'),
 ('rg/catalog/run.py', "e['dates'].get('published') or '', e['native_id']\n\n\ndef host_groups", "e['dates']['published'], e['native_id']\n\n\ndef host_groups"),
 ('rg/catalog/run.py', "etags.pop((row.get('artifact') or {}).get('url'), None)", 'pass'),
 ('rg/catalog/run.py', "f = self._fetcher(src, secrets={token: src['token_host']})", 'f = self._fetcher(src)'),
 ('rg/catalog/run.py', "fold(branch) in {fold(b) for b in src.get('metadata_only_branches', [])}", "branch in src.get('metadata_only_branches', [])"),
 ('rg/catalog/run.py', 'for d in sorted(set(owed) | set(stuck)):', 'for d in []:'),
 ('rg/catalog/run.py', 'for day in dict.fromkeys([date.fromisoformat(d) for d in requeued]', 'for day in list([date.fromisoformat(d) for d in requeued]'),
 ('rg/catalog/run.py', "i not in have or not have[i].get('date_source')", "i in have and not have[i].get('date_source')"),
 ('rg/catalog/run.py', 'if complete:  # a file read only in part', 'if True:  # a file read only in part'),
 ('rg/catalog/run.py', "if d.status == 304 and not e.get('raw_path'):", 'if False:'),
 ('rg/catalog/run.py', "if eid in previous and not validate('catalog_entry', previous[eid]):", 'if False:'),
 ('rg/catalog/run.py', 'if i not in withdrawn)', 'if True)'),
 ('rg/catalog/run.py', 'if not incomplete:', 'if True:'),
 ('rg/catalog/run.py', "if not published and old and old.get('date_source'):", 'if not published and old:'),
 ('rg/catalog/run.py', 'if not stored or not served or not title or unit is None:', 'if not stored or not served or not title:'),
 ('rg/catalog/run.py', 'if not stored or not served or not title or unit is None:', 'if not stored or not title or unit is None:'),
 ('rg/catalog/run.py', "if old and all(old.get(k) == e[k] for k in ('observation', 'title', 'listing')):", 'if False:'),
 ('rg/catalog/run.py', "if resp.status == 304 and not entry.get('raw_path'):", 'if False:'),
 ('rg/catalog/run.py', "if s['status'] not in ('active', 'trial')}", "if s['status'] != 'active'}"),
 ('rg/catalog/run.py', "if st.get('sha256') == meta['sha256'] and st.get('distinct') == catalogued():", "if st.get('sha256') == meta['sha256']:"),
 ('rg/catalog/run.py', "if today is not None and today.isoformat() >= info.get('retry_after', ''):", 'if False:'),
 ('rg/catalog/run.py', "in ('pending', 'failed', 'robots_disallowed')", "in ('pending', 'failed')"),
 ('rg/catalog/run.py', "info.get('rereads', 0) >= MAX_REREADS", "info.get('rereads', 0) >= 10**9"),
 ('rg/catalog/run.py', 'key in days and key not in again and day', 'key in days and day'),
 ('rg/catalog/run.py', "ojn.count_ids(page), len({it['native_id'] for it in items}))\n                    stats['listings']", "len(items), len(items))\n                    stats['listings']"),
 ('rg/catalog/run.py', "ojn.count_ids(page), len({it['native_id'] for it in items}))\n                    stats['municipalities_listed']", "len(items), len(items))\n                    stats['municipalities_listed']"),
 ('rg/catalog/run.py', "or not have[i].get('date_source') for i", 'or False for i'),
 ('rg/catalog/run.py', "prev.get('ids', []) + sidof.listed_ids(page) + [it", "prev.get('ids', []) + [it"),
 ('rg/catalog/run.py', "prev.get('rereads', 0) + 1 if key in again else 0", '0'),
 ('rg/catalog/run.py', "requeued, stuck = short_days(days, self.catalog.snapshot(src['source_id']), src['source_id'], self.today)", 'requeued, stuck = [], []'),
 ('rg/catalog/run.py', 'return 4 if invalid else (3 if bad else 0)', 'return 4 if invalid else 0'),
 ('rg/catalog/run.py', "return normas.cites_nom(e.get('title') or ''), e['dates']", "return False, e['dates']"),
 ('rg/catalog/run.py', "robots_log=self.manifest['robots'], secrets=secrets,", 'secrets=secrets,'),
 ('rg/catalog/run.py', 'run.deadline = time.monotonic() + 60 * x.deadline_minutes', 'pass'),
 ('rg/catalog/run.py', 'self._cover(sid, scope, served, stored_n)', 'self._cover(sid, scope, served, served)'),
 ('rg/catalog/run.py', "self._cover(src['source_id'], f'{key} fecha oficial'", "(lambda *a: None)(src['source_id'], f'{key} fecha oficial'"),
 ('rg/catalog/run.py', "self._cover(src['source_id'], key, None, 0)  # page not read", 'None  # page not read'),
 ('rg/catalog/run.py', "served = indicadores.served_count(r.body, date_key) if stored else 0", 'served = len(observations) if stored else 0'),
 ('rg/catalog/run.py', "sink.bytes != meta['size'] or sink.sha256 != meta['sha256']:", "sink.bytes != meta['size']:"),
 ('rg/catalog/run.py', "st['total_points'], st['rows_read'])", "st['rows_read'], st['rows_read'])"),
 ('rg/catalog/run.py', "stats['source_repeated_rows'] += 1\n                        continue", "stats['source_repeated_rows'] += 1"),
 ('rg/catalog/run.py', 'tratados.derive(run.catalog.dir, run.catalog.snapshot(), manifest)', 'None'),
 ('rg/catalog/run.py', "withdrawn = set(info.get('withdrawn') or [])", "withdrawn = set(info.get('withdrawn', []))"),
 ('rg/catalog/sidof.py', '        return date(int(y), int(m), int(d)).isoformat()', "        return f'{y}-{m}-{d}'"),
 ('rg/catalog/sidof.py', "    if not p.tab_edition and len({i['pane'] for i in p.items}) == 1 and len(set(words)) == 1:", '    if False:'),
 ('rg/catalog/sidof.py', ' and len(set(words)) == 1:', ':'),
 ('rg/catalog/sidof.py', "'published': own or fallback", "'published': fallback or own"),
 ('rg/catalog/sidof.py', "'published': own or fallback", "'published': own"),
 ('rg/catalog/sidof.py', "len({i['pane'] for i in p.items}) == 1 and ", ''),
 ('rg/catalog/sidof.py', "values.get(input_id, ''))", 're.search(r\'id="%s"[^>]*\' % input_id, page_html).group(0) if re.search(r\'id="%s"[^>]*\' % input_id, page_html) else \'\')'),
 ('rg/catalog/store.py', "        if 'observation' in entry:", '        if False:'),
 ('rg/catalog/store.py', ' if f.relative_to(d).parts[0] not in DERIVED]', ']'),
 ('rg/catalog/store.py', "DERIVED = ('normas', 'tratados')", 'DERIVED = ()'),
 ('rg/catalog/store.py', "if entry['source_id'].endswith('.hf-tesis-scjn'):", 'if False:'),
 ('rg/catalog/store.py', 'self.dir.mkdir(parents=True, exist_ok=True)  # a new', 'pass  # a new'),
 ('rg/catalog/tratados.py', '        if cut is None:', '        if False:'),
 ('rg/catalog/tratados.py', "'ok': not missed,", "'ok': True,"),
 ('rg/catalog/tratados.py', "(name[:m.start()] if m else name).rstrip(' .')", '(name[:m.start()] if m else name)'),
 ('rg/catalog/tratados.py', '_OPENINGS = sorted(STAGES, key=len, reverse=True)', '_OPENINGS = sorted(STAGES, key=len)'),
 ('rg/catalog/tratados.py', "if art is None or rest[len(art) + 1:].split(' ', 1)[0].rstrip(',.') not in INSTRUMENTS:", 'if art is None:'),
 ('rg/catalog/tratados.py', "if bool(LOOKS_LIKE.search(fold(e['title']))) != (classify(e['title']) is not None))", 'if False)'),
 ('rg/catalog/tratados.py', "if bool(LOOKS_LIKE.search(fold(e['title']))) != (classify(e['title']) is not None))",
  "if LOOKS_LIKE.search(fold(e['title'])) and classify(e['title']) is None)"),
 ('rg/catalog/tratados.py', 'm = CLAUSE.search(name)', 'm = None'),
 ('rg/catalog/tratados.py', "rec = out.setdefault(fold(name),", 'rec = out.setdefault(name,'),
 ('rg/catalog/tratados.py', "rec['notes'].sort(key=lambda n: (n['published'] or '', n['entry_id']))", 'pass'),
 ('rg/catalog/tratados.py', "return [e for e in entries if e['source_id'] == SOURCE]", 'return list(entries)'),
 ('rg/catalog/tratados.py', "|, ?(?:ADOPTAD|FIRMAD|HECH|SUSCRIT)[OA]S? (?:EN|EL|POR)\\b)')", ")')"),
 ('rg/index.py', '        for f in row_files(d):', "        for f in sorted(Path(d).rglob('*.jsonl')):"),
 ('rg/schemas.py', '        if printed is not None and fold(printed) not in quote:', '        if False:'),
 ('rg/schemas.py', "    if ev['before_ref'] == ev['after_ref']:", '    if False:'),
 ('rg/schemas.py', "    if ev['entry_id'].split(':', 1)[0] != ev['source_id']:", '    if False:'),
 ('rg/schemas.py', "    if ev['provenance']['sha256'] != ev['after_ref']:", '    if False:'),
 ('rg/schemas.py', "    if evid and evid['raw_sha256'] != ev['after_ref']:", '    if False:'),
 ('rg/schemas.py', "    if rel['from'] == rel['to']:", '    if False:'),
 ('rg/schemas.py', "_packet_references, 'change_event': _change_event_checks, 'relation': _relation_checks}", '_packet_references}'),
 ('schemas/catalog_entry.schema.json', '"pattern": "^[0-9]{1,4}(/[0-9]{1,4}){0,2}$"', '"minLength": 1'),
 ('schemas/catalog_entry.schema.json', '(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])', '[0-9]{2}-[0-9]{2}'),
 ('schemas/change_event.schema.json', '"additionalProperties": false,\n  "required": ["source_id"', '"additionalProperties": true,\n  "required": ["source_id"'),
 ('schemas/change_event.schema.json', '"status": { "const": "CANDIDATE" }', '"status": { "type": "string" }'),
 ('schemas/change_event.schema.json', '"then": { "required": ["effective_at_evidence"] },', '"then": true,'),
 ('schemas/relation.schema.json', '"maxProperties": 1,', '"maxProperties": 2,'),
 ('schemas/relation.schema.json', '"status": { "const": "CANDIDATE" }', '"status": { "type": "string" }'),
 ('scripts/auditor_gpt.py', "        'max_output_tokens': MAX_OUTPUT_TOKENS,\n", ''),
 ('scripts/auditor_gpt.py', "        'store': False,\n", "        'store': True,\n"),
 ('scripts/auditor_gpt.py', '        if tail and size > 4 * cap:', '        if False:'),
 ('scripts/auditor_gpt.py', '        text = text[-cap:] if tail else text[:cap]', '        pass'),
 ('scripts/auditor_gpt.py', "    body = re.sub(r'(?i)audit\\s+verdict', 'AUDIT-VERDICT', body)\n", ''),
 ('scripts/auditor_gpt.py', '    cut = size > len(raw) or len(text) > cap', '    cut = False'),
 ('scripts/auditor_gpt.py', "    if answer.get('verdict') not in ('PASS', 'REVISE'):", '    if False:'),
 ('scripts/auditor_gpt.py', "    if answer['head_sha'] != sha:", '    if False:'),
 ('scripts/auditor_gpt.py', '    if looks_like_credential(body):', '    if False:'),
 ('scripts/auditor_gpt.py', '    if not MODEL_RE.fullmatch(model):', '    if False:'),
 ('scripts/auditor_gpt.py', "    if not complete:\n        verdict = 'REVISE'", "    if False:\n        verdict = 'REVISE'"),
 ('scripts/auditor_gpt.py', '    if not key:\n', '    if False:\n'),
 ('scripts/auditor_gpt.py', '    if not model:\n        return skipped', '    if False:\n        return skipped'),
 ('scripts/auditor_gpt.py', "    if not quote or answer['criteria_quote'] != quote:", '    if False:'),
 ('scripts/auditor_gpt.py', "    if re.search(r'(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}', text):", '    if False:'),
 ('scripts/auditor_gpt.py', "    if resp.get('status') != 'completed':", '    if False:'),
 ('scripts/auditor_gpt.py', '    if set(answer) != set(FIELDS):', '    if False:'),
 ('scripts/auditor_gpt.py', '    log_usage(model, resp, len(text), complete)\n', '    pass\n'),
 ('scripts/auditor_gpt.py', '    nonce = secrets.token_hex(8)', "    nonce = '0' * 16"),
 ('scripts/auditor_gpt.py', "PREFIX = 'GPT REVIEW: '", "PREFIX = 'GPT AUDIT VERDICT: '"),
 ('scripts/auditor_gpt.py', 'if _entropy(run) > 4.2 or', 'if _entropy(run) > 99 or'),
 ('scripts/auditor_gpt.py', 'if p.is_symlink() or not p.is_file() or not p.resolve().is_relative_to(root.resolve()):', 'if not p.is_file():'),
]


def shard(items, spec):
    """(i, item) pairs of this shard, numbered from 1; 'k/n' keeps i % n == k, so the n shards partition the list."""
    k, n = (int(x) for x in spec.split('/'))
    if not 0 <= k < n:
        raise ValueError(f'RG_SHARD must be k/n with 0 <= k < n, got {spec!r}')
    return [(i, m) for i, m in enumerate(items, 1) if i % n == k]


def suite(d, failfast=False):
    env = {**os.environ, 'RG_PROPERTY_SCENARIOS': '4'}
    try:  # a mutant that hangs the suite is detected, not waited on until the job limit
        return subprocess.run([PY, '-m', 'unittest', 'discover', '-s', 'tests', '-t', '.'] + ['-f'] * failfast, cwd=d, env=env,
                              capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess([], 124, '', 'timeout')


def copy(d):
    shutil.copytree(R, d, ignore=shutil.ignore_patterns('.git', 'work', '.venv', 'node_modules', '__pycache__'))
    subprocess.run(['git', 'init', '-q'], cwd=d, check=True)
    subprocess.run(['git', 'add', '-A'], cwd=d, check=True)


def mutant(args):
    i, (f, a, b), tmp = args
    d = Path(tmp) / f'm{i}'
    copy(d)
    p = d / f
    s = p.read_text(encoding='utf-8')
    if s.count(a) != 1:
        return i, f, a, 'NOT FOUND'
    p.write_text(s.replace(a, b), encoding='utf-8')
    killed = suite(d, failfast=True).returncode != 0
    shutil.rmtree(d)
    return i, f, a, 'KILLED' if killed else 'ALIVE'


def main():
    mine = shard(MUT, os.environ.get('RG_SHARD') or '0/1')
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / 'base'
        copy(base)
        b = suite(base)
        if b.returncode != 0:
            sys.exit('baseline fails in the copy: ' + b.stderr[-600:])
        shutil.rmtree(base)
        with ThreadPoolExecutor(max_workers=max(1, os.cpu_count() or 1)) as pool:  # one suite per core
            results = list(pool.map(mutant, [(i, m, tmp) for i, m in mine]))
    bad = 0
    for i, f, a, verdict in results:
        bad += verdict != 'KILLED'
        print(f'm{i:02d} {verdict:9s} {f}: {a.strip()[:70]}')
    print(f'{len(results) - bad}/{len(results)} killed')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
