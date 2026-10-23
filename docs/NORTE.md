# RESEARCH GROUP: norte (Universal Knowledge & Capability Acquisition Fabric)

Documento de Braulio, pegado en el chat el 2026-10-23. Aquí van sus 80 secciones completas, en el mismo orden y con
sus diagramas; las listas se pusieron en línea y las secciones que venían en inglés se tradujeron al español. No es
copia literal: el original es el texto del chat. Al final, cómo está RG frente a cada parte (PROPUESTA de trabajo, no
canon).

---

RESEARCH GROUP
Universal Knowledge & Capability Acquisition Fabric

## 0. NORTE

RESEARCH GROUP no decide por ZPMND. No gobierna empresas. No ejecuta acciones productivas. No determina la verdad
canónica final. No necesita conocer CompanyTwin completo.

Su misión es otra: encontrar, adquirir, preservar, actualizar, relacionar, contrastar y empaquetar todo el conocimiento
y las capacidades externas que potencialmente puedan hacer a ZPMND más competente.

```
WORLD
↓
RESEARCH GROUP
↓
EVIDENCE + KNOWLEDGE CANDIDATES + CAPABILITY CANDIDATES
↓
ZPMND KNOWLEDGE AIRLOCK
↓
INTERPRETATION / CRITERION / DECISION / ACTION
```

## 1. Lo que ya tenemos no se tira

Preservar y desarrollar: ResearchRequest, ResearchPacket, SourceArtifact, provenance, sha256, publisher, version,
published_at, license, redistribution, candidate_claims, candidate_methods, candidate_controls, candidate_tests,
limitations, hypotheses, researcher_agents. También preservar `RG output = CANDIDATE`. Nunca `RG output = canonical
truth`.

## 2. El cambio de escala

Hoy RG está orientado principalmente a leyes, NOM y regulación mexicana. Eso debe convertirse progresivamente en THE
WORLD'S USEFUL KNOWLEDGE: no literalmente todo Internet, sino todo lo que razonablemente pueda convertirse en better
criterion, better calculation, better decisions, better capabilities, better execution, better understanding.

## 3. Grandes familias de conocimiento

- A. Derecho y regulación: constituciones, leyes, reglamentos, NOM, regulación sectorial, normatividad estatal y
  municipal, criterios, jurisprudencia cuando aplique, circulares, resoluciones, guidance oficial.
- B. Estándares técnicos: ISO, IEC, IEEE, ASTM, NFPA, ASME, API, DIN, EN, BS, ANSI, SAE, UL, etc. No asumir acceso
  gratuito. Los derechos/licencias forman parte del objeto.
- C. Ingeniería: mechanical, structural, electrical, civil, chemical, industrial, environmental, manufacturing,
  acoustics, materials, controls, software engineering. Incluye methods, equations, material properties, design
  criteria, failure modes, test methods.
- D. Finanzas: corporate finance, valuation, NPV, IRR, TCO, capital structure, risk, portfolio methods, credit analysis,
  project finance, working capital.
- E. Banca: financial products, credit structures, rates, fees, contracts, payment rails, risk, underwriting concepts,
  banking regulation.
- F. Economía: microeconomics, macroeconomics, industrial economics, econometrics, public economics, behavioral
  economics, trade, regional economics.
- G. Contabilidad / fiscal: accounting standards, tax rules, financial reporting, cost accounting, management
  accounting, audit methods.
- H. Management / organización: operations, process design, procurement, supply chain, HR, quality, project
  management, strategy, governance, sales, marketing, pricing, service.
- I. Ciencia / academia: papers, meta-analyses, systematic reviews, books, datasets, academic methods, experimental
  results.
- J. Software: official documentation, APIs, SDKs, repositories, protocols, databases, frameworks, architecture
  patterns, benchmarks, security advisories.
- K. AI ecosystem: models, agents, MCPs, skills, frameworks, evals, inference systems, orchestration, tools, datasets,
  training methods, context methods. Este dominio cambia especialmente rápido.
- L. App / SaaS ecosystem: ERP, CRM, accounting, email, calendar, project management, CAD, BI, inventory, HR, banking,
  automation, communication. RG puede ayudar a descubrir qué capacidades existen.
