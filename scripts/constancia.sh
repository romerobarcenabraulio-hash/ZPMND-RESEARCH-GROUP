#!/bin/bash
# scripts/constancia.sh: the shell half of .github/workflows/constancia.yml (SECURITY.md T20). From the repo root:
#   bash scripts/constancia.sh faltan <out>   writes "<sha256>  <path>" for every file under research-packets/ that no
#                                             attestation signed by constancia.yml on main covers yet; prints only n=<count>
#   bash scripts/constancia.sh comprobar      every file under research-packets/ verifies, and a copy of one of them with
#                                             one byte changed does not
# Needs GH_TOKEN and REPO (owner/name). Packet files are data: they are listed, hashed and copied, never run.
set -euo pipefail
WF="$REPO/.github/workflows/constancia.yml"

verifica() {  # the check a consumer runs, with every pin gh offers: this repo, this workflow, main, GitHub's runners
  gh attestation verify "$1" -R "$REPO" --signer-workflow "$WF" --source-ref refs/heads/main --deny-self-hosted-runners
}

archivos() {  # every packet file, sorted; a name a checksums line could misread stops the run
  find research-packets -type f | LC_ALL=C sort > "$1"
  [ -s "$1" ] || { echo "no packet files under research-packets/" >&2; exit 1; }
  if grep -vqE '^research-packets/[A-Za-z0-9._/-]+$' "$1"; then echo "a packet path has characters outside [A-Za-z0-9._/-]: nothing attested" >&2; exit 1; fi
}

lista=$(mktemp)
case "${1:-}" in
  faltan)
    out=${2:?usage: constancia.sh faltan <out>}
    archivos "$lista"
    : > "$out"
    while IFS= read -r f; do verifica "$f" >/dev/null 2>&1 || sha256sum "$f" >> "$out"; done < "$lista"
    n=$(wc -l < "$out" | tr -d ' ')
    [ "$n" -le 1024 ] || { echo "$n files to attest: over the 1024 subjects one attestation holds" >&2; exit 1; }
    echo "n=$n" ;;
  comprobar)
    archivos "$lista"
    while IFS= read -r f; do verifica "$f" >/dev/null || { echo "not verified: $f" >&2; exit 1; }; done < "$lista"
    muestra=$(while IFS= read -r f; do if [ -s "$f" ]; then echo "$f"; break; fi; done < "$lista")
    [ -n "$muestra" ] || { echo "every packet file is empty: no copy to change" >&2; exit 1; }
    copia=$(mktemp)
    cp "$muestra" "$copia"
    python3 -I -c 'import sys; p = sys.argv[1]; b = bytearray(open(p, "rb").read()); b[0] ^= 1; open(p, "wb").write(b)' "$copia"
    if verifica "$copia" >/dev/null 2>&1; then echo "a copy of $muestra with one byte changed verified" >&2; exit 1; fi
    echo "$(wc -l < "$lista" | tr -d ' ') packet files verified; a copy of $muestra with one byte changed does not" ;;
  *) echo "usage: constancia.sh faltan <out> | comprobar" >&2; exit 2 ;;
esac
