# Estado de RESEARCH GROUP · 2026-11-02

Única entrada del repo (regla 24). Se actualiza en cada entrega; lo superseded se borra.

## Dónde está cada cosa

| Qué | Dónde |
|---|---|
| Código, contrato, seguridad | `main` |
| Reglas | `docs/REGLAS.md` (1–29; 20 y 24–29 dicen "Pendiente" hasta el PR que trae su prueba) |
| Órdenes de la semana | `ORDENES-RG.md` (plan del dueño) |
| Entregable activo y los tres siguientes (WIP = 1) | `COLA.md` |
| Plan día por día hasta el 2026-12-31 | `ITINERARIO-2026-Q4.md` |
| Catálogo de México | rama `catalog`, `mx/`; crudos en release `raw-mx`; texto en `text-mx` (aún no existe: primera corrida de `texto-mx` en curso) |
| Registro de fuentes | `sources/mx.json` (15 fuentes: 8 activas con 7 adaptadores, marca `legacy` en #95; 7 `planned`) + `sources/registro/` (143 fuentes candidatas, 16 familias) |
| Pedidos abiertos | `requests/` (11 + RR-2026-11-02-nom035-autoauditoria P0 + 3 de arte previo + el explorador semanal, que se renueva cada lunes desde el 09-nov) |
| Paquetes | `research-packets/`, con constancia Sigstore |
| Veredictos de ZPPMND | `verdicts/` (esquema en #95; verificación en CI pendiente) |
| Huecos del NORTE | `docs/NORTE.md` → `docs/CIERRE-HUECOS.md` (decisión por hueco) |
| Seguridad pendiente para el especialista | `SECURITY.md`, sección Pending (P1–P6) |
| Diferidos | `BACKLOG.md` (cada uno con su condición de reapertura) |

## Entregable activo

E0 (cerrar el día 1 de las órdenes): #95, #96 y #100 en `main`; CI de `main` en verde en `dfa9f4b` con `tests.test_registro`,
`tests.test_llamada` y `tests.test_schemas`; #103 (documento único) en `414766a`. Este archivo con esos SHA lo cierra.
Siguiente: E1 (`COLA.md`).

## Horas del dueño (norte compartido, meta ≤ 10 por semana)

Sin medir en horas (HIPÓTESIS). Lo que RG sí ve: PR fusionados por el dueño desde el 2026-10-27: 43 (uno más lo fusionó
`automerge`). Desde el 2026-11-02, con WIP = 1: 8 (#86, #92, #94, #95, #96, #97, #98, #100).

## Norte compartido del 2026-11-03: refutación, delta y pedidos

Lectura del documento `ZPMND_Norte_Compartido_Completo_2026-11-03.pdf` (sha256
`e09f60f89769819dce4136052d7d4df7b77843b9870464db573fbf78a51b7a28`), Parte I §4.1 y Partes VII–VIII, contra `main`.

**Refutación** (lo que el norte dice y el repo contradice):
- §4.1 "#95: editar antes de fusionar": ya entró editado (`rg/alcance.py`, `dfa9f4b`). `RESEARCH_CONTRACT.md` §3 no cambió:
  GPT lo rechazó en #95 (REVISE f1ed480) porque declaraba un canal que ningún código lee; cambia con el PR que verifica
  la constancia.
- §4.1 "reemplazar el ESTADO del 10-19 por el del 11-02": hecho en #100 (`637b3aa`); la plantilla del 11-02 traía tres
  datos falsos (INEGI BIE ya era `active` con la corrida 39877667471; `text-mx` no existe; `CIERRE-HUECOS-NORTE.md` no
  existía) que se corrigieron contra el repo.
- §2 "el plan de 11 días es exactamente lo que la híbrida exige de obtener": el primer eslabón está roto: la corrida
  41502576714 de `texto-mx` terminó en `failure` y no hay texto de ningún crudo; #80 verificó 0 de 42 citas (29 de 42 con
  la compuerta de #101, medido en la Mac).
- §3 "puertas cada cinco días hábiles": el dueño decidió el 2026-11-02 que cuentan todos los días; `ITINERARIO-2026-Q4.md`
  usa días de calendario.
- §3 paso 6 "VerdictEvent a RG" (fecha objetivo 2026-12-31): la verificación del `VerdictEvent` en RG (E3) no puede ir
  antes; el itinerario la tenía del 08 al 17-dic y pasa detrás de E4, bloqueada hasta el primer veredicto.
- §2 "se agrega arte previo de entornos de ejecución (OpenClaw, OpenShell)": RG ya lo tiene en parte en
  `docs/OPENCLAW_EVALUATION.md` (`5f04f94`, 2026-10-19: versión v2026.10.5, cadena de suministro, avisos que incluyen
  OpenShell, modelo de confianza con plugins en el proceso del gateway). Falta lo que pide el paso 3; el pedido nuevo
  pregunta solo eso.
- §4.1 crítica, fuente legacy sin consumidor: `mx.hf-tesis-scjn`; ya es candidata en la revisión de muerte semanal.

**Delta del artefacto de RG:**

| Artefacto | Qué cambia | Razón |
|---|---|---|
| `requests/` | `RR-2026-11-03-arte-previo-entornos-agentes` (P1) | paso 3 de ZPPMND: aislamiento por tenant, `tools.elevated`, licencia, OpenShell |
| `docs/ESTADO.md` | esta sección y la fila de horas del dueño | norte §4.1, regla 24 |
| `docs/NORTE.md` | "Pendiente de diseño" con cinco huecos activos y su forma de cierre; los otros tres a `BACKLOG.md` | regla 28 |
| `COLA.md`, `ITINERARIO-2026-Q4.md` | E3 detrás de E4, bloqueado hasta el primer `VerdictEvent`; los paquetes de arte previo corren por la cadena de E1 | paso 6 de ZPPMND |
| No se toca | adaptadores `legacy`; fuentes sin consumidor; `volcado`/`sitemap`/`rastreo`; NeMo Agent Toolkit | formas B y C; deprecado |

**Pedidos a ZPPMND** (concretos):
1. Adoptar `schemas/verdict_event.schema.json` de RG byte a byte (sha256
   `42dc9a3e937682e2a72ad8c24dc4bfb0937f1b46e000a1b974f207552d58ecd6` en `dfa9f4b`) y devolver el sha256 de su copia.
2. La identidad del workflow que firmará los `VerdictEvent` (repo, ruta, rama) y por qué vía llega cada uno a `verdicts/`
   de RG.
3. Qué comprueba el airlock de ZPPMND en "paquete de RG ingerido con constancia" (paso 2), para que el paquete NOM-035 de E1
   lo cumpla.
4. La lista de unidades `zpmnd:<nombre>` válidas como consumidor (reglas 21 y 23); hoy RG solo valida el patrón.
5. Las citas exactas que G06–G09 necesitan del OJN, para los casos dorados de E2.
6. La fecha estimada del paso 3, que fija cuándo hace falta el paquete de entornos de agentes.

## Alcance (reglas 21 y 23)

Ordenado por consumidor. Toda fuente nueva nombra `consumer` antes de `active`. Legacy: 8 fuentes (marca en #95), no se tocan.

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
| mx.inegi-bie | active · legacy | indicadores | sí (39877667471) | 1 / 0 / 0 |
| 143 del registro | candidate | ninguno | — | — |

La marca `legacy` llega a `sources/mx.json` con #95. Los conteos cuadra / descuadra / cuarentena son conteo manual
del dueño: ninguna prueba los comprueba hasta la de la regla 29. Déficit: ninguna `legacy` tiene los tres casos. Se
registra; aplica completo a toda fuente nueva.

## Pendiente, en orden

`COLA.md` (activo: E0, cerrar el día 1; siguiente: E1, primer paquete verificado) y su calendario en
`ITINERARIO-2026-Q4.md`. #94 y #98 ya están en `main`. Después del día 11: sellado del gold
de ZPPMND contra crudos. INEGI BIE ya es `active` con bytes reales (corrida 39877667471).

`vigia.yml` revisa cada día (23:37 UTC) las últimas corridas en `main` de catalog-mx, texto-mx, indicadores-mx, sondeo, descubrir y sondeo-inegi, y mantiene abierta una sola issue, «Vigía de producción», mientras alguno está en rojo o sin una corrida terminada dentro de su tope de días; la cierra con un comentario cuando todo está bien (`scripts/vigia.py`, SECURITY.md T26).

## Bloqueado (no se rodea)

SCJN (403), SRE (reto anti-bots), datos.gob.mx (`/api/` prohibido), CONAMER (403), SINEC (no resuelve).

## Revisión de muerte semanal (regla 26)

| Semana | Revertido | Nota |
|---|---|---|
| 2026-11-02 | — | Primera entrada. Candidatos próxima semana: `mx.hf-tesis-scjn` (sin consumidor), 143 fuentes del registro (regla 23: siguen `candidate`, no se activan) |

## Muestreo del dueño (regla 25)

| PR | Afirmación verificada | Resultado |
|---|---|---|
| — | — | — |

## Último merge en `main`

#103 · `414766a` · 2026-11-03 (antes: #96 · `dfa9f4b`, #100 · `637b3aa`, #95 · `764a25d`); se actualiza en cada entrega
