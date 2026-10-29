"""Treaties from DOF titles: fixed table of openings, name copied from the title, exact grouping, independent check.

REAL titles are copied verbatim from the local DOF catalog (2025-09-24 to 2026-10-20: the only treaty decrees in it);
VARIANTES, verbatim from the catalog back to 2017, are the ones the run of 2026-10-25 found unclassified.
Stages that do not occur in that window (enmienda, denuncia, fe de erratas) use constructed titles, marked as such.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rg.catalog import tratados


def note(i, title, published, source_id='mx.dof'):
    return {'entry_id': f'{source_id}:{i}', 'source_id': source_id, 'title': title, 'dates': {'published': published}}


TPP = ('Protocolo de Adhesión del Reino Unido de Gran Bretaña e Irlanda del Norte al Tratado Integral y Progresista de '
       'Asociación Transpacífico')
BBNJ = ('Acuerdo en el marco de la Convención de las Naciones Unidas sobre el Derecho del Mar relativo a la Conservación '
        'y el Uso Sostenible de la Diversidad Biológica Marina de las Zonas Situadas fuera de la Jurisdicción Nacional')
REAL = [
    note(5776517, 'Decreto por el que se aprueba el Convenio 176 y la Recomendación 183 sobre Seguridad y Salud en las '
                  'Minas, adoptados en Ginebra, el veintidós de junio de mil novecientos noventa y cinco.', '2025-12-18'),
    note(5778417, f'Decreto Promulgatorio del {BBNJ}, adoptado en Nueva York, el diecinueve de junio de dos mil '
                  'veintitrés.', '2026-01-16'),
    note(5778477, f'Decreto por el que se aprueba el {TPP}, hecho en Auckland y Bandar Seri Begawan, el dieciséis de '
                  'julio de dos mil veintitrés.', '2026-01-20'),
    note(5791357, f'Decreto Promulgatorio del {TPP}, hecho en Auckland y Bandar Seri Begawan, el dieciséis de julio de '
                  'dos mil veintitrés.', '2026-06-22'),
]
NOT_TREATIES = [  # real DOF titles that open like an approval decree or name a treaty, and are not treaty decrees
    note(5776837, 'Decreto por el que se aprueba el Programa Sectorial de Energía 2025-2030.', '2025-12-22'),
    note(5770599, 'Decreto por el que se aprueba el Informe que presenta el Ejecutivo Federal de las actividades '
                  'desarrolladas por la Guardia Nacional durante el año inmediato anterior, de conformidad a lo '
                  'establecido en los artículos 86 al 89 de la Ley de la Guardia Nacional, y en cumplimiento a lo '
                  'dispuesto en el artículo 76, fracción IV, de la Constitución Política de los Estados Unidos '
                  'Mexicanos.', '2025-10-22'),
    note(5771627, 'Decreto por el que se establecen directrices de actuación para la identificación de los '
                  'procedimientos de contrataciones públicas que deben llevarse bajo la cobertura de tratados '
                  'comerciales, así como en materia de contenido nacional.', '2025-10-31'),
    note(5801249, 'Acuerdo por el que se da a conocer la Decisión No. 129 de la Comisión Administradora del Tratado de '
                  'Libre Comercio entre los Estados Unidos Mexicanos y la República de Colombia, adoptada el 14 de '
                  'septiembre de 2026.', '2026-10-15'),
    note(5785985, 'Acuerdo Secretarial Núm. 42/2026 por el que se dan a conocer a la comunidad marítima y al público en '
                  'general, las enmiendas al Convenio Internacional para Prevenir la Contaminación por los Buques, 1973 '
                  'y su Protocolo, 1978 (MARPOL 73/78).', '2026-04-27'),
]
# Constructed forms (not in the local catalog's window), built on the real names above.
ENMIENDA = note(1, f'Decreto Promulgatorio de las Enmiendas al {BBNJ}, adoptadas en Nueva York, el uno de marzo de dos '
                   'mil veintiséis.', '2026-09-01')
ENMIENDA_ARTICULOS = note(2, 'Decreto Promulgatorio de las Enmiendas a los Artículos 2 y 4 del Convenio Constitutivo X, '
                             'adoptadas en Washington, el dos de mayo de dos mil veinticinco.', '2026-02-01')
ERRATA = note(3, 'Fe de erratas al Decreto Promulgatorio del PROTOCOLO DE ADHESION del Reino Unido de Gran Bretaña e '
                 'Irlanda del Norte al Tratado Integral y Progresista de  Asociacion Transpacifico, hecho en Auckland y '
                 'Bandar Seri Begawan, el dieciséis de julio de dos mil veintitrés, publicado el 22 de junio de 2026.',
              '2026-06-30')
DENUNCIA = note(4, 'Decreto por el que se aprueba la Denuncia del Tratado de Ejemplo entre los Estados Unidos Mexicanos '
                   'y la República X, firmado en la Ciudad de México, el tres de abril de mil novecientos noventa.',
                '2026-03-01')
SIN_CLAUSULA = note(5, 'Decreto Promulgatorio del Tratado de Extradición entre los Estados Unidos Mexicanos y la '
                       'República X.', '2026-04-01')
SEGUNDO = note(6, 'Decreto Promulgatorio del Segundo Protocolo Adicional al Convenio X, hecho en Roma, el uno de enero '
                  'de dos mil veinticinco.', '2026-05-01')
LIMITES = note(7, 'Decreto por el que se aprueba el Convenio Amistoso para el arreglo de límites entre los Estados de A '
                  'y B.', '2026-05-02')
# Real DOF titles (2017-2022) the table missed until the run of 2026-10-25 (coverage 230/245): an ordinal before the
# instrument, Acta / Anexo / Declaraciones, «se da a conocer la denuncia», «Promulgatorio con», «aprobado/celebrado en».
VARIANTES = [
    note(5487418, 'Decreto por el que se aprueba el Segundo Protocolo Modificatorio al Acuerdo entre el Gobierno de los Estados Unidos Mexicanos y el Gobierno de los Estados Unidos de América sobre el Establecimiento de la Comisión de Cooperación Ecológica Fronteriza y el Banco de Desarrollo de América del Norte, hecho en Washington, D.C. y en la Ciudad de México el diecisiete de enero y el dieciocho de abril de dos mil diecisiete, respectivamente.',
         '2017-06-20'),
    note(5528819, 'Decreto por el que se aprueba La Enmienda del Protocolo de Montreal relativo a las Sustancias que Agotan la Capa de Ozono, aprobada en Kigali, el quince de octubre de dos mil dieciséis.',
         '2018-06-22'),
    note(5545342, 'Decreto por el que se da a conocer la denuncia del Acuerdo entre el Gobierno de los Estados Unidos Mexicanos y el Gobierno de la República de la India para la Promoción y Protección de las Inversiones, hecho en la ciudad de Nueva Delhi, el veintiuno de mayo de dos mil siete.',
         '2018-11-30'),
    note(5584211, 'Decreto por el que se aprueba el Acta de Ginebra del Arreglo de la Haya relativo al Registro Internacional de Dibujos y Modelos Industriales, adoptada en Ginebra el dos de julio de mil novecientos noventa y nueve.',
         '2020-01-17'),
    note(5584213, 'Decreto por el que se aprueban las Declaraciones del Estado Mexicano al Acta de Ginebra del Arreglo de la Haya relativo al Registro Internacional de Dibujos y Modelos Industriales, adoptada en Ginebra el dos de julio de mil novecientos noventa y nueve.',
         '2020-01-17'),
    note(5594545, 'Decreto Promulgatorio con las declaraciones correspondientes por parte del Estado Mexicano en la adhesión al Acta de Ginebra del Arreglo de La Haya relativo al Registro Internacional de Dibujos y Modelos Industriales.',
         '2020-06-05'),
    note(5616645, 'Decreto por el que se aprueba el Acuerdo relativo al Artículo 12 del Acuerdo de Continuidad Comercial entre los Estados Unidos Mexicanos y el Reino Unido de la Gran Bretaña e Irlanda del Norte, celebrado mediante intercambio de cartas fechadas en la Ciudad de México el veintinueve de diciembre de dos mil veinte.',
         '2021-04-23'),
    note(5668505, 'Decreto Promulgatorio del Anexo III Reglas para Prevenir la Contaminación por Sustancias Perjudiciales Transportadas por Mar en Bultos del Convenio Internacional para Prevenir la Contaminación por los Buques, 1973, modificado por el Protocolo de 1978, enmendado.',
         '2022-10-14'),
    note(5723225, 'Decreto por el que se aprueba el Acuerdo Internacional del Café de 2022, aprobado en Londres, Reino Unido, el nueve de junio de dos mil veintidós.',
         '2024-04-12'),
    note(5526722, 'Decreto por el que se aprueba el Acuerdo entre los Estados Unidos Mexicanos y la Unión Europea por el que se Modifica el Anexo III de la Decisión 2/2000 del Consejo Conjunto CE-México del 23 de marzo de 2000, celebrado por intercambio de cartas fechadas en las ciudades de Bruselas y México, el dieciocho de septiembre de dos mil diecisiete.',
         '2018-06-18'),
    note(5636928, 'Decreto por el que se aprueba el Anexo III "Reglas para Prevenir la Contaminación por Sustancias Perjudiciales Transportadas por Mar en Bultos" del Convenio Internacional para Prevenir la Contaminación por los Buques, 1973, modificado por el Protocolo de 1978.',
         '2021-12-01'),
    note(5636929, 'Decreto por el que se aprueba el Anexo IV "Reglas para Prevenir la Contaminación por las Aguas Sucias de los Buques" del Convenio Internacional para Prevenir la Contaminación por los Buques, 1973, modificado por el Protocolo de 1978.',
         '2021-12-01'),
]
# CONSTRUIDO: a promulgation of something outside the table (a Memorándum was until 2026-10-29: mx.dof:2051858)
MEMORANDO = note(9, 'Decreto Promulgatorio del Comunicado Conjunto X, hecho en Roma, el uno de enero de dos mil '
                   'veinticinco.', '2026-05-04')
# CONSTRUIDO: a form the table reads and the title check does not (the real ones carry a conclusion clause)
SIN_EFECTO = note(11, 'Decreto por el cual el Convenio de Ejemplo entre los Estados Unidos Mexicanos y la República X, '
                      'quedará sin efectos en los Estados Unidos Mexicanos, a partir del uno de enero de dos mil '
                      'veintisiete.', '2026-05-06')
DESALINEADO = note(8, 'Decreto Promulgatorio del´Acuerdo X, hecho en Roma, el uno de enero de dos mil veinticinco.',
                   '2026-05-03')


class Classify(unittest.TestCase):
    def test_real_titles_give_stage_and_the_name_as_printed(self):
        self.assertEqual([tratados.classify(e['title']) for e in REAL], [
            ('aprobacion_senado', 'Convenio 176 y la Recomendación 183 sobre Seguridad y Salud en las Minas'),
            ('promulgacion', BBNJ), ('aprobacion_senado', TPP), ('promulgacion', TPP)])

    def test_a_decree_that_approves_something_else_is_not_a_treaty(self):
        self.assertEqual([tratados.classify(e['title']) for e in NOT_TREATIES], [None] * len(NOT_TREATIES))

    def test_longest_opening_followed_by_an_instrument_wins(self):
        self.assertEqual(tratados.classify(ENMIENDA['title']), ('enmienda', BBNJ))
        self.assertEqual(tratados.classify(DENUNCIA['title']),
                         ('retiro_o_denuncia', 'Tratado de Ejemplo entre los Estados Unidos Mexicanos y la República X'))
        # 'Enmiendas a los Artículos...' is not followed by an instrument: the shorter opening takes it, name whole
        self.assertEqual(tratados.classify(ENMIENDA_ARTICULOS['title']),
                         ('promulgacion', 'Enmiendas a los Artículos 2 y 4 del Convenio Constitutivo X'))
        self.assertEqual(tratados.classify(ERRATA['title'])[0], 'fe_de_erratas')

    def test_without_a_conclusion_clause_the_name_runs_to_the_end_without_its_period(self):
        self.assertEqual(tratados.classify(SIN_CLAUSULA['title']),
                         ('promulgacion', 'Tratado de Extradición entre los Estados Unidos Mexicanos y la República X'))

    def test_printed_words_that_do_not_align_with_the_opening_are_left_unclassified(self):
        self.assertIsNone(tratados.classify(DESALINEADO['title']))  # '´' folds to a space: no name is guessed


class Instruments(unittest.TestCase):
    def test_grouped_by_exact_folded_name_and_ordered_by_official_date(self):
        rows = tratados.instruments(list(reversed(REAL)) + NOT_TREATIES)
        self.assertEqual(len(rows), 3)
        self.assertEqual([r['instrument'] for r in rows], sorted(r['instrument'] for r in rows))
        tpp = next(r for r in rows if r['instrument'].startswith('PROTOCOLO DE ADHESION'))
        self.assertEqual([(n['entry_id'], n['stage']) for n in tpp['notes']],
                         [('mx.dof:5778477', 'aprobacion_senado'), ('mx.dof:5791357', 'promulgacion')])

    def test_case_accents_and_spaces_do_not_split_an_instrument_but_other_words_do(self):
        rows = {r['instrument']: r for r in tratados.instruments(REAL + [ERRATA, ENMIENDA, ENMIENDA_ARTICULOS])}
        tpp = next(r for k, r in rows.items() if k.startswith('PROTOCOLO DE ADHESION'))
        self.assertEqual([n['stage'] for n in tpp['notes']], ['aprobacion_senado', 'promulgacion', 'fe_de_erratas'])
        bbnj = next(r for k, r in rows.items() if k.startswith('ACUERDO EN EL MARCO'))
        self.assertEqual([n['stage'] for n in bbnj['notes']], ['promulgacion', 'enmienda'])
        self.assertEqual(len(rows), 4)  # the articles' amendments stay their own instrument

    def test_only_dof_entries_count(self):
        other = note(9, REAL[3]['title'], '2026-07-01', source_id='mx.ojn-estatal')
        self.assertEqual(sum(len(r['notes']) for r in tratados.instruments(REAL + [other])), 4)
        self.assertEqual(tratados.unreconciled(REAL + [other, {**LIMITES, 'source_id': 'mx.ojn-estatal'}]), [])


class IndependentCheck(unittest.TestCase):
    def test_real_catalog_titles_reconcile(self):
        self.assertEqual(tratados.unreconciled(REAL + NOT_TREATIES), [])

    def test_a_treaty_decree_the_table_does_not_classify_is_reported(self):
        self.assertEqual(tratados.unreconciled(REAL + [MEMORANDO, DESALINEADO]), ['mx.dof:8', 'mx.dof:9'])

    def test_the_variants_the_2026_10_25_run_found_are_classified_and_reconcile(self):
        # Coverage 230/245 on 2026-10-25: ordinals, Acta/Anexo/Declaraciones, «se da a conocer la denuncia»,
        # «Promulgatorio con», and the clauses «aprobado en» / «celebrado por|mediante».
        self.assertEqual(tratados.unreconciled(REAL + VARIANTES), [])
        by = {e['entry_id']: tratados.classify(e['title']) for e in VARIANTES}
        self.assertEqual(by['mx.dof:5487418'][0], 'aprobacion_senado')
        self.assertTrue(by['mx.dof:5487418'][1].startswith('Segundo Protocolo Modificatorio al Acuerdo'))
        self.assertEqual(by['mx.dof:5545342'][0], 'retiro_o_denuncia')
        self.assertEqual(by['mx.dof:5594545'][0], 'promulgacion')
        self.assertEqual(by['mx.dof:5723225'], ('aprobacion_senado', 'Acuerdo Internacional del Café de 2022'))
        self.assertEqual(by['mx.dof:5528819'], ('enmienda', 'Protocolo de Montreal relativo a las Sustancias que Agotan '
                                                'la Capa de Ozono'))  # the amended instrument, cut at «, aprobada en»

    def test_a_reviewed_disagreement_is_not_reported_and_a_new_one_with_its_title_is(self):
        self.assertEqual(sorted(tratados.REVIEWED), ['mx.dof:4719647', 'mx.dof:4720018', 'mx.dof:5078128', 'mx.dof:5129541',
                                                     'mx.dof:5339485', 'mx.dof:5672145', 'mx.dof:5759498', 'mx.dof:762740',
                                                     'mx.dof:770677'])
        for i, annex in (('mx.dof:5636928', 'Anexo III'), ('mx.dof:5636929', 'Anexo IV')):
            with self.subTest(i):  # reviewed until 2026-10-29; the title check now reads an approval naming an Annex
                anexo = next(e for e in VARIANTES if e['entry_id'] == i)
                stage, name = tratados.classify(anexo['title'])
                self.assertEqual((stage, name.startswith(f'{annex} "Reglas para Prevenir')), ('aprobacion_senado', True))
                self.assertIsNotNone(tratados.LOOKS_LIKE.search(tratados.fold(anexo['title'])))
                self.assertEqual(tratados.unreconciled([anexo]), [])
        ajustes, i = OLDER_BY['mx.dof:4719647'], 'mx.dof:4719647'  # a disagreement a person reviewed
        self.assertEqual((tratados.classify(ajustes['title']), bool(tratados.LOOKS_LIKE.search(tratados.fold(ajustes['title'])))),
                         (None, True))
        self.assertEqual(tratados.unreconciled([ajustes]), [])
        self.assertEqual(tratados.unreconciled([{**ajustes, 'entry_id': 'mx.dof:99'}]), ['mx.dof:99'])
        # GPT #44: the review holds for the title read, not for the id; a corrected title is checked again
        self.assertEqual(tratados.unreconciled([{**ajustes, 'title': ajustes['title'].replace('2A', '3A')}]), [i])

    def test_a_classified_title_that_does_not_look_like_a_treaty_decree_is_reported(self):
        self.assertEqual(tratados.classify(SIN_EFECTO['title'])[0], 'retiro_o_denuncia')
        self.assertIsNone(tratados.LOOKS_LIKE.search(tratados.fold(SIN_EFECTO['title'])))
        self.assertEqual(tratados.unreconciled(REAL + [SIN_EFECTO]), ['mx.dof:11'])

    def test_an_agreement_between_mexican_states_is_not_a_treaty_and_the_check_still_sees_it(self):
        self.assertIsNone(tratados.classify(LIMITES['title']))  # Constitución art. 46: a 'convenio amistoso'
        self.assertEqual(tratados.unreconciled(REAL + [LIMITES]), ['mx.dof:7'])
        limites = OLDER_BY['mx.dof:4720018']  # the real one (1994): in the view until 2026-10-29, now left out
        self.assertIsNone(tratados.classify(limites['title']))
        self.assertIsNotNone(tratados.LOOKS_LIKE.search(tratados.fold(limites['title'])))
        self.assertEqual(tratados.unreconciled([limites]), [])  # reviewed: the table's answer stands
        self.assertEqual(tratados.unreconciled([{**limites, 'entry_id': 'mx.dof:99'}]), ['mx.dof:99'])


def filed(i, title, published, issuer):
    """A note with the desk the DOF filed it under (category.issuer), as the catalog holds it."""
    return {**note(i, title, published), 'category': {'issuer': issuer}}


# Real DOF titles (1993-2014), copied verbatim with their ids, dates and desks, from the forms the catalog met when it
# reached 1993: the run of 2026-10-29 counted 1484 vs 1561 (341 disagreements over 844,383 DOF titles).
OLDER = [
    filed(4906649, 'DECRETO por el que se aprueban el Reglamento General y de las Resoluciones de la Unión Postal de las '
             'Américas, España y Portugal, adoptados durante el XVI Congreso de la Unión Postal de las Américas, España '
             'y Portugal.', '1996-12-12', issuer='SECRETARIA DE RELACIONES EXTERIORES'),
    filed(4863279, 'DECRETO de Promulgación del Reglamento General y las Resoluciones de la Unión Postal de las Américas, '
             'España y Portugal, adoptados durante el XVI Congreso de la Unión Postal de las Américas, España y '
             'Portugal, celebrado en la Ciudad de México, Distrito Federal.', '1998-01-12',
          issuer='SECRETARIA DE RELACIONES EXTERIORES'),
    filed(5094444, 'Decreto por el que se determina que el Acuerdo por el que se crea la Organización Internacional de la '
             'Viña y el Vino, suscrito en la ciudad de París, Francia, el tres de abril de dos mil uno, queda sin efectos '
             'en México a partir del treinta de junio de dos mil nueve', '2009-06-15',
          issuer='SECRETARIA DE RELACIONES EXTERIORES'),
    filed(4863233, 'DECRETO de Promulgación de la Convención Interamericana contra la Corrupción, adoptada por la '
             'Conferencia Especializada sobre Corrupción de la Organización de los Estados Americanos, en la '
             'ciudad de Caracas, Venezuela.',
         '1998-01-09', issuer='SECRETARIA DE RELACIONES EXTERIORES'),
    filed(4796074, 'DECRETO de promulgación de las enmiendas al Tratado para la Proscripción de las Armas Nucleares '
             'en la América Latina.',
         '1993-10-25', issuer='SECRETARIA DE RELACIONES EXTERIORES'),
    filed(2044527, 'Decreto Promulgatorio de las Modificaciones al Anexo 401 del Tratado de Libre Comercio de '
             'América del Norte, formalizadas mediante intercambio de comunicaciones los días ocho y veintidós '
             'de octubre y quince de noviembre de dos mil cuatro, entre los Gobiernos de los Estados Unidos de '
             'América, Canadá y los Estados Unidos Mexicanos, respectivamente',
         '2005-06-14', issuer='SECRETARIA DE RELACIONES EXTERIORES'),
    filed(670047, 'Fe de errata al Decreto Promulgatorio del Acuerdo de Coproducción Cinematográfica entre los '
             'Estados Unidos Mexicanos y el Reino de España, firmado en la ciudad de Madrid, España, el ocho '
             'de abril de dos mil tres, publicado el 17 de marzo de 2004',
         '2004-05-06', issuer='SECRETARIA DE RELACIONES EXTERIORES'),
    filed(4710809, 'DECRETO por el que se aprueba el texto de la Convención Marco de las Naciones Unidas sobre el '
             'Cambio Climático.',
         '1993-01-13', issuer='SECRETARIA DE RELACIONES EXTERIORES'),
    filed(737415, 'Decreto por el que se aprueba la adhesión al Protocolo de Firma Facultativa sobre Jurisdicción '
             'Obligatoria para la Solución de Controversias de la Convención de Viena sobre Relaciones '
             'Consulares, adoptado en Viena, el veinticuatro de abril de mil novecientos sesenta y tres',
         '2002-01-16', issuer='SECRETARIA DE RELACIONES EXTERIORES'),
    filed(5197492, 'Decreto por que se aprueba el Convenio entre el Gobierno de los Estados Unidos Mexicanos y el '
             'Gobierno del Estado de Kuwait para evitar la doble imposición y prevenir la evasión fiscal en '
             'materia de impuestos sobre la renta, firmado en la Ciudad de Kuwait, el veintisiete de octubre '
             'de dos mil nueve',
         '2011-06-22', issuer='SECRETARIA DE RELACIONES EXTERIORES'),
    filed(2035614, 'Decreto por el cual el Convenio sobre Transporte Marítimo entre los Estados Unidos Mexicanos y '
             'el Reino de los Países Bajos, firmado en la ciudad de La Haya, el dieciocho de octubre de mil '
             'novecientos ochenta y cuatro, quedará sin efectos en los Estados Unidos Mexicanos, a partir del '
             'veinte de octubre de dos mil cinco',
         '2005-05-06', issuer='SECRETARIA DE RELACIONES EXTERIORES'),
    filed(4937867, 'Decreto por el que se determina que el Tratado de Libre Comercio entre los Estados Unidos '
             'Mexicanos, la República de Colombia y la República de Venezuela, firmado en la ciudad de '
             'Cartagena de Indias, Colombia, el trece de junio de mil novecientos noventa y cuatro, queda sin '
             'efectos entre los Estados Unidos Mexicanos y la República Bolivariana de Venezuela, a partir del '
             'diecinueve de noviembre de dos mil seis',
         '2006-11-17', issuer='SECRETARIA DE RELACIONES EXTERIORES'),
    filed(4871130, 'DECRETO por el que se deja sin efectos en los Estados Unidos Mexicanos la Convención sobre '
             'Nacionalidad, firmada en Montevideo, el veintiséis de diciembre de 1933.',
         '1998-03-24', issuer='SECRETARIA DE RELACIONES EXTERIORES'),
    filed(774728, 'Decreto por el que se aprueban el Decimoquinto Protocolo Modificatorio y el Decimosexto '
             'Protocolo Adicional, ambos del Acuerdo de Complementación Económica número 5 celebrado entre los '
             'Estados Unidos Mexicanos y la República Oriental del Uruguay',
         '2001-01-26', issuer='SECRETARIA DE RELACIONES EXTERIORES'),
    filed(2058439, 'Decreto por el que se aprueba el Arreglo de Locarno que establece una Clasificación '
             'Internacional para los Dibujos y Modelos Industriales, firmado en Locarno el 8 de octubre de '
             '1968 y enmendado el 28 de septiembre de 1979',
         '2000-08-07', issuer='SECRETARIA DE RELACIONES EXTERIORES'),
    filed(2091187, 'Decreto por el que se aprueba el Estatuto de Roma de la Corte Penal Internacional, adoptado en '
             'la ciudad de Roma, el diecisiete de julio de mil novecientos noventa y ocho',
         '2005-09-07', issuer='SECRETARIA DE GOBERNACION'),
    filed(4874903, 'DECRETO de promulgación del Mandato del Grupo Internacional de Estudio sobre el Cobre.',
         '1995-06-02', issuer='SECRETARIA DE RELACIONES EXTERIORES'),
    filed(5155445, 'Decreto Promulgatorio de la denuncia de los Estados Unidos Mexicanos al Convenio Constitutivo de '
             'la Unión Latina, adoptado en Madrid el 15 de mayo de 1954',
         '2010-08-16', issuer='SECRETARIA DE RELACIONES EXTERIORES'),
    filed(4740197, 'DECRETO que reforma el diverso que establece las preferencias porcentuales a las mercancías que '
             'se importen al amparo del Acuerdo Comercial número 27 de la Industria del Vidrio, suscrito por '
             'los Estados Unidos Mexicanos y las Repúblicas Federativa del Brasil y Venezuela.',
         '1993-05-27', issuer='SECRETARIA DE COMERCIO Y FOMENTO INDUSTRIAL'),
    filed(5342343, 'Decreto por el que se declara el 2014 como "Año del Bicentenario de la Promulgación de la '
             'Constitución de Apatzingán."',
         '2014-04-28', issuer='SECRETARIA DE GOBERNACION'),
    filed(5028840, 'Decreto por el que se aprueba el Programa Sectorial de Relaciones Exteriores 2007-2012',
         '2008-01-23', issuer='SECRETARIA DE RELACIONES EXTERIORES'),
    filed(4720018, 'DECRETO por el que se aprueba el Convenio Amistoso para la Precisión y Reconocimiento de sus '
             'respectivos Límites Territoriales, celebrado por el Estado Libre y Soberano de México y por el '
             'DEPARTAMENTO DEL DISTRITO FEDERAL',
         '1994-07-27', issuer='SECRETARIA DE GOBERNACION'),
    filed(4719647, 'DECRETO por el que se aprueba el texto de los ajustes a los artículos 2A y 2B del Protocolo de '
             'Montreal, relativo a las sustancias que agotan la capa de ozono.',
         '1994-07-25', issuer='SECRETARIA DE RELACIONES EXTERIORES'),
    filed(5028716, 'Decreto por el que se aprueban las Enmiendas a la Constitución de la Organización Internacional '
             'para las Migraciones, adoptadas durante la Septuagésima Sexta Reunión de su Consejo, el '
             'veinticuatro de noviembre de mil novecientos noventa y ocho',
         '2008-01-21', issuer='SECRETARIA DE RELACIONES EXTERIORES'),
]
OLDER_BY = {e['entry_id']: e for e in OLDER}
NOT_TREATIES_OLDER = ('mx.dof:4740197', 'mx.dof:5342343', 'mx.dof:5028840', 'mx.dof:4720018')
SRE = tratados.DESK


class OlderPrintings(unittest.TestCase):
    def test_each_older_form_gives_its_stage_and_the_name_as_printed(self):
        want = {'mx.dof:4863233': ('promulgacion', 'Convención Interamericana contra la Corrupción'),
                'mx.dof:4796074': ('enmienda', 'Tratado para la Proscripción de las Armas Nucleares en la América Latina'),
                'mx.dof:2044527': ('enmienda', 'Anexo 401 del Tratado de Libre Comercio de América del Norte'),
                'mx.dof:670047': ('fe_de_erratas', 'Acuerdo de Coproducción Cinematográfica entre los Estados Unidos'),
                'mx.dof:4710809': ('aprobacion_senado', 'Convención Marco de las Naciones Unidas sobre el Cambio Climático'),
                'mx.dof:737415': ('aprobacion_senado', 'Protocolo de Firma Facultativa sobre Jurisdicción Obligatoria'),
                'mx.dof:5197492': ('aprobacion_senado', 'Convenio entre el Gobierno de los Estados Unidos Mexicanos y el '
                                                        'Gobierno del Estado de Kuwait'),  # 'Decreto por que', as printed
                'mx.dof:2035614': ('retiro_o_denuncia', 'Convenio sobre Transporte Marítimo entre los Estados Unidos'),
                'mx.dof:4937867': ('retiro_o_denuncia', 'Tratado de Libre Comercio entre los Estados Unidos Mexicanos, la '
                                                        'República de Colombia y la República de Venezuela'),
                'mx.dof:4871130': ('retiro_o_denuncia', 'Convención sobre Nacionalidad'),
                'mx.dof:774728': ('aprobacion_senado', 'Decimoquinto Protocolo Modificatorio'),
                'mx.dof:2058439': ('aprobacion_senado', 'Arreglo de Locarno'),
                'mx.dof:2091187': ('aprobacion_senado', 'Estatuto de Roma de la Corte Penal Internacional'),
                'mx.dof:4874903': ('promulgacion', 'Mandato del Grupo Internacional de Estudio sobre el Cobre'),
                'mx.dof:5155445': ('retiro_o_denuncia', 'Convenio Constitutivo de la Unión Latina'),
                'mx.dof:5028716': ('enmienda', 'Constitución de la Organización Internacional para las Migraciones'),
                'mx.dof:4906649': ('aprobacion_senado', 'Reglamento General y de las Resoluciones de la Unión Postal'),
                'mx.dof:4863279': ('promulgacion', 'Reglamento General y las Resoluciones de la Unión Postal'),
                'mx.dof:5094444': ('retiro_o_denuncia', 'Acuerdo por el que se crea la Organización Internacional de la '
                                                        'Viña y el Vino')}
        for i, (stage, start) in want.items():
            with self.subTest(i):
                got = tratados.classify(OLDER_BY[i]['title'])
                self.assertEqual(got[0], stage)
                self.assertTrue(got[1].startswith(start), got[1])

    def test_a_decree_by_which_an_instrument_is_not_ended_is_no_termination_and_the_check_sees_it(self):
        # GPT REVISE 467c3ff: CONSTRUIDO; 'por el cual' without 'sin efectos' gave retiro_o_denuncia
        for i, title in ((14, 'Decreto por el cual el Convenio de Ejemplo, firmado en Roma, se modifica.'),
                         (15, 'Decreto por el que se determina que el Acuerdo de Ejemplo, firmado en Roma, sigue vigente.'),
                         # GPT REVISE 2421f83: 'sin efectos' that ends an article, not the instrument
                         (17, 'Decreto por el cual el Convenio de Ejemplo, firmado en Roma, se modifica para dejar sin '
                              'efectos su artículo 2.')):
            with self.subTest(title):
                e = note(i, title, '2026-05-08')
                self.assertIsNone(tratados.classify(title))
                self.assertEqual(tratados.unreconciled([e]), [f'mx.dof:{i}'])  # the clause still flags it

    def test_a_mexican_reglamento_is_no_treaty_and_the_check_sees_it(self):
        # GPT REVISE 2421f83: CONSTRUIDO; REGLAMENTO is also a Mexican legal form, read only as a name in tratados.NAMED
        domestic = filed(18, 'Decreto por el que se aprueba el Reglamento Interior de la Secretaría de Salud.', '2026-05-10',
                         'SECRETARIA DE SALUD')
        self.assertIsNone(tratados.classify(domestic['title']))
        self.assertEqual(tratados.unreconciled([domestic]), ['mx.dof:18'])  # left out, and reported: the run exits 3

    def test_a_continuation_of_a_decree_is_an_act_for_the_desk_check(self):
        # GPT REVISE 467c3ff: CONSTRUIDO; 'Continuación del texto del Decreto ...' needs no 'al'
        odd = filed(16, 'Continuación del texto del Decreto por el que se aprueba el Comunicado Conjunto X.', '2026-05-09', SRE)
        self.assertEqual((tratados.classify(odd['title']), tratados.unreconciled([odd])), (None, []))
        self.assertEqual(tratados.desk([odd]), ['mx.dof:16'])

    def test_a_termination_with_an_approved_or_celebrated_clause_is_read_by_that_clause(self):
        # CONSTRUIDO on the real form of mx.dof:2035614 ('Decreto por el cual el Convenio ..., firmado en ...'): only the
        # clause ', celebrado en' tells the title check it is a treaty decree.
        celebrado = note(13, 'Decreto por el cual el Convenio de Ejemplo, celebrado en Roma el uno de enero de mil '
                             'novecientos noventa, quedará sin efectos en los Estados Unidos Mexicanos, a partir del uno '
                             'de enero de dos mil veintisiete.', '2026-05-07')
        self.assertEqual(tratados.classify(celebrado['title']), ('retiro_o_denuncia', 'Convenio de Ejemplo'))
        self.assertEqual(tratados.unreconciled([celebrado]), [])

    def test_both_checks_reconcile_the_older_forms(self):
        self.assertEqual(tratados.unreconciled(OLDER), [])
        self.assertEqual(tratados.desk(OLDER), [])
        self.assertEqual(tratados.unreconciled(REAL + VARIANTES + NOT_TREATIES + OLDER), [])

    def test_goods_imported_under_a_treaty_an_anniversary_and_a_programme_are_not_treaty_decrees(self):
        for i in ('mx.dof:4740197', 'mx.dof:5342343', 'mx.dof:5028840'):  # 'al amparo del Acuerdo Comercial ...',
            with self.subTest(i):                                          # 'Año ... de la Promulgación de la Constitución'
                title = OLDER_BY[i]['title']
                self.assertIsNone(tratados.classify(title))
                self.assertIsNone(tratados.LOOKS_LIKE.search(tratados.fold(title)))
        self.assertEqual(tratados.desk([OLDER_BY['mx.dof:5028840']]), [])  # a programme the Ministry files and approves

    def test_a_word_that_would_rename_an_amendment_already_read_is_not_an_instrument(self):
        self.assertNotIn('ARTICULO', tratados.INSTRUMENTS)  # 'la Enmienda del Artículo XVII (f) del Acuerdo ...' keeps its name
        ajustes = OLDER_BY['mx.dof:4719647']  # 'los ajustes a los artículos 2A y 2B del Protocolo de Montreal'
        self.assertIsNone(tratados.classify(ajustes['title']))
        self.assertEqual(tratados.unreconciled([ajustes]), [])  # reviewed, that exact title
        self.assertEqual(tratados.desk([ajustes]), [])

    def test_the_desk_check_reports_a_foreign_ministry_act_the_table_and_the_title_check_both_miss(self):
        odd = filed(12, 'Decreto por el que se aprueba el Comunicado Conjunto X.', '2026-05-05', SRE)  # CONSTRUIDO
        self.assertIsNone(tratados.classify(odd['title']))
        self.assertEqual(tratados.unreconciled([odd]), [])  # the title check agrees with the table: both miss it
        self.assertEqual(tratados.desk([odd]), ['mx.dof:12'])  # the DOF's own filing does not
        self.assertEqual(tratados.desk([{**odd, 'category': {'issuer': 'PRESIDENCIA DE LA REPUBLICA'}}]), [])
        self.assertEqual(tratados.desk([{k: v for k, v in odd.items() if k != 'category'}]), [])
        self.assertEqual(tratados.desk([{**odd, 'source_id': 'mx.otro'}]), [])


class RunHook(unittest.TestCase):
    """main() writes mx/tratados/tratados.jsonl right after the catalog and reconciles it (exit 3 on disagreement)."""

    ROW = {'category': {'branch': 'PODER EJECUTIVO', 'collection': 'DOF', 'doc_type': 'DECRETO', 'edition': 'VESPERTINA',
                        'issuer': 'PRESIDENCIA DE LA REPUBLICA', 'jurisdiction': 'federal', 'section': 'UNICA SECCION'},
           'country': 'MX', 'first_seen': '2026-10-19T22:02:26Z', 'raw_status': 'pending'}

    def run_main(self, out, notes):
        from rg.catalog import run as runmod

        def execute(self_, sources):
            for n in notes:
                nid = n['entry_id'].split(':')[1]
                self_.catalog.entries[n['entry_id']] = {**self.ROW, **n, 'native_id': nid,
                                                        'url': f'https://sidof.segob.gob.mx/notas/{nid}'}
            self_.manifest.update({'requests_total': 0, 'raw_new_files': 0, 'finished_at': 'x'})
            return self_.manifest
        with mock.patch.object(runmod.Run, 'execute', execute):
            return runmod.main(['--country', 'mx', '--out', out, '--raw', out + '-raw', '--today', '2026-10-22'])

    def manifests(self, out):
        return [json.loads(p.read_text(encoding='utf-8')) for p in sorted((Path(out) / 'mx' / 'runs').glob('*.json'))]

    def test_view_is_written_and_a_second_run_does_not_read_it_back_as_rows(self):
        from rg.catalog.store import Catalog
        with tempfile.TemporaryDirectory() as d:
            out = d + '/out'
            self.assertEqual(self.run_main(out, REAL), 0)
            lines = (Path(out) / 'mx' / 'tratados' / 'tratados.jsonl').read_text(encoding='utf-8').splitlines()
            self.assertEqual(len(lines), 3)
            self.assertEqual(self.run_main(out, []), 0)  # the view folder is in the catalog root: never a row
            self.assertEqual(sorted(Catalog(out, 'MX').entries), sorted(e['entry_id'] for e in REAL))
            m = self.manifests(out)[-1]
        self.assertEqual(m['treaty_instruments'], 3)
        self.assertIn({'source_id': 'mx.tratados', 'scope': 'decretos de tratado: chequeo independiente vs tabla fija',
                       'expected': 4, 'extracted': 4, 'ok': True, 'entries': []}, m['coverage'])

    def test_a_foreign_ministry_act_the_table_misses_fails_the_run_on_the_desk_check(self):
        odd = filed(12, 'Decreto por el que se aprueba el Comunicado Conjunto X.', '2026-05-05', SRE)  # CONSTRUIDO
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_main(d + '/out', REAL + [{**odd, 'category': {**self.ROW['category'], 'issuer': SRE}}]), 3)
            bad = [c for c in self.manifests(d + '/out')[-1]['coverage'] if not c['ok']]
        self.assertEqual([(c['source_id'], c['scope'][:24], c['entries']) for c in bad],
                         [('mx.tratados', 'decretos de la SRE con a', ['mx.dof:12'])])

    def test_a_continued_foreign_ministry_act_the_table_misses_fails_the_run(self):
        odd = filed(16, 'Continuación del texto del Decreto por el que se aprueba el Comunicado Conjunto X.', '2026-05-09', SRE)
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_main(d + '/out', REAL + [{**odd, 'category': {**self.ROW['category'], 'issuer': SRE}}]), 3)
            bad = [c for c in self.manifests(d + '/out')[-1]['coverage'] if not c['ok']]
        self.assertEqual([c['entries'] for c in bad], [['mx.dof:16']])

    def test_an_unclassified_treaty_decree_fails_the_run(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_main(d + '/out', REAL + [MEMORANDO]), 3)
            bad = [c for c in self.manifests(d + '/out')[-1]['coverage'] if not c['ok']]
        self.assertEqual([(c['source_id'], c['entries']) for c in bad], [('mx.tratados', ['mx.dof:9'])])


if __name__ == '__main__':
    unittest.main()
