"""International treaties in Mexico from the DOF catalog: a derived view (SRE's site is never touched).

A treaty enters Mexican law through DOF decrees: the Senate's approval ("Decreto por el que se aprueba el Convenio
...") and the promulgation ("Decreto Promulgatorio del Tratado ..."). A DOF note is a treaty note when its title opens
with an act from a fixed table, then one article, then an instrument word from a fixed list; the stage comes from the
table (the longest opening followed by an instrument wins). The instrument's name is copied from the title: the words
after the article, up to the conclusion clause (", adoptado en", ", firmado en", ", hecho en", ", suscrito en"), else
to the end without the final period. Notes are grouped by the exact name, folded (no accents, upper case, single
spaces), and ordered by official date. Nothing is inferred: no validity, no parties, no merging of different names.

Independent check: a looser regex over every DOF title (LOOKS_LIKE) must select exactly the titles the table
classifies; any disagreement, either way, fails the run's coverage (exit 3), except a note a person reviewed and wrote
down in REVIEWED with the sha256 of the exact title read and the reason: the table's answer stands for that title,
and a new disagreement, or a new title under the same id, still fails the run.
"""
import hashlib
import json
import re
from pathlib import Path

from .categorize import fold

SOURCE = 'mx.dof'

# Folded act opening -> stage. The instrument's name follows the opening after one article.
STAGES = {
    'DECRETO PROMULGATORIO': 'promulgacion',
    'DECRETO POR EL QUE SE APRUEBA': 'aprobacion_senado',
    'DECRETO POR EL QUE SE APRUEBAN': 'aprobacion_senado',
    'DECRETO PROMULGATORIO DE LA ENMIENDA': 'enmienda',
    'DECRETO PROMULGATORIO DE LAS ENMIENDAS': 'enmienda',
    'DECRETO POR EL QUE SE APRUEBA LA ENMIENDA': 'enmienda',
    'DECRETO POR EL QUE SE APRUEBAN LAS ENMIENDAS': 'enmienda',
    'DECRETO PROMULGATORIO DE LA DENUNCIA': 'retiro_o_denuncia',
    'DECRETO POR EL QUE SE APRUEBA LA DENUNCIA': 'retiro_o_denuncia',
    'DECRETO POR EL QUE SE DA A CONOCER LA DENUNCIA': 'retiro_o_denuncia',
    'DECRETO PROMULGATORIO CON': 'promulgacion',  # 'con las declaraciones ... al Acta de Ginebra' (DOF 2020-06-05)
    'DECRETO PROMULGATORIO DEL RETIRO': 'retiro_o_denuncia',
    'DECRETO POR EL QUE SE APRUEBA EL RETIRO': 'retiro_o_denuncia',
    'FE DE ERRATAS AL DECRETO PROMULGATORIO': 'fe_de_erratas',
    'FE DE ERRATAS AL DECRETO POR EL QUE SE APRUEBA': 'fe_de_erratas',
    'ACLARACION AL DECRETO PROMULGATORIO': 'aclaracion',
    'ACLARACION AL DECRETO POR EL QUE SE APRUEBA': 'aclaracion',
}
_OPENINGS = sorted(STAGES, key=len, reverse=True)
# Disagreements a person reviewed (entry id -> sha256 of the exact title read, why the table's answer stands).
# Only notes, never patterns; the review holds for that title only.
REVIEWED = {
    'mx.dof:5636928': ('80ef8b31e6e315c46cdf4c89cd99c287f5e2218b2ce06f6f4a7b1710162ddfb0',
                       'aprueba el Anexo III de MARPOL 73/78 (un tratado); el título no trae cláusula de conclusión'),
    'mx.dof:5636929': ('f9caa9d30dbcf341cb1dc93a378060d41a8f4f7a19a5d3a43139281ebda6ab11',
                       'aprueba el Anexo IV de MARPOL 73/78 (un tratado); el título no trae cláusula de conclusión'),
}
ARTICLES = ('DEL', 'DE LA', 'DE LOS', 'DE LAS', 'AL', 'A LA', 'A LOS', 'A LAS', 'EL', 'LA', 'LOS', 'LAS')
INSTRUMENTS = {'TRATADO', 'TRATADOS', 'CONVENIO', 'CONVENIOS', 'CONVENCION', 'CONVENCIONES', 'ACUERDO', 'ACUERDOS',
               'PROTOCOLO', 'PROTOCOLOS', 'ENMIENDA', 'ENMIENDAS', 'ACTA', 'ACTAS', 'ANEXO', 'ANEXOS', 'DECLARACIONES'}
