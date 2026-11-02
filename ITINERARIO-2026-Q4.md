# Itinerario de RESEARCH GROUP · 2026-11-03 a 2026-12-31

Lo ejecuta y lo regenera la sesión de RG. Fuentes: `ORDENES-RG.md`, `docs/REGLAS.md`, `docs/ESTADO.md`, `COLA.md` y los
PR abiertos (`ENTREGABLE.md` no existe en RG: el entregable activo es el primero de `COLA.md`). Lo que no sale de esas
fuentes está en `BACKLOG.md`. Cifras no medidas: HIPÓTESIS.

Reglas del plan:
- **WIP = 1.** Un entregable activo. El siguiente se toma de `COLA.md` solo cuando el activo está **terminado**: merge en
  `main` + sus casos dorados en verde en el CI de `main` + `docs/ESTADO.md` con el SHA.
- **Capacidad.** El dueño revisa como máximo 3 PR por día; 400 líneas de código por PR (regla 20). No cuentan los fines
  de semana ni el 12, 24, 25 y 31 de diciembre y el 1 de enero.
- **Sesiones.** A = especificación y pruebas; B = implementa; C = audita (veredictos, `listo.sh`, comandos de merge).
- **Tercera REVISE en un PR:** antes del siguiente push se escribe su lista completa de amenazas con su prueba, o se
  parte.
- **Marcas diarias.** Al cerrar cada día real se marca la rama que ocurrió en la columna Día (`✓ PASÓ`, `↺ REVISAR`,
  `✗ REVERTIR`). Si fue REVISAR o REVERTIR, se regenera desde ese día hasta la siguiente puerta. Cada regeneración es un
  commit con su motivo.

## Puertas (cada 5 días hábiles)

| Puerta | Fecha | Qué se mide (por máquina) |
|---|---|---|
| 1 | lun 09-nov | casos en verde: pruebas del CI de `main` y citas `verificada` en el último `citas.jsonl`; huérfanos: PR abiertos que no son del entregable activo ni de `COLA.md`, fuentes `active` sin `consumer` (`rg/alcance.py`); costo: corridas de GPT y NVIDIA del periodo (USD: HIPÓTESIS hasta tener la factura); precisión: citas verificadas / citas totales de los paquetes del periodo. Entrada semanal de la regla 26 en `docs/ESTADO.md` |
| 2 | lun 16-nov | lo mismo |
| 3 | lun 23-nov | lo mismo |
| 4 | lun 30-nov | lo mismo |
| 5 | lun 07-dic | lo mismo, más la precisión de los auditores si `scripts/auditor_stats.py` ya existe (si no: "no medible") |
| 6 | lun 14-dic | lo mismo |
| 7 | lun 21-dic | lo mismo |
| 8 | mié 30-dic | lo mismo, y se regenera el plan del primer trimestre de 2027 |

El detalle diario llega solo hasta la siguiente puerta; después va por semana.

## Dependencias externas

| Dependencia | Dueño | Fecha esperada | Si no llega (rama BLOQUEADO) |
|---|---|---|---|
| Decisión: crudo sellado en almacén privado (R2, secretos ya puestos y sin usar) | Braulio | 2026-11-09 (puerta 1) | E1 cierra con #80 en la cifra que dé la re-descarga (29/42 medido en la Mac); el almacén queda en `BACKLOG.md` |
| Acceso a ZPPMND: identidad del workflow que firma y forma en que un `VerdictEvent` llega a `verdicts/` | Braulio | 2026-11-30 (puerta 4) | E3 se salta y se toma E4; E3 vuelve en la puerta siguiente a su llegada |
| Primer `VerdictEvent` de ZPPMND sobre el paquete NOM-035 de E1 | ZPPMND (sesión de ZPPMND) | 2026-12-07 (puerta 5) | E3 no tiene caso dorado real: se salta, se toma E4 |
| OCR de RG para G06–G09 de ZPPMND | RG (E2) + decisión del dueño sobre el extractor | 2026-12-04 (HIPÓTESIS) | ZPPMND trabaja G01–G05 y G10; RG sigue con E3 |
| `INEGI_TOKEN` vigente | Braulio | vigente (la corrida 41506372436 cerró con `mx.inegi-bie` activo) | `mx.inegi-bie` vuelve a `trial`; nada de `COLA.md` depende de él |
| Auditores (OpenAI y la acción de Claude) | Braulio (cuentas) | continuo | sin dos PASS no hay merge: los días se consumen como colchón y se registra la causa |

## Colchón

8 de 40 días hábiles (20%): vie 06-nov, vie 13-nov, vie 20-nov, vie 27-nov, vie 04-dic, vie 11-dic, vie 18-dic y
mar 29-dic. Están vacíos. Uno que se use se registra aquí con su causa:

| Día | Usado por | Causa |
|---|---|---|
| — | — | — |

## Día 0 · lun 02-nov (ya trabajado)

