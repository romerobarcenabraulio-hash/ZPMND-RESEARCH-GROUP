"""Every quote in a ResearchPacket must appear verbatim in the raw bytes of an artifact it cites (whitespace folded).

  python -m rg.quotes research-packets/<RP>/packet.json --raw work/raw-packets
Exit 1 if any quote is not found or a cited raw file is missing or does not match its sha256.
"""
import hashlib
import json
import sys
from pathlib import Path

EXT = {'text/markdown': 'md', 'text/plain': 'txt', 'application/json': 'json', 'text/html': 'html', 'application/pdf': 'pdf'}


def _fold(text):
    return ' '.join(text.split())


def check(packet, raw_root):
    arts = {a['artifact_id']: a for a in packet['artifacts']}
    problems = []
    for group in ('confirmed', 'conflicting'):
        for i, f in enumerate(packet['findings'][group]):
            if 'quote' not in f:
                continue
            found = False
            for aid in f['artifact_ids']:
                a = arts[aid]
                path = Path(raw_root) / 'sha256' / a['sha256'][:2] / f"{a['sha256']}.{EXT.get(a['media_type'], 'bin')}"
                if not path.exists():
                    problems.append(f'{group}[{i}]: raw for {aid} not found')
                    continue
                body = path.read_bytes()
                if hashlib.sha256(body).hexdigest() != a['sha256']:
                    problems.append(f'{group}[{i}]: raw for {aid} does not match its sha256')
                    continue
                if _fold(f['quote']) in _fold(body.decode('utf-8', errors='replace')):
                    found = True
            if not found:
                problems.append(f'{group}[{i}]: quote not found verbatim in cited artifacts: {f["quote"][:80]!r}')
    return problems


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    packet = json.loads(Path(argv[0]).read_text(encoding='utf-8'))
    problems = check(packet, argv[argv.index('--raw') + 1])
    for p in problems:
        print('FAIL', p)
    n = sum('quote' in f for g in ('confirmed', 'conflicting') for f in packet['findings'][g])
    print(f'{n - len([p for p in problems if "quote not found" in p])}/{n} quotes verified verbatim' if not problems else f'{len(problems)} problem(s)')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
