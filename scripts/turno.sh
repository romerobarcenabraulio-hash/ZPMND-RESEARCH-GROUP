# scripts/turno.sh, sourced by the investigar.yml steps that call the model: one call with the owner's credentials in
# the order RG_ORDEN gives (Braulio, 2026-10-28: "lo más pesado aquí y lo menos allá, que si no será un gastadero").
#   RG_ORDEN=api          his Anthropic API key first, and his subscription only if that call fails;
#   anything else         his subscription alone: a subscription call never falls back to the paid key.
# The step's RG_API and RG_SUSCRIPCION leave the environment before anything runs; each call gets exactly one
# credential, exported in a subshell of its own (never on a command line), and the answer file holds only the last try.
#   turno <answer file> <input file> <command...>
turno() {
  local out="$1" in="$2" api="${RG_API:-}" sub="${RG_SUSCRIPCION:-}" order rc=1
  shift 2
  unset RG_API RG_SUSCRIPCION
  if [ "${RG_ORDEN:-}" = api ]; then order='api suscripcion'; else order='suscripcion'; fi
  for c in $order; do
    if [ "$c" = api ]; then
      [ -n "$api" ] || continue
      ( unset CLAUDE_CODE_OAUTH_TOKEN; export ANTHROPIC_API_KEY="$api"; exec "$@" ) < "$in" > "$out" && { echo "credencial: api"; return 0; } || rc=$?
    else
      [ -n "$sub" ] || continue
      ( unset ANTHROPIC_API_KEY; export CLAUDE_CODE_OAUTH_TOKEN="$sub"; exec "$@" ) < "$in" > "$out" && { echo "credencial: suscripcion"; return 0; } || rc=$?
    fi
    echo "la llamada con $c terminó con $rc"
    if declare -F diagnose > /dev/null; then diagnose "$out"; fi
  done
  return "$rc"
}
