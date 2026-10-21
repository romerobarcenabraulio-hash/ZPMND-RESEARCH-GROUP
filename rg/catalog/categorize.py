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


# Official DOF sections whose notes are all of one kind: the section decides, not the title (whose first words are
# the convening institution's name). Keys are folded section names as printed by SIDOF.
DOF_SECTION_TYPES = {
    'CONVOCATORIAS PARA CONCURSOS DE ADQUISICIONES, ARRENDAMIENTOS, OBRAS Y SERVICIOS DEL SECTOR PUBLICO': 'CONVOCATORIA DE ADQUISICIONES',
    'CONVOCATORIAS PARA CONCURSOS DE PLAZAS VACANTES DEL SERVICIO PROFESIONAL DE CARRERA EN LA ADMINISTRACION PUBLICA FEDERAL': 'CONVOCATORIA DE PLAZAS',
}


def dof_doc_type(title, branch):
    """DOF note type: from the official section when the section is single-kind, else from the title table."""
    return DOF_SECTION_TYPES.get(fold(branch or '')) or doc_type(title)


def doc_type(title):
    folded = fold(title)
    for prefix, label in _TABLE:
        if folded == prefix or folded.startswith(prefix + ' ') or folded.startswith(prefix + ','):
            return label
    return 'OTRO'


def clean_text(text):
    """Remove invisible characters (Unicode Cc except tab/newline, and Cf: zero-width, bidi, BOM) found in source text.
    Deterministic and counted; nothing else changes. Returns (clean, removed)."""
    kept = [c for c in text if c in '\t\n' or unicodedata.category(c) not in ('Cc', 'Cf')]
    return ''.join(kept), len(text) - len(kept)
