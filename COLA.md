# Cola de entregables de RESEARCH GROUP

WIP = 1. El siguiente se toma solo cuando el activo está terminado: merge en `main`, sus casos dorados en verde en el
CI de `main` y `docs/ESTADO.md` con el SHA. El calendario está en `ITINERARIO-2026-Q4.md`.

## Activo

**E0 · cerrar el día 1 de ORDENES.** PR #95 (alcance y esquema `VerdictEvent`), #96 (una sola forma de llamar con
llave, con la lista con fecha que aprobó el dueño) y #100 (órdenes, ESTADO, pedidos, este archivo). Casos dorados:
`tests.test_registro`, `tests.test_llamada` y `tests.test_schemas` en el CI de `main`.

## Siguiente

**E1 · primer paquete verificado.** #101 (la compuerta vuelve a bajar el crudo y comprueba su sha256), la primera
corrida de `texto-mx` con texto publicado, el paquete de `RR-2026-11-02-nom035-autoauditoria` y la re-auditoría de
#80. Casos dorados: `citas.jsonl` del paquete con 100% `verificada` y los tres casos de aceptación de la nota NOM-035
del DOF (regla 29). Va primero porque hoy RG no entrega nada verificado: 0 de 42 citas en #80 y ningún paquete con
veredicto de ZPPMND.

## Los tres que siguen, en este orden

1. **E2 · OCR para OJN** (#93 partido en dos PR, medición sobre 20 crudos reales, paquete de
   `RR-2026-11-02-arte-previo-ocr-ojn`, decisión del dueño, OCR determinista con versión fijada). Va primero porque
   G06–G09 de ZPPMND están detenidos sin texto de los documentos estatales y municipales escaneados.
2. **E3 · `VerdictEvent` verificado en CI** (Sigstore contra el workflow de ZPPMND, `RESEARCH_CONTRACT.md` §3 abre el
   canal en ese mismo PR, `rg/precision.py`). Va segundo porque cierra el circuito con el paquete de E1, y solo puede
   empezar cuando ZPPMND emita su primer veredicto firmado (dependencia externa).
3. **E4 · presupuesto de lectura por fuente** (hueco 4). Va tercero porque mejora todos los paquetes pero no destraba a
   ningún consumidor. Si E3 queda bloqueado, E4 se adelanta.

## Congelados (no reciben rondas hasta su turno)

#75 runner y #73 Postgres (decisión del dueño 2026-11-02: se parten en su turno), #91 tercer revisor (espera la regla
27), #77 despachador nocturno (al final), #89 motor `api` (draft hasta que su primer uso sea `mx.inegi-bie`). #97
(vigía) y #99 (plazo del descubrimiento) ya están construidos: entran si tienen dos PASS; si vuelven a REVISE pasan a
`BACKLOG.md`.

## Después de E4 (orden de ORDENES-RG §2, sin fecha hasta su puerta)

Licencia leída de la fuente (hueco 2); `scripts/auditor_stats.py` (regla 27); mapa de cobertura con denominador
(hueco 7); identificadores canónicos (hueco 6); cambios como eventos (hueco 5); frescura y búsqueda negativa (hueco 8);
motor `api` con `mx.inegi-bie` (#89); ancla: `tests/test_norte.py` (regla 28) y #77.
