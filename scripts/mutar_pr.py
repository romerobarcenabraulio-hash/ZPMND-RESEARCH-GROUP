"""Mutants a PR runs (owner's order 2, 2026-11-03): only those of the files it changes; all of them when it changes
tests/, the mutant runner or the dependencies; none when it changes only docs or data. The whole list runs every night
(mutacion-noche.yml, watched by scripts/vigia.py), so a guard a PR did not touch is still proved within a day. The
changed files come from git against RG_MUT_BASE (ci.yml sets it to the PR's base); without it, everything runs."""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mutar  # noqa: E402

TODOS = ('tests/', 'scripts/mutar.py', 'scripts/mutar_pr.py', 'requirements')


def elegir(cambiados, mut):
    if any(c.startswith(TODOS) for c in cambiados):
        return list(mut)
    return [m for m in mut if m[0] in set(cambiados)]


def cambiados(base):
    out = subprocess.run(['git', 'diff', '--name-only', f'{base}...HEAD'], capture_output=True, text=True, check=True)
    return out.stdout.split()


def main():
    base = os.environ.get('RG_MUT_BASE', '')
    if base:
        files = cambiados(base)
        mutar.MUT = elegir(files, mutar.MUT)
        print(f'{len(mutar.MUT)} mutants for {len(files)} changed files (base {base})')
        if not mutar.MUT:
            return 0
    return mutar.main()


if __name__ == '__main__':
    sys.exit(main())