- M. Mercados / industrias: companies, products, prices, competitors, suppliers, capacity, trade, technology, market
  structure.
- N. Datos públicos: INEGI, World Bank, OECD, IMF, UN, government datasets, open data, geographic data, weather/climate,
  trade, population, economic indicators.
- O. Manuales / fabricantes: datasheets, installation manuals, technical bulletins, maintenance manuals, compatibility
  tables, product specifications.
- P. Conocimiento práctico: tutorials, professional demonstrations, conference talks, videos, field practice, expert
  explanations, forums, communities. Empiezan con menor autoridad, pero pueden contener enorme conocimiento tácito.

## 4. No todo es texto

RG debe llegar a ingerir HTML, PDF, DOC/DOCX, XLS/XLSX, CSV, JSON, XML, API, database export, Git repositories, images,
technical diagrams, audio, video, presentations, datasets. Preservando siempre el original.

## 5. Multimodal knowledge

Un video técnico puede contener spoken explanation, screen demonstration, diagram, code, physical procedure,
measurements, before/after. Transcripción sola pierde conocimiento. Eventualmente: video → timeline → speech + frames +
screen events + objects + procedural steps. Todo candidato hasta ser verificado.

## 6. Raw first

Regla fundamental: nunca sustituir la fuente por el resumen. Conservar el RAW ARTIFACT inmutable. Derivados (text
extraction, translation, segmentation, summary, claims, methods) siempre apuntan al raw original.

## 7. SourceArtifact debe madurar

Además de lo que ya existe: publisher, author, institution, source type, jurisdiction, domain, language, publication
date, effective date, revision, version, identifier, license, redistribution, retrieval timestamp, content hash,
canonical URL, archive reference. No necesariamente todo obligatorio.

## 8. Identificadores nativos

Preservar cuando existan: DOI, ISBN, ISSN, ISO number, NOM identifier, law/article, RFC, CVE, Git commit, package
version, patent number, dataset ID, product/model number. Esto permite reconciliar fuentes.

## 9. Source registry

RG necesita conocer las fuentes, no sólo sus documentos (DOF, ISO, INEGI, GitHub, World Bank, manufacturer X, journal
Y), y mantener: what it publishes, how often, access method, authority scope, format, change mechanism, cost, license,
reliability.

## 10. No existe un "trust score" universal

Una fuente puede ser autoridad para una cosa y no para otra (ISO para un estándar técnico, no para Mexican tax law).
Se necesita source × domain × claim type → authority relevance.

## 11. Primary source first

Cuando exista official law, official standard, official documentation, original paper, original dataset o
manufacturer manual, preferirlo a un blog que lo resume. Los secundarios ayudan a discover, interpret, challenge; no
deben desplazar automáticamente al primario.

## 12. Source lineage

20 websites pueden estar copiando 1 wrong original claim. No contar eso como 20 fuentes independientes. RG debe
intentar construir claim → source lineage → original origin.

## 13. Deduplicación

Varias capas: exact hash duplicate, near duplicate, same edition, same underlying source, same claim copied,
translated copy, mirror. El volumen bruto no es conocimiento.

## 14. Contradiction hunting

RG no debe buscar solamente confirmación: support, contradiction, exception, limitation, alternative method,
retraction, superseding source. ResearchPacket debe poder decir "encontré evidencia incompatible". Eso es una buena
salida.

## 15. Negative search

"I did not find X" no significa "X does not exist". Registrar queries attempted, sources searched, jurisdictions,
dates, coverage, limitations.

## 16. Reproducibility

Una investigación debe poder reconstruirse: ResearchRequest, query plan, queries, sources visited, retrieved
artifacts, timestamps, tools/versions, transformations, ResearchPacket.

## 17. Research modes

1 corpus build; 2 targeted request; 3 watch; 4 landscape; 5 prior art; 6 capability scout; 7 adversarial research;
8 change impact input; 9 benchmark research.

## 18. Corpus build no debe ser aleatorio

Necesita coverage maps (ej.: Mexico / labor / laws 98%, NOM 90%, regulations 72%, state 25%, municipal 5%). Los números
deben tener denominador verificable. No inventar "90%" sin saber qué significa el universo.

