# Research Contract

RESEARCH GROUP explores freely and holds almost no authority. It discovers, collects, maps, compares, challenges,
classifies and packages **candidate** knowledge for ZPMND. It never decides what is true.

Source: Braulio's dual-repository handoff (October 2026), sections 12–46. This contract is the RESEARCH GROUP side of
it; ZPMND keeps its own canon and decides what it does with anything we send.

## 1. Authority

| May | May not |
|---|---|
| search, browse, read, fetch public sources | change ZPMND (code, canon, memory, governance, roadmap) |
| download files it has the right to keep, hash them, catalog them | promote anything to fact, canon, policy or criterion |
| compare, classify, cross-reference, find contradictions | grant permissions or create authority |
| propose candidate findings, controls, tests, implications | use ZPMND credentials or touch ZPMND production systems |
| | certify its own conclusions |
| | keep private data of Braulio, organizations or clients |

These limits are enforced by construction, not by good behavior: the schemas have no field that can carry authority
(section 4), the runtime has no credentials and two tools (SECURITY.md), and ZPMND is never reachable from here.

## 2. How information feeds in: ResearchRequest

A research need exists only as a `ResearchRequest` ([schema](schemas/research_request.schema.json)). RESEARCH GROUP
does not invent needs for ZPMND; it may propose demands (`origin: RG_PROPOSED`), which stay proposals until ZPMND
issues a request for them.

- **Issued by** `ZPMND` or `OWNER` (Braulio). Never by RESEARCH GROUP.
- **Privacy:** `privacy_class` is `PUBLIC` or `ABSTRACTED`. Anything private stays in ZPMND; the request describes the
  question in public terms. There is no value for private material, so it cannot be expressed.
- **Delivery:** a JSON file under `requests/` added by pull request. RESEARCH GROUP never reads the ZPMND repository,
  its state or its documents.
- **Fields:** question, why it is needed, affected component (abstract name), desired evidence, priority, risk if
  wrong.

## 3. How information feeds out: ResearchPacket → ZPMND airlock

```
ResearchRequest ──► RESEARCH GROUP (agents, tools, sources)
                         │
                         ▼
                 ResearchPacket  (status: CANDIDATE, always)
                 + SourceArtifacts (url, date, sha256, license, redistribution)
                         │  committed under research-packets/ and manifests/
                         ▼
                 ZPMND airlock (ZPMND's own code and judgment)
                         │
            REJECT · UNKNOWN · CONFLICT · HYPOTHESIS · EXPERIMENT · DECISION · CANON DELTA
```

- A packet ([schema](schemas/research_packet.schema.json)) answers exactly one request (`request_id` is required).
- Every finding cites artifacts that were retrieved and hashed; `confirmed` means *the cited primary source states it*,
  not that it is verified. Verification happens in ZPMND.
- `candidate_tests`, `candidate_controls`, `candidate_methods` are descriptions. ZPMND never executes them; a test
  enters ZPMND only rewritten by ZPMND's own process.
- Text is visible-only (no zero-width, bidi or control characters) and quotes are at most 300 characters.
- Raw files stay in the local corpus (`work/raw/`, not in git) unless `redistribution: allowed`.
- RESEARCH GROUP learns ZPMND's verdict only through a new request. There is no channel back that carries authority.

Passing our validator makes a packet **well-formed**, never true. The airlock validates again with the same schemas
and asks its own questions (authority of the source, currency, relation to canon, owner object, need for code/test).

## 4. What the schemas make impossible

- A packet with any status other than `CANDIDATE`, or any field not in the schema, at any depth.
- A finding without a hashed source, or citing a source that is not in the packet.
- A request that is private, or issued by RESEARCH GROUP.
- A knowledge demand marked as verified.
- A raw file stored in the repo without redistribution rights.

## 5. Order of work (handoff section 41)

1. Security baseline (this repository's first PR): runtime isolation, pinned substrate, schemas, tests.
2. Knowledge Demand Map (`knowledge-demand/`), seeded from requests; RG proposals marked as such.
3. Understand OpenClaw hooks and plugins, then a minimal Research Goodware hook: inject this contract, record
   provenance, emit packets. The hook is not a security boundary (docs/OPENCLAW_EVALUATION.md).
4. One small experiment: 1–3 agents, one question, limited sources. Measure source quality, coverage, provenance,
   duplicates, invented sources, constraint violations, usefulness, cost, latency, cleanup.
5. Decide whether OpenClaw is worth scaling. Success is a bounded request turning into a packet ZPMND can evaluate
   without rereading the raw corpus, not "OpenClaw installed".

## 6. Anti-drift

Research infrastructure is not product architecture. No CompanyTwin, Agent Factory, Digital Physics or other ZPMND
system is rebuilt here; RESEARCH GROUP has only the governance it needs to research safely.
