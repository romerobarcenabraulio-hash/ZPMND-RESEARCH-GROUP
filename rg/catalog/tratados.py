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

Second check, by the DOF's own filing (category.issuer, not the title): every decree the Foreign Ministry files whose
title opens with an act on an instrument (promulga, aprueba, sin efectos, denuncia) must be classified, except a
programme it approves; one that is not fails the run's coverage too (desk()).
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
    # Forms of the DOF back to 1993, read since the catalog reached it (run of 2026-10-29, 1484 vs 1561): each with a
    # note it reads. 'DECRETO de Promulgación del Convenio ...' (mx.dof:4863233), its amendments (mx.dof:4796074),
    # 'Fe de errata' in the singular (mx.dof:670047), modifications promulgated as such (mx.dof:2044527)
    'DECRETO DE PROMULGACION': 'promulgacion',
    'DECRETO DE PROMULGACION DE LAS ENMIENDAS': 'enmienda',
    'DECRETO PROMULGATORIO DE LAS MODIFICACIONES': 'enmienda',
    'DECRETO PROMULGATORIO DE LA ADHESION': 'promulgacion',
    'FE DE ERRATA AL DECRETO PROMULGATORIO': 'fe_de_erratas',
    'FE DE ERRATAS AL DECRETO DE PROMULGACION': 'fe_de_erratas',
    'ACLARACION AL DECRETO DE PROMULGACION': 'aclaracion',
    'DECRETO POR EL QUE SE DAN A CONOCER LAS MODIFICACIONES': 'enmienda',  # mx.dof:5214869
    'DECRETO POR EL QUE SE APRUEBAN LOS AJUSTES': 'enmienda',  # mx.dof:4863802
    'DECRETO POR EL QUE SE APRUEBAN LAS FRACCIONES ARANCELARIAS OMITIDAS Y CORRECCIONES': 'enmienda',  # mx.dof:4992224
    'DECRETO PROMULGATORIO DE LAS FRACCIONES ARANCELARIAS OMITIDAS Y CORRECCIONES': 'enmienda',  # mx.dof:5008781
    'DECRETO POR EL QUE SE APRUEBA EL TEXTO': 'aprobacion_senado',  # mx.dof:4710809
    'DECRETO POR EL QUE SE APRUEBAN LOS TEXTOS': 'aprobacion_senado',  # mx.dof:4768363
    'DECRETO POR EL QUE SE APRUEBA EL NUEVO TEXTO REVISADO': 'aprobacion_senado',  # mx.dof:4958611
    'DECRETO POR EL QUE SE APRUEBA LA ADHESION': 'aprobacion_senado',  # mx.dof:737415
    'DECRETO POR EL QUE SE APRUEBA LA ADHESION DE LOS ESTADOS UNIDOS MEXICANOS': 'aprobacion_senado',  # mx.dof:5249361
    'DECRETO POR EL QUE SE APRUEBA EN SUS TERMINOS,': 'aprobacion_senado',  # mx.dof:5422787
    'DECRETO POR QUE SE APRUEBA': 'aprobacion_senado',  # printed so, mx.dof:5197492
    'DECRETO POR EL SE APRUEBAN': 'aprobacion_senado',  # printed so, mx.dof:788545
    # a treaty that ceases to have effect: 'Decreto por el cual el Convenio ... quedará sin efectos' (mx.dof:2035614)
    'DECRETO POR EL CUAL': 'retiro_o_denuncia',
    'DECRETO MEDIANTE EL CUAL': 'retiro_o_denuncia',  # mx.dof:755949
    'DECRETO POR EL QUE SE DETERMINA QUE': 'retiro_o_denuncia',  # mx.dof:4937867
    'DECRETO POR EL QUE SE DEJA SIN EFECTOS': 'retiro_o_denuncia',  # mx.dof:5145313
    'DECRETO POR EL QUE SE DEJA SIN EFECTOS EN LOS ESTADOS UNIDOS MEXICANOS': 'retiro_o_denuncia',  # mx.dof:4871130
    'DECRETO PROMULGATORIO DE LA DENUNCIA DE LOS ESTADOS UNIDOS MEXICANOS': 'retiro_o_denuncia',  # mx.dof:5155445
    'DECRETO POR EL QUE SE APRUEBA EL RETIRO PARCIAL': 'retiro_o_denuncia',  # mx.dof:737416
    'DECRETO DE LA CAMARA DE SENADORES DEL H. CONGRESO DE LA UNION, POR EL QUE SE APRUEBA': 'aprobacion_senado',  # mx.dof:4752727
    'DECRETO DE LA CAMARA DE SENADORES DEL H. CONGRESO DE LA UNION POR EL QUE SE APRUEBA': 'aprobacion_senado',  # mx.dof:4752778
    'DECRETO POR EL QUE SE APRUEBA LA SOLICITUD DEL EJECUTIVO FEDERAL PARA LA ADHESION DE NUESTRO PAIS': 'aprobacion_senado',  # mx.dof:676828
    'ACLARACION AL DECRETO POR EL QUE SE APRUEBAN': 'aclaracion',  # mx.dof:4875250
    'CONTINUACION DEL TEXTO DEL DECRETO DE PROMULGACION DE LAS ENMIENDAS': 'enmienda',  # mx.dof:4796377
    'DECRETO PROMULGATORIO DE LA ORGANIZACION': 'promulgacion',  # 'de la Organización del Convenio Andrés Bello', mx.dof:2082205
    'DECRETO POR EL QUE SE APRUEBA LA ORGANIZACION': 'aprobacion_senado',  # mx.dof:789062
    'DECRETO PROMULGATORIO POR EL QUE SE ADOPTA EN LA CIUDAD DE GINEBRA, SUIZA,': 'enmienda',  # mx.dof:4893879
    'DECRETO POR EL QUE SE AUTORIZA, POR ESTAR CONFORME CON LA CONSTITUCION POLITICA DE LOS ESTADOS UNIDOS MEXICANOS,':
        'aprobacion_senado',  # mx.dof:676831
}
_OPENINGS = sorted(STAGES, key=len, reverse=True)
# Disagreements a person reviewed (entry id -> sha256 of the exact title read, why the table's answer stands).
# Only notes, never patterns; the review holds for that title only.
# The two MARPOL annexes reviewed here until 2026-10-29 (mx.dof:5636928, 5636929) reconcile on their own since the
# title check reads an approval that names an Annex.
REVIEWED = {
    # The DOF back to 1993 (2026-10-29). Titles that name articles of an instrument, not the instrument: reading
    # ARTICULO as one would rename 19 amendments already read. Left out of the view, each one here.
    'mx.dof:4719647': ('e6d330bb18849a1c9dc5e154582002f31910c8a4bb67052b11df85a8db5e6e1c',
                       'aprueba el texto de los ajustes a los artículos 2A y 2B del Protocolo de Montreal'),
    'mx.dof:5078128': ('14402ceb1a644e60149b4ccbce1e9e7e723014128f2064e29c93441d7afd3471',
                       'promulga el artículo 11 de un convenio de servicios aéreos con Hong Kong'),
    'mx.dof:5129541': ('a847a619d75b3a79c7762cc765215b99becd83826e935038758fca27eb6757b0',
                       'aprueba ajustes de traducción a artículos de un acuerdo fiscal con la India'),
    'mx.dof:762740': ('89ccb941b6d91b63db13fe7004f0471b6b9a12789de4fecdee328c3ab912bad4',
                      'promulga la modificación de los artículos 24 y 25 de la Constitución de la OMS'),
    'mx.dof:770677': ('d633a173b0d9e5c3bfef62f859fb03d87a6dc4d1f02470c661f67f8ffa9e12a4',
                      'aprueba la modificación de los artículos 24 y 25 de la Constitución de la OMS'),
    'mx.dof:5672145': ('5b1afa18013f0e568eb3444b473e454681cf5836b00e184c1c954d01e3308c03',
                       'aprueba el estatus de la lista de reservas de la Convención Multilateral BEPS: abre con el '
                       'estatus, no con el instrumento; fuera de la vista'),
    'mx.dof:5759498': ('afde311484b1402258228cbef63a3c10a2bb9f92925649cda539d9e3f7f8081a',
                       'reforma un decreto aprobatorio y aprueba una enmienda en el mismo título; fuera de la vista'),
    'mx.dof:4720018': ('bbe8a1f6a2c7ac75bfd7c42311c3fcd79d75c0ac52bb4708d33712517823f684',
                       'convenio amistoso de límites entre el Estado de México y el Distrito Federal: doméstico (DOMESTIC)'),
    'mx.dof:5339485': ('b573407377cd094967eef4f4c0cebbfda126e743295f403e0fde6c9ba9bf926f',
                       'elección de consejeros del INE «aprobado por la Cámara de Diputados»: no es un tratado'),
}
ARTICLES = ('DEL', 'DE LA', 'DE LOS', 'DE LAS', 'AL', 'A LA', 'A LOS', 'A LAS', 'EL', 'LA', 'LOS', 'LAS')
# The words added below (|=) come from the DOF back to 1993 (Arreglo de Locarno, Estatuto de Roma, Decisiones de
# la UPU, the Constitution of an international organization, a Memorándum, Notas intercambiadas, a Reserva...). A word
# that would change a title already read is not one: ARTICULO turned 19 amendments into the article's name.
INSTRUMENTS = {'TRATADO', 'TRATADOS', 'CONVENIO', 'CONVENIOS', 'CONVENCION', 'CONVENCIONES', 'ACUERDO', 'ACUERDOS',
               'PROTOCOLO', 'PROTOCOLOS', 'ENMIENDA', 'ENMIENDAS', 'ACTA', 'ACTAS', 'ANEXO', 'ANEXOS', 'DECLARACIONES'}