| Día | Trabajo | Sesión | Criterio de salida | PASÓ → | REVISAR → | REVERTIR → |
|---|---|---|---|---|---|---|
| ✓ lun 02-nov | Órdenes de la semana; #94 y #98 a `main`; #95 rehecho; correcciones de #96, #97, #99, #100, #93, #73; #101 (compuerta) abierto | C | `gh pr view 94 98 --json state` = MERGED | E0 activo el día 1 | — | — |

## Semana 1 · 03 a 09-nov (detalle diario)

Entregable activo: **E0 · cerrar el día 1 de ORDENES** (#95, #96, #100). Terminado E0: los tres en `main`, el CI de
`main` en verde con `tests.test_registro` (cero errores en el registro real), `tests.test_llamada` (cero llamadas con
llave fuera de la lista con fecha) y `tests.test_schemas`, y `docs/ESTADO.md` con el SHA. Ya construidos y sin trabajo
nuevo: #97 (dos PASS), #99 (una corrección más como máximo; si vuelve REVISE pasa a `BACKLOG.md`).

| Día | Trabajo | Sesión | Criterio de salida | PASÓ → | REVISAR → | REVERTIR → |
|---|---|---|---|---|---|---|
| mar 03-nov | Veredictos de #95, #96 y #100; comandos de merge de los que tengan dos PASS, en ese orden, más #97 (≤3 por día) | C | `listo.sh` sale 0 en el head de cada PR entregado | día 2 con lo que falte | REVISE en #95, #96 o #100: se corrige en el mismo PR ese día (sesión B); consume el día 2 | un merge deja rojo el CI de `main`: `gh pr revert` de ese PR y el plan vuelve al día 1 para él |
| mié 04-nov | Merges restantes de E0 y #99 si tiene dos PASS | C | `gh pr view 95 96 100 --json state` = MERGED | día 3 | otra REVISE en el mismo PR: es la tercera; lista de amenazas o partirlo; consume el colchón del 06-nov | igual que el día 1 |
| jue 05-nov | Cierre de E0: CI de `main` en verde y `docs/ESTADO.md` con el SHA (PR de dos líneas) | B | `gh run list --workflow ci.yml --branch main -L 1` = success y `grep <sha> docs/ESTADO.md` en `main` | E0 terminado; E1 se toma en la puerta 1 | CI de `main` rojo: causa raíz y arreglo en un PR (B); consume el colchón | se revierte el último merge de E0 y E0 sigue activo |
| vie 06-nov | Colchón | — | — | — | — | — |
| lun 09-nov | **Puerta 1**: medir y regenerar semanas 2 a 9; tomar E1 si E0 está terminado | C | archivo de la medición en `docs/ESTADO.md` con las cuatro cifras y el commit de regeneración | E1 activo | E0 sin terminar: E0 sigue activo y se regenera | — |

## Semana 2 · 10 a 16-nov

| Día | Trabajo | Sesión | Criterio de salida | PASÓ → | REVISAR → | REVERTIR → |
|---|---|---|---|---|---|---|
| 10 a 16-nov (colchón vie 13) | **E1 · primer paquete verificado** (cadena crudo → texto → compuerta → paquete): #101 a `main`; primera corrida de `texto-mx` con texto publicado; paquete de `RR-2026-11-02-nom035-autoauditoria` con `investigar.yml`. Puerta 2 el lun 16 | B, C | #101 MERGED; `texto-mx` con conclusión success; PR del paquete abierto con su `citas.jsonl` | semana 3 | REVISE de #101 o falla de `texto-mx`: se corrige en el mismo PR o workflow; consume el colchón | #101 rompe la compuerta en `main`: revert y la compuerta vieja sigue; E1 sigue activo |

## Semana 3 · 17 a 23-nov

| Día | Trabajo | Sesión | Criterio de salida | PASÓ → | REVISAR → | REVERTIR → |
|---|---|---|---|---|---|---|
| 17 a 23-nov (colchón vie 20) | E1: casos dorados (regla 29) de la nota NOM-035 del DOF en `tests/aceptacion/mx.dof/` (cuadra, descuadra y cuarentena, de bytes reales); merge del paquete; re-auditar #80 con la compuerta. Puerta 3 el lun 23 | A, B, C | `citas.jsonl` del paquete NOM-035 con 100% `verificada`; los tres casos en verde en el CI de `main`; cifra X/42 de #80 en su artefacto `packet-gate` | E1 terminado con `docs/ESTADO.md` y su SHA; E2 activo | una cita no verificada: se corrige el paquete, nunca la compuerta; consume el colchón | el paquete entra con una cita falsa: revert y E1 sigue activo |

## Semana 4 · 24 a 30-nov

| Día | Trabajo | Sesión | Criterio de salida | PASÓ → | REVISAR → | REVERTIR → |
|---|---|---|---|---|---|---|
| 24 a 30-nov (colchón vie 27) | **E2 · OCR para OJN**: #93 partido en dos PR de 400 líneas o menos (aislamiento del lector con su prueba real; medición); merge de ambos; corrida de `ocr-medir` sobre 20 crudos del OJN. Puerta 4 el lun 30 | A, B, C | los dos PR MERGED; artefacto `ocr-medicion` con versión fijada de cada motor y confianza por página | semana 5 | la prueba real de aislamiento falla en Linux: se arregla el código, no la prueba | el aislamiento rompe `preparar`: revert del PR de aislamiento y la medición espera |

## Semana 5 · 01 a 07-dic

| Día | Trabajo | Sesión | Criterio de salida | PASÓ → | REVISAR → | REVERTIR → |
|---|---|---|---|---|---|---|
| 01 a 07-dic (colchón vie 04) | E2: paquete de `RR-2026-11-02-arte-previo-ocr-ojn`; decisión del dueño; PR de OCR determinista con versión fijada, confianza por página y casos dorados de páginas reales del OJN. Puerta 5 el lun 07 | A, B, C | paquete MERGED; PR de OCR con sus casos dorados en verde | E2 terminado; E3 activo si llegó el `VerdictEvent`, si no E4 | decisión del dueño pendiente: los días se registran como colchón | el OCR determinista cambia texto ya publicado: revert; `mx/texto` no cambia |

## Semana 6 · 08 a 14-dic

| Día | Trabajo | Sesión | Criterio de salida | PASÓ → | REVISAR → | REVERTIR → |
|---|---|---|---|---|---|---|
| 08 a 14-dic (colchón vie 11) | **E3 · `VerdictEvent` verificado**: verificación Sigstore en CI contra el workflow de ZPPMND; `RESEARCH_CONTRACT.md` §3 abre el canal en el mismo PR; `rg/precision.py` publica `docs/PRECISION.md`. Puerta 6 el lun 14 | A, B, C | el primer `VerdictEvent` real verifica en CI y uno alterado falla; `docs/PRECISION.md` generado en `main` | semana 7 | BLOQUEADO (sin `VerdictEvent` real): se toma E4 y E3 vuelve en la puerta siguiente a su llegada | la verificación acepta algo que no debe: revert; nada lee `verdicts/` |

## Semana 7 · 15 a 21-dic

| Día | Trabajo | Sesión | Criterio de salida | PASÓ → | REVISAR → | REVERTIR → |
|---|---|---|---|---|---|---|
| 15 a 21-dic (colchón vie 18) | Cierre de E3; **E4 · presupuesto de lectura por fuente** (hueco 4): tope de caracteres por fuente en cada parte, exceso a `limitations` con su conteo. Puerta 7 el lun 21 | A, B, C | E3 terminado; caso dorado de E4 hecho del paquete real de #80 en verde | semana 8 | igual que arriba | revert del PR de E4; los paquetes salen como hoy |

## Semana 8 · 22 a 30-dic

| Día | Trabajo | Sesión | Criterio de salida | PASÓ → | REVISAR → | REVERTIR → |
|---|---|---|---|---|---|---|
| 22, 23, 28 y 30-dic (colchón mar 29) | E4 a `main` y terminado; **puerta 8** el mié 30: medición del trimestre y regeneración para 2027 desde `COLA.md` | B, C | E4 MERGED con su caso dorado en verde; `ITINERARIO-2027-Q1.md` en un PR | fin del trimestre | lo que no cerró pasa al primer día de 2027 con su causa | — |

## AMBIGÜEDADES (lo que supuse)

1. `ENTREGABLE.md` y `COLA.md` no existían en RG. Definí los entregables con `ORDENES-RG.md` §1 y §2 y con la decisión
   del dueño del 2026-11-02 (primero la cadena crudo → texto → compuerta → paquete; #75 y #73 congelados).
2. "Casos dorados" en RG: las pruebas que el entregable pone en verde en el CI de `main`, los casos de aceptación por
   fuente de la regla 29 y, para un paquete, su `citas.jsonl` con el 100% de las citas `verificada`.
3. El lunes 16-nov es feriado en México, pero no está en la lista de días que no cuentan: lo conté como hábil.
4. Las puertas son trabajo de auditoría (sesión C) y caen en lunes; el día de puerta puede llevar trabajo del
   entregable si la medición sale bien.
5. Las marcas diarias se escriben en este archivo con el PR del día, si hay uno; si no, se juntan en el commit de la
   puerta. Así no se abre un PR solo para marcar el día.
6. Las duraciones de E1 a E4 son HIPÓTESIS, sacadas de la última semana: 30 PR fusionados, 2 a 4 rondas de auditoría
   en un PR típico y 10 a 11 rondas en #73 y #75.
7. E3 depende de que ZPPMND emita un `VerdictEvent` firmado; si no llega, E4 se adelanta sin cambiar el resto.
8. #91, #77 y #89 no están en los próximos tres entregables; siguen abiertos y congelados (cuentan en el tope de 6 PR
   abiertos). #80 es parte de E1 y #93 de E2.
9. El orden de `ORDENES-RG.md` §1 ponía #75, #93 y #91 antes que la cadena; el dueño aprobó cambiarlo el 2026-11-02.
