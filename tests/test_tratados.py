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
MEMORANDO = note(9, 'Decreto Promulgatorio del Memorándum de Entendimiento X, hecho en Roma, el uno de enero de dos '
                   'mil veinticinco.', '2026-05-04')  # CONSTRUIDO: a promulgation of something outside the table
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
        self.assertEqual(sorted(tratados.REVIEWED), ['mx.dof:5636928', 'mx.dof:5636929'])
        for i, annex in (('mx.dof:5636928', 'Anexo III'), ('mx.dof:5636929', 'Anexo IV')):
            with self.subTest(i):
                anexo = next(e for e in VARIANTES if e['entry_id'] == i)
                stage, name = tratados.classify(anexo['title'])
                self.assertEqual((stage, name.startswith(f'{annex} "Reglas para Prevenir')), ('aprobacion_senado', True))
                self.assertIsNone(tratados.LOOKS_LIKE.search(tratados.fold(anexo['title'])))  # the disagreement reviewed
                self.assertEqual(tratados.unreconciled([anexo]), [])
                self.assertEqual(tratados.unreconciled([{**anexo, 'entry_id': 'mx.dof:99'}]), ['mx.dof:99'])
                # GPT #44: the review holds for the title read, not for the id; a corrected title is checked again
                self.assertEqual(tratados.unreconciled([{**anexo, 'title': anexo['title'].replace('1978', '1997')}]), [i])

    def test_a_classified_title_that_does_not_look_like_a_treaty_decree_is_reported(self):
        self.assertEqual(tratados.unreconciled(REAL + [LIMITES]), ['mx.dof:7'])


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

    def test_an_unclassified_treaty_decree_fails_the_run(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_main(d + '/out', REAL + [MEMORANDO]), 3)
            bad = [c for c in self.manifests(d + '/out')[-1]['coverage'] if not c['ok']]
        self.assertEqual([(c['source_id'], c['entries']) for c in bad], [('mx.tratados', ['mx.dof:9'])])


if __name__ == '__main__':
    unittest.main()
