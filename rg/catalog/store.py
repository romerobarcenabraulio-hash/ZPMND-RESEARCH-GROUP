"""Raw bytes by content address, catalog rows ordered and deduplicated, run state, and the category index.

Layout under <catalog_root>/<cc>/:
  <source>.jsonl or <source>/<year>.jsonl   one row per instrument or note, sorted
  _state.json                               what has been indexed (days, ETags), so runs are incremental
  INDEX.md, index.json                      counts per category, computed from the rows
  runs/<run_id>.json                        manifest of each run (coverage, counts, budget, errors)
"""
import hashlib
import json
import os
import threading
from collections import Counter, defaultdict
from pathlib import Path


def _dump(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


TREE_LEVELS = (('país', lambda e: e['country']),
               ('ámbito', lambda e: e['category']['jurisdiction']),
               ('estado', lambda e: e['category'].get('locality') if e['category']['jurisdiction'] != 'federal' else None),
               ('municipio', lambda e: e['category'].get('municipality')),
               ('poder', lambda e: e['category'].get('branch')),
               ('dependencia', lambda e: e['category'].get('issuer')),
               ('tipo', lambda e: e['category']['doc_type']))
NO_DATA = '(sin dato en la fuente)'


def build_tree(entries):
    """País → ámbito → estado → municipio → poder → dependencia → tipo, with counts. A level the source does not give
    is shown as NO_DATA (never inferred); levels that do not apply (estado for federal) are skipped."""
    root = {'n': 0, 'children': {}}
    for e in entries:
        node = root
        node['n'] += 1
        for name, get in TREE_LEVELS:
            if name == 'estado' and e['category']['jurisdiction'] == 'federal':
                continue
            if name == 'municipio' and e['category']['jurisdiction'] != 'municipal':
                continue
            key = get(e) or NO_DATA
            node = node['children'].setdefault(f'{name}: {key}', {'n': 0, 'children': {}})
            node['n'] += 1
    return root


def _tree_lines(node, depth=0):
    for key, child in sorted(node['children'].items(), key=lambda kv: (-kv[1]['n'], kv[0])):
        yield f"{'  ' * depth}- {key} — {child['n']}"
        yield from _tree_lines(child, depth + 1)


class RawStore:
    def __init__(self, root):
        self.root = Path(root)
        self.new_files = []

    def put(self, body, ext):
        sha = hashlib.sha256(body).hexdigest()
        rel = f'sha256/{sha[:2]}/{sha}.{ext}'
        path = self.root / rel
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f'{path.suffix}.{os.getpid()}.{threading.get_ident()}.part')
            tmp.write_bytes(body)
            tmp.replace(path)
            self.new_files.append(rel)
        return sha, rel


