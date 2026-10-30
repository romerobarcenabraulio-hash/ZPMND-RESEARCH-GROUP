#!/bin/bash
# scripts/runner_setup.sh: turn the rented Ubuntu server into RG's own runner for the long, polite crawls (docs/COSTOS.md),
# one throwaway runner per job. Run as root on the server, once (and again to update the runner: a PR bumps the pin), from
# a folder holding this file, runner_controller.sh and runner_reach.sh, all downloaded by main's exact commit and checked by sha256:
#   bash runner_setup.sh
# It asks once for a fine-grained GitHub token of this repository only (Administration: read and write, to create the
# one-job runners; Actions: read, to see queued jobs) and never echoes it or puts it on a command line or near a job.
# What it builds, by construction (SECURITY.md T19; GPT on 2308494: a long-lived runner whose jobs share its user can be
# copied and replaced by any job that goes wrong, so here no runner lives longer than its one job):
#   - a root service (rg-runner.service, /opt/rg/runner_controller.sh) that starts a just-in-time runner only while
#     GitHub shows a queued job of catalog-mx.yml or texto-mx.yml on main, from schedule or dispatch; GitHub registers it
#     for that one job and removes it after, so its credential dies with the job;
#   - every job runs as rgjob (locked password, no sudo, no new privileges) in a systemd unit of its own, from a fresh copy
#     of the runner in an empty folder with an empty home; when it ends, the unit's processes are killed and both folders
#     deleted, so nothing a job leaves (a process, a venv, a .pth) reaches the next one;
#   - rgjob can read neither the token (/etc/rg, root 700, hidden from the unit) nor write the runner, the controller or
#     the guard (root's); a root-owned guard (/opt/rg/runner_guard.sh) refuses any other job before its first step;
#   - the master copy of the runner pinned by version and sha256 (a PR bumps it); if GitHub requires a newer one, a job's
#     own copy updates itself and is deleted with the job, the master copy never changes.
set -euo pipefail
RUNNER_VERSION=2.338.2
RUNNER_SHA256=baebf204307bac6193480852732f0aba2ae97b6c5597c244f4d5558390147c40  # actions/runner release notes, linux-x64
REPO=romerobarcenabraulio-hash/ZPMND-RESEARCH-GROUP
DIR=/opt/actions-runner
HERE=$(cd "$(dirname "$0")" && pwd)

[ "$(id -u)" = 0 ] || { echo "run it as root"; exit 1; }
. /etc/os-release
[ "${ID:-}" = ubuntu ] || { echo "Ubuntu only (this is ${ID:-unknown})"; exit 1; }
command -v python3 >/dev/null && python3 -c 'import sys; sys.exit(sys.version_info < (3, 12))' \
  || { echo "the system python3 must be 3.12 or later: the catalog job runs on it, after its tests"; exit 1; }
command -v systemd-run >/dev/null || { echo "systemd-run is missing: every job runs in a systemd unit of its own"; exit 1; }
for f in runner_controller.sh runner_reach.sh; do [ -f "$HERE/$f" ] || { echo "$f must sit next to this script"; exit 1; }; done

read -rsp "Fine-grained GitHub token of $REPO only (Administration: read and write; Actions: read): " token
echo
[[ "$token" =~ ^github_pat_[A-Za-z0-9_]{50,255}$ ]] || { echo "that is not a fine-grained GitHub token (github_pat_...)"; exit 1; }

apt-get update -q
DEBIAN_FRONTEND=noninteractive apt-get install -yq ca-certificates curl git jq python3 python3-venv python3-pip
id rgjob >/dev/null 2>&1 || useradd --create-home --shell /bin/bash rgjob
passwd -l rgjob >/dev/null
gpasswd -d rgjob sudo >/dev/null 2>&1 || true

# The token, root's alone, as a header file curl reads with -H @file: never an argument, never in a job's reach.
install -d -o root -g root -m 700 /etc/rg
(umask 077 && printf 'Authorization: Bearer %s\n' "$token" > /etc/rg/auth-header)
unset token
chown root:root /etc/rg/auth-header && chmod 600 /etc/rg/auth-header
curl -fsS -o /dev/null -H @/etc/rg/auth-header -H 'Accept: application/vnd.github+json' \
  "https://api.github.com/repos/$REPO/actions/runners" || { echo "GitHub refused the token for $REPO's runners"; exit 1; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
curl -fsSL -o "$tmp/runner.tgz" "https://github.com/actions/runner/releases/download/v$RUNNER_VERSION/actions-runner-linux-x64-$RUNNER_VERSION.tar.gz"
echo "$RUNNER_SHA256  $tmp/runner.tgz" | sha256sum -c -
systemctl disable --now rg-runner >/dev/null 2>&1 || true  # an update starts it again only after the reach check
systemctl stop 'rg-job-*.service' >/dev/null 2>&1 || true
rm -rf /var/lib/rg/job  # a job folder left by an older install would be rgjob's, so the reach check below would refuse it
rm -rf "$DIR"
install -d -o root -g root -m 755 "$DIR"
tar -xzf "$tmp/runner.tgz" -C "$DIR"
chown -R root:root "$DIR"  # the master copy: each job gets its own copy, deleted after
"$DIR/bin/installdependencies.sh" >/dev/null

# The guard and the controller, in files no job can edit.
install -d -o root -g root -m 755 /opt/rg /var/lib/rg
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
install -o root -g root -m 755 "$HERE/runner_controller.sh" /opt/rg/runner_controller.sh

cat > /etc/systemd/system/rg-runner.service <<'UNIT'
[Unit]
Description=RG: one just-in-time GitHub runner per allowed job (scripts/runner_controller.sh)
After=network-online.target
Wants=network-online.target
[Service]
ExecStart=/opt/rg/runner_controller.sh
Restart=always
RestartSec=60
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload

# What the jobs' user can reach, proved before anything starts: not the token, nor the runner, the controller, the guard,
# the jobs' parent folder or the service (runner_reach.sh fails closed; GPT on fa742b6). A failure here leaves nothing on.
bash "$HERE/runner_reach.sh" rgjob /etc/rg "$DIR" /opt/rg /var/lib/rg /etc/systemd/system/rg-runner.service
systemctl enable --now rg-runner
sleep 5
systemctl --no-pager --lines=3 status rg-runner || true
echo "rg-runner is on: one just-in-time runner per allowed job, as rgjob; guard: /opt/rg/runner_guard.sh"
