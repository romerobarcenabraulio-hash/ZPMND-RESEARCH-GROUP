"""Rule 10 on the text front: the quote of a ChangeEvent or relation occurs in the text its evidence names.

  python -m rg.text.quote change_event|relation <doc.json> --manifest data/mx/texto --text texto

Evidence is {raw_sha256, extractor, quote}. The manifest line of raw_sha256 must carry that same extractor and a text;
the text must hash to the line's text_sha256; and the quote, whitespace folded exactly as the contract folds it
(rg.quotes._fold, the fold rg.schemas uses), must occur in the folded text. The answer says where: code-point offsets
in the text and, for a PDF, the pages. rg.schemas does not call this: it validates one document with no text store,
and the airlock re-runs the pinned extractor on the raw itself (PR #12).
"""
import argparse
import bisect
import json
import sys
from pathlib import Path

from ..quotes import _fold as fold
from ..schemas import validate
from .store import TextStore, read_manifest


def find(quote, text, pages=None):
    """{'start', 'end', 'occurrences'} of the first match in `text` (code points; end exclusive), plus 'page_start' and
    'page_end' (1-based) when the PDF's page offsets are given; None when the folded quote does not occur."""
    q, folded = fold(quote), fold(text)
    at = folded.find(q) if q else -1
    if at < 0:
        return None
    f_starts, t_starts, f_pos, t_pos = [], [], 0, 0
    for token in text.split():  # the tokens fold joins with one space, mapped back to where they sit in text
        t_pos = text.index(token, t_pos)
        f_starts.append(f_pos)
        t_starts.append(t_pos)
        f_pos += len(token) + 1
        t_pos += len(token)

    def back(i):  # i is a non-space position of the folded text
        k = bisect.bisect_right(f_starts, i) - 1
        return t_starts[k] + i - f_starts[k]

    loc = {'start': back(at), 'end': back(at + len(q) - 1) + 1, 'occurrences': folded.count(q)}
    if pages:
        starts = [p[0] for p in pages]
        loc['page_start'] = bisect.bisect_right(starts, loc['start'])
        loc['page_end'] = bisect.bisect_right(starts, loc['end'] - 1)
    return loc


def check(evidence, lines, texts):
    """(problems, location) for one evidence; `lines` maps raw sha256 to its manifest line, `texts` is a TextStore."""
    sha = evidence['raw_sha256']
    line = lines.get(sha)
    if not line:
        return [f'raw {sha[:12]}: no line in the text manifest'], None
    if line['extractor'] != evidence['extractor']:
        return [f"raw {sha[:12]}: evidence cites {evidence['extractor']}, the text is from {line['extractor']}"], None
    if not line.get('text_sha256'):
        return [f"raw {sha[:12]}: status {line['status']}, no text"], None
    text = texts.get(line['text_sha256'])
    if text is None:
        return [f"raw {sha[:12]}: text {line['text_sha256'][:12]} missing or not matching its sha256"], None
    loc = find(evidence['quote'], text, line.get('pages'))
    return ([] if loc else [f'raw {sha[:12]}: quote not found in its text']), loc


def evidences(kind, doc):
    if kind == 'change_event':
        return [('effective_at_evidence', doc['effective_at_evidence'])] if doc.get('effective_at_evidence') else []
    return [('evidence', doc['evidence'])]


def main(argv=None):
    a = argparse.ArgumentParser(description='check ChangeEvent / relation quotes against the extracted text')
    a.add_argument('kind', choices=('change_event', 'relation'))
    a.add_argument('doc')
    a.add_argument('--manifest', required=True, help='manifest folder (data branch mx/texto)')
    a.add_argument('--text', required=True, help='text store root (release text-mx, unpacked)')
    x = a.parse_args(argv)
    doc = json.loads(Path(x.doc).read_text(encoding='utf-8'))
    errors = validate(x.kind, doc)
    if not errors:
        lines = {line['raw_sha256']: line for line in read_manifest(x.manifest)}
        for field, ev in evidences(x.kind, doc):
            problems, loc = check(ev, lines, TextStore(x.text))
            errors += [f'{field}: {p}' for p in problems]
            if loc:
                print(f'FOUND {field}: {json.dumps(loc, sort_keys=True)}')
    for e in errors:
        print('FAIL', e)
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