class Catalog:
    def __init__(self, root, country):
        self.dir = Path(root) / country.lower()
        self.entries = {}
        self.lock = threading.RLock()  # sources run in parallel threads; every read-for-iteration and write takes it
        for f in sorted(self.dir.rglob('*.jsonl')):
            for line in f.read_text(encoding='utf-8').splitlines():
                if line.strip():
                    e = json.loads(line)
                    self.entries[e['entry_id']] = e
        state = self.dir / '_state.json'
        self.state = json.loads(state.read_text(encoding='utf-8')) if state.exists() else {}

    def previous(self, entry_ids):
        """The rows of these entries as last written to disk (before this run), for the ones that exist."""
        out, want = {}, set(entry_ids)
        if not want:
            return out
        for f in sorted(self.dir.rglob('*.jsonl')):
            for line in f.read_text(encoding='utf-8').splitlines():
                if line.strip():
                    e = json.loads(line)
                    if e['entry_id'] in want:
                        out[e['entry_id']] = e
        return out

    def snapshot(self, source_id=None):
        """A list copy of the entries (optionally of one source), safe to iterate while other threads upsert."""
        with self.lock:
            return [e for e in self.entries.values() if source_id is None or e['source_id'] == source_id]

    def upsert(self, entry):
        with self.lock:
            return self._upsert(entry)

    def _upsert(self, entry):
        old = self.entries.get(entry['entry_id'])
        if old:
            entry['first_seen'] = old['first_seen']
            if 'versions' in old:  # append-only history of every text version ever retrieved
                known = {v['sha256'] for v in old['versions']}
                entry['versions'] = old['versions'] + [v for v in entry.get('versions', []) if v['sha256'] not in known]
        self.entries[entry['entry_id']] = entry
        return old is None

    @staticmethod
    def _file_for(entry):
        short = entry['source_id'].split('.', 1)[1]
        if entry['source_id'].endswith('.dof'):
            return f"{short}/{(entry['dates'].get('published') or '0000')[:4]}.jsonl"
        if 'state_code' in entry.get('listing', {}):
            return f"{short}/{entry['listing']['state_code']:02d}.jsonl"
        return f'{short}.jsonl'

    @staticmethod
    def _order(entry):
        listing = entry.get('listing', {})
        return (entry['dates'].get('published') or '', listing.get('page_order', 0), entry['native_id'])

    def write(self):
        self.dir.mkdir(parents=True, exist_ok=True)  # a new country or a clean checkout has no folder yet
        groups = defaultdict(list)
        for e in self.entries.values():
            groups[self._file_for(e)].append(e)
        for rel, rows in groups.items():
            path = self.dir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(''.join(_dump(e) + '\n' for e in sorted(rows, key=self._order)), encoding='utf-8')
        (self.dir / '_state.json').write_text(json.dumps(self.state, ensure_ascii=False, sort_keys=True, indent=1) + '\n',
                                              encoding='utf-8')
        self._write_index()

    def _write_index(self):
        facets = {'source': Counter(), 'doc_type': Counter(), 'raw_status': Counter(), 'year': Counter(),
                  'branch_issuer': Counter(), 'status_printed': Counter(), 'locality': Counter()}
        for e in self.entries.values():
            c = e['category']
            facets['source'][e['source_id']] += 1
            facets['doc_type'][f"{e['source_id']} | {c['doc_type']}"] += 1
            facets['raw_status'][f"{e['source_id']} | {e['raw_status']}"] += 1
            facets['year'][f"{e['source_id']} | {(e['dates'].get('published') or e['dates'].get('original_publication') or '????')[:4]}"] += 1
            facets['branch_issuer'][f"{c.get('branch') or '-'} | {c.get('issuer') or '-'}"] += 1
            if c.get('status_printed'):
                facets['status_printed'][f"{e['source_id']} | {c['status_printed']}"] += 1
            if c.get('locality'):
                facets['locality'][f"{e['source_id']} | {c['locality']}"] += 1
        index = {k: dict(sorted(v.items())) for k, v in facets.items()}
        index['total'] = len(self.entries)
        (self.dir / 'index.json').write_text(json.dumps(index, ensure_ascii=False, indent=1, sort_keys=True) + '\n',
                                             encoding='utf-8')
        lines = [f'# Catálogo {self.dir.name.upper()}', '', f'Total de registros: **{len(self.entries)}**. '
                 'Conteos calculados de los registros; nada resumido ni interpretado.', '']
        titles = {'source': 'Por fuente', 'doc_type': 'Por tipo de documento (tabla fija sobre el título oficial)',
                  'status_printed': 'Por estado impreso en el listado oficial', 'raw_status': 'Estado del crudo',
                  'year': 'Por año (publicación u original)', 'branch_issuer': 'Por poder / emisor (estructura oficial)',
                  'locality': 'Por entidad federativa (como la imprime la fuente)'}
        for key, title in titles.items():
            lines += [f'## {title}', '', '| categoría | registros |', '|---|---:|']
            lines += [f'| {k} | {n} |' for k, n in sorted(facets[key].items(), key=lambda kv: (-kv[1], kv[0]))]
            lines.append('')
        (self.dir / 'INDEX.md').write_text('\n'.join(lines), encoding='utf-8')
        tree = build_tree(self.entries.values())
        (self.dir / 'arbol.json').write_text(json.dumps(tree, ensure_ascii=False, sort_keys=True) + '\n', encoding='utf-8')
        (self.dir / 'ARBOL.md').write_text('\n'.join([f'# Árbol del catálogo {self.dir.name.upper()}', '',
            'País → ámbito → estado → municipio → poder → dependencia → tipo. Conteos de los registros; '
            f'"{NO_DATA}" marca un nivel que la fuente no publica (nunca se infiere).', ''] + list(_tree_lines(tree))) + '\n',
            encoding='utf-8')

    def write_run(self, manifest):
        runs = self.dir / 'runs'
        runs.mkdir(parents=True, exist_ok=True)
        (runs / f"{manifest['run_id']}.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + '\n',
                                                        encoding='utf-8')
