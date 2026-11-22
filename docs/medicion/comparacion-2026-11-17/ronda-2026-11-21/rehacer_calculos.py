"""rehacer_calculos.py <answer.json>: M3, cálculos (protocolo de la comparación del 2026-11-17). Rehace cada cálculo con
una gramática explícita y nada más. La fórmula se parte en tramos por ';'. Cada tramo tiene una etiqueta opcional y una
cadena de expresiones unidas por '='; cada expresión es una suma (+) de productos (x) de números, con '$' y las unidades
MTok, MTok-h o h. Lo que cuesta un tramo es la primera expresión que lleva '$', y en ella cada producto debe llevar un
monto en dólares. Cada expresión que la sigue tras '=' debe valer lo mismo (un centavo o 0.1 %, lo mayor): si no, la
igualdad es falsa y el cálculo no cuadra (GPT en a522331). Un tramo que no se lee entero (una división, una resta, una
palabra suelta, un número sin '$' en lo que cuesta), que no tiene '$' o que trae una expresión antes de lo que cuesta
(una conversión de cantidades que esta lectura no comprueba) deja el cálculo como no comprobable (cuadra: null) y lo
nombra (GPT en 9ce44ea y 815764a). Sin ningún tramo, o con un monthly_usd que no es un número, tampoco es comprobable
(GPT en 269352a). Si todo se lee, no cuadra cuando la suma de los tramos difiere más de 1 % de monthly_usd (protocolo,
M3). Comprueba la aritmética escrita, no que el precio o la cantidad sean los correctos.

Lo que garantiza para cualquier JSON (GPT en 9ce44ea, 815764a, a522331, 269352a y 0459898, un caso suelto cada vez): la
salida es JSON estricto, sin NaN ni Infinity, y cada cálculo sale con cuadra true, false o null. true solo si cada tramo
se lee entero, sus igualdades se cumplen, cada suma es un número finito (un número, producto o suma que no cabe en un
float desborda) y el total está a 1 % de un monthly_usd finito; false solo por una igualdad falsa o un total fuera del
1 %; lo demás es null y nombra por qué (motivo sin_tramos, sin_monto, desborda o no_es_objeto, o los tramos en
sin_interpretar o desbordan). Un archivo que no es un objeto con una lista calculations termina con error."""
import json
import math
import re
import sys

LABEL = re.compile(r'\s*[^\W\d_]+(?:\s+[^\W\d_]+)*\s*:?(?=\s*[$\d])')
TOK = re.compile(r'\s*(?:(\$)?\s*((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?:\s*(?:MTok-h|MTok|h))?(?![\w/.,])|([x×*+=]))')


def tramo(s):
    """(lo que cuesta un tramo, None) si se lee y sus igualdades se cumplen; (None, 'sin_interpretar') o (None,
    'igualdad_falsa') si no."""
    m = LABEL.match(s)
    i, toks, fin = (m.end() if m else 0), [], len(s.rstrip())
    while i < fin:
        t = TOK.match(s, i)
        if not t:
            return None, 'sin_interpretar'
        toks.append(t.groups())
        i = t.end()
    exprs, cur = [], []
    for d, n, op in toks:
        if op == '=':
            exprs, cur = exprs + [cur], []
        else:
            cur.append((d, n, op))
    vals = []
    for e in exprs + [cur]:
        if not e or len(e) % 2 == 0 or any((k % 2 == 0) == (op is not None) for k, (_, _, op) in enumerate(e)):
            return None, 'sin_interpretar'  # número, operador, número...: nada más
        prods, v, dol = [], 1.0, False
        for k in range(0, len(e), 2):
            v, dol = v * float(e[k][1].replace(',', '')), dol or bool(e[k][0])
            if k + 1 == len(e) or e[k + 1][2] == '+':
                prods, v, dol = prods + [(dol, v)], 1.0, False
        vals.append(prods)
    i = next((k for k, p in enumerate(vals) if any(d for d, _ in p)), None)
    if i is None or i > 0 or not all(d for d, _ in vals[i]):
        return None, 'sin_interpretar'  # sin '$', una cantidad antes del costo, o un sumando sin dólares en él
    sumas = [sum(v for _, v in p) for p in vals]  # i == 0: lo que cuesta, y lo que debe valer lo mismo
    if not all(map(math.isfinite, sumas)):
        return None, 'desborda'  # un infinito, o un 0 por un infinito: nada que comparar
    costo = sumas[0]
    if any(abs(s - costo) > max(0.01, 0.001 * abs(costo)) for s in sumas[1:]):
        return None, 'igualdad_falsa'
    return costo, None


def finito(x):
    """x es un número (nunca un booleano) que cabe en un float finito."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return False
    try:
        return math.isfinite(x)
    except OverflowError:  # un entero mayor que cualquier float
        return False


def dato(x):
    """Un valor de la respuesta tal cual, o como texto si no es JSON estricto (un NaN o un infinito que leyó json.load)."""
    try:
        json.dumps(x, allow_nan=False)
        return x
    except ValueError:
        return str(x)


data = json.load(open(sys.argv[1], encoding='utf-8'))
calcs = data.get('calculations') if isinstance(data, dict) else None  # sin la clave no hay lista: error, nunca cero cálculos (GPT en 3bd73c0)
if not isinstance(calcs, list):
    sys.exit('rehacer_calculos.py: se espera un objeto JSON con una lista calculations')
rows = []
for c in calcs:
    if not isinstance(c, dict):
        rows.append({'cuadra': None, 'motivo': 'no_es_objeto'})
        continue
    formula, usd = c.get('formula'), c.get('monthly_usd')
    partes = [p for p in formula.split(';') if p.strip()] if isinstance(formula, str) else []
    vals = [tramo(p) for p in partes]
    sueltos = [p.strip() for p, (_, e) in zip(partes, vals) if e == 'sin_interpretar']
    falsas = [p.strip() for p, (_, e) in zip(partes, vals) if e == 'igualdad_falsa']
    desbordan = [p.strip() for p, (_, e) in zip(partes, vals) if e == 'desborda']
    total = sum(v for v, _ in vals if v is not None)
    motivo = 'sin_tramos' if not partes else 'sin_monto' if not finito(usd) else 'desborda' if not math.isfinite(total) else None
    ok = False if falsas else None if sueltos or desbordan or motivo else abs(total - usd) <= 0.01 * max(abs(usd), 1e-9)
    rows.append({'provider': dato(c.get('provider')), 'model': dato(c.get('model')), 'scenario': dato(c.get('scenario')),
                 'dice': dato(usd), 'rehecho': round(total, 4) if math.isfinite(total) else None, 'cuadra': ok,
                 **({'sin_interpretar': sueltos} if sueltos else {}), **({'igualdad_falsa': falsas} if falsas else {}),
                 **({'desbordan': desbordan} if desbordan else {}), **({'motivo': motivo} if motivo else {})})
print(json.dumps({'rows': rows, 'resumen': {'calculos': len(rows), 'cuadran': sum(r['cuadra'] is True for r in rows),
                                            'no_cuadran': sum(r['cuadra'] is False for r in rows),
                                            'no_comprobables': sum(r['cuadra'] is None for r in rows)}}, ensure_ascii=False, indent=1))
