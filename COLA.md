# Cola de entregables de RESEARCH GROUP

WIP = 1. El siguiente se toma solo cuando el activo está terminado: merge en `main`, sus casos dorados en verde en el
CI de `main` y `docs/ESTADO.md` con el SHA.

## Activo

**T1 · transición a ZPMND-FINAL** (directiva del dueño del 2026-11-17). Entregables:
- la comparación de `docs/medicion/comparacion-2026-11-17/protocolo.md` (#172), fijada antes de correr;
- el primer paquete horizontal que sale de ella, con su evidencia, pruebas, costo y limitaciones.

Termina con el informe de la comparación y ese paquete en `main`. El consumidor es `ZPMND-FINAL`; `ZPPMND` queda como
fuente histórica de solo lectura.

## Histórico, diferido o sustituible (2026-11-17)

Ninguno se borra: su evidencia sigue en el repo y en sus PR.

- **E0** cerrado: #105 (`c1fc920`, 2026-11-03).
- **E1** histórico en lo fiscal.
  - El primer paquete verificado sí entró: #166 (`RP-2026-11-08-nom035-dof-publicacion`, 2026-11-14), con la compuerta
    de #101.
  - Quedan diferidos, sin rondas nuevas: sus casos dorados de NOM-035 y la autoauditoría (#170).
  - Se conserva lo genérico que salió de él: fidelidad de citas (#155, #164, #167) y conciliación (#171).
- **E2** (OCR para OJN), diferido. Su consumidor eran G06–G09 de ZPPMND; reabre si ZPMND-FINAL pide texto de documentos
  escaneados. #93 queda en draft.
- **E3** (`VerdictEvent`), bloqueado. `schemas/verdict_event.schema.json` solo acepta como firmante el workflow de
  ZPPMND, así que un veredicto de ZPMND-FINAL falla cerrado hasta una versión 2 que nombre el suyo.
- **E4** (presupuesto de lectura por fuente), sustituible: entra si la comparación lo pide.
- **Diferidos hasta que ZPMND-FINAL emita sus pedidos:** los paquetes de arte previo de esta cola y el explorador de
  capacidades semanal.
- **Pedidos fiscales y de NOM-035 en `requests/`:** históricos; no se despachan. Son seis: `RR-2026-10-21-nom-vigencia`,
  `RR-2026-10-21-nom035-obligaciones`, `RR-2026-10-21-unidades-de-referencia`, `RR-2026-11-02-nom035-autoauditoria`,
  `RR-2026-11-08-nom035-dof-publicacion` y `RR-2026-11-08-familia-g-contabilidad-fiscal`.

## Congelados (no reciben rondas; cerrarlos es decisión del dueño)

En draft, sin rondas:
- #75, el runner, y #73, Postgres. El dueño decidió el 2026-11-02 partirlos en su turno.
- #91, el tercer revisor: espera la regla 27.
- #77, el despachador nocturno: va al final.
- #89, el motor `api`: espera que su primer uso sea `mx.inegi-bie`.
- #118, el empaquetador del catálogo.
- #93, la medición de OCR (E2).

#97 (vigía) y #99 (plazo del descubrimiento) ya entraron en `main` (`3703172` y `0373d34`).

## Después de E4 (histórico: orden de ORDENES-RG §2 para ZPPMND; no gobierna T1)

Licencia leída de la fuente (hueco 2); `scripts/auditor_stats.py` (regla 27); mapa de cobertura con denominador
(hueco 7); identificadores canónicos (hueco 6); cambios como eventos (hueco 5); frescura y búsqueda negativa (hueco 8);
motor `api` con `mx.inegi-bie` (#89); ancla: `tests/test_norte.py` (regla 28) y #77.
