"""NOM lineages from DOF titles (real titles, copied from the DOF) and the historic DOF pages the 1993 floor needs."""
import unittest

from rg.catalog import normas, sidof
from tests.test_catalog import FIX


def note(i, title, published):
    return {'entry_id': f'mx.dof:{i}', 'title': title, 'dates': {'published': published}}


REAL = [
    note(1, 'Respuesta a los comentarios recibidos respecto del Proyecto de Norma Oficial Mexicana PROY-NOM-137-SSA1-2024, '
            'Etiquetado de dispositivos médicos, publicado el 23 de abril de 2024.', '2025-11-03'),
    note(2, 'Norma Oficial Mexicana NOM-137-SSA1-2025, Etiquetado de dispositivos médicos.', '2026-01-15'),
    note(3, 'Norma Oficial Mexicana de Emergencia NOM-EM-007-ASEA- 2025, Distribución de Gas Licuado de Petróleo '
            '(cancela a la NOM-007-SESH-2010 Vehículos para el transporte y distribución de Gas L.P.).', '2025-10-01'),
    note(4, 'Aviso por el cual se prorroga por un plazo de seis meses la vigencia de la Norma Oficial Mexicana de '
            'Emergencia NOM-EM-007-ASEA-2025, Distribución de Gas Licuado de Petróleo.', '2026-04-01'),
    note(5, 'Aviso de consulta pública del Proyecto de Norma Oficial Mexicana PROY-NOM-011-SICT2/2025, Condiciones para '
            'el transporte de mercancías peligrosas embaladas/ envasadas en cantidades limitadas.', '2025-12-01'),
    note(6, 'Norma Oficial Mexicana NOM-008-TUR-2022, Que establece los elementos a que deben sujetarse los guías de '
            'turistas de carácter cultural (cancela la NOM-08-TUR-2002, Que establece los elementos).', '2025-10-20'),
    note(7, 'Aviso de consulta pública del Proyecto de Modificación de la Norma Oficial Mexicana NOM-157-SEMARNAT-2009, '
            'Que establece los elementos y procedimientos para instrumentar planes de manejo de residuos mineros.', '2025-10-10'),
    note(8, 'Fe de erratas a la Norma Oficial Mexicana NOM-037-SICT2-2026, Barreras de protección en carreteras y vías '
            'urbanas, publicada el 19 de mayo de 2026.', '2026-06-01'),
    note(9, 'Decreto por el que se reforma la Ley de Infraestructura de la Calidad.', '2025-11-01'),
    note(10, 'Modificación a la Norma Oficial Mexicana NOM-051-SCFI/SSA1-2010, Especificaciones generales de etiquetado '
             'para alimentos y bebidas no alcohólicas preenvasados-Información comercial y sanitaria.', '2020-03-27'),
    note(11, 'Norma Oficial Mexicana NOM-087-ECOL-SSA1-2002, Protección ambiental-Salud ambiental-Residuos peligrosos '
             'biológico-infecciosos-Clasificación y especificaciones de manejo.', '2003-02-17'),
    note(12, 'Norma Oficial Mexicana NOM-241- SSA1-2025, Buenas prácticas de fabricación de dispositivos médicos.', '2025-12-01'),
    note(13, 'Modificación a la Norma Oficial Mexicana NOM-021/3- SCT3-2010, Que establece los requerimientos que deben '
             'cumplir los helicópteros.', '2026-02-01'),
]

# Real DOF titles that failed coverage 'titulos con NOM sin codigo leido' in catalog run 39691250207 (2026-10-21),
# with their real entry ids and official dates.
REAL_SEPARATORS = [
    note(5638496, 'Respuestas a los comentarios recibidos durante el plazo de consulta pública, del Proyecto de Norma '
                  'Oficial Mexicana PROY-NOM-020-SCT2/-2020, Especificaciones generales para el diseño, construcción y '
                  'pruebas de autotanques destinados al autotransporte de substancias, materiales y residuos peligrosos, '
                  'especificaciones SCT 406, SCT 407 y SCT 412, publicado el 16 de diciembre de 2020.', '2021-12-16'),
    note(5763083, 'Respuesta a los comentarios recibidos al Proyecto de Norma Oficial Mexicana PROY-NOM-016ENER2024, '
                  'Eficiencia energética de motores de corriente alterna, trifásicos, de inducción, tipo jaula de ardilla, '
                  'en potencia nominal de 0.746 kW a 373 kW. Límites, método de prueba y marcado.', '2025-07-16'),
]


