# Reglas de trabajo de RESEARCH GROUP

Cada regla nace de un error real (casi todos del 2026-10-19). Cada una dice qué la hace cumplir. Una regla que solo
depende de que el modelo "se acuerde" no cuenta: necesita una prueba, un cuadre o una guarda.

| # | Regla | Origen | Qué la hace cumplir |
|---|---|---|---|
| 1 | Nada se da por bueno sin verificación mecánica: prueba, cuadre o recibo. "Terminado" sin recibo no existe | Cuatro defectos del parser que la revisión no vio y el cuadre sí | `run.py` (salida 3/4), suite de pruebas, delivery-check de Goodware |
| 2 | Toda fuente activa tiene un **conteo independiente** en la misma página oficial. Sin conteo independiente, la fuente no se activa | Día del DOF con 0 de 107 notas extraídas; leyes y reglamentos omitidos | `_cover()` en cada adaptador; `tests/test_catalog.py` |
| 3 | La categoría se **copia** de la estructura oficial o sale de una **tabla fija**. Sin coincidencia es `OTRO`; un nivel ausente es "sin dato en la fuente". Nunca se infiere | Diseño; 3,702 OTRO resueltos por la sección oficial, no por adivinanza | `categorize.py`, `recategorize()`, `build_tree()` |
| 4 | Las categorías derivadas se recalculan cada corrida desde los campos verbatim, para que una mejora a la tabla se aplique hacia atrás | Convocatorias clasificadas como OTRO | `recategorize()` |
| 5 | Una falla de red nunca tumba una corrida, y pase lo que pase se escribe lo reunido | Un `IncompleteRead` perdió 1.5 h de trabajo | reintentos en `fetch.py`; `try` en `main`; prueba de red |
| 6 | Paralelo solo **por servidor**; un sitio nunca recibe dos hilos. Lecturas concurrentes solo sobre copias con candado | Leyes y reglamentos comparten servidor; "dictionary changed size during iteration" | `host_groups()`, `Catalog.snapshot()`, pruebas de concurrencia |
| 7 | Decodificar según el estándar WHATWG (ISO-8859-1 = windows-1252). Los caracteres invisibles se quitan y se cuentan | Comillas 0x93/0x94 del OJN; U+FEFF en un título de la CDMX | `decode_html()`, `normalize_strings()`, esquema |
| 8 | robots.txt, términos, retos anti-bots y tokens **no se rodean**. Se registra la causa y se pide al operador o a Braulio | SRE (Radware), datos.gob.mx (`/api/`), SCJN y CONAMER (403) | `fetch.py`; `sources/mx.json` (`blocked_by`); `docs/SOLICITUDES.md` |
| 9 | Hasta la **exploración** pasa por robots.txt: nada de `curl` directo a rutas que no se han revisado | Una petición a `/api/` de datos.gob.mx durante la exploración (error propio) | explorar con `rg.collect` o el `Fetcher`, que revisan robots |
| 10 | Toda cita de un paquete existe **literal** en el crudo hasheado de la fuente que cita | Prevención de citas inventadas | `rg.quotes` (6/6 en el primer paquete), `rg.packets`; en `packet-gate`, el crudo que el paquete no guarda se baja de nuevo y se compara su sha256 sin publicarlo (`rg.recrudo`, T29) |
| 11 | Toda app, cuenta, token o conector se **solicita** a Braulio; RG nunca los crea | Instrucción de Braulio, 2026-10-19 | `docs/SOLICITUDES.md` |
| 12 | Entradas de usuario en CI van como variables de entorno validadas, nunca interpoladas en el script | Riesgo de inyección en `catalog-mx.yml` | revisión del flujo; `grep '${{' dentro de run:` vacío |
| 13 | Una prueba nunca corre sin límite (bucles, datos crecientes) | Prueba de concurrencia que tardaba más de 2 minutos | límites explícitos en las pruebas |
| 14 | Mientras un PR está en auditoría, su rama no se mueve; lo nuevo espera o va en otro PR contra `main` (regla 14b) | No mover lo que Braulio está revisando | el head auditado es el que se cita en el veredicto |
| 14b | **No apilar PR**: todo PR va contra `main`. Si algo depende de un PR abierto, se espera o se incluye, porque borrar la rama base **cierra** el PR dependiente | 2026-10-20: al fusionar #1 y borrar su rama, GitHub cerró #3 sin fusionar; #4 terminó en `catalog-mx` y no en `main` | base `main` en cada `gh pr create` |
| 15 | Cifras no medidas (precios, tiempos, tamaños) se etiquetan como HIPÓTESIS hasta medirlas | Costos de GPU sin verificar | redacción de paquetes y documentos |
| 16 | Los textos con derechos de autor (ISO, NMX de venta) y los datos personales (edictos) quedan **solo como metadatos** | Avisos judiciales del DOF | `metadata_only_branches`; `redistribution` en el esquema |
| 16b | Una prueba de mutación vale solo si la **línea base pasa** en la misma copia; la copia no tiene remoto | 2026-10-20: copia sin `.git`; una prueba usa `git ls-files`, la línea base fallaba y toda mutación contó como muerta | `scripts/mutar.py` verifica la línea base antes de mutar; corre en CI (job `mutation`) en cada PR |
| 17 | Con Braulio: en su idioma; leer la intención y pesarla contra la evidencia, sin tomar sus palabras como verdad literal; no preguntar lo que el contrato resuelve | Sus mensajes del 2026-10-19 | `CLAUDE.md` |
| 18 | robots.txt se lee como dice el RFC 9309, no como lo lee la biblioteca: hasta 5 redirecciones dentro de la lista de hosts, y los grupos del mismo agente se combinan | 2026-10-21: el robots.txt de Banxico redirige (302) y repite `User-agent: *`; la biblioteca de Python tomaba la redirección como bloqueo y se quedaba con el primer grupo (dejaba pasar `/ALEPH` y `/V`) | `_robots_for` y `_Robots` en `fetch.py`; `tests/test_catalog.py` FetchGuards con el robots.txt real |
| 19 | Un token va solo a su host y nunca se escribe: ni en la URL registrada (`<token>`), ni en el manifiesto, ni en un crudo | INEGI pone el token en la ruta de la URL (2026-10-21) | `secrets` del `Fetcher`, `redact_secrets` en `run.py`, paso de búsqueda en `indicadores-mx.yml`, `tests/test_indicadores.py` |
| 20 | **PR chico o no hay PR.** Tope de 400 líneas de diff de código (datos, fixtures y paquetes aparte). Excepción solo con etiqueta `renombre` o `fixtures`, puesta por el dueño | Un humano revisa lo que cabe en una pantalla; lo demás lo aprueba | **Pendiente** (entra con su PR): `tests/test_reglas.py` mide el diff contra el merge-base y falla arriba del tope |
| 21 | **Toda fuente nueva nombra consumidor antes de `active`.** Una fuente pasa a `active` o `trial` solo con `consumer` (un `request_id` existente en `requests/` o una unidad `zpmnd:<nombre>`) y un bloque `adquisicion` válido. Las fuentes `legacy: true` de `sources/mx.json` conservan su excepción y no se reescriben. RG no se congela: adquiere para quien lo pide | 143 fuentes de 16 familias registradas (#84) para un airlock que consume una; decisión del dueño 2026-11-02: ordenar, no detener | `rg/alcance.py` y `tests/test_registro.py`: `active`/`trial` sin `consumer` o con `request_id` inexistente falla; frontera `legacy` fijada a mano en la prueba |
| 22 | **RG conoce su precisión.** `VerdictEvent` (esquema nuevo, `verdicts/`): packet_id, verdict de lista fija, reason_code de lista fija, finding_ids, issued_by = ZPMND. Sin texto libre, sin campo que cargue autoridad. `rg/precision.py` publica `docs/PRECISION.md` por fuente, modo y corrida | RG aprende de operación (§66) pero no de resultado: diseñado ciego | `schemas/verdict_event.schema.json` y `tests/test_schemas.py` VerdictEvents (un veredicto nunca instruye ni autoriza: nada fuera del esquema, verdict y reason_code de lista fija, constancia obligatoria con el bundle Sigstore y la identidad del workflow de ZPMND). `issued_by` vale solo con la constancia verificada. Pendientes, cada uno en su PR: esa verificación en CI, `rg/precision.py` y la falla de CI por un paquete con más de 30 días sin veredicto ni etiqueta `sin-consumidor`. Hasta ese PR el contrato no cambia: RG conoce el veredicto solo por un pedido nuevo (`RESEARCH_CONTRACT.md` §3); el PR que verifica la constancia es el que abre ese canal en el contrato |
| 23 | **Fuente sin consumidor nombrado no se activa.** `consumer` es obligatorio en toda fuente que corre y debe existir en `requests/` o nombrar una unidad de ZPPMND | Catálogo de 16 familias para un consumidor | Misma guarda que la 21 (`rg/alcance.py`); la 23 es su enunciado desde el lado del registro. Una `adquisicion` que corre (cualquier vía salvo `manual`) también exige `consumer`, sea cual sea el `status` |
| 24 | **Un ancla, no una cadena.** `docs/ESTADO.md` es la única entrada; se actualiza en cada entrega; nada se marca superseded, se borra | `ESTADO.md` del 10-19 con 88 PR después | **Pendiente** (entra con su PR): CI falla si `ESTADO.md` es anterior al último merge en `main` por más de 7 días, o si algún `.md` contiene la palabra en inglés para "reemplazado" en mayúsculas (salvo la propia regla) |
| 25 | **El dueño revisa salidas, no narración.** Todo PR adjunta su artefacto (manifiesto, recibo, reporte) como archivo del CI; el cuerpo del PR no excede 15 líneas; de cada 3 PR fusionados el dueño abre 1 al azar y verifica una afirmación contra el código, con registro en `ESTADO.md` | Seis PR al día fusionados por un solo humano | **Pendiente** (entra con su PR): plantilla de PR y prueba de longitud del cuerpo en `auditor.yml` |
| 26 | **Revisión de muerte semanal.** Lo fusionado que ningún pedido abierto necesitaba se revierte; entrada semanal en `ESTADO.md` aunque sea vacía | Nunca se quitó nada | **Pendiente** (entra con su PR): CI falla si pasan 8 días sin entrada |
| 27 | **Auditoría medida, no acumulada.** Cada auditor lleva en `docs/PRECISION.md` su tasa de hallazgos únicos (defectos reales que los otros no vieron) sobre los últimos 30 PR. Por debajo del 10% se vuelve opcional. El tercero (NVIDIA, #91) corre solo en discrepancia y solo mide hasta tener esa cifra | Regla 15 aplicada a los propios auditores | **Pendiente** (entra con su PR): `scripts/auditor_stats.py` sobre `AUDIT VERDICT`, `GPT REVIEW`, `LOCAL REVIEW` y las correcciones que siguieron |
| 28 | **Un hueco entra al NORTE solo con forma de cierre (A código, B frontera, C diferimiento), prueba mecánica y consumidor.** La lista activa no excede cinco; lo demás va a `BACKLOG.md` con condición de reapertura | Ocho huecos abiertos desde 2026-10-31 sin definición de terminado (`docs/CIERRE-HUECOS.md`) | **Pendiente** (entra con su PR): `tests/test_norte.py` lee "Pendiente de diseño" de `docs/NORTE.md`: falla con más de cinco entradas o con una sin prueba y consumidor |
| 29 | **Casos por fuente, no por PR.** Toda fuente o adaptador nuevo trae en `tests/aceptacion/<fuente>/`: fixture real (bytes de una corrida, nunca construidos), cuadre esperado y sha256 del crudo. Mínimo tres casos: cuadra, descuadra (salida 3), cuarentena (salida 4). Un refactor corre todos y no agrega ninguno. Las `legacy` registran su déficit y no se reescriben | Acuerdo del 2026-11-02: N simulaciones por función; en RG la función es la fuente | **Pendiente** (entra con su PR): `tests/test_registro.py` falla con una fuente `active` no `legacy` sin carpeta de aceptación con los tres casos; `ESTADO.md` lleva el conteo |
| 30 | **Caja de tiempo: dos REVISE por el mismo motivo cambian el diseño.** Un mecanismo que recibe dos REVISE del mismo auditor por el mismo motivo se simplifica o se sustituye por arte previo; no hay tercera iteración del mismo diseño | Cada ronda repetida cuesta horas de auditoría y de espera y no converge: 49 REVISE en los 30 últimos PR, 8 de ellos con dos o más (lead time en `docs/ESTADO.md`) | **Vigente** desde #109 (orden 4 del dueño, `auditor.yml`): tras dos REVISE del mismo auditor desde su último PASS el PR espera la decisión del dueño (su comentario "otra ronda"); una REVISE que un PASS posterior del mismo auditor ya respondió no cuenta (dueño, 2026-11-09). Prueba: `tests/test_workflows.py`. La revisión semanal (regla 26) lista los PR que lo activaron |

## Segundo auditor (GPT): una segunda opinión independiente

`auditor.yml` corre dos auditores sobre el mismo head, en paralelo y con la misma compuerta (`gate`):

- **Claude** (`audit` → `post`): comentario `AUDIT VERDICT: PASS|REVISE <sha>` y estado `auditor`. Sin cambios.
- **GPT** (`audit-gpt` → `post-gpt`): comentario `GPT REVIEW: PASS|REVISE <sha>` y estado `auditor-gpt`. Otro
  proveedor y otro modelo, que no ve la respuesta de Claude: es una segunda opinión, no un reemplazo.

Qué lo hace seguro y barato por construcción (`scripts/auditor_gpt.py`; pruebas en `tests/test_auditor_gpt.py` y
`tests/test_workflows.py`; mutantes en `scripts/mutar.py`):

- El job saca `main`, nunca el head del PR. El head llega solo como objetos de git para calcular el mismo diff que el
  job `audit`; el código del PR nunca corre donde está la llave. `OPENAI_API_KEY` existe solo en el paso que llama a la
  API. El modelo no tiene herramientas: recibe texto (criterios de `main`, diff, commits y la evidencia, marcada como no
  confiable).
- Las mismas pruebas que el auditor de Claude: esquema estricto, el head correcto, `criteria_quote` igual a la primera
  línea del README de `main` y el filtro de credenciales sobre el cuerpo. Si algo falla, se publica REVISE.
- Costo acotado: una llamada por head auditado; topes fijos de caracteres por archivo (diff + evidencia: 160,000); si
  algo se trunca o falta, no puede salir PASS ("no pude leer todo"); tope de 12,000 tokens de salida. El uso de tokens
  que reporta la API queda en el resumen del job.
- Los crudos de un paquete (`research-packets/<RP>/raw/`) se comprueban por máquina, no leyéndolos. El job
  `packet-gate`, sin secretos, saca `main` y corre su `rg.packets` sobre las carpetas de paquete que cambia el head,
  escritas desde los objetos de git byte por byte (`scripts/packet_gate.py`: `ls-tree` y `cat-file`, nunca `archive`,
  que aplica los atributos de exportación del head; ningún código del PR corre; el token solo en el paso del fetch). Si una carpeta pasa (sin problemas ni
  avisos), cada crudo suyo llega a GPT como una línea con su sha256 y no cuenta como contenido sin leer; el resultado
  llega como sección confiable `packets.json`. Si no pasa, o el resultado es de otro head, el crudo va entero.
- El modelo sale de la variable del repo `OPENAI_AUDIT_MODEL`; el código no trae ninguno. Sin ella no se llama a nada y
  el estado `auditor-gpt` queda `pending` con "skipped: OPENAI_AUDIT_MODEL not set".
- Distinguibles por construcción: un comentario de GPT nunca contiene "AUDIT VERDICT" (su línea dice `GPT REVIEW` y el
  cuerpo reescribe cualquier mención; `post-gpt` se niega a publicar si aparece). Ninguna búsqueda del veredicto de
  Claude, con o sin ancla, puede tomar una opinión de GPT por un veredicto.

**PROPUESTA de política de merge (la decide Braulio):** el merge sigue requiriendo `AUDIT VERDICT: PASS` de Claude
sobre el head exacto. Un `GPT REVIEW: REVISE` se lee, y antes del merge se responde en el PR o se corrige. GPT no
bloquea mientras Braulio no decida volverlo obligatorio (por ejemplo, exigiendo el estado `auditor-gpt` en `main`).

**Merge automático de datos (Braulio, 2026-10-27: "sí, fusión automática para PRs de datos"):** un PR que solo agrega
o modifica paquetes (`research-packets/<RP>/`) o planes de fuentes (`requests/plans/<RR>.json`), o, desde la orden 5 del
dueño (2026-11-03) y solo mientras él tenga puesta la variable del repo `RG_AUTOMERGE_DOCS=si`, documentos `docs/<nombre>.md` que no sean sus reglas, decisiones ni contratos (`REGLAS.md`, `NORTE.md`,
`CIERRE-HUECOS.md`, `OUTBOX.md`, `SOLICITUDES.md`); los casos de aceptación no, porque definen qué es correcto, desde una rama de este
repo, se fusiona solo cuando los dos auditores dieron PASS sobre su commit exacto y todo CI está verde
(`scripts/automerge.py`, flujo `automerge.yml`, SECURITY.md T15). Para datos, GPT sí bloquea: hace falta su PASS. La
aprobación se lee de las corridas de `auditor.yml` (su trabajo `pass-both`) y de `ci.yml` sobre ese commit, nunca de un
estado o un comentario, que cualquier flujo de una rama podría imitar (REVISE de GPT en #48). Todo
lo demás (código, flujos, documentos, pruebas, mutantes, o un PR que borra o renombra) sigue esperando el merge de
Braulio.

## Qué cambia en mi forma de trabajar

- **Antes de activar una fuente:** robots.txt revisado; formato leído en páginas reales guardadas como fixtures; conteo independiente definido; prueba de regresión sobre la página real.
- **Antes de afirmar algo:** recibo (`gw observe`, manifiesto o prueba) o la etiqueta HIPÓTESIS.
- **Al encontrar un error propio:** causa raíz, prueba que falla sin el arreglo, una fila en esta tabla.
