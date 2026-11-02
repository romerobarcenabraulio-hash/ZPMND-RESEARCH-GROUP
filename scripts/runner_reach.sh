#!/bin/bash
# scripts/runner_reach.sh USER SECRET_DIR PATH...: succeeds only if USER can neither enter SECRET_DIR nor write anything under
# the PATHs. runner_setup.sh runs it before the service starts (SECURITY.md T19). It fails closed: a check it cannot finish,
# such as a folder find cannot read, is a failure, never a pass (GPT on fa742b6: find over the token's 700 folder aborted the
# installer after the service had started).
set -u
user=$1 secret=$2
shift 2
as() { if [ "$user" = "$(id -un)" ]; then "$@"; else runuser -u "$user" -- "$@"; fi; }
if as test -x "$secret"; then echo "$user can enter $secret"; exit 1; fi
if ! writable=$(as find "$@" -writable -print); then echo "could not check what $user can write: find failed"; exit 1; fi
if [ -n "$writable" ]; then echo "$user can write: $(printf '%s\n' "$writable" | head -n 5)"; exit 1; fi
echo "$user cannot enter $secret nor write in: $*"
