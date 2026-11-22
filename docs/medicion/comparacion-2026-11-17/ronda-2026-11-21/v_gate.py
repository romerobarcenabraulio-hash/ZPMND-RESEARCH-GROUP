"""v_gate.py <answer.json> <out dir> <main checkout>: la capa V de la comparación, hecha con lo que RG ya tiene.
Baja cada URL de la respuesta una vez con rg.investigar.fetch (el Fetcher de RG: solo los hosts que la respuesta cita,
https, robots.txt, direcciones públicas, redirecciones revisadas, pausa por host y presupuesto) y comprueba cada cita
como la compuerta (rg.packets: texto de rg.text, espacios plegados, al menos MIN_QUOTE caracteres, solo un cuerpo 200).
Cada afirmación sale con su resultado: verificada, cita_corta, rechazada, http_<código>, sin_cuerpo, sin_texto o
cita_ausente. Los crudos quedan en <out dir>/raw por sha256 y no se redistribuyen. Corre dentro de una copia de main."""
import collections
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit


def gate(ans, out, opener=None, sleep=None):
    from rg.investigar import fetch
    from rg.packets import MIN_QUOTE, _texts, fold
    out = Path(out)
    plan = {'sources': [{'url': u, 'redistribution': 'metadata_only'} for u in dict.fromkeys(c['url'] for c in ans['claims'])]}
    rows = {r['url']: r for r in fetch(plan, out, opener=opener, sleep=sleep, discovered=True)}
    for r in rows.values():  # another URL with the same bytes: its claims are checked on that one artifact
        if r['status'] == 'duplicate':
            r.update(rows[r['error'].removeprefix('same bytes as ')], url=r['url'])
    texts = _texts({str(out / r['raw']): r['media_type'] for r in rows.values() if r.get('artifact_id')})

    def resultado(c):
        r, q = rows[c['url']], fold(c['quote'])
        if len(q) < MIN_QUOTE:
            return 'cita_corta'
        if r['status'] in ('refused', 'not_fetched'):
            return 'rechazada'
        if not r.get('artifact_id'):
            return 'sin_cuerpo' if r['status'] == 200 else f"http_{r['status']}"
        t = texts.get(str(out / r['raw']))
        return 'sin_texto' if t is None else 'verificada' if q in t else 'cita_ausente'

    filas = [{'claim': c['claim'], 'url': c['url'], 'http': rows[c['url']]['status'], 'sha256': rows[c['url']].get('sha256'),
              'media': rows[c['url']].get('media_type'), 'resultado': resultado(c)} for c in ans['claims']]
    for f in filas:
        f['compuerta'] = f['resultado'] == 'verificada'
    return {'hosts': sorted({urlsplit(u).hostname for u in rows}), 'rows': filas,
            'resumen': {'afirmaciones': len(filas), 'compuerta': sum(f['compuerta'] for f in filas),
                        'por_resultado': dict(collections.Counter(f['resultado'] for f in filas))}}


if __name__ == '__main__':
    sys.path.insert(0, sys.argv[3])
    print(json.dumps(gate(json.load(open(sys.argv[1], encoding='utf-8')), sys.argv[2]), ensure_ascii=False, indent=1))