## 19. Knowledge coverage graph

RG debería poder responder: what domains do we cover? which jurisdictions? which source classes? which periods? what is
missing? what is stale?

## 20. Freshness classes

STATIC-ish, PERIODIC, HIGH-CHANGE, REAL-TIME (old scientific theorem; tax rules; API docs; financial market price).
La estrategia de vigilancia difiere.

## 21. Change watchers

No solamente DOF: regulators, standards bodies, software docs, GitHub releases, security advisories, API changelogs,
government datasets, model providers, pricing pages.

## 22. Change ≠ hash change

Un sitio puede cambiar footer, advertising o format sin cambio semántico. Progresivamente: raw diff, structural diff,
semantic diff.

## 23. Supersession graph

Source A AMENDS Source B; Standard v2 SUPERSEDES v1; API v3 DEPRECATES endpoint X. Invaluable downstream.

## 24. Relaciones entre fuentes

law → regulation; standard → referenced standard; paper → cited paper; software → dependency; API → SDK; method →
validation study. Esto crea un candidate evidence/source graph.

## 25. La extracción produce candidatos tipados

No solo summary: CandidateClaim, CandidateDefinition, CandidateRule, CandidateObligation, CandidateThreshold,
CandidateStandardRequirement, CandidateMethod, CandidateFormula, CandidateModel, CandidateProcedure,
CandidateBenchmark, CandidateDataset, CandidateFailureMode, CandidateControl, CandidateTest, CandidateCapability,
CandidateAppCapability, CandidateTool. Todos siguen siendo candidatos.

## 26. Formulas

RG encuentra formula, variables, units, assumptions, validity, source. ZPMND decide aplicabilidad operativa y hace el
cálculo gobernado.

## 27. Methods

(NPV, Monte Carlo, FMEA, root-cause analysis, finite-element method, A/B testing.) RG da what method is, source,
conditions described, inputs, limitations, evidence. ZPMND lo convierte en MethodSpec/TaskStandardSpec operativo.

## 28. Standards

Necesitan standard ID, issuer, edition, revision, scope, referenced standards, status, effective date if applicable,
supersession, license/access.

## 29. Copyright / licensing

Que un estándar sea útil no significa que RG pueda redistribuir su texto completo. Distinguir public-domain/open,
licensed, company-owned licensed copy, metadata only, paywalled, restricted redistribution. Nunca resolver la cobertura
de estándares descargando copias ilegalmente.

## 30. Source procurement

A veces el resultado correcto es "necesitamos comprar/licenciar el estándar X". RG lo identifica; la persona o la
empresa toma la decisión comercial/legal.

## 31. Datasets

Son activos de conocimiento: schema, units, geography, time coverage, methodology, revision, missingness, license,
provenance.

## 32. Data quality

Que un dataset exista no lo hace confiable: freshness, coverage, missing data, revisions, methodology, known breaks.

## 33. Code as knowledge

Repositorios con algorithms, implementation patterns, protocols, benchmarks, tools. RG puede analizar repo identity,
license, maintenance, release history, dependencies, tests, security.

## 34. Capability scout

Descubrir continuamente new AI models, agents, MCP servers, APIs, open-source tools, libraries, datasets, frameworks,
SaaS, algorithms. Alimenta el Capability Resolver de ZPMND.

## 35. Capability candidate

what it does, provider, interface, deployment, license, cost, free tier, self-hosted?, data exposure, permissions,
dependencies, maturity, maintenance, benchmarks, known failures, alternatives. Candidato.

## 36. Tool landscape research

Para una CapabilityDemand (ej. web extraction) RG devuelve candidatos A, B, C con evidencia; ZPMND decide cuál encaja.

## 37. Prior art engine

Antes de que ZPMND construya un subsistema: ¿ya está resuelto? ¿por quién? ¿con qué arquitectura? ¿open source? ¿paper?
¿producto comercial? ¿por qué no resuelve del todo nuestra necesidad?

## 38. Prior art con lecciones negativas

failures, abandoned frameworks, security incidents, scaling failures, design criticisms.

## 39. AI practice watch

