#!/bin/bash
# abrir_sellados.sh <list> <out>: for each <sha256>.<sha256 of its URL> in the list (packet_gate.py --pedir), the copy R2
# keeps sealed (sealed/sha256/<aa>/<sha>/<url hash>.sobre, written only by investigar.yml's guardar job; SECURITY T31),
# opened into <out>/sha256/<aa>/<sha>/<url hash>/ with the URL it was fetched from (<sha>.url) only when its file's bytes
# hash to that sha256 and its URL file to that hash. A missing or bad copy is skipped: the gate then downloads that raw again, as before. The R2 read key and endpoint reach
# aws alone and the private key sobre.sh alone; nothing here parses a raw. Without the read key it opens nothing.
set -uo pipefail
L=$1; O=$2; D=$(dirname "$0")
ak=${R2_LECTURA_ACCESS_KEY_ID:-}; sk=${R2_LECTURA_SECRET_ACCESS_KEY:-}; ep=${R2_ENDPOINT:-}; pk=${RG_ARTIFACT_KEY:-}
unset R2_LECTURA_ACCESS_KEY_ID R2_LECTURA_SECRET_ACCESS_KEY R2_ENDPOINT RG_ARTIFACT_KEY  # no child inherits them from here on
mkdir -p "$O"; n=0; bytes=0; cap=${RG_SELLADOS_MAX_BYTES:-500000000}  # T29: 500 MB for one head in all
[ -n "$ak" ] && [ -n "$sk" ] && [ -n "$ep" ] && [ -n "$pk" ] || { echo "R2: no read key; every raw is downloaded again"; exit 0; }
while read -r p; do
  [[ "$p" =~ ^([0-9a-f]{64})\.([0-9a-f]{64})$ ]] || continue
  sha=${BASH_REMATCH[1]} uh=${BASH_REMATCH[2]}
  t=$(mktemp -d)
  if AWS_ACCESS_KEY_ID="$ak" AWS_SECRET_ACCESS_KEY="$sk" AWS_DEFAULT_REGION=auto AWS_REQUEST_CHECKSUM_CALCULATION=when_required \
       AWS_RESPONSE_CHECKSUM_VALIDATION=when_required aws s3api get-object --bucket "${BUCKET:-rg-crudos}" \
       --key "sealed/sha256/${sha:0:2}/$sha/$uh.sobre" --endpoint-url "$ep" "$t/s.tar" >/dev/null 2>&1 \
     && mkdir "$t/env" && tar -C "$t/env" -xf "$t/s.tar" datos.enc datos.mac llave.enc \
     && RG_ARTIFACT_KEY="$pk" bash "$D/sobre.sh" open "$t/env" "$t/out" >/dev/null 2>&1; then
    f=$(find "$t/out/sha256/${sha:0:2}" -maxdepth 1 -type f -name "$sha.*" ! -name "$sha.url" 2>/dev/null | head -1)
    u="$t/out/sha256/${sha:0:2}/$sha.url"
    if [ -n "$f" ] && [ -f "$u" ] && [ ! -L "$u" ] && [ "$(sha256sum "$f" | cut -d' ' -f1)" = "$sha" ] \
       && [ "$(sha256sum < "$u" | cut -d' ' -f1)" = "$uh" ]; then  # its URL is the one its key names
      bytes=$((bytes + $(stat -c %s "$f")))
      [ "$bytes" -le "$cap" ] || { rm -rf "${t:?}"; break; }
      mkdir -p "$O/sha256/${sha:0:2}/$sha/$uh" && mv "$f" "$u" "$O/sha256/${sha:0:2}/$sha/$uh/" && n=$((n+1))
    fi
  fi
  rm -rf "${t:?}"
done < "$L"
echo "R2: $n sealed raws opened"
