"""Semantic index of a country catalog with an open Hugging Face model (default BAAI/bge-m3, MIT, pinned revision).

  python -m rg.index build  --catalog /work/catalog/mx [--catalog ...] --out /work/index/mx
  python -m rg.index search --index /work/index/mx -k 10 "consulta en lenguaje natural"

Derived data only: it finds entries; it never decides categories or truth. Each hit returns entry_id, title, url and the
raw sha256 when the raw is stored, so any answer built on it can cite the exact bytes. `search` also reports how many
model tokens the hits cost versus reading every indexed title (tokenizer of the embedding model; not an LLM's).
"""
import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .catalog.store import row_files

MODEL = 'BAAI/bge-m3'
REVISION = '5617a9f61b028005a4858fdac845db406aefb181'  # pinned: Hub sha recorded in RP-2026-10-19-hf-zpmnd


def entry_text(e):
    c = e['category']
    parts = [e['title'], c['doc_type'], c.get('issuer') or '', c.get('locality') or '', c.get('municipality') or '']
    return ' | '.join(p for p in parts if p)


def load_entries(catalog_dirs):
    rows = {}
    for d in catalog_dirs:
        for f in row_files(d):  # derived views (store.DERIVED) are not rows
            for line in f.read_text(encoding='utf-8').splitlines():
                if line.strip():
                    e = json.loads(line)
                    rows[e['entry_id']] = e
    return [rows[k] for k in sorted(rows)]


def _model(name, revision):
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(name, revision=revision, device='cpu')


def build(catalog_dirs, out, name=MODEL, revision=REVISION, batch=64):
    import numpy as np
    entries = load_entries(catalog_dirs)
    texts = [entry_text(e) for e in entries]
    t0 = time.time()
    vecs = _model(name, revision).encode(texts, batch_size=batch, normalize_embeddings=True, show_progress_bar=False)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    np.save(out / 'vectors.npy', vecs.astype('float16'))
    with (out / 'ids.jsonl').open('w', encoding='utf-8') as fh:
        for e, t in zip(entries, texts):
            fh.write(json.dumps({'entry_id': e['entry_id'], 'text': t, 'url': e['url'],
                                 'sha256': (e.get('artifact') or {}).get('sha256')}, ensure_ascii=False) + '\n')
    digest = hashlib.sha256('\n'.join(e['entry_id'] + '\t' + t for e, t in zip(entries, texts)).encode()).hexdigest()
    manifest = {'model': name, 'revision': revision, 'entries': len(entries), 'dimensions': int(vecs.shape[1]),
                'catalog_digest': digest, 'seconds': round(time.time() - t0, 1),
                'built_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=1) + '\n', encoding='utf-8')
    return manifest


def search(index_dir, query, k=10):
    import numpy as np
    index_dir = Path(index_dir)
    manifest = json.loads((index_dir / 'manifest.json').read_text(encoding='utf-8'))
    vecs = np.load(index_dir / 'vectors.npy').astype('float32')
    ids = [json.loads(l) for l in (index_dir / 'ids.jsonl').read_text(encoding='utf-8').splitlines()]
    model = _model(manifest['model'], manifest['revision'])
    q = model.encode([query], normalize_embeddings=True)[0].astype('float32')
    scores = vecs @ q
    top = scores.argsort()[::-1][:k]
    hits = [{**ids[i], 'score': round(float(scores[i]), 4)} for i in top]
    tok = model.tokenizer
    all_tokens = sum(len(tok(r['text'])['input_ids']) for r in ids)
    hit_tokens = sum(len(tok(h['text'])['input_ids']) for h in hits)
    return {'query': query, 'hits': hits, 'tokens_all_titles': all_tokens, 'tokens_hits': hit_tokens,
            'tokenizer': manifest['model']}


def main(argv=None):
    a = argparse.ArgumentParser(description='Semantic index of the catalog (derived data)')
    sub = a.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build')
    b.add_argument('--catalog', action='append', required=True)
    b.add_argument('--out', required=True)
    s = sub.add_parser('search')
    s.add_argument('--index', required=True)
    s.add_argument('-k', type=int, default=10)
    s.add_argument('query', nargs='+')
    x = a.parse_args(argv)
    if x.cmd == 'build':
        print(json.dumps(build(x.catalog, x.out), indent=1))
    else:
        for q in x.query:
            print(json.dumps(search(x.index, q, x.k), ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
