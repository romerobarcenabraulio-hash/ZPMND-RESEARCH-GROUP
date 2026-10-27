#!/bin/bash
# The sealed envelope of investigar.yml's work folder: the repository and its Actions artifacts are public, and the
# folder holds the bodies and texts of the plan's sources, some of which may only be cited (redistribution
# metadata_only), never republished.
#
#   bash scripts/sobre.sh seal <folder> <envelope dir> <public key PEM>   # no secret: any job can seal
#   bash scripts/sobre.sh open <envelope dir> <folder>                    # needs RG_ARTIFACT_KEY (private key PEM)
#
# seal: a tar of the folder, encrypted with AES-256-CBC under a fresh random key (PBKDF2), then authenticated with
# HMAC-SHA256 under a second fresh key (encrypt-then-MAC); both keys are encrypted with RSA-OAEP to the repository's
# public key (keys/rg-artifacts.pub.pem). The envelope holds datos.enc, datos.mac and llave.enc only.
# open: the private key leaves the environment before any other program starts (no child, tar included, ever sees
# it); the MAC is checked before anything is decrypted, the tar is decrypted whole to a file and only then extracted,
# so a tampered or cut envelope writes nothing. Keys never go on a command line (ps would show them).
set -euo pipefail
ITER=200000

hmac() {  # hmac <key hex in M> <file>: HMAC-SHA256 hex of the file, the key read from the environment
  M="$1" python3 -I -c 'import hashlib, hmac, os, sys
h = hmac.new(bytes.fromhex(os.environ["M"]), digestmod=hashlib.sha256)
with open(sys.argv[1], "rb") as f:
    for chunk in iter(lambda: f.read(1 << 20), b""):
        h.update(chunk)
print(h.hexdigest())' "$2"
}

case "${1:-}" in
  seal)
    [ $# -eq 4 ] || { echo "usage: sobre.sh seal <folder> <envelope> <public key>"; exit 2; }
    mkdir -p "$3"
    k=$(openssl rand -hex 32)
    m=$(openssl rand -hex 32)
    tar -C "$2" -cf - . | K="$k" openssl enc -aes-256-cbc -pbkdf2 -iter "$ITER" -salt -pass env:K -out "$3/datos.enc"
    hmac "$m" "$3/datos.enc" > "$3/datos.mac"
    printf '%s %s' "$k" "$m" | openssl pkeyutl -encrypt -pubin -inkey "$4" -pkeyopt rsa_padding_mode:oaep -out "$3/llave.enc"
    ;;
  open)
    [ $# -eq 3 ] || { echo "usage: sobre.sh open <envelope> <folder>"; exit 2; }
    [ -n "${RG_ARTIFACT_KEY:-}" ] || { echo "RG_ARTIFACT_KEY is not set"; exit 2; }
    pem=$RG_ARTIFACT_KEY
    unset RG_ARTIFACT_KEY  # from here on no program inherits the private key
    keys=$(openssl pkeyutl -decrypt -inkey <(printf '%s\n' "$pem") -pkeyopt rsa_padding_mode:oaep -in "$2/llave.enc")
    unset pem
    k=${keys%% *}
    m=${keys##* }
    [ "$(hmac "$m" "$2/datos.enc")" = "$(cat "$2/datos.mac")" ] || { echo "the envelope does not authenticate"; exit 3; }
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    K="$k" openssl enc -d -aes-256-cbc -pbkdf2 -iter "$ITER" -pass env:K -in "$2/datos.enc" -out "$tmp/datos.tar"
    mkdir -p "$3"
    tar -C "$3" -xf "$tmp/datos.tar" --no-same-owner
    ;;
  *)
    echo "usage: sobre.sh seal|open ..."; exit 2
    ;;
esac
