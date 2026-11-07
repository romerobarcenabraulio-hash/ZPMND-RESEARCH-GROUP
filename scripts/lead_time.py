"""Lead time of merged PRs (owner's order 1, 2026-11-03: "MEDIR PRIMERO"; no process change is declared a success
without this). Pure: it reads what `gh` printed and calls nothing (no key, no network; tests/test_llamada.py).

For each merged PR, from its comments, its commits and the check runs of the head it merged, as they stood at the merge
(a verdict, a run or a re-run after the merge does not count):
  total         opened -> merged
  antes_head    opened -> the merged head was committed (writing, earlier rounds, rebases); 0 if the head is older
  ci            the merged head's ci.yml jobs (`checks` and every `mutation (k)` shard): first start -> last finish
  auditoria     the head was up for review (committed, not before the PR opened) -> both PASS on that head
  espera_ci     both PASS -> CI finished, when it finished later (merge commands wait for every check)
  espera_dueno  the later of both PASS and CI finished -> merged (the owner's merge, including order waits)
  revise        REVISE verdicts before the merge, by auditor (Claude "AUDIT VERDICT", GPT "GPT REVIEW")
A verdict counts only from github-actions (auditor.yml posts them), in its exact first-line form; a PASS counts only if
it names the merged head. A CI is complete only with `checks` and shards 0..n-1 of `mutation`, each one's last run
before the merge finished before the merge; otherwise the PR is listed in ci_incompleto and has no ci, espera_ci nor
espera_dueno (never a partial CI counted as whole). A PR merged without both PASS on its head is listed in sin_dos_pass.

Data (docs/medicion/: the input, trimmed by --recortar to what is read here, with its capture time and commands):
  gh pr list -R <repo> --state merged -L 30 --json number,createdAt,mergedAt,headRefOid,additions,deletions,comments,commits > prs.json
  for s in $(jq -r '.[].headRefOid' prs.json); do gh api "repos/<repo>/commits/$s/check-runs?per_page=100" > checks/$s.json; done
  python scripts/lead_time.py prs.json --checks checks --recortar docs/medicion/lead-time-<date>.json --capturado <UTC time>
  python scripts/lead_time.py docs/medicion/lead-time-<date>.json
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

AUTORES = ('github-actions', 'github-actions[bot]')
VEREDICTO = re.compile(r'(AUDIT VERDICT|GPT REVIEW): (PASS|REVISE) ([0-9a-f]{40})$')
CI = re.compile(r'checks$|mutation \((\d+)\)$')  # ci.yml's job names as check runs
SHA = re.compile(r'[0-9a-f]{40}')
COMPONENTES = ('total', 'antes_head', 'ci', 'auditoria', 'espera_ci', 'espera_dueno')
COMANDOS = [x.strip() for x in __doc__.split('Data (')[1].split('\n', 1)[1].strip().splitlines()]


def _t(s):
    return datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)


def _h(a, b):
    return round((b - a).total_seconds() / 3600, 2)


def veredictos(comments, hasta):
    """(auditor, verdict, sha, time) of each verdict github-actions posted up to `hasta`; first line, exact form."""
    out = []
    for c in comments or ():
        if (c.get('author') or {}).get('login') not in AUTORES:
            continue
        m = VEREDICTO.match(str(c.get('body', '')).split('\n', 1)[0].rstrip('\r'))
        if m and _t(c['createdAt']) <= hasta:
            out.append(('claude' if m.group(1) == 'AUDIT VERDICT' else 'gpt', m.group(2), m.group(3), _t(c['createdAt'])))
    return out


def ci_tramo(runs, hasta):
    """(first start, last finish) of the head's ci.yml jobs as they stood at `hasta`, or None if not complete then."""
    ultimo = {}
    for r in runs or ():
        nombre = str(r.get('name', ''))
        if not CI.fullmatch(nombre) or not r.get('started_at') or _t(r['started_at']) > hasta:
            continue
        clave = (_t(r['started_at']), r.get('id') or 0)
        if nombre not in ultimo or clave > ultimo[nombre][0]:
            ultimo[nombre] = (clave, r)  # a re-run replaces the run it repeats
    shards = sorted(int(CI.fullmatch(n).group(1)) for n in ultimo if n != 'checks')
    if 'checks' not in ultimo or not shards or shards != list(range(len(shards))):
        return None
    fines = []
    for _, r in ultimo.values():
        if r.get('status') != 'completed' or not r.get('completed_at') or _t(r['completed_at']) > hasta:
            return None
        fines.append(_t(r['completed_at']))
    return min(k[0] for k, _ in ultimo.values()), max(fines)