# Real DOF titles of 1993-2004 (one reprinted in 2017) that failed 'titulos con NOM sin codigo leido' on 2026-10-29
# (88 titles once the catalog reached 1993), with their real ids and official dates.
OLDER = [
    note(4670808, 'PROYECTO de Norma Oficial Mexicana NOM-051-SSA1-93, jeringas estériles desechables de plástico.',
         '1994-02-18'),
    note(4677076, 'PROYECTO de Norma Oficial Mexicana NOM-038-SSA I-1993, Bienes y servicios, materias primas para '
             'alimentos, productos de perfumería y belleza, colorantes orgánicos sintéticos y especificaciones '
             'sanitarias.',
         '1994-03-11'),
    note(4697265, 'RESPUESTA a los comentarios del Proyecto de Norma Oficial Mexicana NOM-005-SSA 2- 1993, de los '
             'Servicios de Planificación Familiar',
         '1994-05-20'),
    note(4732595, 'NORMA Oficial Mexicana (con carácter de emergencia) NOM-EM-004 FITO-1994, Requisitos '
             'fitosanitarios y procedimientos para la movilización de frutos cítricos para exportación y '
             'mercado nacional.',
         '1994-08-26'),
    note(4794338, 'NORMA Oficial Mexicana NOM-1811-SCFI-1993 Recipientes portátiles para contener gas L.P. no '
             'expuestos a calentamiento por medios artificiales - fabricación.',
         '1993-10-19'),
    note(4954245, 'Norma Oficial Mexicana Emergente NOM-EM-0000-SCT/3-99, Que establece medidas y actividades que '
             'los concesionarios y permisionarios de servicios de transporte aéreo y operadores de aeronaves, '
             'deben adoptar para asegurar que los sistemas de informática que se utilicen en sus aeronaves y '
             'que estén implicados en la operación, mantenimiento, comunicaciones y navegación a bordo de las '
             'mismas, no se afecten por el cambio al año 2000 y permitan la continuidad en la prestación de '
             'servicios con altos niveles de seguridad y calidad',
         '1999-09-20'),
    note(5469372, 'Proyecto de Modificación a la Norma Oficial Mexicana NOM-025/ 1-NUCL-2000, Requisitos para '
             'equipo de radiografía industrial. Parte 1: Requisitos generales',
         '2017-01-19'),
    note(4762178, 'PROYECTO de Norma Oficial Mexicana NOM-034-STPS, Higiene Industrial - Medio Ambiente Laboral - '
             'Determinación de Niebla de Aceite Mineral en el Aire - Método Espectrofotométrico de '
             'Fluorescencia.',
         '1993-07-21'),
    note(661160, 'Respuesta a los comentarios y modificaciones al Proyecto de Modificación a la Norma Oficial '
             'Mexicana PROY-NOM-013-2004, Que regula sanitariamente la importación de árboles de navidad '
             'naturales de las especies de los géneros Pinus y Abies y la especie Pseudotsuga menziesii, '
             'publicado el 21 de junio de 2004',
         '2004-09-27'),
]