INSTRUMENTS |= {'ARREGLO', 'CONSTITUCION', 'CONVENIO-MARCO', 'DECISION', 'DECISIONES', 'DECLARACION', 'ESTATUTO', 'ESTATUTOS',
                'INSTRUMENTO', 'INSTRUMENTOS', 'MANDATO', 'MEMORANDUM', 'MODIFICACIONES', 'NOTAS', 'RECOMENDACION',
                'RESERVA', 'RESOLUCION', 'RESOLUCIONES'}
# A word that is also a Mexican legal form counts only as a name in this fixed table (GPT on 2421f83: 'se aprueba el
# Reglamento Interior de la Secretaría de Salud' is no treaty). The only international reglamentos the DOF has printed
# back to 1993 are the UPAEP's (mx.dof:4906649, 4863279); a new one is left unclassified and the check reports it.
NAMED = {'REGLAMENTO': ('REGLAMENTO GENERAL Y DE LAS RESOLUCIONES DE LA UNION POSTAL DE LAS AMERICAS',
                        'REGLAMENTO GENERAL Y LAS RESOLUCIONES DE LA UNION POSTAL DE LAS AMERICAS')}
# One ordinal may precede the instrument word: 'el Segundo Protocolo Modificatorio', 'el Tercer Protocolo Adicional'.
ORDINALS = {'PRIMER', 'PRIMERO', 'PRIMERA', 'SEGUNDO', 'SEGUNDA', 'TERCER', 'TERCERO', 'TERCERA', 'CUARTO', 'CUARTA',
            'QUINTO', 'QUINTA', 'SEXTO', 'SEXTA', 'SEPTIMO', 'SEPTIMA', 'OCTAVO', 'OCTAVA', 'NOVENO', 'NOVENA', 'DECIMO',
            'DECIMA'}
