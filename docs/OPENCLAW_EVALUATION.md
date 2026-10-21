# OpenClaw evaluation

Status: **candidate substrate**, not a dependency. Stages (handoff section 15): install ✔ · understand ✔ (security
surface) · isolate ✔ · small pilot ☐ · observe ☐ · measure ☐ · decide ☐.

## Version and supply chain (2026-10-19)

- Pinned: 2026.10.5, the latest stable release (released 2026-10-18). Tag `v2026.10.5` has a verified signature
  (commit `1b58cb9a`).
- The npm tarball's sha256 (`dbb1bdcf…`) equals the entry in the signed release manifest. That manifest's own sha256
  matches the published `.sha256`. Its sha512 equals the npm registry integrity.
- 564 packages are pinned in `substrate/runtime/package-lock.json`. Five dependencies ship install scripts (esbuild,
  koffi, protobufjs, @google/genai, openclaw); none run, except OpenClaw's own postinstall, which is invoked
  explicitly.
- Base image: the same `node:24-bookworm-slim` digest that OpenClaw pins in its Dockerfile.

## Advisories

- 722 published GitHub advisories (14 critical, 249 high) between 2026-01-31 and 2026-09-11. None affect 2026.10.5.
  Version 2026.4.9 is hit by 200 of them.
- Each issue reported in the press maps to an advisory fixed by 2026.8.1:
  - Claw Chain / OpenShell: GHSA-wppj, GHSA-5h3g;
  - hook events promoted to trusted system events: GHSA-7g8c;
  - senderIsOwner escalation: GHSA-g5cg;
  - MCP loopback sandbox deny: GHSA-5m4g, fixed 2026.8.1.
- The cadence is roughly 90 advisories a month, then none since 2026-09-11. Unexplained (UNKNOWN).

## Trust model (from OpenClaw SECURITY.md, v2026.10.5)

- It is built as a personal assistant with one trusted operator. It is not a multi-tenant boundary.
- Plugins run in-process with the gateway's privileges.
- The sandbox defaults to off, and exec runs on the host.
- Code Mode's default executor (`node:vm`) is not a security boundary.
- The egress proxy covers HTTP and WebSocket only, so the proxy's own policy is the real boundary.
- Prompt injection alone is out of scope for their reports. The model is not trusted.

## Traps found while hardening (each now has a check)

1. `plugins.allow: []` restricts nothing. 41 bundled plugins loaded, including `cua-computer`, `browser`,
   `file-transfer`, `github`, `device-pair` and `linux-node`.
2. `openclaw config validate` rejects unknown keys and bad enum values. It accepts an unknown name inside
   `tools.deny`, so a misspelled group denies nothing and the config still reads as valid.
3. `memory-core` loads outside `plugins.allow` and adds tools (`memory_get`, `memory_search`, `intent`) unless
   `plugins.slots.memory` is `"none"`.
4. Denying the `browser` tool leaves the browser-control service on. `browser.enabled: false` is also required.
5. At startup the gateway fetches a remote model catalog (`catalog.openclaw.ai`), and it runs a daily update check.
   These are turned off (`models.catalogRefresh.enabled`, `update.checkOnStart`, `OPENCLAW_NO_AUTO_UPDATE`) and
   blocked at the proxy.
6. `read`/`write` are not offered over `/tools/invoke`. The agent does not need them: a packet leaves as the agent's
   output.

## Measured runtime (2026-10-19, no model key)

- `openclaw config validate` passes.
- `openclaw security audit`: 0 critical. One warning ("trusted proxies missing") does not apply: the gateway binds to
  loopback inside the container.
- Plugins loaded: `anthropic`, `web-readability`. Neither registers tools or hooks.
- Through the real gateway (`/tools/invoke`):
  - `web_fetch` of a public page works, and the proxy log shows that traffic.
  - Metadata, loopback and rebinding addresses are refused.
  - 21 other tools are not offered (exec, process, code_execution, browser, canvas, computer, nodes, message, memory,
    sessions, sub-agents, file transfer, cron, gateway, plugins, edit, apply_patch, read, write).
  - There is no vendor traffic.

## For the Research Goodware hook (next)

- A disabled bundled plugin named `policy` exists. Read it before writing our own hook.
- Hooks inject the contract, record provenance and shape packets. They are not enforcement: GHSA-68xw-r643-9p5w
  showed skill dispatch skipping before-tool-call hooks.
- `web_search` needs a provider. Claude's native search through the `anthropic` plugin adds no new egress host. Choose
  this in the pilot.
- Prompt-injection detectors on Hugging Face (checked 2026-10-19). These are an extra signal on fetched content, never
  a boundary, because a classifier can be evaded:
  - `protectai/deberta-v3-base-prompt-injection-v2`: Apache-2.0, not gated, mostly English.
  - `proventra/mdeberta-v3-base-prompt-injection`: MIT, multilingual. Relevant because most sources are in Spanish.

  Measure both on Spanish legal pages before relying on either. Downloading them is a pilot step.
