"""The mechanical gate of a ResearchPacket folder (research-packets/<RP>/): nothing is published without it.

    python -m rg.packets research-packets/<RP> [--raw DIR ...] [--strict]

- packet.json validates against schemas/research_packet.schema.json;
- the folder holds only what it declares: packet.json, receipt.json, sources.json and, under raw/, exactly one file
  raw/sha256/<2>/<sha>.<ext> per artifact with stored_at 'repo', and only when its redistribution is 'allowed'. Any
  other file (an undeclared raw, a second copy, a symlink, a note) is a problem;
- every kept raw hashes to its artifact's sha256 and has its declared size;
- every quote of a finding (confirmed and conflicting) has at least MIN_QUOTE characters and is found, whitespace
  folded as the contract folds it, in the text of one of the raws it cites. That text is what rg.text extracts (html, pdf, docx; each raw parsed in its own
  process with time, size and memory limits). Only a format rg.text does not read (formato_no_soportado) whose
  media type is plain text (TEXTUAL) is read as strict UTF-8, up to MAX_PLAIN bytes; a failed extraction gives no
  text, so a quote from it is never found in the raw bytes. --raw adds folders of raws that are not kept (a manual
  run that read metadata-only sources): their quotes are checked too, and without them such a quote is a warning,
  never a pass.
Exit 1 on any problem; with --strict, also on any warning.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from .quotes import _fold as fold
from .schemas import validate
from .text.extract import UNSUPPORTED
from .text.run import extract_all

TOP = ('packet.json', 'receipt.json', 'sources.json')
TEXTUAL = ('text/plain', 'text/markdown', 'text/csv', 'application/json', 'application/xml', 'text/xml')
MAX_PLAIN = 20_000_000
MIN_QUOTE = 12  # folded characters: a shorter quote is found almost anywhere and locates nothing
RAW = re.compile(r'^raw/sha256/[0-9a-f]{2}/([0-9a-f]{64})\.[a-z0-9]{1,5}$')


def plain_text(path, media_type, result):
    """The text of one raw: rg.text's, or strict UTF-8 for a plain-text format rg.text does not read; else None."""
    text = result.get('text') if result else None
    if text is not None:
        return text
    if (result or {}).get('status') != UNSUPPORTED or media_type not in TEXTUAL or Path(path).stat().st_size > MAX_PLAIN:
        return None
    try:
        return Path(path).read_bytes().decode('utf-8')
    except UnicodeDecodeError:
        return None


def _raws(folders):
    out = {}
    for d in folders:
        for f in sorted(Path(d).glob('sha256/*/*')):
            if f.is_file():
                out.setdefault(f.name.split('.')[0], f)
    return out


def _texts(cited):
    """{path: folded text or None} through rg.text in isolated processes; cited is {path: media_type}."""
    return {path: (None if t is None else fold(t)) for path, t in
            ((p, plain_text(p, cited[p], res)) for p, res in extract_all(sorted(cited), workers=2, timeout=120))}


def _undeclared(folder, packet):
    """Every file or link in the folder that the packet does not declare."""
    allowed = {f"raw/sha256/{a['sha256'][:2]}/" + a['sha256'] for a in packet.get('artifacts', [])
               if a.get('stored_at') == 'repo' and a.get('redistribution') == 'allowed'}
    out, per_sha = [], {}
    for f in sorted(folder.rglob('*')):
        rel = f.relative_to(folder).as_posix()
        if f.is_symlink():
            out.append(f'{rel}: a link, not a file')
        elif f.is_dir():
            continue
        elif rel in TOP:
            continue
        elif (m := RAW.match(rel)) and rel.rsplit('.', 1)[0] in allowed:
            per_sha.setdefault(m.group(1), []).append(rel)
        else:
            out.append(f'{rel}: not declared by packet.json (only {", ".join(TOP)} and the raws of artifacts '
                       "stored_at repo with redistribution allowed)")
    out += [f'{sha[:12]}: more than one raw ({", ".join(rels)})' for sha, rels in per_sha.items() if len(rels) > 1]
    return out


def check(folder, extra=()):
    """(problems, warnings, stats) for one packet folder."""
    folder = Path(folder)
    packet = json.loads((folder / 'packet.json').read_text(encoding='utf-8'))
    problems = [f'schema: {e}' for e in validate('research_packet', packet)] + _undeclared(folder, packet)
    kept, seen = _raws([folder / 'raw']), _raws([folder / 'raw', *extra])
    cited = {}
    for a in packet.get('artifacts', []):
        f, here = seen.get(a['sha256']), kept.get(a['sha256'])
        if a['stored_at'] == 'repo' and here is None:
            problems.append(f"{a['artifact_id']}: stored_at repo but its raw is not in raw/")
        if here is not None and a['redistribution'] != 'allowed':
            problems.append(f"{a['artifact_id']}: raw kept but redistribution is {a['redistribution']}")
        if f is None:
            continue
        body = f.read_bytes()
        if hashlib.sha256(body).hexdigest() != a['sha256'] or len(body) != a['bytes']:
            problems.append(f"{a['artifact_id']}: raw does not match its sha256 and size")
            continue
        cited[a['artifact_id']] = (f, a['media_type'])
    texts = _texts({str(f): media for f, media in cited.values()})
    quotes = verified = 0
    warnings = []
    for group in ('confirmed', 'conflicting'):
        for i, finding in enumerate(packet.get('findings', {}).get(group, [])):
            if 'quote' not in finding:  # a hand-made packet may omit it: nothing to verify, so never a silent pass
                warnings.append(f'{group}[{i}]: no quote, so nothing to verify')
                continue
            quotes += 1
            at_hand = [a for a in finding['artifact_ids'] if a in cited]
            sources = [texts[str(cited[a][0])] for a in at_hand if texts[str(cited[a][0])] is not None]
            if len(fold(finding['quote'])) < MIN_QUOTE:
                problems.append(f'{group}[{i}]: the quote has fewer than {MIN_QUOTE} characters once its whitespace is folded')
            elif not at_hand:
                warnings.append(f'{group}[{i}]: no raw at hand for its artifacts; quote not checked')
            elif not sources:
                problems.append(f'{group}[{i}]: no text could be extracted from the raws it cites; quote not verifiable')
            elif any(fold(finding['quote']) in t for t in sources):
                verified += 1
            else:
                problems.append(f'{group}[{i}]: quote not found in the text of the raws it cites')
    return problems, warnings, {'artifacts': len(packet.get('artifacts', [])), 'raws_kept': len(kept),
                                'quotes': quotes, 'quotes_verified': verified}


def main(argv=None):
    a = argparse.ArgumentParser(description='mechanical gate of a ResearchPacket folder')
    a.add_argument('folder')
    a.add_argument('--raw', action='append', default=[], help='a folder of raws that are not kept (sha256/<2>/<sha>.<ext>)')
    a.add_argument('--strict', action='store_true', help='warnings fail too')
    x = a.parse_args(argv)
    problems, warnings, stats = check(x.folder, x.raw)
    print(json.dumps({**stats, 'problems': problems, 'warnings': warnings}, ensure_ascii=False, indent=1))
    return 1 if problems or (x.strict and warnings) else 0


if __name__ == '__main__':
    sys.exit(main())
