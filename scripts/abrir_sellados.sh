#!/bin/bash
# abrir_sellados.sh <list> <out>: for each <sha256>.<sha256 of its URL> in the list (packet_gate.py --pedir), the copy R2 keeps sealed
# (sealed/sha256/<aa>/<sha>/<url hash>.sobre, written only by investigar.yml's guardar job; SECURITY T31), opened into <out>/sha256/<aa>/<sha>/<url hash>/
# with the URL it was fetched from (<sha>.url) only when its file's bytes hash to that sha256 and its URL file to that hash. A missing or bad copy is
# skipped: the gate then downloads that raw again, as before. The R2 read key and endpoint reach aws alone and the private key sobre.sh alone; nothing
# here parses a raw. Without the read key it opens nothing. Each object R2 holds may be a hostile fetch job's (T31; GPT on 1a8b369): a range of RG_SELLADO_MAX_BYTES
# and one more, RG_SELLADO_SEGUNDOS each, sobre_partes.py externo; RG_SELLADOS_SEGUNDOS and T29's bytes in all, counted as R2 sends them (GPT on 7b649b1).
set -uo pipefail
L=$1; O=$2; D=$(dirname "$0")
ak=${R2_LECTURA_ACCESS_KEY_ID:-}; sk=${R2_LECTURA_SECRET_ACCESS_KEY:-}; ep=${R2_ENDPOINT:-}; pk=${RG_ARTIFACT_KEY:-}
unset R2_LECTURA_ACCESS_KEY_ID R2_LECTURA_SECRET_ACCESS_KEY R2_ENDPOINT RG_ARTIFACT_KEY  # no child inherits them from here on
mkdir -p "$O"; n=0; got=0; cap=${RG_SELLADOS_MAX_BYTES:-500000000}  # T29: 500 MB for one head in all
uno=${RG_SELLADO_MAX_BYTES:-64000000}; plazo=${RG_SELLADO_SEGUNDOS:-120}; fin=$((SECONDS + ${RG_SELLADOS_SEGUNDOS:-600}))  # one object: a 60 MB body sealed (T31) is under 61 MB; sellados' job has 15 minutes
[ -n "$ak" ] && [ -n "$sk" ] && [ -n "$ep" ] && [ -n "$pk" ] || { echo "R2: no read key; every raw is downloaded again"; exit 0; }
while read -r p; do
  [ "$SECONDS" -lt "$fin" ] || { echo "R2: out of time, the rest are downloaded again"; break; }
  [ "$got" -lt "$cap" ] || { echo "R2: out of bytes, the rest are downloaded again"; break; }
  [[ "$p" =~ ^([0-9a-f]{64})\.([0-9a-f]{64})$ ]] || continue
  sha=${BASH_REMATCH[1]} uh=${BASH_REMATCH[2]}; t=$(mktemp -d); r=$((cap - got - 1 < uno ? cap - got - 1 : uno))
  AWS_ACCESS_KEY_ID="$ak" AWS_SECRET_ACCESS_KEY="$sk" AWS_DEFAULT_REGION=auto AWS_REQUEST_CHECKSUM_CALCULATION=when_required \
       AWS_RESPONSE_CHECKSUM_VALIDATION=when_required timeout "$plazo" aws s3api get-object --bucket "${BUCKET:-rg-crudos}" \
       --key "sealed/sha256/${sha:0:2}/$sha/$uh.sobre" --range "bytes=0-$r" --endpoint-url "$ep" "$t/s.tar" >/dev/null 2>&1; ok=$?
  got=$((got + $(stat -c %s "$t/s.tar" 2>/dev/null || echo 0)))  # sent by R2, whatever follows
  if [ "$ok" = 0 ] && [ "$(stat -c %s "$t/s.tar")" -le "$uno" ] \
     && python3 -I "$D/sobre_partes.py" externo "$t/s.tar" "$t/env" "$uno" >/dev/null 2>&1 \
     && RG_ARTIFACT_KEY="$pk" bash "$D/sobre.sh" open "$t/env" "$t/out" >/dev/null 2>&1; then
    f=$(find "$t/out/sha256/${sha:0:2}" -maxdepth 1 -type f -name "$sha.*" ! -name "$sha.url" 2>/dev/null | head -1); u="$t/out/sha256/${sha:0:2}/$sha.url"
    if [ -n "$f" ] && [ "$(sha256sum "$f" | cut -d' ' -f1)" = "$sha" ] \
       && [ "$(sha256sum < "$u" | cut -d' ' -f1)" = "$uh" ]; then  # its URL is the one its key names ($u is regular or missing: sobre.sh open writes no other, T31)
      mkdir -p "$O/sha256/${sha:0:2}/$sha/$uh" && mv "$f" "$u" "$O/sha256/${sha:0:2}/$sha/$uh/" && n=$((n+1))
    fi
  fi
  rm -rf "${t:?}"
done < "$L"
echo "R2: $n sealed raws opened"
