"""Lead time of merged PRs (owner's order 1, 2026-11-03: "MEDIR PRIMERO"; no process change is declared a success
without this). Pure: it reads what `gh` printed and calls nothing (no key, no network; tests/test_llamada.py).

For each merged PR, from its comments, its commits and, if given, the check runs of the head it merged:
  total         opened -> merged
  antes_head    opened -> the merged head was committed (writing, earlier rounds, rebases)
  ci            the merged head's ci.yml runs (checks and mutation shards): first start -> last finish
  auditoria     merged head committed -> both PASS on that head (the gate's wait for `checks`, both audits)
  espera_ci     both PASS -> the merged head's CI finished, when it finished later (merge commands wait for all checks)
  espera_dueno  the later of both PASS and CI finished -> merged (the owner's merge, including order waits)
  revise        REVISE verdicts on any head, by auditor (Claude "AUDIT VERDICT", GPT "GPT REVIEW")
A verdict counts only from github-actions (auditor.yml posts them); a PASS counts only if it names the merged head.
A PR merged without both PASS on its head has no auditoria/espera_dueno and is listed in sin_dos_pass.

  gh pr list -R <repo> --state merged -L 30 --json number,createdAt,mergedAt,headRefOid,additions,deletions,comments,commits > prs.json
  for s in $(jq -r '.[].headRefOid' prs.json); do gh api "repos/<repo>/commits/$s/check-runs?per_page=100" > checks/$s.json; done
  python scripts/lead_time.py prs.json --checks checks
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
CI = re.compile(r'(checks|mutation \(\d+\))$')  # ci.yml's job names as check runs
SHA = re.compile(r'[0-9a-f]{40}')
COMPONENTES = ('total', 'antes_head', 'ci', 'auditoria', 'espera_ci', 'espera_dueno')


def _t(s):
    return datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)


def _h(a, b):
    return round((b - a).total_seconds() / 3600, 2)


def veredictos(comments):
    """(auditor, verdict, sha, time) of each verdict comment posted by github-actions; first line, exact form."""
    out = []
    for c in comments or ():
        if (c.get('author') or {}).get('login') not in AUTORES:
            continue
        m = VEREDICTO.match(str(c.get('body', '')).split('\n', 1)[0].rstrip('\r'))
        if m:
            out.append(('claude' if m.group(1) == 'AUDIT VERDICT' else 'gpt', m.group(2), m.group(3), _t(c['createdAt'])))
    return out


def ci_tramo(runs):
    """(first start, last finish) of the merged head's ci.yml jobs; None without a finished one."""
    rs = [r for r in runs or () if CI.match(str(r.get('name', ''))) and r.get('started_at') and r.get('completed_at')]
    if not rs:
        return None
    return min(_t(r['started_at']) for r in rs), max(_t(r['completed_at']) for r in rs)


def medir(pr, runs=None):
    head = pr['headRefOid']
    if not SHA.fullmatch(str(head)):
        raise ValueError(f"#{pr.get('number')}: head is not a sha")
    abierto, fusionado = _t(pr['createdAt']), _t(pr['mergedAt'])
    commits = [c for c in pr.get('commits') or () if c.get('oid') == head]
    head_t = _t(commits[-1]['committedDate']) if commits else None
    v = veredictos(pr.get('comments'))
    pas = {a: max((t for a2, ver, s, t in v if a2 == a and ver == 'PASS' and s == head), default=None) for a in ('claude', 'gpt')}
    dos = max(pas.values()) if all(pas.values()) else None
    ci = ci_tramo(runs)
    listo = max(dos, ci[1]) if dos and ci else dos  # merge commands are given once both PASS and every check finished
    return {
        'pr': pr['number'],
        'lineas': (pr.get('additions') or 0) + (pr.get('deletions') or 0),
        'total': _h(abierto, fusionado),
        'antes_head': _h(abierto, head_t) if head_t else None,
        'ci': _h(*ci) if ci else None,
        'auditoria': _h(head_t, dos) if head_t and dos else None,
        'espera_ci': _h(dos, listo) if dos and ci else None,
        'espera_dueno': _h(listo, fusionado) if listo else None,
        'revise': {a: sum(1 for a2, ver, _, _ in v if a2 == a and ver == 'REVISE') for a in ('claude', 'gpt')},
    }


def _p90(xs):
    xs = sorted(xs)
    return xs[max(0, -(-len(xs) * 9 // 10) - 1)]  # nearest rank


def resumen(filas):
    out = {'prs': len(filas), 'sin_dos_pass': [f['pr'] for f in filas if f['espera_dueno'] is None]}
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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('prs', type=Path)
    ap.add_argument('--checks', type=Path, help='folder with <head sha>.json from the check-runs API')
    a = ap.parse_args(argv)
    prs = json.loads(a.prs.read_text(encoding='utf-8'))
    filas = []
    for pr in prs:
        runs = None
        if a.checks is not None:
            f = a.checks / f"{pr['headRefOid']}.json"
            runs = json.loads(f.read_text(encoding='utf-8')).get('check_runs', []) if f.is_file() else None
        filas.append(medir(pr, runs))
    r = resumen(filas)
    fechas = sorted(pr['mergedAt'][:10] for pr in prs)
    print(json.dumps({'resumen': r, 'fila': fila_estado(r, fechas[0], fechas[-1]) if fechas else None, 'prs': filas},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
