"""Treaties from DOF titles: fixed table of openings, name copied from the title, exact grouping, independent check.

REAL titles are copied verbatim from the local DOF catalog (2025-09-24 to 2026-10-20: the only treaty decrees in it).
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
        self.assertEqual(tratados.unreconciled(REAL + [SEGUNDO, DESALINEADO]), ['mx.dof:6', 'mx.dof:8'])

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
            self.assertEqual(self.run_main(d + '/out', REAL + [SEGUNDO]), 3)
            bad = [c for c in self.manifests(d + '/out')[-1]['coverage'] if not c['ok']]
        self.assertEqual([(c['source_id'], c['entries']) for c in bad], [('mx.tratados', ['mx.dof:6'])])


if __name__ == '__main__':
    unittest.main()