context engineering, agent orchestration, memory, tool use, coding agents, research agents, evals, multimodal,
inference optimization, new open models. Para que Braulio no tenga que descubrir personalmente cada Firecrawl.

## 40. World learning agenda

Impulsada por ResearchRequests, known gaps, staleness, failures, capability demand, new technologies, important world
changes.

## 41. Bounded serendipity

Escaneo de horizonte limitado ("¿qué apareció esta semana que pueda ampliar capacidades de forma material?"), sin
raspar todo Internet a ciegas.

## 42. Research economics

compute, API, storage, bandwidth, commercial databases, human time. Adquisición consciente del costo.

## 43. Cache aggressively

No volver a download, extract, embed, analyze artefactos sin cambio. Hash/version/freshness lo evitan.

## 44. Storage tiers

RAW / COLD, PARSED / WARM, ACTIVE CANDIDATES / HOT. El corpus crudo masivo, barato.

## 45. Search no solo embeddings

lexical search, semantic search, metadata filtering, identifiers, source relationships, structural references,
temporal filters. Solo vectores nos va a dañar.

## 46. Entity resolution

same company, same standard, same law, same product, same author, same API, same software project, aunque cambie el
nombre.

## 47. Cross-language

Preservar el idioma original; las traducciones son derivados. Nunca borrar el original.

## 48. Translation provenance

translator/model, version, date, source span, translation. La interpretación legal/técnica puede requerir el original.

## 49. Contradiction packets

Si las fuentes no coinciden y RG no tiene autoridad, devolver un ConflictSet: claims, sources, source authority
contexts, dates, possible reasons, unresolved question.

## 50. Source independence

Diez notas que citan un comunicado de gobierno no son diez testigos independientes. Rastrear linaje.

## 51. Dimensiones de calidad de la evidencia

primary vs secondary, authority in relevant domain, currency, methodological strength, independence, directness,
reproducibility. No necesariamente un solo puntaje.

## 52. Sin precisión falsa

Mejor "high authority primary source" que "trust score = 87.43", salvo justificación empírica.

## 53. Los agentes son detalle de implementación

RG puede usar 100 investigadores o crawlers, parsers, LLMs, APIs, buscadores. No hacer de "un agente persona por
dominio" la arquitectura.

## 54. Roles funcionales

planner, source discovery, primary-source hunter, downloader, parser, extractor, lineage resolver, contradiction
hunter, method extractor, change watcher, prior-art mapper, capability scout, quality checker. Software o agentes.

## 55. Maker / checker

Quien encuentra un claim no siempre es su único verificador. En paquetes con consecuencia: researcher → independent
challenger/checker.

## 56. Adversarial search

Para una hipótesis importante, buscar explícitamente por qué está mal, contraejemplos, fallas, críticas, retracciones,
explicaciones alternativas.

## 57. Security

El contenido de investigación es entrada hostil (prompt injection, malware, poisoned repository, malicious PDF,
tracking, script injection). Todo entra como dato, nunca como autoridad de instrucción.

## 58. Sandbox de artefactos no confiables

Código, archivos comprimidos, ejecutables, documentos con scripts/macros: no se ejecutan solo porque la investigación
los encontró.

## 59. Frontera privado / público

RG trata sobre todo conocimiento global. Un artefacto privado de una empresa requiere scope de tenant explícito. Nunca
volver global una fuente privada en silencio.

> **Nota RG (2026-10-23):** hoy el contrato no permite esto. RG no guarda datos privados de organizaciones ni de
> clientes (`RESEARCH_CONTRACT.md`, `SECURITY.md`): lo privado queda en ZPMND. Admitir artefactos privados con scope de
> tenant es una PROPUESTA incompatible con el contrato actual, y no se implementa sin reconciliarlo antes (como §61).

## 60. Privacidad de los pedidos

