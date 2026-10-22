"""NOM lineages from the DOF catalog (Mexican Official Standards, Normas Oficiales Mexicanas).

Every DOF note whose official title names a NOM code is grouped by lineage (the code without its year, e.g.
NOM-137-SSA1: one standard and its successive editions) and ordered by official publication date. The stage of each
note comes from a fixed table of title openings (project, public consultation, response to comments, standard,
correction, extension, cancellation...); a title that matches none is OTRO. Relations between standards are copied
from the title itself: a NOM named after the word CANCELA is 'cancela'; any other NOM named in the title is
'menciona'. Nothing is inferred: no validity is computed, no lineage is merged by subject.
"""
import json
import re
from pathlib import Path

from .categorize import fold

# NOM-137-SSA1-2025, PROY-NOM-034-ENER-2025, NOM-EM-007-ASEA- 2025, NOM-011-SICT2/2025, NOM-08-TUR-2002, and compound
# issuers: NOM-051-SCFI/SSA1-2010, NOM-087-ECOL-SSA1-2002
# printed variants seen in the DOF: a space after the number (NOM-241- SSA1-2025), a sub-number (NOM-021/3- SCT3-2010),
# two separators before the year (PROY-NOM-020-SCT2/-2020, mx.dof:5638496), and no separator at all
# (PROY-NOM-016ENER2024, mx.dof:5763083).
# The no-separator form (second branch) is read only when the issuer is letters only, between a 2-3 digit number and a
# 4-digit year that ends the word: letters and digits are disjoint, so the split is unique. An issuer ending in a digit
# (SSA1, SCT2) cannot be told from the year without a separator ('SSA12024': SSA1 + 2024 or SSA + 12024?), so such a
# code yields nothing and stays in unparsed(), visible, instead of being guessed.
CODE = re.compile(r'\b(PROY-)?NOM-(EM-)?(?:(\d{2,3}(?:/\d+)?)\s*-\s*((?:[A-Z0-9]+\s*[-/]\s*)*?[A-Z0-9]+)\s*(?:[-/]|/-)\s*(\d{4})'
                  r'|(\d{2,3})([A-Z]+)(\d{4}))\b')
LOOKS_LIKE = re.compile(r'\bNOM-(?:EM-)?\d')  # independent of CODE: any title that seems to name a NOM

# Folded title opening -> stage; the longest matching opening wins.
STAGES = {
    'AVISO DE CONSULTA PUBLICA DEL PROYECTO DE MODIFICACION': 'consulta_proyecto_modificacion',
    'AVISO DE CONSULTA PUBLICA': 'consulta_proyecto',
    'PROYECTO DE MODIFICACION': 'proyecto_modificacion',
    'PROYECTO DE NORMA OFICIAL MEXICANA': 'proyecto',
    'RESPUESTA A LOS COMENTARIOS': 'respuesta_comentarios',
    'RESPUESTAS A LOS COMENTARIOS': 'respuesta_comentarios',
    'NORMA OFICIAL MEXICANA DE EMERGENCIA': 'norma_emergencia',
    'NORMA OFICIAL MEXICANA': 'norma',
    'MODIFICACION A LA NORMA OFICIAL MEXICANA': 'modificacion',
    'MODIFICACION DE LA NORMA OFICIAL MEXICANA': 'modificacion',
    'ACLARACION': 'aclaracion',
    'NOTA ACLARATORIA': 'aclaracion',
    'FE DE ERRATAS': 'fe_de_erratas',
    'AVISO POR EL CUAL SE PRORROGA': 'prorroga',
    'AVISO POR EL QUE SE PRORROGA': 'prorroga',
    'AVISO DE CANCELACION': 'cancelacion',
    'DECLARATORIA DE CANCELACION': 'cancelacion',
    'CONVOCATORIA': 'convocatoria',
}


def stage(title):
    t = fold(title)
    best = max((p for p in STAGES if t.startswith(p)), key=len, default=None)
    return STAGES[best] if best else 'OTRO'


def codes(title):
    """NOM codes printed in a title, in order: (lineage, edition, printed, is_project, position)."""
    out = []
    for m in CODE.finditer(fold(title)):
        proj, em, num, issuer, year, num_bare, issuer_bare, year_bare = m.groups()
        if num is None:  # the no-separator branch matched
            num, issuer, year = num_bare, issuer_bare, year_bare
        head, _, sub = num.partition('/')
        issuer = re.sub(r'\s+', '', issuer)  # 'SCFI/ SSA1' as printed is the issuer SCFI/SSA1
        lineage = f"NOM-{'EM-' if em else ''}{int(head):03d}{'/' + sub if sub else ''}-{issuer}"
        out.append((lineage, int(year), m.group(0), bool(proj), m.start()))
    return out


def unparsed(entries):
    """Entry ids whose title seems to name a NOM but yields no code: the parser's independent check."""
    return sorted(e['entry_id'] for e in entries if LOOKS_LIKE.search(fold(e['title'])) and not codes(e['title']))


def cites_nom(title):
    return bool(CODE.search(fold(title)))


def lineages(entries):
    """One record per lineage, notes ordered by official date. The first code in a title is its subject; later codes
    are relations ('cancela' when the word CANCELA comes before them, else 'menciona')."""
    out = {}
    for e in entries:
        found = codes(e['title'])
        if not found:
            continue
        t = fold(e['title'])
        subject, edition, printed, is_project, _ = found[0]
        rec = out.setdefault(subject, {'lineage': subject, 'notes': [], 'relations': []})
        rec['notes'].append({'entry_id': e['entry_id'], 'published': e['dates'].get('published'), 'stage': stage(e['title']),
                             'code_printed': printed, 'edition': edition, 'project': is_project, 'title': e['title']})
        for lineage, ed, other, _, pos in found[1:]:
            if lineage == subject and ed == edition:
                continue
            kind = 'cancela' if 'CANCELA' in t[:pos] else 'menciona'
            rec['relations'].append({'type': kind, 'to': other, 'to_lineage': lineage, 'to_edition': ed,
                                     'entry_id': e['entry_id'], 'published': e['dates'].get('published')})
    for rec in out.values():
        rec['notes'].sort(key=lambda n: (n['published'] or '', n['entry_id']))
        rec['relations'].sort(key=lambda r: (r['published'] or '', r['entry_id'], r['to']))
        rec['editions'] = sorted({n['edition'] for n in rec['notes']})
    return [out[k] for k in sorted(out)]


def write(catalog_dir, entries):
    """mx/normas/nom.jsonl, one lineage per line, sorted; rewritten whole every run (derived from the catalog)."""
    d = Path(catalog_dir) / 'normas'
    d.mkdir(parents=True, exist_ok=True)
    rows = lineages(entries)
    (d / 'nom.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n' for r in rows),
                                 encoding='utf-8')
    return len(rows)
