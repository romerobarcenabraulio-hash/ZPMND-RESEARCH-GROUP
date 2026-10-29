#!/bin/bash
# scripts/runner_setup.sh: turn the rented Ubuntu server into RG's own runner for the long, polite crawls (docs/COSTOS.md).
# Run as root on the server, once, and again to update the runner (a PR bumps RUNNER_VERSION and RUNNER_SHA256):
#   bash runner_setup.sh
# It asks for the one-hour registration token and never echoes it, writes it to disk or puts it on a command line.
# What it builds, by construction:
#   - user rg, locked password, no sudo: every job runs as rg;
#   - the runner in /opt/actions-runner, owned by root and read-only for rg, so no job can change the runner, its
#     settings (.runner, .env, .path), its credentials or the guard: rg reads its settings and credentials and writes
#     only its work folder (/home/rg/_work) and the runner's logs (_diag);
#   - a guard (/opt/rg/runner_guard.sh, root's) the runner runs before every job: it refuses any job that is not
#     catalog-mx.yml or texto-mx.yml from refs/heads/main, started by schedule or by the owner's dispatch. A branch or
#     a pull request can carry its own workflow naming this machine's labels; the guard is what stops it;
#   - the runner pinned by version and sha256, self-update off: an update is this script again, with the new pin.
set -euo pipefail
RUNNER_VERSION=2.338.2
RUNNER_SHA256=baebf204307bac6193480852732f0aba2ae97b6c5597c244f4d5558390147c40  # actions/runner release notes, linux-x64
REPO=romerobarcenabraulio-hash/ZPMND-RESEARCH-GROUP
DIR=/opt/actions-runner
WORK=/home/rg/_work
NAME=rg-catalog-vultr
LABELS=rg-catalog

[ "$(id -u)" = 0 ] || { echo "run it as root"; exit 1; }
. /etc/os-release
[ "${ID:-}" = ubuntu ] || { echo "Ubuntu only (this is ${ID:-unknown})"; exit 1; }
command -v python3 >/dev/null && python3 -c 'import sys; sys.exit(sys.version_info < (3, 12))' \
  || { echo "the system python3 must be 3.12 or later: the catalog job runs on it, after its tests"; exit 1; }

token="${RUNNER_TOKEN:-}"
unset RUNNER_TOKEN
if [ -z "$token" ]; then
  read -rsp 'Registration token (GitHub: Settings > Actions > Runners > New self-hosted runner): ' token
  echo
fi
[[ "$token" =~ ^[A-Z0-9]{20,64}$ ]] || { echo "that is not a runner registration token"; exit 1; }

apt-get update -q
DEBIAN_FRONTEND=noninteractive apt-get install -yq ca-certificates curl git jq python3 python3-venv python3-pip
id rg >/dev/null 2>&1 || useradd --create-home --shell /bin/bash rg
passwd -l rg >/dev/null
gpasswd -d rg sudo >/dev/null 2>&1 || true
install -d -o rg -g rg -m 700 "$WORK"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
curl -fsSL -o "$tmp/runner.tgz" "https://github.com/actions/runner/releases/download/v$RUNNER_VERSION/actions-runner-linux-x64-$RUNNER_VERSION.tar.gz"
echo "$RUNNER_SHA256  $tmp/runner.tgz" | sha256sum -c -
if [ -x "$DIR/svc.sh" ]; then (cd "$DIR" && { ./svc.sh stop || true; ./svc.sh uninstall || true; }); fi
rm -rf "$DIR"
install -d -o rg -g rg -m 755 "$DIR"
tar -xzf "$tmp/runner.tgz" -C "$DIR"
chown -R rg:rg "$DIR"
"$DIR/bin/installdependencies.sh" >/dev/null

# Registration as rg (the runner refuses root). The token reaches config.sh through its documented environment input,
# never its arguments, and leaves the environment right after.
export ACTIONS_RUNNER_INPUT_TOKEN="$token"
(cd "$DIR" && runuser -u rg -- ./config.sh --unattended --replace --disableupdate --url "https://github.com/$REPO" \
   --name "$NAME" --labels "$LABELS" --work "$WORK")
unset ACTIONS_RUNNER_INPUT_TOKEN token

# The runner's tree becomes root's. rg keeps write access to its logs only; its settings and credentials it can read,
# never change (GPT on cf3e36e: a job that rewrote .runner would steer every later start).
chown -R root:root "$DIR"
install -d -o rg -g rg -m 755 "$DIR/_diag"
for f in .runner .credentials .credentials_rsaparams; do
  if [ -e "$DIR/$f" ]; then chown root:rg "$DIR/$f" && chmod 640 "$DIR/$f"; fi
done

# The guard, before every job, in files no job can edit.
install -d -o root -g root -m 755 /opt/rg
cat > /opt/rg/runner_guard.sh <<'GUARD'
#!/bin/bash
set -u
repo=romerobarcenabraulio-hash/ZPMND-RESEARCH-GROUP
case "${GITHUB_EVENT_NAME:-}" in
  schedule|workflow_dispatch) ;;
  *) echo "runner guard: event '${GITHUB_EVENT_NAME:-}' is not allowed on this machine"; exit 1 ;;
esac
case "${GITHUB_WORKFLOW_REF:-}" in
  "$repo/.github/workflows/catalog-mx.yml@refs/heads/main"|"$repo/.github/workflows/texto-mx.yml@refs/heads/main") ;;
  *) echo "runner guard: workflow '${GITHUB_WORKFLOW_REF:-}' is not allowed on this machine"; exit 1 ;;
esac
echo "runner guard: ${GITHUB_WORKFLOW_REF} (${GITHUB_EVENT_NAME}) allowed"
GUARD
chown root:root /opt/rg/runner_guard.sh && chmod 755 /opt/rg/runner_guard.sh
cd "$DIR"
touch .env && { grep -v '^ACTIONS_RUNNER_HOOK_JOB_STARTED=' .env > .env.new || true; }
echo 'ACTIONS_RUNNER_HOOK_JOB_STARTED=/opt/rg/runner_guard.sh' >> .env.new
mv .env.new .env && chown root:root .env && chmod 644 .env  # the runner reads it; no job can rewrite it

./svc.sh install rg
./svc.sh start
sleep 5
./svc.sh status | tail -n 3
# What the jobs' user can change in the runner: nothing but its logs. A file it could write is a failure here.
writable=$(runuser -u rg -- find "$DIR" -path "$DIR/_diag" -prune -o -writable -print | head -n 5)
[ -z "$writable" ] || { echo "rg can write in the runner: $writable"; exit 1; }
echo "runner $NAME ($LABELS) installed; jobs run as rg; guard: /opt/rg/runner_guard.sh"
