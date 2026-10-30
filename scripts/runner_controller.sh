#!/bin/bash
# scripts/runner_controller.sh: RG's runner service (SECURITY.md T19), installed by scripts/runner_setup.sh as
# /opt/rg/runner_controller.sh and run by root from rg-runner.service, day and night. Each pass: while GitHub shows a
# queued job of an allowed workflow, ask GitHub for a just-in-time runner (it takes one job and GitHub removes it),
# run it as the jobs' user in a systemd unit of its own, from a fresh copy of the runner in an empty folder with an
# empty home; when it ends, kill whatever the unit left and delete both folders. No runner outlives its job, so a job
# that goes wrong cannot reach the next one (GPT on 2308494).
# RG_CONTROLLER_ONCE=1 does a single pass without sleeping; the RG_* paths and the user are set only by the tests.
set -uo pipefail
REPO=romerobarcenabraulio-hash/ZPMND-RESEARCH-GROUP
API=https://api.github.com/repos/$REPO/actions
LABEL=rg-catalog
HEADER=${RG_AUTH_HEADER:-/etc/rg/auth-header}   # "Authorization: Bearer <token>", root 600 in a root 700 folder
RUNNER=${RG_RUNNER_DIR:-/opt/actions-runner}
JOB=${RG_JOB_DIR:-/var/lib/rg/job}
JOBHOME=${RG_JOB_HOME:-/home/rgjob}
JOBUSER=${RG_JOB_USER:-rgjob}
JOBGROUP=${RG_JOB_GROUP:-rgjob}

api() {  # the token goes to curl from its file, never on a command line another process could read
  curl -fsS --max-time 60 -H @"$HEADER" -H 'Accept: application/vnd.github+json' -H 'X-GitHub-Api-Version: 2022-11-28' "$@"
}

nap() { [ "${RG_CONTROLLER_ONCE:-}" = 1 ] || sleep "$1"; }

allowed_queued() {  # queued jobs that may run here: catalog-mx.yml or texto-mx.yml on main, by schedule or dispatch, our label
  local runs ids id k n=0
  runs=$(api "$API/runs?status=queued&branch=main&per_page=50" && api "$API/runs?status=in_progress&branch=main&per_page=50") || return 1
  ids=$(jq -r --arg repo "$REPO" '.workflow_runs[]
        | select(.repository.full_name == $repo and .head_repository.full_name == $repo and .head_branch == "main")
        | select(.event == "schedule" or .event == "workflow_dispatch")
        | select((.path | split("@")[0]) as $p | $p == ".github/workflows/catalog-mx.yml" or $p == ".github/workflows/texto-mx.yml")
        | .id' <<<"$runs") || return 1
  for id in $ids; do
    [[ "$id" =~ ^[0-9]+$ ]] || return 1
    k=$(api "$API/runs/$id/jobs?filter=latest&per_page=100" |
        jq --arg l "$LABEL" '[.jobs[] | select(.status == "queued" and (.labels | index($l)))] | length') || return 1
    n=$((n + k))
  done
  echo "$n"
}

clean() {  # nothing of a job outlives it: its unit, its processes, its folder, its home
  systemctl stop 'rg-job-*.service' >/dev/null 2>&1 || true
  pkill -KILL -u "$JOBUSER" >/dev/null 2>&1
  local rc=$?  # 0 killed some, 1 none were left; anything else means it could not kill (GPT on fa742b6)
  [ "$rc" -le 1 ] || { echo "could not kill $JOBUSER's processes (pkill $rc): stopping"; exit 1; }
  sleep 1
  pgrep -u "$JOBUSER" >/dev/null
  rc=$?  # only 1, no process, lets the next job start: 0 is a survivor, anything else means we could not tell
  [ "$rc" = 1 ] || { echo "a process of $JOBUSER survived its job, or pgrep could not tell ($rc): stopping"; exit 1; }
  rm -rf "$JOB" "$JOBHOME"
}

run_one() {  # one just-in-time runner, one job, then nothing left
  local resp jit id
  resp=$(jq -n --arg n "rg-$(date +%s)" --arg l "$LABEL" \
           '{name: $n, runner_group_id: 1, labels: ["self-hosted", $l], work_folder: "_work"}' |
         api -X POST "$API/runners/generate-jitconfig" --data @-) || { echo "GitHub gave no runner"; return 1; }
  jit=$(jq -r '.encoded_jit_config // empty' <<<"$resp")
  id=$(jq -r '.runner.id // empty' <<<"$resp")
  [ -n "$jit" ] && [[ "$id" =~ ^[0-9]+$ ]] || { echo "GitHub gave no runner"; return 1; }
  clean
  install -d -o "$JOBUSER" -g "$JOBGROUP" -m 700 "$JOB" "$JOBHOME"
  cp -a "$RUNNER/." "$JOB/runner"
  printf 'ACTIONS_RUNNER_HOOK_JOB_STARTED=/opt/rg/runner_guard.sh\n' > "$JOB/runner/.env"  # root's guard, before every job
  install -o "$JOBUSER" -g "$JOBGROUP" -m 600 /dev/null "$JOB/jit"
  printf '%s' "$jit" > "$JOB/jit"  # the job's own one-job credential, deleted with the folder
  chown -R "$JOBUSER:$JOBGROUP" "$JOB/runner"
  systemd-run --unit="rg-job-$id" --uid="$JOBUSER" --gid="$JOBGROUP" --collect --quiet \
    -p WorkingDirectory="$JOB/runner" -p Environment=HOME="$JOBHOME" -p RuntimeMaxSec=86400 \
    -p KillMode=control-group -p NoNewPrivileges=yes -p PrivateTmp=yes -p ProtectSystem=strict \
    -p ReadWritePaths="$JOB" -p ReadWritePaths="$JOBHOME" -p InaccessiblePaths="$(dirname "$HEADER")" \
    -p RestrictSUIDSGID=yes -p ProtectKernelTunables=yes -p ProtectControlGroups=yes \
    /bin/bash -c 'exec ./run.sh --jitconfig "$(cat ../jit)"' || { echo "rg-job-$id did not start"; finish "$id"; return 1; }
  local waited=0 busy=false
  while systemctl is-active --quiet "rg-job-$id.service"; do  # a runner no job reaches in 10 minutes is stopped
    [ "$busy" = true ] || busy=$(api "$API/runners/$id" | jq -r '.busy // false' 2>/dev/null || echo false)
    if [ "$busy" != true ] && [ "$waited" -ge 600 ]; then echo "no job reached rg-job-$id in 10 minutes"; break; fi
    nap 30; waited=$((waited + 30))
  done
  echo "runner rg-job-$id ended"
  finish "$id"
}

finish() {  # GitHub removes a used runner; this removes one never used. Then nothing of the job is left.
  api -X DELETE "$API/runners/$1" >/dev/null 2>&1 || true
  clean
}

[ -r "$HEADER" ] || { echo "no token at $HEADER: run scripts/runner_setup.sh"; exit 1; }
clean  # a crash or a reboot in the middle of a job leaves nothing behind either
while true; do
  if n=$(allowed_queued); then
    if [ "$n" -gt 0 ]; then run_one || { echo "no runner ran; retrying in a minute"; nap 60; }; else nap 30; fi
  else
    echo "GitHub did not answer; retrying in a minute"; nap 60
  fi
  [ "${RG_CONTROLLER_ONCE:-}" = 1 ] && break
done
