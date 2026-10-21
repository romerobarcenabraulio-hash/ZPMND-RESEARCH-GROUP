"""Reproduce the figures of docs/DIMENSIONES.md from a catalog checkout (deterministic, exact title matches only).

    python scripts/medir_dimensiones.py work/catalog/mx
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rg.catalog.categorize import fold  # noqa: E402
from rg.catalog.store import row_files  # noqa: E402

NOM = re.compile(r'\bNOM-\d{3}-[A-Z0-9]+-\d{4}\b')


def load(root, name):
    out = []
    for f in sorted(Path(root).glob(name)):
        out += [json.loads(line) for line in f.read_text(encoding='utf-8').splitlines() if line.strip()]
    return out


def main(root):
    laws = load(root, 'leyes-federales.jsonl')
    regs = load(root, 'reglamentos-federales.jsonl')
    dof = load(root, 'dof/*.jsonl') or load(root, 'dof.jsonl')
    titles = sorted({fold(e['title']) for e in laws if e['category'].get('status_printed') == 'VIGENTE'}, key=len, reverse=True)
    linked = sum(1 for r in regs if any(t in fold(r['title']) for t in titles))
    named = Counter()
    notes_naming = 0
    for n in dof:
        t = fold(n['title'])
        hit = next((law for law in titles if law in t), None)  # longest title first
        if hit:
            notes_naming += 1
            named[hit] += 1
    codes = Counter(c for n in dof for c in set(NOM.findall(fold(n['title']))))
    ojn = load(root, 'ojn-estatal/*.jsonl') + load(root, 'ojn-municipal/*.jsonl')
    states = {e['listing'].get('state_code') for e in ojn if e.get('listing')}
    municipalities = {(e['listing'].get('state_code'), e['category'].get('municipality')) for e in ojn
                      if e['source_id'].endswith('municipal') and e['category'].get('municipality')}
    total = sum(1 for f in row_files(root) for line in f.read_text(encoding='utf-8').splitlines() if line.strip())
    versioned = sum(1 for e in laws + regs if e.get('versions') and all(v.get('sha256') for v in e['versions']))
    print(json.dumps({
        'reglamentos_ligados_a_su_ley_por_titulo': [linked, len(regs)],
        'notas_dof_que_nombran_una_ley_vigente': [notes_naming, len(dof)],
        'leyes_mas_nombradas': named.most_common(3),
        'codigos_nom_en_titulos_dof': len(codes),
        'codigos_nom_con_mas_de_una_nota': sum(1 for c in codes.values() if c > 1),
        'registros_totales': total,
        'estados_con_registros_ojn': len(states),
        'municipios_con_registros_ojn': len(municipalities),
        'instrumentos_federales_con_version_hasheada': [versioned, len(laws) + len(regs)],
    }, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main(sys.argv[1])
