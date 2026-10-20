"""Mutation check: every guard of the catalog must have a test that fails without it.

    python scripts/mutar.py            # from the repo root; writes nothing to the repo

Each mutant runs in its own throwaway copy with `git init` and NO remote (a mutant can never be pushed; incident
2026-10-11). The unmutated baseline must pass in such a copy first, or the run stops: a copy that cannot pass makes
every mutant look killed (2026-10-20, REGLAS 16b). The property test runs with fewer scenarios here
(RG_PROPERTY_SCENARIOS) to keep the run short; the full suite runs it in full.
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
MUT = [
 ('rg/catalog/run.py', "requeued, stuck = short_days(days, self.catalog.snapshot(src['source_id']), src['source_id'], self.today)", "requeued, stuck = [], []"),
 ('rg/catalog/run.py', "'notes': max(len(ids), sidof.count_listed(page), prev.get('notes', 0))", "'notes': len(ids)"),
 ('rg/catalog/run.py', "[date.fromisoformat(d) for d in requeued] + [g for g", "[] + [g for g"),
 ('rg/catalog/run.py', "key in days and key not in again and day", "key in days and day"),
 ('rg/catalog/run.py', "list(dict.fromkeys(prev.get('ids', []) + [it['native_id'] for it in items]))", "[it['native_id'] for it in items]"),
 ('rg/catalog/run.py', "for day in dict.fromkeys([date.fromisoformat(d) for d in requeued]", "for day in list([date.fromisoformat(d) for d in requeued]"),
 ('rg/catalog/run.py', "info.get('rereads', 0) >= MAX_REREADS", "info.get('rereads', 0) >= 10**9"),
 ('rg/catalog/run.py', "prev.get('rereads', 0) + 1 if key in again else 0", "0"),
 ('rg/catalog/run.py', "self._cover(src['source_id'], f'{key} fecha oficial'", "(lambda *a: None)(src['source_id'], f'{key} fecha oficial'"),
 ('rg/catalog/run.py', "or any(i not in have_ids for i in info['ids'])", ""),
 ('rg/catalog/run.py', "len(info['ids']) < info.get('notes', 0) or ", ""),
 ('rg/catalog/sidof.py', "'published': own or fallback", "'published': own"),
 ('rg/catalog/sidof.py', "values.get(input_id, ''))", "re.search(r'id=\"%s\"[^>]*' % input_id, page_html).group(0) if re.search(r'id=\"%s\"[^>]*' % input_id, page_html) else '')"),
 ('rg/catalog/fetch.py', "if parts.scheme != 'https' or", "if parts.scheme not in ('https', 'http') or"),
 ('rg/catalog/fetch.py', "elif r.status in (401, 403, 429):", "elif r.status in ():"),
 ('rg/catalog/fetch.py', "return self._robots_status.get(f'{parts.scheme}://{parts.netloc}') == 200 and not rp.can_fetch(USER_AGENT, url)", "return not rp.can_fetch(USER_AGENT, url)"),
 ('rg/catalog/fetch.py', "OSError, ValueError) as e:", "OSError) as e:"),
 ('rg/catalog/fetch.py', "if self.deadline is not None and self._clock() >= self.deadline:", "if False:"),
 ('rg/catalog/leyesbiblio.py', "is_regla = 'regley/' in ' '.join(text_links)", "is_regla = 'regley/' in ' '.join(text_links) or not re.fullmatch(r'\\d{3}', cells[0])"),
 ('rg/catalog/run.py', "[g for g in gaps if g.isoformat() not in days]\n", "[]\n"),
 ('rg/catalog/run.py', "self._cover(src['source_id'], key, None, 0)  # page not read", "None  # page not read"),
 ('rg/catalog/run.py', "fold(branch) in {fold(b) for b in src.get('metadata_only_branches', [])}", "branch in src.get('metadata_only_branches', [])"),
 ('rg/catalog/run.py', "in ('pending', 'failed', 'robots_disallowed')", "in ('pending', 'failed')"),
 ('rg/catalog/run.py', "if resp.status == 304 and not entry.get('raw_path'):", "if False:"),
 ('rg/catalog/run.py', "if d.status == 304 and not e.get('raw_path'):", "if False:"),
 ('rg/catalog/run.py', "if not incomplete:", "if True:"),
 ('rg/catalog/run.py', "if eid in previous and not validate('catalog_entry', previous[eid]):", "if False:"),
 ('rg/catalog/run.py', "                if not items:  # no real DOF day", "                if False:  # no real DOF day"),
 ('rg/catalog/sidof.py', "    if not p.tab_edition and len({i['pane'] for i in p.items}) == 1 and len(set(words)) == 1:", "    if False:"),
 ('rg/catalog/run.py', "ojn.count_ids(page), len({it['native_id'] for it in items}))\n                    stats['listings']", "len(items), len(items))\n                    stats['listings']"),
 ('rg/catalog/ojn.py', "        return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()", "        return f'{m.group(3)}-{m.group(2)}-{m.group(1)}'"),
 ('rg/catalog/run.py', "                del e['dates'][k]", "                pass"),
 ('schemas/catalog_entry.schema.json', '(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])', '[0-9]{2}-[0-9]{2}'),
 ('rg/catalog/run.py', "key=lambda e: (e['dates'].get('published') or '', e['native_id'])", "key=lambda e: (e['dates']['published'], e['native_id'])"),
 ('rg/catalog/run.py', "it['published'] or ((old or {}).get('dates') or {}).get('published')", "it['published']"),
 ('rg/catalog/run.py', "max(len(ids), sidof.count_listed(page), prev.get('notes', 0))", "max(len(ids), prev.get('notes', 0))"),
 ('rg/catalog/run.py', "short = info.get('notes', 0) == 0 or (", "short = False or ("),
 ('rg/catalog/run.py', "self._cover(src['source_id'], f'{d} notas debidas", "None and self._cover(src['source_id'], f'{d} notas debidas"),
 ('rg/catalog/run.py', "if today is not None and today.isoformat() >= info.get('retry_after', ''):", "if False:"),
 ('rg/catalog/run.py', "days[key]['retry_after'] = (self.today", "_ = (self.today"),
 ('rg/catalog/run.py', "etags.pop((row.get('artifact') or {}).get('url'), None)", "pass"),
 ('rg/catalog/run.py', ",\n                       deadline=self.deadline)", ")"),
 ('rg/catalog/run.py', "run.deadline = time.monotonic() + 60 * x.deadline_minutes", "pass"),
 ('rg/catalog/run.py', "return 4 if invalid else (3 if bad else 0)", "return 4 if invalid else 0"),
 ('rg/catalog/run.py', "    if x.bundle and run.raw.new_files:", "    if crashed:\n        return 1\n    if x.bundle and run.raw.new_files:"),
 ('rg/catalog/run.py', "ojn.count_ids(page), len({it['native_id'] for it in items}))\n                    stats['municipalities_listed']", "len(items), len(items))\n                    stats['municipalities_listed']"),
 ('rg/catalog/sidof.py', " and len(set(words)) == 1:", ":"),
 ('rg/catalog/sidof.py', "len({i['pane'] for i in p.items}) == 1 and ", ""),
 ('rg/catalog/sidof.py', "'published': own or fallback", "'published': fallback or own"),
 ('rg/catalog/store.py', "self.dir.mkdir(parents=True, exist_ok=True)  # a new", "pass  # a new"),
]


def suite(d):
    env = {**os.environ, 'RG_PROPERTY_SCENARIOS': '6'}
    return subprocess.run([PY, '-m', 'unittest', 'discover', '-s', 'tests', '-t', '.'], cwd=d, env=env,
                          capture_output=True, text=True)


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
    killed = suite(d).returncode != 0
    shutil.rmtree(d)
    return i, f, a, 'KILLED' if killed else 'ALIVE'


def main():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / 'base'
        copy(base)
        b = suite(base)
        if b.returncode != 0:
            sys.exit('baseline fails in the copy: ' + b.stderr[-600:])
        shutil.rmtree(base)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(mutant, [(i, m, tmp) for i, m in enumerate(MUT, 1)]))
    bad = 0
    for i, f, a, verdict in results:
        bad += verdict != 'KILLED'
        print(f'm{i:02d} {verdict:9s} {f}: {a.strip()[:70]}')
    print(f'{len(results) - bad}/{len(results)} killed')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
