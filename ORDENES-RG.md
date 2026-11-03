# ÓRDENES · RESEARCH GROUP · semana del 2026-11-02

Emitido por OWNER. Una sesión nueva lee esto, `docs/REGLAS.md` y `ESTADO.md`, y opera sin preguntar. Lo que no está
aquí no se hace esta semana. Repo: `romerobarcenabraulio-hash/ZPMND-RESEARCH-GROUP`. Repo del consumidor:
`romerobarcenabraulio-hash/ZPPMND` (es el que nombra `verdict_event.schema.json`).

Decisiones cerradas (no reabrir): RG no se congela. Los 7 adaptadores de México son `legacy` y no se reescriben.
`VerdictEvent` entra en #95. #89 queda draft; el primer uso del motor `api` es INEGI BIE. Auditor NVIDIA solo en
discrepancia y solo mide (#91). OCR primero mide (#93). GOODWARE no es repo: es `canon/` dentro de ZPPMND.

**Estado de este documento.** Es el plan del dueño para la semana, no una regla en vigor. Gobiernan el código, las
pruebas, `docs/REGLAS.md` y `RESEARCH_CONTRACT.md`; cada regla de la sección 3 entra a `REGLAS.md` solo con su prueba.
El canal `VerdictEvent` (§1 #95, §2 días 8 y 10, §3 regla 22) es una propuesta pendiente de reconciliar con
`RESEARCH_CONTRACT.md` §3: hasta el PR que verifica la constancia y cambia ese contrato con su prueba, RG conoce un
veredicto solo por un pedido nuevo y ningún código lee `verdicts/`. El orden de trabajo vigente está en `COLA.md` e
`ITINERARIO-2026-Q4.md` (el dueño aprobó el 2026-11-02 ir primero por la cadena crudo → texto → compuerta → paquete).

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

El estado vigente vive solo en `docs/ESTADO.md` (regla 24). La plantilla que el dueño escribió aquí se aplicó allí
contrastada con el repo el 2026-11-02: INEGI BIE ya es `active` con bytes reales (corrida 39877667471), `text-mx`
aún no existe y `CIERRE-HUECOS-NORTE.md` no existe (su calendario es la sección 2).

## 5. CapabilityDemand autorizados y su arte previo

Solo estos tres entran esta semana. Cada uno: demanda → `ResearchRequest` de arte previo → paquete → decisión del
dueño. Ninguno se instala antes del paquete. Licencia leída, no asumida. Costos: HIPÓTESIS hasta medir.

| Demanda | Consumidor | Qué debe traer el paquete | Lo que NO es |
|---|---|---|---|
| OCR y layout para OJN (`.doc`, PDF escaneado) | gold ZPPMND G06, G07, G09; reglamento municipal | Comparación medida (ya en #93: Tesseract, nemotron-parse, LibreOffice): precisión por página sobre 20 crudos reales del OJN, costo por página, licencia, versión fijable, salida con confianza por página | Un servicio de resumen; nada con LLM en el paso de OCR |
| Modelo abierto para auditor 3 | regla 27 | Candidatos de familia distinta a Claude/GPT (Nemotron, Qwen, DeepSeek, Llama, Mistral): licencia, tamaño que cabe en el servidor rentado, servidor compatible con protocolo OpenAI (vLLM/NIM/Ollama), costo por auditoría | Un auditor que bloquee; un cuarto auditor |
| Embeddings para índice del catálogo | hueco 7 (búsqueda del catálogo), NORTE §45 | bge-m3 y alternativas abiertas: licencia, dimensión, costo de indexar ~300 mil registros, tokens ahorrados medidos (ya pedido en ESTADO del 10-19 punto 3) | Una base vectorial como única búsqueda (§45, §71) |

Los tres pedidos de arte previo son archivos, sin copia aquí:
[`RR-2026-11-02-arte-previo-ocr-ojn`](requests/RR-2026-11-02-arte-previo-ocr-ojn.json),
[`RR-2026-11-02-arte-previo-auditor-abierto`](requests/RR-2026-11-02-arte-previo-auditor-abierto.json),
[`RR-2026-11-02-arte-previo-embeddings-catalogo`](requests/RR-2026-11-02-arte-previo-embeddings-catalogo.json).

## 6. Pedido P0 de autoauditoría NOM-035

[`requests/RR-2026-11-02-nom035-autoauditoria.json`](requests/RR-2026-11-02-nom035-autoauditoria.json): el consumidor del
primer `VerdictEvent`.

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
