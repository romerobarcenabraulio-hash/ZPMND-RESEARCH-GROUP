# Estado de RESEARCH GROUP · 2026-11-02

Única entrada del repo (regla 24). Se actualiza en cada entrega; lo superseded se borra.

## Dónde está cada cosa

| Qué | Dónde |
|---|---|
| Código, contrato, seguridad | `main` |
| Reglas | `docs/REGLAS.md` (1–19; 21–23 en #95; el resto entra con su prueba) |
| Órdenes de la semana | `ORDENES-RG.md` (plan del dueño) |
| Entregable activo y los tres siguientes (WIP = 1) | `COLA.md` |
| Plan día por día hasta el 2026-12-31 | `ITINERARIO-2026-Q4.md` |
| Catálogo de México | rama `catalog`, `mx/`; crudos en release `raw-mx`; texto en `text-mx` (aún no existe: primera corrida de `texto-mx` en curso) |
| Registro de fuentes | `sources/mx.json` (15 fuentes: 8 activas con 7 adaptadores, marca `legacy` en #95; 7 `planned`) + `sources/registro/` (143 fuentes candidatas, 16 familias) |
| Pedidos abiertos | `requests/` (11 + RR-2026-11-02-nom035-autoauditoria P0 + 3 de arte previo) |
| Paquetes | `research-packets/`, con constancia Sigstore |
| Veredictos de ZPPMND | `verdicts/` (esquema en #95; verificación en CI pendiente) |
| Huecos del NORTE | `docs/NORTE.md` → `ORDENES-RG.md` §2 (calendario) |
| Diferidos | `BACKLOG.md` (cada uno con su condición de reapertura) |

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

#94 · `ea21874` · 2026-11-02 (se actualiza en cada entrega)
