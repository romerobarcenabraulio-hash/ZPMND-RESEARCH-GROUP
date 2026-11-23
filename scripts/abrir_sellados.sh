#!/bin/bash
# abrir_sellados.sh <list> <out>: for each <sha256>.<sha256 of its URL> in the list (packet_gate.py --pedir), the copy R2 keeps sealed
# (sealed/sha256/<aa>/<sha>/<url hash>.sobre, written only by investigar.yml's guardar job; SECURITY T31), opened into <out>/sha256/<aa>/<sha>/<url hash>/
# with the URL it was fetched from (<sha>.url) only when its file's bytes hash to that sha256 and its URL file to that hash. A missing or bad copy is
# skipped: the gate then downloads that raw again, as before. The R2 read key and endpoint reach aws alone and the private key sobre.sh alone; nothing
# here parses a raw. Without the read key it opens nothing. Each object R2 holds may be a hostile fetch job's (T31; GPT on 1a8b369): a range of RG_SELLADO_MAX_BYTES
# and one more, RG_SELLADO_SEGUNDOS each, sobre_partes.py externo; RG_SELLADOS_SEGUNDOS and T29's bytes in all, counted as R2 sends them (GPT on 7b649b1).
# Each program, aws and the two readers, gets only the time the step has left, then KILL to its whole group (acota).
# Each copy it does not open is named in the log, by its sha256's first 12 hex, with the stage that stopped it and, for
# get-object, AWS's error code alone: never its message, the endpoint or a key (#178 and #179 opened 0 with no reason).
set -uo pipefail
acota() {  # acota <s> <program...>: at most <s> seconds (0: no limit of its own) and never past the step's end ($fin); nothing
  local s=$((fin - SECONDS)) p w quien rc; [ "$s" -gt 0 ] || return 124  # once that has passed (GPT on e9ef1e1)
  [ "$1" -gt 0 ] && [ "$1" -lt "$s" ] && s=$1; shift
  setsid "$@" & p=$!  # its own session and group, whatever timeout the runner has (uutils signals no group): GPT on e706b0e
  sleep "$s" & w=$!
  wait -n -p quien "$p" "$w"; rc=$?
  kill -KILL -- -"$p" 2>/dev/null; kill "$w" 2>/dev/null; wait "$p" "$w" 2>/dev/null  # the whole group, children that ignore TERM too
  [ "$quien" = "$p" ] && return "$rc"; return 124
}
[ "${BASH_SOURCE[0]}" = "$0" ] || return 0  # sourced by its tests: the function only
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
       AWS_RESPONSE_CHECKSUM_VALIDATION=when_required acota "$plazo" aws s3api get-object --bucket "${BUCKET:-rg-crudos}" \
       --key "sealed/sha256/${sha:0:2}/$sha/$uh.sobre" --range "bytes=0-$r" --endpoint-url "$ep" "$t/s.tar" >/dev/null 2>"$t/err"; ok=$?
  got=$((got + $(stat -c %s "$t/s.tar" 2>/dev/null || echo 0)))  # sent by R2, whatever follows
  why=  # why this one stays unopened; only a code in parentheses is taken from what aws printed
  if [ "$ok" = 124 ]; then why='get-object: out of time'
  elif [ "$ok" != 0 ]; then code=$(grep -oE '\([A-Za-z]{2,40}\)' "$t/err" 2>/dev/null | head -n 1 | tr -d '()'); why="get-object: ${code:-no error code}"
  elif [ "$(stat -c %s "$t/s.tar")" -gt "$uno" ]; then why='larger than one envelope'
  elif ! acota 0 python3 -I "$D/sobre_partes.py" externo "$t/s.tar" "$t/env" "$uno" >/dev/null 2>&1; then why='not an envelope'
  elif ! RG_ARTIFACT_KEY="$pk" acota 0 bash "$D/sobre.sh" open "$t/env" "$t/out" >/dev/null 2>&1; then why='does not open (another key, or altered)'
  else
    f=$(find "$t/out/sha256/${sha:0:2}" -maxdepth 1 -type f -name "$sha.*" ! -name "$sha.url" 2>/dev/null | head -1); u="$t/out/sha256/${sha:0:2}/$sha.url"
    # its bytes and its URL checked, then moved, within the step's time like the rest (GPT on 6bdcc38); its URL is the one its key
    # names ($u is regular or missing: sobre.sh open writes no other, T31)
    if [ -n "$f" ] && acota 0 bash -c 'read -r h _ < <(sha256sum "$1") && [ "$h" = "$2" ] && read -r h _ < <(sha256sum < "$3") && [ "$h" = "$4" ] && mkdir -p "$5" && mv "$1" "$3" "$5/"' \
         guardar "$f" "$sha" "$u" "$uh" "$O/sha256/${sha:0:2}/$sha/$uh"; then
      n=$((n+1))
    else
      why="its bytes or its URL are not its key's"
    fi
  fi
  [ -z "$why" ] || echo "R2: ${sha:0:12} not opened: $why"
  rm -rf "${t:?}"
done < "$L"
echo "R2: $n sealed raws opened"
