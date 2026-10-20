#!/bin/sh
# End-to-end: the real gateway on the internal network, its own tools, egress only via the proxy. Exits 1 on failure.
set -u
cd "$(dirname "$0")"
export OPENCLAW_GATEWAY_TOKEN="$(openssl rand -hex 32)"
cleanup() { docker compose down -v >/dev/null 2>&1; }
trap cleanup EXIT
docker compose up -d --build egress gateway >/dev/null 2>&1 || { echo "FAIL compose up"; exit 1; }
i=0; until docker compose exec -T gateway node -e "fetch('http://127.0.0.1:18789/healthz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))" 2>/dev/null; do
  i=$((i+1)); [ $i -gt 60 ] && { echo "FAIL gateway not healthy"; docker compose logs gateway | tail -20; exit 1; }; sleep 2; done
# The root is read-only, so the probe is streamed over stdin instead of copied in.
docker compose exec -T -e OPENCLAW_GATEWAY_TOKEN gateway node --input-type=module - < e2e_probe.mjs; rc=$?
echo "egress log (gateway traffic):"; docker compose logs egress 2>&1 | grep -E 'TCP_|NONE_' | sed 's/^egress-1 *| */  /' | tail -8
# Vendor phone-home must not happen (catalog refresh, update checks, telemetry, marketplace).
if docker compose logs egress 2>&1 | grep -qiE 'openclaw\.ai|clawhub'; then echo "FAIL gateway contacted an OpenClaw vendor host"; rc=1; else echo "PASS no vendor phone-home"; fi
exit $rc
