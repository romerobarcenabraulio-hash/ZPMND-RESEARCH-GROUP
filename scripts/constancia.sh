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

verifica_ya() {  # a fresh attestation can take a moment to be found: three tries before a file counts as not verified
  local i
  for i in 1 2 3; do
    verifica "$1" >/dev/null && return 0
    [ "$i" = 3 ] || sleep "${RG_RETRY_SLEEP:-15}"
  done
  return 1
}

archivos() {  # every packet file, NUL-separated and sorted, so a name holding a newline is one name, never two (GPT on
  # e0aa9d7); a whole path a checksums line could misread stops the run before any check
  local f
  find research-packets -type f -print0 | LC_ALL=C sort -z > "$1"
  [ -s "$1" ] || { echo "no packet files under research-packets/" >&2; exit 1; }
  while IFS= read -r -d '' f; do
    [[ "$f" =~ ^research-packets/[A-Za-z0-9._/-]+$ ]] || { echo "a packet path has characters outside [A-Za-z0-9._/-]: nothing attested" >&2; exit 1; }
  done < "$1"
}

lista=$(mktemp)
case "${1:-}" in
  faltan)
    out=${2:?usage: constancia.sh faltan <out>}
    archivos "$lista"
    : > "$out"
    while IFS= read -r -d '' f; do verifica "$f" >/dev/null 2>&1 || sha256sum "$f" >> "$out"; done < "$lista"
    n=$(wc -l < "$out" | tr -d ' ')
    [ "$n" -le 1024 ] || { echo "$n files to attest: over the 1024 subjects one attestation holds" >&2; exit 1; }
    echo "n=$n" ;;
  comprobar)
    archivos "$lista"
    while IFS= read -r -d '' f; do verifica_ya "$f" || { echo "not verified: $f" >&2; exit 1; }; done < "$lista"
    muestra=$(while IFS= read -r -d '' f; do if [ -s "$f" ]; then echo "$f"; break; fi; done < "$lista")
    [ -n "$muestra" ] || { echo "every packet file is empty: no copy to change" >&2; exit 1; }
    copia=$(mktemp)
    cp "$muestra" "$copia"
    # one byte changed, never into the bytes of another packet file (that one is attested, so it would verify; GPT)
    python3 -I -c '
import hashlib, sys
p, lista = sys.argv[1], sys.argv[2]
known = {hashlib.sha256(open(f, "rb").read()).digest() for f in open(lista, "rb").read().split(b"\0") if f}
b = bytearray(open(p, "rb").read())
def cambiado():
    for i in range(len(b)):
        for bit in range(8):
            b[i] ^= 1 << bit
            if hashlib.sha256(b).digest() not in known:
                return b
            b[i] ^= 1 << bit
    sys.exit("every one-byte change of the sample is another packet file")
open(p, "wb").write(cambiado())' "$copia" "$lista"
    if verifica "$copia" >/dev/null 2>&1; then echo "a copy of $muestra with one byte changed verified" >&2; exit 1; fi
    echo "$(tr -cd '\0' < "$lista" | wc -c | tr -d ' ') packet files verified; a copy of $muestra with one byte changed does not" ;;
  *) echo "usage: constancia.sh faltan <out> | comprobar" >&2; exit 2 ;;
esac
