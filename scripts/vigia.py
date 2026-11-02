"""Vigía de producción (SECURITY.md T26): on 2026-11-02 nobody had noticed for days that catalog-mx.yml failed 5 of its
last 6 scheduled runs and that texto-mx.yml had never run. From the last 20 runs on main (schedule or dispatch only) of
each workflow below and the time alone, one state each: rojo (the last finished run did not succeed), ok (it succeeded
and started no more whole days ago than the cap), en_curso (neither, but a run started within the cap is queued or
running), sin_correr (none of these). The issue text holds only the fixed names, these states, dates and numbers
formatted here and run links built here from the repo name and the run id, never text the API carries."""
import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# (workflow, cap in whole days); catalog-mx runs on days 1, 4, ... 31, so a cap of 2 whole days alarms on the third.
VIGILADOS = (('catalog-mx.yml', 2), ('texto-mx.yml', 8), ('indicadores-mx.yml', 8), ('sondeo.yml', 8),
             ('descubrir.yml', 2), ('sondeo-inegi.yml', 35))
TITULO = 'Vigía de producción'
AUTOR = 'github-actions[bot]'  # the issue this workflow opened; anyone can open one with the same title
POR_PAGINA, PAGINAS = 100, 30  # per_page of vigia.yml's listing of open issues, and the most pages it reads
EVENTOS = ('schedule', 'workflow_dispatch')  # the triggers of every watched workflow (tests/test_vigia.py)
EN_CURSO = ('queued', 'in_progress', 'waiting', 'requested', 'pending')
CONCLUSIONES = ('success', 'failure', 'cancelled', 'timed_out', 'action_required', 'neutral', 'skipped', 'stale', 'startup_failure')
ALERTA = ('rojo', 'sin_correr')
REPO = re.compile(r'[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}')


def _hora(s):
    if not isinstance(s, str):
        raise ValueError('a run without its time')
    return datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)


def corridas(datos):
    """Runs of main by schedule or dispatch, newest first; anything malformed stops it all (ValueError), issue untouched."""
    if not isinstance(datos, dict) or not isinstance(datos.get('workflow_runs'), list):
        raise ValueError('not a list of workflow runs')
    out = []
    for r in datos['workflow_runs']:
        if not isinstance(r, dict) or not isinstance(r.get('status'), str):
            raise ValueError('a run without its status')
        if not all(type(r.get(k)) is int and r[k] > 0 for k in ('id', 'run_number')):
            raise ValueError('a run without its id or number')
        creada = _hora(r.get('created_at'))
        inicio = _hora(r['run_started_at']) if r.get('run_started_at') is not None else creada  # a re-run starts again
        if r.get('head_branch') == 'main' and r.get('event') in EVENTOS:
            out.append({'id': r['id'], 'numero': r['run_number'], 'status': r['status'],
                        'conclusion': r.get('conclusion'), 'creada': creada, 'inicio': inicio})
    return sorted(out, key=lambda c: (c['creada'], c['id']), reverse=True)


def dias(desde, ahora):  # whole days gone by
    return (ahora - desde) // timedelta(days=1)


def decidir(datos, tope, ahora):
    runs = corridas(datos)
    hechas = [c for c in runs if c['status'] == 'completed']
    ultima = hechas[0] if hechas else None
    exito = next((c for c in hechas if c['conclusion'] == 'success'), None)
    curso = next((c for c in runs if c['status'] in EN_CURSO and dias(c['inicio'], ahora) <= tope), None)
    if ultima and ultima['conclusion'] != 'success':
        estado = 'rojo'  # before en_curso: a new run never hides that the last one failed
    elif ultima and dias(ultima['inicio'], ahora) <= tope:
        estado = 'ok'
    elif curso:
        estado = 'en_curso'
    else:
        estado = 'sin_correr'
    return {'estado': estado, 'corrida': curso if estado == 'en_curso' else ultima, 'exito': exito}


