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
| `rg/catalog/` | guarded fetcher, site adapters (SIDOF/DOF, LeyesBiblio, OJN; SCJN tesis from a secondary Hugging Face dataset; Banxico SIE and INEGI BIE (INPC) indicators, active), fixed doc-type table, store, run with coverage reconciliation |
| `rg/text/` | text of each stored raw by pinned extractor (HTML, DOCX, PDF text layer), one status per raw, quote check ([docs/TEXTO.md](docs/TEXTO.md)) |
| `tests/` | one failing case per guard |
| `requests/`, `knowledge-demand/`, `research-packets/`, `hooks/research-goodware/` | next steps; see the contract, section 5. A packet on main is published: Git is the outbox ([docs/OUTBOX.md](docs/OUTBOX.md)) |

Raw downloads, the agent workspace and run outputs live in `work/`. That folder is never committed.

## Before a PR: make check

No PR is opened or updated red (owner's order 7). `make check` runs what CI runs on a pull request: the whole suite and
the offline policy check, then the mutants of the files the branch changes against `origin/main` (`scripts/mutar_pr.py`;
all of them when it touches `tests/`, the mutant runner or the dependencies). Commit first: the changed files come from
git. On the 16-thread test server, with Python 3.12 from `requirements-dev.txt` and the Postgres tests on:

```
export TMPDIR=$(mktemp -d ~/tmp/run.XXXXXX) RG_TEST_DB_URL='postgresql:///rgtest?host=/var/run/postgresql' RG_REQUIRE_DB_TESTS=1
make -j16 check SHARDS=16
```

`BASE=origin/<branch>` compares with another base and `PYTHON=` picks the interpreter. The PR carries the last lines of
that run as its receipt.

## Startup protocol for a new session

1. Read this README, the contract and the security notes.
2. Read the Knowledge Demand Map and the schemas.
3. Check open requests and the state of the OpenClaw experiment.
4. Continue the highest-priority question.
5. Never change ZPMND, and never present candidate research as canon.
