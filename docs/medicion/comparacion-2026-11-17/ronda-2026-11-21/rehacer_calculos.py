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
M3). Comprueba la aritmética escrita, no que el precio o la cantidad sean los correctos."""
import json
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
    costo = sum(v for _, v in vals[i])
    if any(abs(sum(v for _, v in p) - costo) > max(0.01, 0.001 * abs(costo)) for p in vals[i + 1:]):
        return None, 'igualdad_falsa'
    return costo, None


rows = []
for c in json.load(open(sys.argv[1], encoding='utf-8')).get('calculations', []):
    formula, usd = c.get('formula'), c.get('monthly_usd')
    partes = [p for p in formula.split(';') if p.strip()] if isinstance(formula, str) else []
    vals = [tramo(p) for p in partes]
    motivo = 'sin_tramos' if not partes else 'sin_monto' if isinstance(usd, bool) or not isinstance(usd, (int, float)) else None
    sueltos = [p.strip() for p, (_, e) in zip(partes, vals) if e == 'sin_interpretar']
    falsas = [p.strip() for p, (_, e) in zip(partes, vals) if e == 'igualdad_falsa']
    total = sum(v for v, _ in vals if v is not None)
    ok = False if falsas else None if sueltos or motivo else abs(total - usd) <= 0.01 * max(abs(usd), 1e-9)
    rows.append({'provider': c.get('provider'), 'model': c.get('model'), 'scenario': c.get('scenario'), 'dice': usd,
                 'rehecho': round(total, 4), 'cuadra': ok, **({'sin_interpretar': sueltos} if sueltos else {}),
                 **({'igualdad_falsa': falsas} if falsas else {}), **({'motivo': motivo} if motivo else {})})
print(json.dumps({'rows': rows, 'resumen': {'calculos': len(rows), 'cuadran': sum(r['cuadra'] is True for r in rows),
                                            'no_cuadran': sum(r['cuadra'] is False for r in rows),
                                            'no_comprobables': sum(r['cuadra'] is None for r in rows)}}, ensure_ascii=False, indent=1))