def fila(nombre, tope, d, ahora, repo):
    c = d['corrida']
    if c is None:
        corrida = 'ninguna entre las últimas 20'
    else:
        que = 'en curso' if c['status'] in EN_CURSO else (c['conclusion'] if c['conclusion'] in CONCLUSIONES else 'otra')
        corrida = f"[#{c['numero']}](https://github.com/{repo}/actions/runs/{c['id']}) {c['inicio']:%Y-%m-%d %H:%M} UTC, {que}"
    exito = 'ninguno entre los últimos 20' if d['exito'] is None else str(dias(d['exito']['inicio'], ahora))
    return f"| `{nombre}` | {d['estado']} | {corrida} | {exito} | {tope} |"


def revisar(datos, ahora, repo):
    """(alerta, issue text) from the runs JSON of every watched workflow; a missing one raises."""
    if not REPO.fullmatch(repo):
        raise ValueError('repo must be owner/name')
    filas, alerta = [], False
    for nombre, tope in VIGILADOS:
        d = decidir(datos[nombre], tope, ahora)
        alerta = alerta or d['estado'] in ALERTA
        filas.append(fila(nombre, tope, d, ahora, repo))
    texto = '\n'.join([
        f'Revisión del {ahora:%Y-%m-%d %H:%M} UTC de las corridas en `main` (`scripts/vigia.py`, SECURITY.md T26).', '',
        '| Workflow | Estado | Última corrida | Días desde el último éxito | Tope (días) |', '|---|---|---|---|---|',
        *filas, '',
        'rojo: la última corrida terminada no fue success. sin_correr: ninguna corrida terminada dentro del tope '
        '(días enteros). en_curso: una corrida iniciada dentro del tope sigue en marcha.', ''])
    return alerta, texto


def elegir_issue(issues):
    """The lowest-numbered open issue titled exactly TITULO that github-actions[bot] opened, never a PR, or None."""
    if not isinstance(issues, list):
        raise ValueError('not a list of issues')
    nums = [i['number'] for i in issues
            if isinstance(i, dict) and i.get('title') == TITULO and i.get('state') == 'open'
            and 'pull_request' not in i and isinstance(i.get('user'), dict) and i['user'].get('login') == AUTOR
            and type(i.get('number')) is int and i['number'] > 0]
    return min(nums) if nums else None


def issue_de(paginas):
    """'mas' while the last page read is full (the next one is read too), then the vigía issue among every page or ''.
    A page that is not a list (gh failed) or more than PAGINAS full pages stops it, so nothing is written."""
    if not paginas or not all(isinstance(p, list) for p in paginas):
        raise ValueError('not pages of issues')
    if len(paginas[-1]) >= POR_PAGINA:
        if len(paginas) >= PAGINAS:
            raise ValueError(f'more than {PAGINAS} pages of open issues')
        return 'mas'
    n = elegir_issue([i for p in paginas for i in p])
    return '' if n is None else str(n)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('orden', choices=('lista', 'decidir', 'issue'))  # lista | decidir --repo O/N --dir DIR | issue --dir DIR --paginas N
    for opcion, tipo in (('--repo', str), ('--dir', Path), ('--paginas', int)):
        p.add_argument(opcion, type=tipo)
    a = p.parse_args(argv)
    if a.orden == 'lista':
        print('\n'.join(n for n, _ in VIGILADOS))
    elif a.orden == 'issue':
        print(issue_de([json.loads((a.dir / f'issues-{k}.json').read_text(encoding='utf-8')) for k in range(1, a.paginas + 1)]))
    else:
        datos = {n: json.loads((a.dir / f'{n}.json').read_text(encoding='utf-8')) for n, _ in VIGILADOS}
        alerta, texto = revisar(datos, datetime.now(timezone.utc), a.repo)
        (a.dir / 'vigia.md').write_text(texto, encoding='utf-8')
        for nombre, carga in (('nueva', {'title': TITULO, 'body': texto}), ('cuerpo', {'body': texto}),
                              ('cierre', {'body': 'Todo en orden: nada en rojo ni sin correr. La vigía cierra esta '
                                                  'issue y abre otra si algo vuelve a fallar.\n\n' + texto})):
            (a.dir / f'{nombre}.json').write_text(json.dumps(carga), encoding='utf-8')
        print(f"alerta={'true' if alerta else 'false'}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