ZPMND puede necesitar conocimiento por una situación privada. Debe poder preguntar algo saneado ("normas vigentes de
aire comprimido industrial en México") sin mandar "la empresa X tiene el compresor Y fallando en la planta Z", salvo que
sea necesario y esté autorizado.

> **Nota RG (2026-10-23):** hoy un pedido solo puede ser `PUBLIC` o `ABSTRACTED` (`schemas/research_request.schema.json`):
> se manda la versión saneada. Mandar detalles privados "cuando sea necesario y esté autorizado" es una PROPUESTA
> incompatible con el contrato actual, y no se implementa sin reconciliarlo antes (como §61).

## 61. El puente manual actual es seguro, pero a futuro es deuda de autonomía

Hoy ZPMND → Braulio → ResearchRequest → RG es aceptable como arranque. A largo plazo, una frontera tipada y angosta:
ResearchDemand → sanitizer → signed request queue → RG. RG sigue sin leer CompanyTwin. No implementarlo hasta
reconciliarlo con el contrato actual.

## 62. Dos planos de investigación

WORLD KNOWLEDGE RESEARCH (laws, science, standards, methods, data) y CAPABILITY ECOSYSTEM RESEARCH (software, models,
agents, tools, APIs, MCPs, datasets). Mismo RG, salidas distintas.

## 63. Tercer plano: prior art

Investigación sobre cómo construir ZPMND mismo: distributed systems, object-capability security, workflow engines,
autonomic computing, knowledge graphs, AI governance, multi-agent coordination, memory, formal methods.

## 64. La salida es evidencia, no ensayo

source artifacts, typed findings, claims, contradictions, methods, formulas, capability candidates, datasets,
limitations, unknowns.

## 65. Research receipt

what was asked, what was searched, what was found, what was not found, what artifacts were acquired, what
transformations occurred, what remains uncertain, cost/time.

## 66. RG también aprende

No verdad, sino operación de investigación (ej.: la fuente A bloquea descargas automáticas; la B es espejo secundario;
el método C encuentra reformas de forma confiable).

## 67. Source performance

availability, latency, failure rate, freshness, coverage, cost.

## 68. Crawler performance

Qué crawler, parser, browser o API funciona mejor por tipo de fuente.

## 69. Agnóstico de modelo

GPT/Claude/etc. pueden ayudar, pero corpus, procedencia y artefactos sobreviven al cambio de modelo. Ninguna evidencia
importante atrapada en la memoria de un modelo.

## 70. Arquitectura final

```
                    WORLD
                      │
       ┌──────────────┼──────────────┐
       │              │              │
   WEB/SOURCES      DATASETS      SOFTWARE
       │              │              │
       └──────────────┼──────────────┘
                      ▼
                SOURCE DISCOVERY
                      ▼
               SOURCE REGISTRY
                      ▼
              ACQUISITION ENGINE
                      ▼
              RAW ARTIFACT STORE
                      ▼
                 NORMALIZATION
                      ▼
             STRUCTURE / SEGMENTS
                      ▼
              SOURCE RELATIONSHIPS
                      ▼
           EVIDENCE / LINEAGE GRAPH
                      ▼
              CANDIDATE EXTRACTION
                      ▼
           CONTRADICTION / CHALLENGE
                      ▼
                RESEARCH PACKET
                      ▼
                 KNOWLEDGE AIRLOCK
                      ▼
                    ZPMND
```

## 71. Lo que RG nunca debe volverse

Un LLM que busca en Google; una base vectorial gigante; un descargador de PDF; un scraper legal; un oráculo autónomo
de verdad.

## 72. Lo que RG debe volverse

Una infraestructura de investigación en expansión continua, anclada en fuentes, consciente del cambio y reproducible,
capaz de adquirir casi cualquier conocimiento o descripción de capacidad disponible externamente y entregarlo a ZPMND
como evidencia candidata estructurada que preserva la procedencia.

## 73. La relación que se compone

Si RG mejora, más del mundo queda disponible; si ZPMND mejora, más de lo recolectado se vuelve usable. Capacidad de
adquisición de RG × capacidad de digestión de ZPMND = conocimiento efectivo del sistema.

## 74. Lo más importante que construir después en RG

No otro scraper de dominio al azar. Priorizar el sustrato general de adquisición: Source Registry, robustez de
SourceArtifact, adquisición universal, watchers de versión/cambio, linaje/deduplicación, normalización multiformato,
coverage map, extracción de candidatos tipados, capability scouting, research receipts. Una vez que esas primitivas
funcionan, ley, estándar, paper, documentación de API, método financiero y manual de ingeniería se vuelven familias de
fuentes distintas sobre la misma infraestructura.

## 75. Primera prueba de estrés

No probar solo leyes. Darle a RG: 1 ley mexicana, 1 fuente de metadatos de ISO/estándar técnico, 1 paper científico,
1 dataset económico oficial, 1 documentación de API de software, 1 herramienta open source en GitHub, 1 manual técnico
de fabricante, 1 video/tutorial experto. ¿Puede el mismo RG preservar procedencia, estructura, versión, relaciones y
candidatos útiles sin codificar ocho sistemas separados? Si sí, la arquitectura se está volviendo general.

## 76. Segunda prueba: cambio

Revisión de una ley, de una API de software, de un dataset, un release de GitHub: ¿detecta qué cambió, qué no y qué
artefacto reemplazó a cuál?

## 77. Tercera prueba: contradicción

Fuente primaria, resumen secundario equivocado, artículos copiados equivocados, corrección posterior: ¿preserva el
conflicto y el linaje?

## 78. Cuarta prueba: descubrimiento de capacidades

Una necesidad semántica sin nombre de proveedor ("structured web extraction"): ¿devuelve un panorama útil (open source,
free tier, comercial, self-hosted) con evidencia? Es la prueba Firecrawl.

## 79. Quinta prueba: tipo de fuente desconocido

Si cada formato desconocido exige rediseño de arquitectura, RG todavía no es general.

## 80. Norte final

Poder responder: qué sabe hoy la humanidad, qué fuentes lo sostienen, dónde no coinciden, qué cambió, qué herramientas
y capacidades existen para actuar sobre ello, y qué evidencia puedo entregar a ZPMND sin pretender autoridad para
decidir qué es verdad o qué debe hacer la organización.

---

## Estado de RG frente a este norte (2026-10-23, PROPUESTA)

| Pieza del norte | Qué ya existe en RG | Qué falta |
|---|---|---|
| §1 contrato (Request, Packet, SourceArtifact, CANDIDATE) | `schemas/`, `RESEARCH_CONTRACT.md`; `tests/test_schemas.py` (un paquete nunca reclama verdad ni autoridad) | Campos de §7-8 (autor, idioma, vigencia, identificadores nativos) |
| §6 raw first | `RawStore` direccionado por sha256, release `raw-mx`, manifiesto por corrida | Formatos de §4 más allá de HTML, PDF, DOCX y JSON |
| §9 source registry | `sources/mx.json`: host permitido, robots, licencia, redistribución, `max_requests`, estado (active/trial/planned con su bloqueo) | Autoridad por dominio (§10), frecuencia y mecanismo de cambio (§20-21), desempeño (§67) |
| §18-19 coverage map con denominador | Cuadre por fuente contra el listado oficial (exit 3 si no cuadra); `index.json` por fuente y estado del crudo | Un mapa por dominio × jurisdicción × periodo que lo resuma |
| §21-23 cambios y reemplazos | Relectura de días del DOF, versiones por registro, linajes NOM (cancela/menciona), tratados | Watchers fuera del DOF; diff estructural y semántico |
| §25 candidatos tipados | `candidate_*` en ResearchPacket; obligaciones con cita literal verificada (`rg.quotes`, `rg.text.quote`) | Tipos de §25 como esquema; extracción |
| §34-36 capability scout | Evaluaciones a mano (OpenClaw, Hugging Face, OmniRoute en `requests/`) | Modo capability scout como flujo |
| §57-58 seguridad | Fetcher con lista de hosts, robots y tokens atados al host; aislamiento del extractor (proceso, tiempo, tamaño, memoria); auditor doble | Sandbox para repositorios y código encontrado |
| §65 research receipt | Manifiesto por corrida (peticiones, errores, cuadre); `gw observe` | Recibo por paquete (consultas hechas, no encontrado, costo) |

**Siguiente paso propuesto (§74-75):** correr la primera prueba de estrés con un artefacto de cada uno de los ocho
tipos, sobre el mismo `RawStore`, `SourceArtifact` y `ResearchPacket`. Así se ve qué está codificado a la medida de
México y qué ya es general. México sigue catalogándose en segundo plano mientras tanto.
