"""NOM lineages from the DOF catalog (Mexican Official Standards, Normas Oficiales Mexicanas).

Every DOF note whose official title names a NOM code is grouped by lineage (the code without its year, e.g.
NOM-137-SSA1: one standard and its successive editions) and ordered by official publication date. The stage of each
note comes from a fixed table of title openings (project, public consultation, response to comments, standard,
correction, extension, cancellation...); a title that matches none is OTRO. Relations between standards are copied
from the title itself: a NOM named after the word CANCELA is 'cancela'; any other NOM named in the title is
'menciona'. Nothing is inferred: no validity is computed, no lineage is merged by subject.
"""
import hashlib
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
# Older printings (the DOF of 1993-2000, the third branch, read only where the first fails): a year of two digits from
# the 1990s (NOM-051-SSA1-93, mx.dof:4670808; NOM-EM-0000-SCT/3-99, mx.dof:4954245), a space instead of the hyphen
# after the number (NOM-EM-004 FITO-1994, mx.dof:4732595), the issuer's last character after a space (NOM-038-SSA
# I-1993, mx.dof:4677076; NOM-005-SSA 2- 1993, mx.dof:4697265), a four-digit number (NOM-1811-SCFI-1993,
# mx.dof:4794338) and a space after the slash of a sub-number (NOM-025/ 1-NUCL-2000, mx.dof:5469372). The issuer is
# copied as printed without its spaces (SSA I is SSAI, never SSA1); a two-digit year 9x is 199x and no other is read.
# A code printed without its issuer or its year (PROY-NOM-013-2004, NOM-034-STPS) still yields nothing. The branch
# needs one of those older features (OLD_FEATURE), so a code the first branch reads is never read by it as well.
OLD_FEATURE = (r'(?=\d{4}\s*-|\d{2,3}/\s|\d{2,4}\s+[A-Z]|\d{2,4}(?:/\d+)?\s*-\s*[A-Z]+\s(?:\d|I)\b'
               r'|\d{2,4}(?:/\s?\d+)?(?:\s*-\s*|\s+)[A-Z]+(?:\s?\d|\sI)?(?:/\d)?\s*-\s*9\d\b)')
CODE = re.compile(r'\b(PROY-)?NOM-(EM-)?(?:(\d{2,3}(?:/\d+)?)\s*-\s*((?:[A-Z0-9]+\s*[-/]\s*)*?[A-Z0-9]+)\s*(?:[-/]|/-)\s*(\d{4})'
                  r'|' + OLD_FEATURE + r'(\d{2,4}(?:/\s?\d+)?)(?:\s*-\s*|\s+)([A-Z]+(?:\s?\d|\sI)?(?:/\d)?)\s*-\s*(\d{4}|9\d)'
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
        proj, em, num, issuer, year, num_old, issuer_old, year_old, num_bare, issuer_bare, year_bare = m.groups()
        if num_old is not None:  # an older printing (third branch): its spaces dropped, a year 9x is 199x
            num, issuer, year = num_old.replace(' ', ''), issuer_old, year_old if len(year_old) == 4 else '19' + year_old
        if num is None:  # the no-separator branch matched
            num, issuer, year = num_bare, issuer_bare, year_bare
        head, _, sub = num.partition('/')
        issuer = re.sub(r'\s+', '', issuer)  # 'SCFI/ SSA1' as printed is the issuer SCFI/SSA1
        lineage = f"NOM-{'EM-' if em else ''}{int(head):03d}{'/' + sub if sub else ''}-{issuer}"
        out.append((lineage, int(year), m.group(0), bool(proj), m.start()))
    return out


# Titles a person reviewed that name a NOM with no readable code (entry id -> sha256 of the exact title read, why).
# Only notes, never patterns; the review holds for that title only.
REVIEWED = {
    'mx.dof:5583405': ('e632f71f9d17b86d9b648c267326db4b5329982704d1fa812c0e5cfe68e93159',
                       'convenio de subsidios que cita «conforme a la NOM-046.» sin emisor ni año: no es una nota de NOM'),
    # The DOF back to 1993 (2026-10-29): codes printed without their year or their issuer, read by no branch above.
    # Each is a NOM note left out of the lineages, here and nowhere else.
    'mx.dof:4762178': ('b991c952aa2979644ffc6fb3140bc1a969b916710ea776e1c0f25e42fbf1fad3', 'NOM-034-STPS: sin año'),
    'mx.dof:4779095': ('ca1197d8214a19113c14763d3953e7c03cbc827b236624674fa539d9cfec750e', 'NOM-001-SCT-2: sin año'),
    'mx.dof:4792756': ('c234c63a403780bc34d66572653857cd3406da40936dd5e7b8565e1b2674cf99', 'NOM-001-SCT-2: sin año (aclaración)'),
    'mx.dof:671024': ('c0cf770ff156dfef7be8136eb13a0718fc7ece12ce95dcb6c51017caba2a213f', 'NOM-EM-144-SEMARNAT: sin año'),
    'mx.dof:688153': ('ffe947fba8f14855bc00063e183b3672e1fd0608624fb4f4a1049793071c15ed', 'NOM-EM-144-SEMARNAT: sin año'),
    'mx.dof:4658304': ('29c4693590025d4eff91f3c577f6ceeff5b0db58670ffa1a7263e0cfc0b65743', 'NOM-EM-002-1993: sin emisor'),
    'mx.dof:661160': ('27912ab1dc0812b99279c13b3100a641ae78b5fecb4407e86748a007e03252f7', 'PROY-NOM-013-2004: sin emisor'),
}


def reviewed(entry):
    """True only for the exact title a person reviewed: a corrected title under the same id is checked again."""
    seen = REVIEWED.get(entry['entry_id'])
    return seen is not None and seen[0] == hashlib.sha256(entry['title'].encode('utf-8')).hexdigest()


def unparsed(entries):
    """Entry ids whose title seems to name a NOM but yields no code: the parser's independent check. A reviewed note
    (REVIEWED, that exact title) is not reported; a new one, or a new title under its id, is."""
    entries = [e for e in entries if not reviewed(e)]
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
