# Security

The research agent is assumed hostile: any web page it reads can steer it (OpenClaw's own trust model says the model
is not a trusted principal). Security therefore comes from what the agent **cannot reach or hold**, not from what it is
told. Every control below has a check that fails without it.

## Threats, controls, checks

| # | Threat | Control | Check |
|---|---|---|---|
| T1 | A packet claims truth, canon or authority | `status` is the constant `CANDIDATE`; no unknown field at any depth | `tests/test_schemas.py` NoAuthority |
| T2 | Invented or untraceable sources | every finding cites hashed artifacts present in the packet; confirmed findings need a primary source | `tests/test_schemas.py` Provenance |
| T3 | Hidden instructions travel into ZPMND | visible-text only (no zero-width, bidi, control chars), quotes ≤ 300 chars, size cap | `tests/test_schemas.py` HiddenContent |
| T4 | Private data enters the research world | requests are `PUBLIC`/`ABSTRACTED` only, issued by ZPMND or the owner; RG never reads ZPMND; repo private as defense in depth | `tests/test_schemas.py` PrivacyAndRights |
| T5 | Vulnerable or tampered substrate | OpenClaw 2026.10.5: signed tag 1b58cb9a; npm tarball sha256 matches the signed release manifest; 564 deps pinned by lockfile, `npm ci --ignore-scripts`; base image pinned by digest | `tests/test_advisories.py`, `python -m rg.advisories --fetch` (CI weekly) |
| T6 | Over-capable agent | effective tools = `web_search`, `web_fetch`; plugins = `anthropic`, `web-readability`; no exec, files, browser, memory, sessions, sub-agents, code mode; no vendor phone-home | `tests/test_openclaw_policy.py`, `substrate/runtime/verify_config.sh`, `substrate/runtime/verify_e2e.sh` |
| T7 | Credential leakage | no ZPMND credentials exist here; config holds only `${ENV}` references; the model key is RG-only and spend-capped; the Banxico and INEGI tokens are bound to their own host in the Fetcher and never written (recorded URLs carry `<token>`, the manifest is redacted, a response that echoes a token is not stored, the dispatch job scans its artifact) | `tests/test_no_secrets.py`, literal-secret check in `rg/openclaw_policy.py`, `tests/test_indicadores.py` |
| T8 | Reaching internal systems (SSRF, metadata, host, DNS rebinding) | gateway on an internal network; only route out is the egress proxy, which denies internal/metadata/reserved ranges by resolved address, vendor marketplace/telemetry hosts, and non-web ports | `substrate/runtime/verify.sh` (16 probes), `substrate/runtime/mutate_egress.sh` (each rule removed → check fails) |
| T9 | Escaping the container | read-only root, all capabilities dropped, `no-new-privileges`, non-root user, pid/memory limits, **no Docker socket** | `substrate/runtime/compose.yml`; e2e shows the read-only root refusing writes |
| T10 | The catalog fetcher is abused or abuses a site | host allowlist per source, TLS verified, https only, robots.txt honored per RFC 9309 (up to 5 redirects inside the allowlist, groups of one agent combined; unreachable or 401/403/429 = disallow; unreachable never persisted as 'disallowed'), ≥1 s per host or Crawl-delay, redirects re-checked, size cap, request budget and run deadline. Local runs go through the internal network and the egress proxy; the scheduled job runs on a GitHub runner with the same Fetcher guards and no write token on disk while pages are parsed | `tests/test_catalog.py` FetchGuards, `tests/test_run_guards.py` |
| T11 | Silent incompleteness ("all" that is not all) | every run reconciles extracted items against an independent count on the same official page; mismatch = exit 3 and a manifest entry; every entry validated against `catalog_entry` (exit 4) | `tests/test_catalog.py` parsers and reconciliation, `rg/catalog/run.py` |
| T12 | A hostile raw file (PDF, DOCX, tar) hangs or takes over the text run | format by first bytes; each raw parsed in its own process with a time, size and address-space limit, and no more workers than the memory holds at that limit (a hang, crash or blow-up = `fallo` for that file only); DOCX parts capped (zip bomb); raw bundles verified against their sha256 before unpacking, a member over 200 MB or over the run's unpack budget stopping its bundle before it is written, and only regular `sha256/<2>/<sha>.<ext>` members written at a path rebuilt from the name; no token while raw files are unpacked or parsed; every raw gets one status by the current extractor of its format, or exit 3 | `tests/test_texto.py`, `rg/text/run.py`, `rg/text/bundles.py` |

OpenClaw's built-in sandbox stays off on purpose: it needs the Docker socket, which is root on the host. The outer
container is the sandbox.

## How to verify

```
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -t .
sh substrate/runtime/verify.sh          # egress isolation
sh substrate/runtime/mutate_egress.sh   # every proxy rule is needed
sh substrate/runtime/verify_config.sh   # OpenClaw validate + effective plugins + security audit, no network
sh substrate/runtime/verify_e2e.sh      # the real gateway's own tools through the proxy
```

## Residual risks (accepted, with reason)

- **Exfiltration through allowed requests.** Open-web research needs outbound HTTPS, so anything in the agent's context
  can leave in a URL. Mitigation by construction: nothing private is ever in this world (T4).
- **Steering within two tools.** Prompt injection can make the agent fetch or search the wrong things. Outputs are
  CANDIDATE data that ZPMND evaluates; nothing here acts on the world.
- **The model key sits in the gateway process.** It must be a key used only by RESEARCH GROUP, with a spend limit.
- **Host.** The runtime runs in Docker Desktop on the owner's Mac. A dedicated VM or host is stronger and is the step
  before scaling past the pilot.
- **Advisory feed gap.** OpenClaw published 722 advisories from 2026-01-31 to 2026-09-11 and none since. Unexplained;
  the gate re-runs weekly and before every pilot.
- **Not yet exercised:** IPv6 egress (no IPv6 route on the internal network; ranges are listed anyway); dev tooling is
  pinned by version, not hash; the proxy's squid comes from Debian security updates at build time.
- **Hooks are not a boundary.** OpenClaw advisory GHSA-68xw-r643-9p5w: skill dispatch skipped before-tool-call hooks.
  The Research Goodware hook will inject the contract and record provenance; enforcement stays in config, network and
  container.
