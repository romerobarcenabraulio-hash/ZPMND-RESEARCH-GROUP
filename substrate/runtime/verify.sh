#!/bin/sh
# Egress isolation check for the RESEARCH GROUP runtime. Exits 1 on any mismatch. Usage: sh verify.sh (from this dir).
set -u
cd "$(dirname "$0")"
docker compose --profile verify up -d --build egress probe >/dev/null 2>&1 || { echo "FAIL compose up"; exit 1; }
sleep 3
fails=0
check() { # name expected kind url [proxy]
  name=$1; want=$2; kind=$3; url=$4; px=${5:-}
  if [ -n "$px" ]; then args="-x $px"; else args=""; fi
  got=$(docker compose exec -T probe curl -s -o /dev/null --max-time 15 $args -w "%{$kind}" "$url" 2>/dev/null); rc=$?
  [ "$want" = "unreachable" ] && { [ "$rc" -ne 0 ] && [ "$got" = "000" ] && got=unreachable; }
  if [ "$got" = "$want" ]; then echo "PASS $name ($got)"; else echo "FAIL $name want=$want got=$got rc=$rc"; fails=$((fails+1)); fi
}
P=http://egress:3128
check public_https_via_proxy   200 http_code    https://example.com/ $P
check metadata_ip              403 http_code    http://169.254.169.254/latest/meta-data/ $P
check loopback_ip              403 http_code    http://127.0.0.1/ $P
check ipv4_mapped_loopback    403 http_code    'http://[::ffff:127.0.0.1]/' $P
check private_10               403 http_code    http://10.0.0.1/ $P
check private_192              403 http_code    http://192.168.65.254/ $P
check docker_host_name         403 http_code    http://host.docker.internal/ $P
check rebind_name_to_loopback  403 http_code    http://localtest.me/ $P
check rebind_name_to_metadata  403 http_code    http://169.254.169.254.nip.io/ $P
check clawhub_marketplace     403 http_connect https://clawhub.ai/ $P
check vendor_catalog          403 http_connect https://catalog.openclaw.ai/models/v2/catalog.json $P
check plain_http_non_web_port 403 http_code    http://example.com:8080/ $P
check connect_tunnel_port_80  403 http_connect http://example.com:80/ "$P -p"
check connect_non_443          403 http_connect https://github.com:22/ $P
check direct_https_no_proxy    unreachable http_code https://example.com/
check direct_ip_no_proxy       unreachable http_code http://1.1.1.1/
docker compose --profile verify down >/dev/null 2>&1
[ "$fails" -eq 0 ] && echo "EGRESS OK" || { echo "EGRESS FAIL ($fails)"; exit 1; }