class OlderPrintings(unittest.TestCase):
    def test_each_older_printing_yields_its_code_as_printed(self):
        want = {'mx.dof:4670808': ('NOM-051-SSA1', 1993, 'NOM-051-SSA1-93'),  # a year of two digits
                'mx.dof:4677076': ('NOM-038-SSAI', 1993, 'NOM-038-SSA I-1993'),  # SSA I is SSAI, never SSA1
                'mx.dof:4697265': ('NOM-005-SSA2', 1993, 'NOM-005-SSA 2- 1993'),
                'mx.dof:4732595': ('NOM-EM-004-FITO', 1994, 'NOM-EM-004 FITO-1994'),  # a space for the hyphen
                'mx.dof:4794338': ('NOM-1811-SCFI', 1993, 'NOM-1811-SCFI-1993'),  # four digits
                'mx.dof:4954245': ('NOM-EM-000-SCT/3', 1999, 'NOM-EM-0000-SCT/3-99'),
                'mx.dof:5469372': ('NOM-025/1-NUCL', 2000, 'NOM-025/ 1-NUCL-2000')}  # a space after the slash
        by = {e['entry_id']: e for e in OLDER}
        for i, code in want.items():
            with self.subTest(i):
                self.assertEqual([c[:3] for c in normas.codes(by[i]['title'])], [code])
        self.assertEqual(normas.unparsed(OLDER), [])

    def test_a_code_without_its_year_or_its_issuer_still_yields_nothing_and_its_review_holds_for_that_title(self):
        by = {e['entry_id']: e for e in OLDER}
        for i in ('mx.dof:4762178', 'mx.dof:661160'):  # NOM-034-STPS, PROY-NOM-013-2004
            with self.subTest(i):
                self.assertEqual(normas.codes(by[i]['title']), [])
                self.assertEqual(normas.unparsed([by[i]]), [])
                self.assertEqual(normas.unparsed([{**by[i], 'entry_id': 'mx.dof:99'}]), ['mx.dof:99'])

    def test_a_two_digit_year_outside_the_1990s_is_never_read(self):
        odd = [note(41, 'Norma Oficial Mexicana NOM-051-SSA1-05, texto construido.', '2006-01-01'),  # CONSTRUIDO
               note(42, 'Norma Oficial Mexicana NOM-052-SSA 1-05, texto construido.', '2006-01-01')]  # another old feature
        for e in odd:
            self.assertEqual(normas.codes(e['title']), [])
        self.assertEqual(normas.unparsed(odd), ['mx.dof:41', 'mx.dof:42'])

    def test_the_older_branch_changes_nothing_already_read(self):
        before = normas.lineages(REAL + REAL_SEPARATORS)
        new = {c[0] for e in OLDER for c in normas.codes(e['title'])}
        after = [r for r in normas.lineages(REAL + REAL_SEPARATORS + OLDER) if r['lineage'] not in new]
        self.assertEqual(after, before)


