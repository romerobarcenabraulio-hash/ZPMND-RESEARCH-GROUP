# ZPMND RESEARCH GROUP

An external research lab that feeds candidate evidence to ZPMND. It explores freely and has almost no authority.
It is not a second ZPMND and never a source of canonical truth.

```
ResearchRequest (from ZPMND or Braulio) ──► RESEARCH GROUP ──► ResearchPacket (CANDIDATE) ──► ZPMND airlock
```

- **Start here:** [RESEARCH_CONTRACT.md](RESEARCH_CONTRACT.md) covers what we may and may not do, and how information
  enters and leaves.
- **Security:** [SECURITY.md](SECURITY.md) maps each threat to its control and its check.
- **Substrate:** [docs/OPENCLAW_EVALUATION.md](docs/OPENCLAW_EVALUATION.md) has what we found in OpenClaw so far.
- **Catalog:** [docs/CATALOGO.md](docs/CATALOGO.md) covers the per-country catalog: official sources raw, categorized and
  ordered, never summarized. Mexico comes first and runs every 3 days.

## Layout

| Path | What it holds |
|---|---|
| `schemas/` | ResearchRequest, ResearchPacket, SourceArtifact, KnowledgeDemand, CatalogEntry, ChangeEvent, Relation (JSON Schema 2020-12) |
| `rg/` | validator (`rg.schemas`), OpenClaw advisory gate (`rg.advisories`), effective-policy check (`rg.openclaw_policy`) |
| `substrate/` | pinned OpenClaw (`openclaw.lock.json`), hardened profile (`openclaw.json`), isolated runtime (`runtime/`), catalog runner (`runtime/Dockerfile.catalog`) |
| `sources/` | per-country source registry (data, not code): active sources and planned ones with their observed blocker |
| `rg/catalog/` | guarded fetcher, site adapters (SIDOF/DOF, LeyesBiblio, OJN; SCJN tesis from a secondary Hugging Face dataset; Banxico SIE indicators, active; INEGI BIE, in trial), fixed doc-type table, store, run with coverage reconciliation |
| `tests/` | one failing case per guard |
| `requests/`, `knowledge-demand/`, `research-packets/`, `manifests/`, `hooks/research-goodware/` | next steps; see the contract, section 5 |

Raw downloads, the agent workspace and run outputs live in `work/`. That folder is never committed.

## Startup protocol for a new session

1. Read this README, the contract and the security notes.
2. Read the Knowledge Demand Map and the schemas.
3. Check open requests and the state of the OpenClaw experiment.
4. Continue the highest-priority question.
5. Never change ZPMND, and never present candidate research as canon.