def medir(pr, runs):
    head = pr['headRefOid']
    if not SHA.fullmatch(str(head)):
        raise ValueError(f"#{pr.get('number')}: head is not a sha")
    abierto, fusionado = _t(pr['createdAt']), _t(pr['mergedAt'])
    commits = [c for c in pr.get('commits') or () if c.get('oid') == head]
    head_t = min(max(_t(commits[-1]['committedDate']), abierto), fusionado) if commits else None  # up for review
    v = veredictos(pr.get('comments'), fusionado)
    pas = {a: max((t for a2, ver, s, t in v if a2 == a and ver == 'PASS' and s == head), default=None) for a in ('claude', 'gpt')}
    dos = max(pas.values()) if all(pas.values()) else None
    ci = ci_tramo(runs, fusionado)
    listo = max(dos, ci[1]) if dos and ci else None  # merge commands are given once both PASS and every check finished
    return {
        'pr': pr['number'],
        'lineas': (pr.get('additions') or 0) + (pr.get('deletions') or 0),
        'total': _h(abierto, fusionado),
        'antes_head': _h(abierto, head_t) if head_t else None,
        'ci': _h(*ci) if ci else None,
        'auditoria': _h(head_t, dos) if head_t and dos and dos >= head_t else None,
        'espera_ci': _h(dos, listo) if listo else None,
        'espera_dueno': _h(listo, fusionado) if listo else None,
        'revise': {a: sum(1 for a2, ver, _, _ in v if a2 == a and ver == 'REVISE') for a in ('claude', 'gpt')},
        'dos_pass': bool(dos),
        'ci_completo': bool(ci),
    }


def _p90(xs):
    xs = sorted(xs)
    return xs[max(0, -(-len(xs) * 9 // 10) - 1)]  # nearest rank


def resumen(filas):
    out = {'prs': len(filas), 'sin_dos_pass': [f['pr'] for f in filas if not f['dos_pass']],
           'ci_incompleto': [f['pr'] for f in filas if not f['ci_completo']]}
    for k in COMPONENTES:
        xs = [f[k] for f in filas if f[k] is not None]
        out[k] = {'n': len(xs), 'mediana': round(median(xs), 1), 'p90': round(_p90(xs), 1)} if xs else {'n': 0}
    rv = [f['revise']['claude'] + f['revise']['gpt'] for f in filas]
    out['revise'] = {'total': sum(rv), 'mediana': median(rv) if rv else 0, 'prs_con_2_o_mas': sum(1 for x in rv if x >= 2)}
    return out


def fila_estado(r, desde, hasta):
    """One line for docs/ESTADO.md: medians (p90) in hours."""
    c = lambda k: f"{r[k]['mediana']} ({r[k]['p90']})" if r[k].get('n') else 's/d'
    return (f"| {desde} → {hasta} | {r['prs']} | {c('total')} | {c('antes_head')} | {c('ci')} | {c('auditoria')} | "
            f"{c('espera_ci')} | {c('espera_dueno')} | {r['revise']['total']} ({r['revise']['prs_con_2_o_mas']} PR con 2+) |")


def recortar(prs, runs, capturado):
    """What medir reads, and nothing else: the data file docs/ESTADO.md's figures are recomputed from (tests)."""
    _t(capturado)
    out = []
    for pr in prs:
        out.append({k: pr[k] for k in ('number', 'createdAt', 'mergedAt', 'headRefOid', 'additions', 'deletions')} | {
            'commits': [{'oid': c.get('oid'), 'committedDate': c.get('committedDate')} for c in pr.get('commits') or ()],
            'comments': [{'author': {'login': (c.get('author') or {}).get('login')}, 'createdAt': c.get('createdAt'),
                          'body': str(c.get('body', '')).split('\n', 1)[0][:200]} for c in pr.get('comments') or ()],
            'check_runs': [{k: r.get(k) for k in ('id', 'name', 'status', 'started_at', 'completed_at')}
                           for r in runs[pr['headRefOid']]]})
    return {'capturado': capturado, 'comandos': COMANDOS, 'prs': out}


def calcular(prs, runs):
    filas = [medir(pr, runs[pr['headRefOid']]) for pr in prs]
    r = resumen(filas)
    fechas = sorted(pr['mergedAt'][:10] for pr in prs)
    return {'resumen': r, 'fila': fila_estado(r, fechas[0], fechas[-1]) if fechas else None, 'prs': filas}


def leer(ruta, checks=None):
    """(prs, runs by head) from gh's output plus a check-runs folder, or from a trimmed data file."""
    datos = json.loads(Path(ruta).read_text(encoding='utf-8'))
    if isinstance(datos, dict):
        return datos['prs'], {pr['headRefOid']: pr['check_runs'] for pr in datos['prs']}
    if checks is None:
        raise SystemExit('gh output needs --checks with one <head sha>.json per PR')
    faltan = [pr['headRefOid'] for pr in datos if not (Path(checks) / f"{pr['headRefOid']}.json").is_file()]
    if faltan:
        raise SystemExit(f'missing check runs for {len(faltan)} heads: {" ".join(faltan)}')
    runs = {pr['headRefOid']: json.loads((Path(checks) / f"{pr['headRefOid']}.json").read_text(encoding='utf-8'))['check_runs']
            for pr in datos}
    return datos, runs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('prs', type=Path)
    ap.add_argument('--checks', type=Path, help='folder with <head sha>.json from the check-runs API')
    ap.add_argument('--recortar', type=Path, help='also write the trimmed data file here')
    ap.add_argument('--capturado', help='UTC time the data was fetched, YYYY-MM-DDTHH:MM:SSZ (with --recortar)')
    a = ap.parse_args(argv)
    prs, runs = leer(a.prs, a.checks)
    if a.recortar:
        if not a.capturado:
            raise SystemExit('--recortar needs --capturado')
        a.recortar.write_text(json.dumps(recortar(prs, runs, a.capturado), ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps(calcular(prs, runs), ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