class Lineages(unittest.TestCase):
    def setUp(self):
        self.by = {r['lineage']: r for r in normas.lineages(REAL)}

    def test_project_and_standard_with_different_years_share_a_lineage(self):
        r = self.by['NOM-137-SSA1']
        self.assertEqual([(n['stage'], n['edition'], n['project']) for n in r['notes']],
                         [('respuesta_comentarios', 2024, True), ('norma', 2025, False)])
        self.assertEqual(r['editions'], [2024, 2025])

    def test_printed_variants_of_a_code_are_read_as_printed(self):
        self.assertIn('NOM-EM-007-ASEA', self.by)                  # 'NOM-EM-007-ASEA- 2025' (space in the source)
        self.assertIn('NOM-011-SICT2', self.by)                    # 'SICT2/2025' (slash in the source)
        self.assertEqual(self.by['NOM-011-SICT2']['notes'][0]['code_printed'], 'PROY-NOM-011-SICT2/2025')

    def test_stages_come_from_the_fixed_table(self):
        stages = {r['lineage']: [n['stage'] for n in r['notes']] for r in self.by.values()}
        self.assertEqual(stages['NOM-EM-007-ASEA'], ['norma_emergencia', 'prorroga'])
        self.assertEqual(stages['NOM-157-SEMARNAT'], ['consulta_proyecto_modificacion'])
        self.assertEqual(stages['NOM-037-SICT2'], ['fe_de_erratas'])
        self.assertEqual(normas.stage('Nota aclaratoria a la Norma Oficial Mexicana NOM-004-SAGARPA- 2018, Carne'), 'aclaracion')
        self.assertEqual(normas.stage('Algo sin tabla NOM-001-SE-2020'), 'OTRO')

    def test_compound_issuers_are_read_whole(self):
        # Audit of #8: codes with a compound issuer (SCFI/SSA1, ECOL-SSA1) were silently dropped.
        self.assertEqual([n['stage'] for n in self.by['NOM-051-SCFI/SSA1']['notes']], ['modificacion'])
        self.assertEqual(self.by['NOM-087-ECOL-SSA1']['editions'], [2002])
        self.assertIn('NOM-241-SSA1', self.by)         # space after the number, as printed
        self.assertIn('NOM-021/3-SCT3', self.by)       # sub-number, as printed

    def test_spaces_inside_a_compound_issuer_do_not_split_the_lineage(self):
        # Audit of #8 (REVISE 198ab49): the strip matched a literal backslash, not whitespace.
        spaced = [note(30, 'Aviso de cancelación de la Norma Oficial Mexicana NOM-051-SCFI/ SSA1-2010, Especificaciones.', '2026-05-01'),
                  note(31, 'Aclaración a la Norma Oficial Mexicana NOM-087-ECOL - SSA1-2002, Protección ambiental.', '2026-05-02')]
        by = {r['lineage']: r for r in normas.lineages(REAL + spaced)}
        self.assertEqual([n['entry_id'] for n in by['NOM-051-SCFI/SSA1']['notes']], ['mx.dof:10', 'mx.dof:30'])
        self.assertEqual([n['entry_id'] for n in by['NOM-087-ECOL-SSA1']['notes']], ['mx.dof:11', 'mx.dof:31'])
        self.assertEqual([k for k in by if ' ' in k], [])

    def test_a_reviewed_title_is_not_reported_and_a_new_one_like_it_is(self):
        # Real title (DOF 2020-01-03, mx.dof:5583405): «conforme a la NOM-046.», no issuer, no year (run of 2026-10-25).
        title = ('Convenio de Coordinación que celebran la Secretaría de Gobernación y el Estado de Guerrero, que tiene '
                 'por objeto el otorgamiento de subsidios para el proyecto Estrategias de fortalecimiento interinstitucional '
                 'para la Atención de la Declaratoria de Alerta de Violencia de Género- Desarrollar un Protocolo de Atención '
                 'Médica y Psicológica a Víctimas de Violencia Sexual Infantil, conforme a la NOM-046.')
        reviewed = {'entry_id': 'mx.dof:5583405', 'title': title, 'dates': {'published': '2020-01-03'}}
        self.assertIn('mx.dof:5583405', normas.REVIEWED)
        self.assertEqual(normas.unparsed([reviewed]), [])
        self.assertEqual(normas.unparsed([{**reviewed, 'entry_id': 'mx.dof:99'}]), ['mx.dof:99'])
        # GPT #44: the review holds for the title read, not for the id; a corrected title is checked again
        self.assertEqual(normas.unparsed([{**reviewed, 'title': title.replace('Guerrero', 'Oaxaca')}]), ['mx.dof:5583405'])

    def test_a_title_that_names_a_nom_but_yields_no_code_is_reported(self):
        odd = [note(20, 'Aviso de la NOM-5-XX-, texto truncado en la fuente.', '2026-01-01')]
        self.assertEqual(normas.unparsed(REAL + odd), ['mx.dof:20'])
        self.assertEqual(normas.unparsed(REAL), [])

    def test_relations_are_copied_from_the_title(self):
        self.assertEqual([(x['type'], x['to_lineage'], x['to_edition']) for x in self.by['NOM-EM-007-ASEA']['relations']],
                         [('cancela', 'NOM-007-SESH', 2010)])
        self.assertEqual([(x['type'], x['to_lineage'], x['to_edition']) for x in self.by['NOM-008-TUR']['relations']],
                         [('cancela', 'NOM-008-TUR', 2002)])           # '08' as printed, normalized to 008
        self.assertEqual(self.by['NOM-137-SSA1']['relations'], [])

    def test_titles_without_a_nom_code_are_not_standards(self):
        self.assertEqual(len(self.by), 10)
        self.assertFalse(normas.cites_nom(REAL[8]['title']))  # the decree without a NOM code
        self.assertTrue(normas.cites_nom(REAL[0]['title']))

    def test_written_file_is_sorted_and_complete(self):
        import json, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(normas.write(d, REAL), 10)
            rows = [json.loads(l) for l in (Path(d) / 'normas' / 'nom.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual([r['lineage'] for r in rows], sorted(r['lineage'] for r in rows))
            self.assertEqual(sum(len(r['notes']) for r in rows), 12)

    def test_the_lineage_file_is_not_read_back_as_catalog_rows(self):
        # Found while building #13: the run after normas.write died with KeyError 'entry_id' loading nom.jsonl.
        import tempfile
        from pathlib import Path
        from rg.catalog.store import Catalog
        with tempfile.TemporaryDirectory() as d:
            normas.write(Path(d) / 'mx', REAL)
            catalog = Catalog(d, 'mx')
            self.assertEqual((catalog.entries, catalog.previous(['mx.dof:1'])), ({}, {}))


class CodesAsPrinted(unittest.TestCase):
    """Run 39691250207: two real titles name a NOM with separators the parser did not read."""

    def test_two_separators_before_the_year(self):
        self.assertEqual([c[:4] for c in normas.codes(REAL_SEPARATORS[0]['title'])],
                         [('NOM-020-SCT2', 2020, 'PROY-NOM-020-SCT2/-2020', True)])  # 'SCT 406' is not a NOM code

    def test_no_separator_with_a_letters_only_issuer(self):
        self.assertEqual([c[:4] for c in normas.codes(REAL_SEPARATORS[1]['title'])],
                         [('NOM-016-ENER', 2024, 'PROY-NOM-016ENER2024', True)])

    def test_the_failed_titles_now_yield_a_code_and_a_lineage(self):
        self.assertEqual(normas.unparsed(REAL_SEPARATORS), [])
        self.assertEqual(normas.unparsed(REAL + REAL_SEPARATORS), [])
        by = {r['lineage']: r for r in normas.lineages(REAL + REAL_SEPARATORS)}
        self.assertEqual([(n['entry_id'], n['published'], n['stage'], n['edition'], n['project'])
                          for k in ('NOM-020-SCT2', 'NOM-016-ENER') for n in by[k]['notes']],
                         [('mx.dof:5638496', '2021-12-16', 'respuesta_comentarios', 2020, True),
                          ('mx.dof:5763083', '2025-07-16', 'respuesta_comentarios', 2024, True)])

    def test_the_new_forms_change_nothing_already_read(self):
        before = normas.lineages(REAL)
        after = [r for r in normas.lineages(REAL + REAL_SEPARATORS) if r['lineage'] not in ('NOM-020-SCT2', 'NOM-016-ENER')]
        self.assertEqual(after, before)

    def test_an_issuer_ending_in_a_digit_without_separator_is_never_guessed(self):
        # CONSTRUIDO (not a DOF title): 'SSA12024' is SSA1 + 2024 or SSA + 12024; nothing is read and the run reports it.
        odd = [note(40, 'Aviso relativo a la Norma Oficial Mexicana NOM-016SSA12024, texto construido.', '2026-01-01')]
        self.assertEqual(normas.codes(odd[0]['title']), [])
        self.assertEqual(normas.unparsed(odd), ['mx.dof:40'])


class RawPriority(unittest.TestCase):
    def test_standards_texts_are_fetched_first_then_newest(self):
        from rg.catalog.run import raw_priority
        pending = [note(1, 'Acuerdo por el que se da a conocer algo.', '2026-10-01'),
                   note(2, 'Norma Oficial Mexicana NOM-137-SSA1-2025, Etiquetado de dispositivos médicos.', '2025-01-01'),
                   note(3, 'Aviso de algo.', '2026-10-05'), {'entry_id': 'mx.dof:4', 'native_id': '4', 'dates': {}}]
        for e in pending:
            e.setdefault('native_id', e['entry_id'].split(':')[1])
        order = [e['native_id'] for e in sorted(pending, key=raw_priority, reverse=True)]
        self.assertEqual(order, ['2', '3', '1', '4'])


class RunCoverage(unittest.TestCase):
    def test_a_run_with_an_unreadable_nom_title_is_not_whole(self):
        import json, tempfile
        from pathlib import Path
        from unittest import mock
        from rg.catalog import run as runmod
        row = json.loads((FIX / 'catalog_row_ley.json').read_text(encoding='utf-8'))
        odd = {**row, 'entry_id': 'mx.dof:99', 'native_id': '99', 'source_id': 'mx.dof',
               'title': 'Aviso relativo a la NOM-5-XX-, texto truncado en la fuente.'}

        def execute(self_, sources):
            self_.catalog.entries[odd['entry_id']] = odd
            self_.manifest.update({'requests_total': 0, 'raw_new_files': 0, 'finished_at': 'x'})
            return self_.manifest
        with tempfile.TemporaryDirectory() as d, mock.patch.object(runmod.Run, 'execute', execute):
            rc = runmod.main(['--country', 'mx', '--out', d + '/out', '--raw', d + '/raw', '--today', '2026-10-22'])
            manifest = json.loads(next((Path(d) / 'out' / 'mx' / 'runs').glob('*.json')).read_text(encoding='utf-8'))
        self.assertEqual(rc, 3)
        self.assertIn('mx.dof:99', [x for c in manifest['coverage'] if not c['ok'] for x in c.get('entries', [])])


class HistoricDof(unittest.TestCase):
    def test_pages_back_to_1994_parse_whole_with_their_official_date(self):
        # The 1993 floor depends on SIDOF serving old days in the same format (checked 2026-10-20: 1994, 1999).
        for name, day, listed in (('sidof_day_1999-03-01_historic.html', '1999-03-01', 58),
                                  ('sidof_day_1994-06-02_historic.html', '1994-06-02', 39)):
            page = (FIX / name).read_text(encoding='utf-8', errors='replace')
            items = sidof.parse_day(page)
            self.assertEqual((len(items), sidof.count_listed(page)), (listed, listed), name)
            self.assertEqual({i['published'] for i in items}, {day}, name)


if __name__ == '__main__':
    unittest.main()
