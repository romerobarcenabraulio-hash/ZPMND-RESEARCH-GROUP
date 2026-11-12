#!/bin/bash
# sellar_crudos.sh <work> <out> <public key PEM>: each raw of <work>/raw/sha256/<aa>/<sha>.<ext> sealed on its own
# (scripts/sobre.sh) with the URL it came from (<work>/fuentes.json, final_url, as <sha>.url) into one file
# <out>/<sha>.<url sha256>.sobre (a tar of the envelope), so R2 keeps one object per body and URL (SECURITY T31). A file
# whose bytes are not the sha256 its name says, outside its own two-hex folder, with no URL in fuentes.json, or any
# link on the way from <work> stops it: R2 never holds bytes under another sha256 or without where they came from.
# <out>/sellados.txt lists "<sha> <url sha256>" of what was sealed, empty when nothing was fetched. No secret: the
# public key seals.
set -euo pipefail
W=$1; O=$2; K=$3; D=$(dirname "$0")
mkdir -p "$O"; : > "$O/sellados.txt"
shopt -s nullglob
for p in "$W" "$W/raw" "$W/raw/sha256"; do [ ! -L "$p" ] || { echo "a link on the way: $p"; exit 3; }; done
U=$(mktemp -d)  # <sha>.url for each fetched raw whose final_url is one https URL with no space or control character
[ ! -f "$W/fuentes.json" ] || python3 -I -c 'import json, os, re, sys
for r in json.load(open(sys.argv[1], encoding="utf-8")):
    s, u = r.get("sha256"), r.get("final_url")
    if isinstance(s, str) and re.fullmatch("[0-9a-f]{64}", s) and isinstance(u, str) and re.fullmatch(r"https://[!-~]{1,2000}", u):
        p = f"{sys.argv[2]}/{s}.url"
        if not os.path.exists(p):  # the first row of a sha256 names its URL
            open(p, "x", encoding="utf-8").write(u)' "$W/fuentes.json" "$U"
for f in "$W"/raw/sha256/*/*; do
  n=$(basename "$f"); sha=${n%%.*}; aa=$(basename "$(dirname "$f")")
  [[ "$sha" =~ ^[0-9a-f]{64}$ && "$aa" == "${sha:0:2}" && -f "$f" && ! -L "$f" && ! -L "$(dirname "$f")" ]] || { echo "not a content address: $f"; exit 3; }
  [ "$(sha256sum "$f" | cut -d' ' -f1)" = "$sha" ] || { echo "$f: its bytes are not $sha"; exit 3; }
  [ -f "$U/$sha.url" ] || { echo "$f: no URL for it in fuentes.json"; exit 3; }
  t=$(mktemp -d); e=$(mktemp -d); mkdir -p "$t/sha256/$aa"; cp "$f" "$t/sha256/$aa/$n"; cp "$U/$sha.url" "$t/sha256/$aa/$sha.url"
  bash "$D/sobre.sh" seal "$t" "$e" "$K"  # the envelope outside the folder it seals: tar never reads a file being written
  uh=$(sha256sum < "$U/$sha.url" | cut -d' ' -f1)  # the same bytes from another URL are another object (GPT on d7a44e5)
  tar -C "$e" -cf "$O/$sha.$uh.sobre" datos.enc datos.mac llave.enc; rm -rf "${t:?}" "${e:?}"
  echo "$sha $uh" >> "$O/sellados.txt"
done
