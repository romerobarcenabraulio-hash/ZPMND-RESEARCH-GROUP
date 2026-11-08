"""Lead time of merged PRs (owner's order 1, 2026-11-03: "MEDIR PRIMERO"; no process change is declared a success
without this). Pure: it reads what `gh` printed and calls nothing (no key, no network; tests/test_llamada.py).

Each column and every rule of what counts: docs/medicion/README.md.

Data (docs/medicion/: the input, trimmed by --recortar to what is read here, with its capture time and commands):
  gh pr list -R <repo> --state merged -L 1000 --json number, then for each: gh pr view <n> --json number,createdAt,mergedAt,
    headRefOid,additions,deletions,comments,commits -> prs.json (the list of all of them)
  for s in <the 30 heads by mergedAt>; do for each ci.yml pull_request run <id> of head_sha=$s and each attempt <n>:
    gh api repos/<repo>/actions/runs/<id>/attempts/<n> and, paginated, .../attempts/<n>/jobs -> corridas/$s.json
    as [{"run_id","run_attempt","status","run_started_at","jobs_total","jobs":[{"name","status","completed_at"}]}]
  python scripts/lead_time.py prs.json --corridas corridas --recortar docs/medicion/lead-time-<date>.json --capturado <UTC time>
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
SHA = re.compile(r'[0-9a-f]{40}')
LIMITE_LISTA, ULTIMOS = 1000, 30
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


def ci_tramo(intentos, hasta):
    """(start, last job finish) of ci.yml's last attempt started by `hasta`, or None unless that attempt was complete then."""
    previos = [x for x in intentos or () if x.get('run_started_at') and _t(x['run_started_at']) <= hasta]
    if not previos:
        return None
    x = max(previos, key=lambda x: (_t(x['run_started_at']), x.get('run_id') or 0, x.get('run_attempt') or 0))
    jobs = x.get('jobs') or []
    if x.get('status') != 'completed' or not jobs or x.get('jobs_total') != len(jobs):
        return None
    if any(j.get('status') != 'completed' or not j.get('completed_at') or _t(j['completed_at']) > hasta for j in jobs):
        return None
    return _t(x['run_started_at']), max(_t(j['completed_at']) for j in jobs)


def medir(pr, runs):
    head = pr['headRefOid']
    if not SHA.fullmatch(str(head)):
        raise ValueError(f"#{pr.get('number')}: head is not a sha")
    abierto, fusionado = _t(pr['createdAt']), _t(pr['mergedAt'])
    commits = [c for c in pr.get('commits') or () if c.get('oid') == head]
    head_t = min(max(_t(commits[-1]['committedDate']), abierto), fusionado) if commits else None  # up for review
    v = veredictos(pr.get('comments'), fusionado)
    pas = {}
    for a2, ver, s, t in sorted(v, key=lambda x: x[3]):  # a later REVISE on the head cancels a PASS; a repeated PASS does not move it
        if s == head:
            pas[a2] = (pas.get(a2) or t) if ver == 'PASS' else None
    pas = {a: pas.get(a) for a in ('claude', 'gpt')}
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
    c = lambda k: f"{r[k]['mediana']} ({r[k]['p90']})" if r[k].get('n') else 's/d'
    return (f"| {desde} → {hasta} | {r['prs']} | {c('total')} | {c('antes_head')} | {c('ci')} | {c('auditoria')} | "
            f"{c('espera_ci')} | {c('espera_dueno')} | {r['revise']['total']} ({r['revise']['prs_con_2_o_mas']} PR con 2+) |")


def recortar(prs, runs, capturado, listados):
    """What medir reads and nothing else: small, so the PR's diff fits what its reviewers read."""
    _t(capturado)
    out = []
    for pr in prs:
        primeras = [(c, str(c.get('body', '')).split('\n', 1)[0].rstrip('\r')) for c in pr.get('comments') or ()]
        out.append({k: pr[k] for k in ('number', 'createdAt', 'mergedAt', 'headRefOid', 'additions', 'deletions')} | {
            'commits': [{'oid': c['oid'], 'committedDate': c.get('committedDate')} for c in pr.get('commits') or ()
                        if c.get('oid') == pr['headRefOid']][-1:],
            'comments': [{'author': {'login': (c.get('author') or {}).get('login')}, 'createdAt': c.get('createdAt'), 'body': l}
                         for c, l in primeras if VEREDICTO.match(l)],
            'corridas': [{k: x.get(k) for k in ('run_id', 'run_attempt', 'status', 'run_started_at', 'jobs_total')} |
                         {'jobs': [{k: j.get(k) for k in ('name', 'status', 'completed_at')} for j in x.get('jobs') or ()]}
                         for x in runs[pr['headRefOid']]]})
    return {'capturado': capturado, 'comandos': COMANDOS, 'listados': listados, 'prs': out}


def escribir(datos):
    cab = json.dumps({k: datos[k] for k in ('capturado', 'comandos', 'listados')}, ensure_ascii=False)
    filas = ',\n'.join(json.dumps(pr, ensure_ascii=False, separators=(',', ':')) for pr in datos['prs'])
    return cab[:-1] + ',"prs":[\n' + filas + '\n]}\n'


def calcular(prs, runs):
    filas = [medir(pr, runs[pr['headRefOid']]) for pr in prs]
    r = resumen(filas)
    fechas = sorted(pr['mergedAt'][:10] for pr in prs)
    return {'resumen': r, 'fila': fila_estado(r, fechas[0], fechas[-1]) if fechas else None, 'prs': filas}


def ultimos(prs, n=ULTIMOS):
    return sorted(prs, key=lambda pr: (pr['mergedAt'], pr['number']), reverse=True)[:n]


def leer(ruta, corridas=None):
    """(prs, attempts by head, how many were listed) from gh's full listing plus a corridas folder, or a trimmed data file."""
    datos = json.loads(Path(ruta).read_text(encoding='utf-8'))
    if isinstance(datos, dict):
        return datos['prs'], {pr['headRefOid']: pr['corridas'] for pr in datos['prs']}, datos['listados']
    if corridas is None:
        raise SystemExit('gh output needs --corridas with one <head sha>.json per chosen PR')
    if len(datos) >= LIMITE_LISTA:
        raise SystemExit(f'the listing reached its limit ({LIMITE_LISTA}): it may be cut, so the last merges are not known')
    prs = ultimos(datos)
    faltan = [pr['headRefOid'] for pr in prs if not (Path(corridas) / f"{pr['headRefOid']}.json").is_file()]
    if faltan:
        raise SystemExit(f'missing ci.yml attempts for {len(faltan)} heads: {" ".join(faltan)}')
    runs = {pr['headRefOid']: json.loads((Path(corridas) / f"{pr['headRefOid']}.json").read_text(encoding='utf-8')) for pr in prs}
    return prs, runs, len(datos)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('prs', type=Path)
    ap.add_argument('--corridas', type=Path, help="folder with <head sha>.json: ci.yml's attempts and their jobs")
    ap.add_argument('--recortar', type=Path, help='also write the trimmed data file here')
    ap.add_argument('--capturado', help='UTC time the data was fetched, YYYY-MM-DDTHH:MM:SSZ (with --recortar)')
    a = ap.parse_args(argv)
    prs, runs, listados = leer(a.prs, a.corridas)
    if a.recortar:
        if not a.capturado:
            raise SystemExit('--recortar needs --capturado')
        a.recortar.write_text(escribir(recortar(prs, runs, a.capturado, listados)), encoding='utf-8')
    print(json.dumps(calcular(prs, runs), ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
