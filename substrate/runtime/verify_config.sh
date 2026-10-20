#!/bin/sh
# Effective-state check of the OpenClaw profile, inside the pinned image with NO network. Exits 1 on any failure.
# Usage: sh substrate/runtime/verify_config.sh   (needs Docker and the repo venv: python3 -m venv .venv; pip install -r requirements-dev.txt)
set -eu
here=$(cd "$(dirname "$0")" && pwd); repo=$(cd "$here/../.." && pwd)
out="$repo/work/verify"; mkdir -p "$out"   # git-ignored; overwritten on every run
trap 'docker volume rm -f rg-verify-state >/dev/null 2>&1 || true' EXIT
cd "$here" && docker compose build -q gateway >/dev/null
run() { docker run --rm --network none --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges:true \
  -e OPENCLAW_GATEWAY_TOKEN="$(openssl rand -hex 32)" -v rg-verify-state:/state rg-gateway "$@"; }
run --version
run config validate | tee "$out/validate.txt"
grep -q '^Config valid:' "$out/validate.txt" || { echo "FAIL openclaw config validate"; exit 1; }
run plugins list --json > "$out/plugins.json"
run security audit --json > "$out/audit.json"
cd "$repo" && .venv/bin/python -m rg.openclaw_policy "$repo/substrate/openclaw.json" --plugins "$out/plugins.json" --audit "$out/audit.json"