# and the compound ones: 'el Decimoquinto Protocolo Modificatorio' (mx.dof:774728), 'Vigesimosegundo'
ORDINALS |= {f'{ten}{unit}' for ten in ('DECIMO', 'VIGESIMO', 'TRIGESIMO') for unit in ORDINALS if not unit.startswith('DECIM')}
ORDINALS |= {'UNDECIMO', 'UNDECIMA', 'DUODECIMO', 'DUODECIMA', 'VIGESIMO', 'VIGESIMA', 'TRIGESIMO', 'TRIGESIMA'}
CLAUSE = re.compile(r',\s*(?:adoptad|aprobad|celebrad|firmad|hech|suscrit)[oa]s?\b', re.IGNORECASE)
# Independent of the table: a decree that names a promulgation, or a decree with a conclusion clause.
# Goods imported under a treaty ('mercancías que se importen al amparo del Acuerdo ...', mx.dof:4740197) are a tariff
# measure, not an act on the treaty. An approval names an instrument word anywhere in the title, not only right after
# the article (the table's rule); what the title alone cannot tell apart is the issuer's to check (desk() below).
LOOKS_LIKE = re.compile(r'^(?!.*\bIMPORTEN AL AMPARO DE)\b.*\bDECRETO\b.*'
                        r'(?:\bPROMULGATORI[OA]S?\b|(?<=DECRETO) DE PROMULGACION\b'
                        r'|\bSE APRUEBAN?\b.*\b(?:TRATADOS?|CONVENIOS?|CONVENCION(?:ES)?|ACUERDOS?|PROTOCOLOS?|ENMIENDAS?|ACTAS?'
                        r'|ANEXOS?|ESTATUTOS?|ARREGLOS?|MEMORANDUM|MANDATO|PACTO|CARTA|RESOLUCION(?:ES)?|DECISION(?:ES)?'
                        r'|RECOMENDACION|DECLARACION(?:ES)?|INSTRUMENTOS?|MODIFICACIONES|NOTAS|RESERVA|REGLAMENTO'
                        r'|CONSTITUCION(?! POLITICA))\b'
                        r'|, ?(?:APROBAD|CELEBRAD)[OA]S? (?:EN|POR|MEDIANTE)\b'
                        r'|, ?(?:ADOPTAD|FIRMAD|HECH|SUSCRIT)[OA]S? (?:EN|EL|POR)\b)')


