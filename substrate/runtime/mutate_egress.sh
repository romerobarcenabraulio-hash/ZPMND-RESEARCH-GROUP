#!/bin/sh
# Mutation check: removing ANY deny rule from squid.conf must make verify.sh fail. Restores squid.conf at the end.
set -u
cd "$(dirname "$0")"
cp squid.conf squid.conf.orig
trap 'mv -f squid.conf.orig squid.conf; docker compose --profile verify down >/dev/null 2>&1' EXIT
survivors=0
for rule in 'deny blocked_vendor' 'deny blocked_dst' 'deny !web_ports' 'deny CONNECT !SSL_ports' 'allow research_net'; do
  grep -vxF "http_access $rule" squid.conf.orig > squid.conf
  if sh verify.sh >/dev/null 2>&1; then echo "SURVIVED without: $rule"; survivors=$((survivors+1)); else echo "KILLED  without: $rule"; fi
done
[ "$survivors" -eq 0 ] && echo "MUTATION OK" || { echo "MUTATION FAIL ($survivors survivors)"; exit 1; }
