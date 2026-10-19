"""Document type from the leading words of the OFFICIAL title. A fixed table, no inference: no match means OTRO.

Longest prefix wins, compared without accents or case. Adding a type is one row here plus a test case.
"""
import unicodedata

DOC_TYPES = [
    ('PROYECTO DE NORMA OFICIAL MEXICANA', 'PROYECTO DE NORMA OFICIAL MEXICANA'),
    ('RESPUESTA A LOS COMENTARIOS', 'RESPUESTA A COMENTARIOS'),
    ('NORMA OFICIAL MEXICANA', 'NORMA OFICIAL MEXICANA'),
    ('INDICE NACIONAL DE PRECIOS', 'INDICADOR ECONOMICO'),
    ('TIPO DE CAMBIO', 'INDICADOR ECONOMICO'),
    ('TASAS DE INTERES', 'INDICADOR ECONOMICO'),
    ('TASA DE INTERES', 'INDICADOR ECONOMICO'),
    ('VALOR DE LA UNIDAD DE INVERSION', 'INDICADOR ECONOMICO'),
    ('EQUIVALENCIA DE LAS MONEDAS', 'INDICADOR ECONOMICO'),
    ('FE DE ERRATAS', 'ACLARACION'),
    ('NOTA ACLARATORIA', 'ACLARACION'),
    ('ACLARACION', 'ACLARACION'),
    ('CONSTITUCION', 'CONSTITUCION'),
    ('CODIGO', 'CODIGO'),
    ('LEY', 'LEY'),
    ('REGLAMENTO', 'REGLAMENTO'),
    ('ESTATUTO', 'ESTATUTO'),
    ('ORDENANZA', 'ORDENANZA'),
    ('PRESUPUESTO DE EGRESOS', 'PRESUPUESTO'),
    ('DECRETO', 'DECRETO'),
    ('ACUERDO', 'ACUERDO'),
    ('RESOLUCION', 'RESOLUCION'),
    ('SENTENCIA', 'SENTENCIA'),
    ('LINEAMIENTOS', 'LINEAMIENTOS'),
    ('REGLAS', 'REGLAS'),
    ('DISPOSICIONES', 'DISPOSICIONES'),
    ('CIRCULAR', 'CIRCULAR'),
    ('CONVENIO', 'CONVENIO'),
    ('DECLARATORIA', 'DECLARATORIA'),
    ('MANUAL', 'MANUAL'),
    ('PROGRAMA', 'PROGRAMA'),
    ('CONVOCATORIA', 'CONVOCATORIA'),
    ('EDICTO', 'EDICTO'),
    ('AVISO', 'AVISO'),
    ('EXTRACTO', 'EXTRACTO'),
    ('OFICIO', 'OFICIO'),
    ('INDICE', 'INDICE'),
    ('ESTADOS FINANCIEROS', 'INFORMACION FINANCIERA'),
    ('ESTADO DE POSICION FINANCIERA', 'INFORMACION FINANCIERA'),
    ('BALANCE', 'INFORMACION FINANCIERA'),
]
_TABLE = sorted(((p, t) for p, t in DOC_TYPES), key=lambda pt: -len(pt[0]))


def fold(text):
    """Uppercase without accents, single spaces: the comparison form, never stored."""
    plain = ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c))
    return ' '.join(plain.upper().split())


def doc_type(title):
    folded = fold(title)
    for prefix, label in _TABLE:
        if folded == prefix or folded.startswith(prefix + ' ') or folded.startswith(prefix + ','):
            return label
    return 'OTRO'