# Constitución, art. 46: two states settle their limits by 'convenios amistosos' the Congress approves; the DOF
# prints the approval like a treaty's ('Decreto por el que se aprueba el Convenio Amistoso ...', mx.dof:4720018).
DOMESTIC = ('CONVENIO AMISTOSO',)
# Openings that say only 'the decree by which the Convenio ...': a termination only in the fixed form all 13 such notes
# in the DOF back to 1993 print, the instrument's own verb after its clause: ', quedará sin efectos en los Estados Unidos
# Mexicanos, a partir del ...', 'en México a partir del' (mx.dof:5094444), 'entre los Estados Unidos Mexicanos y la
# República Bolivariana de Venezuela, a partir del' (4937867). 'Sin efectos' anywhere else ('se modifica para dejar sin
# efectos su artículo 2', GPT on 2421f83) is no termination: left unclassified, so the check reports it.
ENDING = {'DECRETO POR EL CUAL', 'DECRETO MEDIANTE EL CUAL', 'DECRETO POR EL QUE SE DETERMINA QUE'}
ENDS = re.compile(r', QUEDA(?:RA)? SIN EFECTOS? (?:EN LOS ESTADOS UNIDOS MEXICANOS|EN MEXICO|ENTRE LOS ESTADOS UNIDOS '
                  r'MEXICANOS Y [^,]+),? A PARTIR DEL? ')
# The desks the DOF files treaty decrees under; only the Foreign Ministry's are checked against the table (desk()):
# every decree it files that opens with an act on an instrument is a treaty note, except a programme it approves.
DESK = 'SECRETARIA DE RELACIONES EXTERIORES'
ACT = re.compile(r'^(?!.*\bSE APRUEBA EL PROGRAMA\b)(?:(?:FE DE ERRATAS?|ACLARACION) AL? |CONTINUACION DEL TEXTO DEL )?'
                 r'DECRETO\b.{0,120}?\b(?:PROMULGA\w*|SE APRUEBAN?|SIN EFECTOS?|DENUNCIA)\b')


def classify(title):
    """(stage, instrument name as printed) for a treaty decree title, else None."""
    t = fold(title)
    for opening in _OPENINGS:
        if not t.startswith(opening + ' '):
            continue
        if opening in ENDING and not ENDS.search(t):  # 'por el cual el Convenio ... se modifica' is no termination
            continue
        rest = t[len(opening) + 1:]
        art = next((a for a in ARTICLES if rest.startswith(a + ' ')), None)
        if art is not None and rest[len(art) + 1:].split(' ', 1)[0] in ORDINALS:  # the instrument word follows it
            rest = f"{art} {rest[len(art) + 1:].split(' ', 1)[-1]}"
        if art is None or rest[len(art) + 1:].split(' ', 1)[0].rstrip(',.') not in INSTRUMENTS:
            if art is None or not rest[len(art) + 1:].startswith(NAMED.get(rest[len(art) + 1:].split(' ', 1)[0], ())):
                continue  # a word that is also a Mexican legal form counts only as one of its NAMED forms
        words, prefix = title.split(), f'{opening} {art}'
        cut = next((i for i in range(len(words) + 1) if fold(' '.join(words[:i])) == prefix), None)
        if cut is None:  # the printed words do not align with the folded opening: left unclassified (reported)
            return None
        name = ' '.join(words[cut:])
        if fold(name).startswith(DOMESTIC):  # an agreement between Mexican states, not a treaty
            return None
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


def desk(entries):
    """DOF entry ids filed by the Foreign Ministry (category.issuer, the DOF's own filing, not the title's words) whose
    title opens with an act on an instrument and that the table does not classify: the check that does not read the
    title the way the table does. A reviewed title (REVIEWED) is not reported."""
    return sorted(e['entry_id'] for e in _dof(entries) if not reviewed(e)
                  and (e.get('category') or {}).get('issuer') == DESK and ACT.match(fold(e['title']))
                  and classify(e['title']) is None)


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
    filed = desk(entries)
    manifest['coverage'].append({
        'source_id': 'mx.tratados', 'scope': 'decretos de la SRE con acto sobre un instrumento: emisor vs tabla fija',
        'expected': sum(1 for e in _dof(entries) if (e.get('category') or {}).get('issuer') == DESK and ACT.match(fold(e['title']))),
        'extracted': sum(1 for e in _dof(entries) if (e.get('category') or {}).get('issuer') == DESK and ACT.match(fold(e['title']))
                         and classify(e['title']) is not None),
        'ok': not filed, 'entries': filed[:20]})
    return len(rows)
