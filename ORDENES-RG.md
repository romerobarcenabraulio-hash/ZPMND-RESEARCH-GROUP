# ÓRDENES · RESEARCH GROUP · semana del 2026-11-02

Emitido por OWNER. Una sesión nueva lee esto, `docs/REGLAS.md` y `ESTADO.md`, y opera sin preguntar. Lo que no está
aquí no se hace esta semana. Repo: `romerobarcenabraulio-hash/ZPMND-RESEARCH-GROUP`. Repo del consumidor:
`romerobarcenabraulio-hash/ZPPMND` (es el que nombra `verdict_event.schema.json`).

Decisiones cerradas (no reabrir): RG no se congela. Los 7 adaptadores de México son `legacy` y no se reescriben.
`VerdictEvent` entra en #95. #89 queda draft; el primer uso del motor `api` es INEGI BIE. Auditor NVIDIA solo en
discrepancia y solo mide (#91). OCR primero mide (#93). GOODWARE no es repo: es `canon/` dentro de ZPPMND.

## 1. Orden de merge de los 12 PR abiertos

| Orden | PR | Acción | Regla | Qué comprobar antes del merge |
|---|---|---|---|---|
| 1 | #95 alcance / VerdictEvent | **Editar y fusionar** (diff abajo) | 21→23, 22 | `tests/test_registro.py` y `tests/test_schemas.py` verdes; mutantes nuevos muertos |
| 2 | #94 salida de GPT como artefacto | Fusionar | 1 | Un REVISE de prueba llega al PR |
| 3 | #96 una sola forma de llamar API con llave (T27) | Fusionar | 19 | `grep` de llamadas con llave fuera de la función única = 0 |
| 4 | #98 tope de criterios 45,000 | Fusionar | 15 | `tests/test_auditor_gpt.py` verde; anotar en revisión semanal que `SECURITY.md` crece |
| 5 | #75 runner de un solo uso en el servidor | Fusionar tras auditoría doble | 20 | Diff de código ≤400 líneas o etiqueta justificada; ningún secreto en disco tras el job |
| 6 | #93 ocr-medir (Tesseract vs nemotron-parse, .doc con LibreOffice) | Fusionar | 15 | Solo mide: ningún resultado entra a `mx/texto/`; versiones fijadas |
| 7 | #91 tercera opinión NVIDIA en discrepancia | Fusionar | 27 | Corre solo si `AUDIT VERDICT` ≠ `GPT REVIEW` sobre el mismo head; no bloquea |
| 8 | #80 paquete prueba de estrés | Fusionar (datos; exige dos PASS) | 29 | Recibo adjunto; es la evidencia de huecos 3 y 4 |
| 9 | #97 vigía de producción en rojo | Fusionar | 24 | Una issue abierta por estado, no una por corrida |
| 10 | #73 Postgres (Supabase) | Fusionar tras #75 | — | Estado operativo únicamente; el corpus sigue en `catalog` y releases |
| 11 | #77 despachador nocturno | Fusionar después de 1–10 | 25 | Tope de PR por noche ≤ lo que el dueño revisa (3) |
| — | #89 motor `api` + OpenAlex | **Draft.** Reabrir solo con primer uso = `mx.inegi-bie` (consumidor: indicadores) | 23 | — |

### Edición exacta de #95 (en palabras; el código lo hace la sesión)

| Archivo | Quitar | Poner |
|---|---|---|
| `docs/REGLAS.md` fila 21 | "Alcance congelado hasta el primer veredicto. Ninguna fuente nueva entra..." | Texto de la regla 21 de la sección 3 de este documento |
| `rg/alcance.py` | Chequeos "new source" contra `congelado.json` y "a registry source does not run" | Chequeo único: toda fuente con `status` en `active`/`trial` que no sea `legacy: true` debe traer `consumer` (un `request_id` existente en `requests/` o una unidad `zpmnd:<nombre>`) **y** un bloque `adquisicion` válido. Legacy conserva su excepción. Un `adquisicion` que corre sin `consumer` sigue siendo error |
| `sources/congelado.json` | El archivo | Borrar. La frontera `legacy` ya vive a mano en `tests/test_registro.py` (`LEGADO`) |
| `tests/test_registro.py` | Casos `new registry source`, `new mx source, even planned`, `test_the_repo_keeps_the_scope_frozen` | Casos: `active sin consumer` → error; `trial sin consumer` → error; `consumer con request_id inexistente` → error; `active con consumer y adquisicion` → sin error; `planned sin consumer` → sin error. Prueba del repo real: cero errores en `main` |
| `SECURITY.md` T28 | "A false verdict unfreezes RG (rule 21)" | "A false verdict carries authority into RG (rule 22) or activates a source without a consumer (rule 23)". El resto de T28 queda igual: la constancia sigue siendo obligatoria y su verificación en CI sigue pendiente |
| `scripts/mutar.py` | Mutantes de `congelado.json` y de `alcance.py` que ya no aplican | Mutantes: quitar el `if` de `consumer`; aceptar `consumer` vacío; aceptar `request_id` inexistente |
| `RESEARCH_CONTRACT.md` | Nada | Nada (el cambio de #95 ahí es correcto) |

Resultado: RG sigue catalogando, el sondeo sigue midiendo, #89 puede salir de draft cuando INEGI sea su primer uso, y
ninguna de las 143 fuentes del registro pasa a `active` sin decir para quién.

## 2. Calendario de cierre de huecos, reconciliado con los PR abiertos

| Día | Hueco (NORTE) | Forma | Cubierto por | Falta abrir |
|---|---|---|---|---|
| 1 | 1 · frontera `legacy`; 22 · `VerdictEvent` | B + A | **#95** (editado) | — |
| 1 | Infra de auditoría y seguridad | — | #94, #96, #98, #75 | — |
| 2 | 3 · compuerta sin republicar el crudo (0/42 → 42/42) | A | — | **PR nuevo**: la compuerta re-descarga por el `Fetcher`, comprueba sha256 contra `SourceArtifact`, lee la cita en `work/`; repetir #80 como prueba |
| 3 | 4 · presupuesto de lectura por fuente | A | — | **PR nuevo**: tope de caracteres por fuente dentro de cada parte; exceso a `limitations` con conteo |
| 3 | OCR (destapa estatal/municipal) | medir | #93 | Decisión tras la medición: PR de OCR determinista con versión fijada y confianza por página |
| 4 | 2 · licencia leída de la fuente | A | — | **PR nuevo**: tabla fija por host en `sources/`; `license_read_at` + cita; `NO VERIFICADA` solo fuera de la tabla |
| 4 | Auditoría medida | — | #91 | `scripts/auditor_stats.py` (regla 27) en PR propio |
| 5 | 7 · mapa de cobertura con denominador | A | — | **PR nuevo**: `rg/cobertura.py` → `mx/cobertura.json`; celda sin denominador = `sin_denominador`; borrar tablero externo de `ESTADO.md` |
| 6 | 6 · identificadores canónicos (mínimo) | A + C | — | **PR nuevo**: `entity_id` por ley, artículo, linaje NOM, municipio (clave INEGI), fuente |
| 7 | 5 · cambios como eventos (acotado) | A + C | — | **PR nuevo**: un vigía produce `ChangeEvent` por nota nueva en linaje NOM y por ETag cambiado en leyes/reglamentos |
| 8 | 8 · frescura + búsqueda negativa | A + C | — | **Dos PR chicos**: `freshness` de lista fija en el registro; `no_encontrado` en `receipt.json` |
| 8 | 22 · precisión | A | — | **PR nuevo**: `rg/precision.py` → `docs/PRECISION.md`; CI falla por paquete >30 días sin veredicto ni etiqueta `sin-consumidor` |
| 9 | Operación | — | #80, #97, #73 | — |
| 9–10 | 1 · motor por vía (A) | A | #89 (reabierto con INEGI) | Motor `api` con `mx.inegi-bie`; `volcado` en PR siguiente con una fuente con consumidor |
| 10 | 22 · constancia verificada en CI | A | — | **PR nuevo**: verificación Sigstore del `VerdictEvent` contra el workflow de ZPPMND |
| 11 | Ancla | — | — | `ESTADO.md` reescrito (sección 4); `BACKLOG.md` con los 6 diferidos; `tests/test_norte.py` (regla 28); #77 al final |

Diferidos a `BACKLOG.md` con condición (forma C): motores `sitemap` y `rastreo`; diff semántico del DOF y watchers
externos; resolución de entidades entre fuentes y near-duplicate; caza de contradicciones; explorador de capacidades
como flujo; artefactos privados con scope de tenant (§59–61).

## 3. Reglas 20–29 para `docs/REGLAS.md`

| # | Regla | Origen | Qué la hace cumplir |
|---|---|---|---|
| 20 | **PR chico o no hay PR.** Tope de 400 líneas de diff de código (datos, fixtures y paquetes aparte). Excepción solo con etiqueta `renombre` o `fixtures`, puesta por el dueño | Un humano revisa lo que cabe en una pantalla; lo demás lo aprueba | `tests/test_reglas.py` mide el diff contra el merge-base y falla arriba del tope |
| 21 | **Toda fuente nueva nombra consumidor antes de `active`.** Una fuente pasa a `active` o `trial` solo con `consumer` (un `request_id` existente en `requests/` o una unidad `zpmnd:<nombre>`) y un bloque `adquisicion` válido. Las fuentes `legacy: true` de `sources/mx.json` conservan su excepción y no se reescriben. RG no se congela: adquiere para quien lo pide | 143 fuentes de 16 familias registradas (#84) para un airlock que consume una; decisión del dueño 2026-11-02: ordenar, no detener | `rg/alcance.py` y `tests/test_registro.py`: `active`/`trial` sin `consumer` o con `request_id` inexistente falla; frontera `legacy` fijada a mano en la prueba |
| 22 | **RG conoce su precisión.** `VerdictEvent` (`verdicts/`, `schemas/verdict_event.schema.json`): `packet_id`, `verdict` y `reason_code` de lista fija, `finding_ids`, `issued_by = ZPMND`, constancia Sigstore obligatoria. Sin texto libre, sin campo que cargue autoridad. `rg/precision.py` publica `docs/PRECISION.md` por fuente, modo y corrida | RG aprende de operación (§66) pero no de resultado | `tests/test_schemas.py` VerdictEvents (#95). Pendientes, cada uno en su PR: verificación de la constancia en CI, `rg/precision.py`, CI falla por paquete >30 días sin veredicto ni etiqueta `sin-consumidor` |
| 23 | **Fuente sin consumidor nombrado no se activa.** `consumer` es obligatorio en toda fuente que corre y debe existir en `requests/` o nombrar una unidad de ZPPMND | Catálogo de 16 familias para un consumidor | Misma guarda que la 21 (`rg/alcance.py`); la 23 es su enunciado desde el lado del registro |
| 24 | **Un ancla, no una cadena.** `docs/ESTADO.md` es la única entrada; se actualiza en cada entrega; nada se marca superseded, se borra | `ESTADO.md` del 10-19 con 88 PR después | CI falla si `ESTADO.md` es anterior al último merge en `main` por más de 7 días, o si algún `.md` contiene "SUPERSEDED" |
| 25 | **El dueño revisa salidas, no narración.** Todo PR adjunta su artefacto (manifiesto, recibo, reporte) como archivo del CI; el cuerpo del PR no excede 15 líneas; de cada 3 PR fusionados el dueño abre 1 al azar y verifica una afirmación contra el código, con registro en `ESTADO.md` | Seis PR al día fusionados por un solo humano | Plantilla de PR; prueba de longitud del cuerpo en `auditor.yml` |
| 26 | **Revisión de muerte semanal.** Lo fusionado que ningún pedido abierto necesitaba se revierte; entrada semanal en `ESTADO.md` aunque sea vacía | Nunca se quitó nada | CI falla si pasan 8 días sin entrada |
| 27 | **Auditoría medida, no acumulada.** Cada auditor lleva en `docs/PRECISION.md` su tasa de hallazgos únicos (defectos reales que los otros no vieron) sobre los últimos 30 PR. Por debajo del 10% se vuelve opcional. El tercero (NVIDIA, #91) corre solo en discrepancia y solo mide hasta tener esa cifra | Regla 15 aplicada a los propios auditores | `scripts/auditor_stats.py` sobre `AUDIT VERDICT`, `GPT REVIEW`, `LOCAL REVIEW` y las correcciones que siguieron |
| 28 | **Un hueco entra al NORTE solo con forma de cierre (A código, B frontera, C diferimiento), prueba mecánica y consumidor.** La lista activa no excede cinco; lo demás va a `BACKLOG.md` con condición de reapertura | Ocho huecos abiertos desde 2026-10-31 sin definición de terminado | `tests/test_norte.py` lee "Pendiente de diseño" de `docs/NORTE.md`: falla con más de cinco entradas o con una sin prueba y consumidor |
| 29 | **Casos por fuente, no por PR.** Toda fuente o adaptador nuevo trae en `tests/aceptacion/<fuente>/`: fixture real (bytes de una corrida, nunca construidos), cuadre esperado y sha256 del crudo. Mínimo tres casos: cuadra, descuadra (salida 3), cuarentena (salida 4). Un refactor corre todos y no agrega ninguno. Las `legacy` registran su déficit y no se reescriben | Acuerdo del 2026-11-02: N simulaciones por función; en RG la función es la fuente | `tests/test_registro.py`: fuente `active` no `legacy` sin carpeta de aceptación con los tres casos falla; `ESTADO.md` lleva el conteo |

## 4. `docs/ESTADO.md` (reemplaza al del 2026-10-19)

```markdown
# Estado de RESEARCH GROUP · 2026-11-02

Única entrada del repo (regla 24). Se actualiza en cada entrega; lo superseded se borra.

## Dónde está cada cosa

| Qué | Dónde |
|---|---|
| Código, contrato, seguridad | `main` |
| Reglas | `docs/REGLAS.md` (1–29) |
| Órdenes de la semana | `ORDENES-RG.md` |
| Catálogo de México | rama `catalog`, `mx/`; crudos en release `raw-mx`; texto en `text-mx` |
| Registro de fuentes | `sources/mx.json` (8 fuentes `legacy`, 7 adaptadores) + `sources/registro/` (143 fuentes candidatas, 16 familias) |
| Pedidos abiertos | `requests/` (11 + RR-2026-11-02-nom035-autoauditoria P0 + 3 de arte previo) |
| Paquetes | `research-packets/`, con constancia Sigstore |
| Veredictos de ZPPMND | `verdicts/` (esquema en #95; verificación en CI pendiente) |
| Huecos del NORTE | `docs/NORTE.md` → `CIERRE-HUECOS-NORTE.md` (11 PR) |
| Diferidos | `BACKLOG.md` (6, con condición de reapertura) |

## Alcance (reglas 21 y 23)

Ordenado por consumidor. Toda fuente nueva nombra `consumer` antes de `active`. Legacy: 8 fuentes, no se tocan.

## Casos de aceptación por fuente (regla 29)

| Fuente | Estado | Consumidor | Fixture real | Cuadra / Descuadra / Cuarentena |
|---|---|---|---|---|
| mx.dof | active · legacy | catálogo MX; RR nom035 | sí | 1 / 0 / 0 |
| mx.leyes-federales | active · legacy | RR nom035 (LFT); gold ZPPMND | sí | 1 / 0 / 0 |
| mx.reglamentos-federales | active · legacy | gold ZPPMND | sí | 1 / 0 / 0 |
| mx.ojn-estatal | active · legacy | gold ZPPMND G06–G09 (sin texto: OCR) | sí | 1 / 0 / 0 |
| mx.ojn-municipal | active · legacy | gold ZPPMND G09 | sí | 1 / 0 / 0 |
| mx.hf-tesis-scjn | active · legacy · secundaria | — (sin consumidor: candidato a revisión semanal) | sí | 1 / 0 / 1 |
| mx.banxico-sie | active · legacy | indicadores (RR unidades-de-referencia) | sí (39709378896) | 1 / 1 / 0 |
| mx.inegi-bie | trial · legacy | indicadores | no (401/400) | 0 / 0 / 0 |
| 143 del registro | candidate | ninguno | — | — |

Déficit: ninguna `legacy` tiene los tres casos. Se registra; aplica completo a toda fuente nueva.

## Pendiente, en orden

Ver `ORDENES-RG.md` §1 (merge de 12 PR) y §2 (11 días). Después del día 11: sellado del gold de ZPPMND contra
crudos; INEGI BIE a `active` cuando el dueño reponga `INEGI_TOKEN` y corra `indicadores-mx` con `-f sources=mx.inegi-bie`.

## Bloqueado (no se rodea)

SCJN (403), SRE (reto anti-bots), datos.gob.mx (`/api/` prohibido), CONAMER (403), SINEC (no resuelve). INEGI BIE:
pendiente del dueño.

## Revisión de muerte semanal (regla 26)

| Semana | Revertido | Nota |
|---|---|---|
| 2026-11-02 | — | Primera entrada. Candidatos próxima semana: `mx.hf-tesis-scjn` (sin consumidor), 143 fuentes del registro (regla 23: siguen `candidate`, no se activan) |

## Muestreo del dueño (regla 25)

| PR | Afirmación verificada | Resultado |
|---|---|---|
| — | — | — |

## Último merge en `main`

`(actualizar en cada entrega: número de PR, SHA, fecha)`
```

## 5. CapabilityDemand autorizados y su arte previo

Solo estos tres entran esta semana. Cada uno: demanda → `ResearchRequest` de arte previo → paquete → decisión del
dueño. Ninguno se instala antes del paquete. Licencia leída, no asumida. Costos: HIPÓTESIS hasta medir.

| Demanda | Consumidor | Qué debe traer el paquete | Lo que NO es |
|---|---|---|---|
| OCR y layout para OJN (`.doc`, PDF escaneado) | gold ZPPMND G06, G07, G09; reglamento municipal | Comparación medida (ya en #93: Tesseract, nemotron-parse, LibreOffice): precisión por página sobre 20 crudos reales del OJN, costo por página, licencia, versión fijable, salida con confianza por página | Un servicio de resumen; nada con LLM en el paso de OCR |
| Modelo abierto para auditor 3 | regla 27 | Candidatos de familia distinta a Claude/GPT (Nemotron, Qwen, DeepSeek, Llama, Mistral): licencia, tamaño que cabe en el servidor rentado, servidor compatible con protocolo OpenAI (vLLM/NIM/Ollama), costo por auditoría | Un auditor que bloquee; un cuarto auditor |
| Embeddings para índice del catálogo | hueco 7 (búsqueda del catálogo), NORTE §45 | bge-m3 y alternativas abiertas: licencia, dimensión, costo de indexar ~300 mil registros, tokens ahorrados medidos (ya pedido en ESTADO del 10-19 punto 3) | Una base vectorial como única búsqueda (§45, §71) |

### `requests/RR-2026-11-02-arte-previo-ocr-ojn.json`

```json
{
  "request_id": "RR-2026-11-02-arte-previo-ocr-ojn",
  "issued_by": "OWNER",
  "issued_at": "2026-11-02T20:00:00Z",
  "question": "Para extraer texto con posición de página de los documentos del Orden Jurídico Nacional que no tienen capa de texto (archivos .doc antiguos y PDF escaneados de legislación estatal y municipal), ¿qué extractores y modelos de OCR y layout existen con licencia que permita uso en producción, versión fijable, salida con confianza por página y ejecución local en un servidor sin GPU dedicada o con una GPU de consumo, y cuál es su precisión y costo por página medidos sobre documentos reales de esa fuente?",
  "why_needed": "La compuerta de RG exige cita literal en el texto del crudo; sin texto, ninguna obligación estatal o municipal puede llegar confirmada (ZPPMND G06, G07, G09). La medición de #93 compara Tesseract, nemotron-parse y LibreOffice; falta el panorama completo con licencias y arte previo antes de fijar uno.",
  "affected_component": "rg/text (extractores fijados) y mx/texto",
  "desired_evidence": [
    "por candidato: nombre, versión, licencia leída literalmente de su repositorio o documentación oficial con cita y sha256 del documento de licencia",
    "requisitos de hardware y forma de ejecución local documentados por el proveedor",
    "si publica confianza por página o por bloque, y en qué formato",
    "resultados publicados sobre documentos legales en español o en escaneos de calidad similar, con su fuente; lo no publicado marcado como desconocido",
    "costo por página: solo si el proveedor lo publica; lo demás como HIPÓTESIS",
    "lo que no se encontró: consultas hechas sin resultado"
  ],
  "priority": "P0",
  "risk_if_wrong": "Elegir un extractor que no se pueda fijar por versión o cuya licencia no permita el uso, y tener que rehacer mx/texto; o atribuir a una página una confianza que el extractor no produce.",
  "privacy_class": "PUBLIC"
}
```

### `requests/RR-2026-11-02-arte-previo-auditor-abierto.json`

```json
{
  "request_id": "RR-2026-11-02-arte-previo-auditor-abierto",
  "issued_by": "OWNER",
  "issued_at": "2026-11-02T20:05:00Z",
  "question": "¿Qué modelos de lenguaje de pesos abiertos, de una familia distinta a los de Anthropic y OpenAI, pueden servirse localmente detrás de un servidor compatible con el protocolo de chat de OpenAI, con licencia que permita uso comercial interno, y qué tamaño, memoria requerida, contexto máximo y desempeño publicado en revisión de código tienen, para usarse como tercera opinión de auditoría solo cuando dos auditores discrepan?",
  "why_needed": "Regla 27 y #91: una tercera opinión descorrelacionada de Claude y GPT, que mide y no decide, y que se mantiene solo si en 30 PR encuentra defectos reales que los otros dos no vieron.",
  "affected_component": "auditor.yml (tercer auditor) y scripts/auditor_gpt.py (base_url configurable)",
  "desired_evidence": [
    "por candidato: nombre, versión, licencia leída literalmente con cita y sha256; cláusulas de uso comercial o restricciones",
    "tamaños disponibles y memoria requerida documentados por el proveedor; contexto máximo",
    "servidores que lo sirven con protocolo compatible con OpenAI, según su documentación oficial",
    "resultados publicados en evaluaciones de revisión de código o detección de defectos, con fuente; lo no publicado marcado como desconocido",
    "qué requiere del servidor rentado: HIPÓTESIS hasta medir en #75",
    "lo que no se encontró"
  ],
  "priority": "P1",
  "risk_if_wrong": "Instalar un modelo cuya licencia no permite el uso, o uno correlacionado con los otros dos que no aporta hallazgos únicos y solo añade tiempo de CI.",
  "privacy_class": "PUBLIC"
}
```

### `requests/RR-2026-11-02-arte-previo-embeddings-catalogo.json`

```json
{
  "request_id": "RR-2026-11-02-arte-previo-embeddings-catalogo",
  "issued_by": "OWNER",
  "issued_at": "2026-11-02T20:10:00Z",
  "question": "Para indexar semánticamente un catálogo de alrededor de trescientos mil registros de legislación, normas y notas oficiales en español, ¿qué modelos de embeddings de pesos abiertos y multilingües existen con licencia de uso comercial, qué dimensión y longitud de entrada tienen, cómo se desempeñan en evaluaciones publicadas de recuperación en español y jurídico, y qué costo de cómputo documentan para indexar y consultar localmente, de modo que la búsqueda semántica complemente, no sustituya, la búsqueda léxica y por identificadores?",
  "why_needed": "ESTADO del 2026-10-19 punto 3 (índice semántico con medición de tokens ahorrados) y NORTE §45 (búsqueda no solo por vectores). Antes de elegir bge-m3 por costumbre hace falta el panorama con licencias.",
  "affected_component": "índice del catálogo (rama catalog) y búsqueda de la compuerta",
  "desired_evidence": [
    "por candidato: nombre, versión, licencia leída literalmente con cita y sha256",
    "dimensión, longitud máxima de entrada, idiomas declarados por el proveedor",
    "resultados en evaluaciones públicas de recuperación multilingüe o en español, con fuente y fecha; lo no publicado marcado como desconocido",
    "costo de indexación y consulta: solo cifras publicadas por el proveedor; el resto HIPÓTESIS",
    "alternativas léxicas o híbridas documentadas con las que se compara",
    "lo que no se encontró"
  ],
  "priority": "P2",
  "risk_if_wrong": "Indexar trescientos mil registros con un modelo que luego no se puede usar o que no mejora la recuperación frente a la búsqueda léxica, y pagar la indexación dos veces.",
  "privacy_class": "PUBLIC"
}
```

## 6. `requests/RR-2026-11-02-nom035-autoauditoria.json`

```json
{
  "request_id": "RR-2026-11-02-nom035-autoauditoria",
  "issued_by": "OWNER",
  "issued_at": "2026-11-02T20:15:00Z",
  "question": "Para un centro de trabajo en México, ¿cuál es el conjunto completo de obligaciones del patrón bajo la NOM-035-STPS-2018 (numerales 5 a 10 y guías de referencia), a qué tramo de trabajadores aplica cada una, qué documento o registro demuestra su cumplimiento según el propio texto, y qué dicen literalmente los transitorios sobre su entrada en vigor por fases? Cada obligación con su cita literal en tramos de 300 caracteres o menos.",
  "why_needed": "Primera unidad de autoauditoría de ZPPMND: una lista de obligaciones tipadas, con evidencia exigible y vigencia, que una empresa pueda contestar sola. Hoy solo están curados el numeral 2 y parte de 5 a 8 (RR-2026-10-21-nom035-obligaciones). Es el consumidor del primer VerdictEvent.",
  "affected_component": "autoauditoría tipada de ZPPMND, plano de conocimiento",
  "desired_evidence": [
    "texto del DOF del 23 de octubre de 2018 con sha256 y fecha, y cualquier aclaración o modificación posterior publicada en el DOF, con su linaje NOM-035-STPS",
    "por cada obligación: numeral, condición de aplicación (tramo de trabajadores u otra), evidencia documental que el texto exige, cita literal",
    "transitorios: fechas de entrada en vigor por fase, con cita literal",
    "lo que el texto no decide, marcado como desconocido; lo que solo diga una fuente secundaria, como candidate_claim",
    "lo que no se encontró: consultas hechas sin resultado"
  ],
  "priority": "P0",
  "risk_if_wrong": "Una empresa se declara en cumplimiento por una obligación que no le aplica, o se le exige evidencia que la norma no pide.",
  "privacy_class": "PUBLIC"
}
```

## 7. Lo que NO se toca esta semana

| Qué | Por qué |
|---|---|
| Los 7 adaptadores `legacy` de México | Forma B: funcionan con cuadre; reescribirlos es una obra, no un cierre |
| Fuentes nuevas en el registro | Regla 23: ninguna tiene consumidor; las 143 siguen `candidate` |
| OpenAlex como primer uso del motor `api` | Sin consumidor; INEGI BIE sí lo tiene |
| Instalar nemotron-parse, Nemotron, bge-m3 o cualquier modelo | Primero el paquete de arte previo (regla 16 de ZPPMND, §5 aquí) |
| Motores `volcado`, `sitemap`, `rastreo` | `api` con INEGI primero (#89); los demás con una fuente que los pida |
| Despachador nocturno (#77) antes de los 10 merges | Sin alcance ordenado produce más de lo que el dueño revisa |
| Lectura de `verdicts/` por cualquier código | La verificación de la constancia en CI es el PR del día 10; hasta entonces un archivo ahí no prueba nada |
| `SECURITY.md` como lugar de reglas nuevas | Ya pasó dos veces el tope de criterios (#72, #98); las reglas van a `REGLAS.md` |
| Diff semántico del DOF, watchers externos, entidades entre fuentes, contradicciones, capacidades como flujo, tenancy privado | Forma C: en `BACKLOG.md` con condición; sin pedido que los necesite |
| Cualquier cosa de Alquimia | Fuera del alcance de RG esta semana por decisión del dueño |