# One ordinal may precede the instrument word: 'el Segundo Protocolo Modificatorio', 'el Tercer Protocolo Adicional'.
ORDINALS = {'PRIMER', 'PRIMERO', 'PRIMERA', 'SEGUNDO', 'SEGUNDA', 'TERCER', 'TERCERO', 'TERCERA', 'CUARTO', 'CUARTA',
            'QUINTO', 'QUINTA', 'SEXTO', 'SEXTA', 'SEPTIMO', 'SEPTIMA', 'OCTAVO', 'OCTAVA', 'NOVENO', 'NOVENA', 'DECIMO',
            'DECIMA'}
CLAUSE = re.compile(r',\s*(?:adoptad|aprobad|celebrad|firmad|hech|suscrit)[oa]s?\b', re.IGNORECASE)
# Independent of the table: a decree that names a promulgation, or a decree with a conclusion clause.
LOOKS_LIKE = re.compile(r'\bDECRETO\b.*(?:\bPROMULGATORI[OA]S?\b|, ?(?:APROBAD|CELEBRAD)[OA]S? (?:EN|POR|MEDIANTE)\b'
                        r'|, ?(?:ADOPTAD|FIRMAD|HECH|SUSCRIT)[OA]S? (?:EN|EL|POR)\b)')


def classify(title):
    """(stage, instrument name as printed) for a treaty decree title, else None."""
    t = fold(title)
    for opening in _OPENINGS:
        if not t.startswith(opening + ' '):
            continue
        rest = t[len(opening) + 1:]
        art = next((a for a in ARTICLES if rest.startswith(a + ' ')), None)
        if art is not None and rest[len(art) + 1:].split(' ', 1)[0] in ORDINALS:  # the instrument word follows it
            rest = f"{art} {rest[len(art) + 1:].split(' ', 1)[-1]}"
        if art is None or rest[len(art) + 1:].split(' ', 1)[0].rstrip(',.') not in INSTRUMENTS:
            continue
        words, prefix = title.split(), f'{opening} {art}'
        cut = next((i for i in range(len(words) + 1) if fold(' '.join(words[:i])) == prefix), None)
        if cut is None:  # the printed words do not align with the folded opening: left unclassified (reported)
            return None
        name = ' '.join(words[cut:])
        m = CLAUSE.search(name)
        return STAGES[opening], (name[:m.start()] if m else name).rstrip(' .')
    return None


def reviewed(entry):
    """True only for the exact title a person reviewed: a corrected title under the same id is checked again."""
    seen = REVIEWED.get(entry['entry_id'])
    return seen is not None and seen[0] == hashlib.sha256(entry['title'].encode('utf-8')).hexdigest()


def _dof(entries):
    return [e for e in entries if e['source_id'] == SOURCE]


def unreconciled(entries):
    """DOF entry ids where the independent check and the table disagree: a title that looks like a treaty decree and
    is not classified, or one classified that does not look like one."""
    entries = [e for e in entries if not reviewed(e)]  # reviewed: the table's answer stands for that title
    return sorted(e['entry_id'] for e in _dof(entries)
                  if bool(LOOKS_LIKE.search(fold(e['title']))) != (classify(e['title']) is not None))


def instruments(entries):
    """One record per instrument (exact folded name), its notes ordered by official date."""
    out = {}
    for e in _dof(entries):
        found = classify(e['title'])
        if not found:
            continue
        stage, name = found
        rec = out.setdefault(fold(name), {'instrument': fold(name), 'notes': []})
        rec['notes'].append({'entry_id': e['entry_id'], 'published': e['dates'].get('published'), 'stage': stage,
                             'name_printed': name, 'title': e['title']})
    for rec in out.values():
        rec['notes'].sort(key=lambda n: (n['published'] or '', n['entry_id']))
    return [out[k] for k in sorted(out)]


def derive(catalog_dir, entries, manifest):
    """Rewrite <catalog_dir>/tratados/tratados.jsonl (one instrument per line, sorted) and add its reconciliation to
    the run's coverage. Returns the number of instruments."""
    rows = instruments(entries)
    d = Path(catalog_dir) / 'tratados'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'tratados.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n' for r in rows),
                                      encoding='utf-8')
    missed = unreconciled(entries)
    manifest['treaty_instruments'] = len(rows)
    manifest['coverage'].append({
        'source_id': 'mx.tratados', 'scope': 'decretos de tratado: chequeo independiente vs tabla fija',
        'expected': sum(1 for e in _dof(entries) if LOOKS_LIKE.search(fold(e['title']))),
        'extracted': sum(len(r['notes']) for r in rows), 'ok': not missed, 'entries': missed[:20]})
    return len(rows)
