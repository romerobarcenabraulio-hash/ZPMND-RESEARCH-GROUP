# Itinerario de RESEARCH GROUP · 2026-11-03 a 2026-12-31

Lo ejecuta y lo regenera la sesión de RG. Fuentes: `ORDENES-RG.md`, `docs/REGLAS.md`, `docs/ESTADO.md`, `COLA.md` y los
PR abiertos (`ENTREGABLE.md` no existe en RG: el entregable activo es el primero de `COLA.md`). Lo que no sale de esas
fuentes está en `BACKLOG.md`. Cifras no medidas: HIPÓTESIS.

Reglas del plan:
- **Todos los días cuentan**, domingo a domingo, feriados incluidos (decisión del dueño, 2026-11-02): 59 días, del
  martes 03-nov al jueves 31-dic.
- **WIP = 1.** Un entregable activo. El siguiente se toma de `COLA.md` solo cuando el activo está **terminado**: merge en
  `main` + sus casos dorados en verde en el CI de `main` + `docs/ESTADO.md` con el SHA.
- **Capacidad.** El dueño revisa como máximo 3 PR por día; 400 líneas de código por PR (regla 20).
- **Merges que chocan.** Dos PR que tocan `SECURITY.md` o `scripts/mutar.py` no se entregan juntos: entra el primero y
  el segundo se rebasa y se re-audita.
- **Sesiones.** A = especificación y pruebas; B = implementa; C = audita (veredictos, `listo.sh`, comandos de merge).
- **Tercera REVISE en un PR:** antes del siguiente push se escribe su lista completa de amenazas con su prueba, o se
  parte. Si dos REVISE seguidas son de la misma clase, se cambia el método en vez de parchar.
- **Marcas diarias.** Al cerrar cada día real se marca la rama que ocurrió en la columna Día (`✓ PASÓ`, `↺ REVISAR`,
  `✗ REVERTIR`). Si fue REVISAR o REVERTIR, se regenera desde ese día hasta la siguiente puerta. Cada regeneración es un
  commit con su motivo.

**Regenerado el 2026-11-03** con el norte compartido de ese día: E4 pasa antes que E3, porque el primer `VerdictEvent`
llega con el paso 6 de ZPPMND (31-dic, HIPÓTESIS). Los paquetes de arte previo (OCR, entornos de agentes, auditor,
embeddings) corren por la cadena de E1 una vez que E1 esté terminado.

**Recurrente:** cada lunes (09, 16, 23 y 30-nov; 07, 14, 21 y 28-dic) entra el pedido del explorador semanal con la
fecha del día y se corre `investigar.yml`. Sale un paquete, nunca una instalación, y no cuenta como entregable.

## Puertas (cada 5 días)

sáb 07-nov, jue 12-nov, mar 17-nov, dom 22-nov, vie 27-nov, mié 02-dic, lun 07-dic, sáb 12-dic, jue 17-dic, mar 22-dic,
dom 27-dic y jue 31-dic (la última regenera el plan de 2027).

En cada puerta se mide por máquina:
- **Casos en verde:** pruebas del CI de `main` y citas `verificada` en el último `citas.jsonl`.
- **Huérfanos:** PR abiertos que no son del entregable activo ni de `COLA.md`, y fuentes `active` sin `consumer`
  (`rg/alcance.py`).
- **Costo:** corridas de GPT y NVIDIA del periodo. En USD es HIPÓTESIS hasta tener la factura.
- **Precisión:** citas verificadas entre citas totales de los paquetes del periodo. La de los auditores, desde que
  exista `scripts/auditor_stats.py`; antes, "no medible".

Además, la entrada de la regla 26 en `docs/ESTADO.md`. El detalle diario llega solo hasta la siguiente puerta; después
va por tramo de puerta a puerta.

## Dependencias externas

| Dependencia | Dueño | Fecha esperada | Si no llega (rama BLOQUEADO) |
|---|---|---|---|
| Decisión: crudo sellado en almacén privado (R2, secretos ya puestos y sin usar) | Braulio | sáb 07-nov (puerta 1) | E1 cierra con #80 en la cifra que dé la re-descarga (29/42 medido en la Mac); el almacén sigue en `BACKLOG.md` |
| Acceso a ZPPMND: identidad del workflow que firma y forma en que un `VerdictEvent` llega a `verdicts/` | Braulio | vie 27-nov | E3 se salta y se toma E4; E3 vuelve en la puerta siguiente a su llegada |
| Primer `VerdictEvent` de ZPPMND sobre el paquete NOM-035 de E1 | ZPPMND (su sesión) | jue 31-dic (paso 6 del norte compartido del 2026-11-03; HIPÓTESIS) | E3 no tiene caso dorado real: queda bloqueado y pasa al plan de 2027; E4 y el siguiente de la cola siguen |
| OCR de RG para G06–G09 de ZPPMND | RG (E2) + decisión del dueño sobre el extractor | lun 07-dic (HIPÓTESIS) | ZPPMND trabaja G01–G05 y G10; RG sigue con E3 |
| `INEGI_TOKEN` vigente | Braulio | vigente (la corrida 41506372436 cerró con `mx.inegi-bie` activo) | `mx.inegi-bie` vuelve a `trial`; nada de `COLA.md` depende de él |
| Auditores (OpenAI y la acción de Claude) | Braulio (cuentas) | continuo | sin dos PASS no hay merge: los días se consumen como colchón y se registra la causa |

## Colchón

12 de 59 días (20%), el día antes de cada puerta: vie 06-nov, mié 11-nov, lun 16-nov, sáb 21-nov, jue 26-nov,
mar 01-dic, dom 06-dic, vie 11-dic, mié 16-dic, lun 21-dic, sáb 26-dic y mié 30-dic. Están vacíos. Si se usa uno, se
registra aquí con su causa:

| Día | Usado por | Causa |
|---|---|---|
| — | — | — |

## Día 0 · lun 02-nov (ya trabajado)

| Día | Trabajo | Sesión | Criterio de salida | PASÓ → | REVISAR → | REVERTIR → |
|---|---|---|---|---|---|---|
| ✓ lun 02-nov | Órdenes de la semana; #94, #98 y #97 a `main`; #95 rehecho; #96 rebasado sobre #97; correcciones de #99, #100, #93 y #73; #101 (compuerta) abierto | C | `gh pr view 94 98 97 --json state` = MERGED | E0 activo el día 1 | — | — |

## Tramo 1 · mar 03 a sáb 07-nov (detalle diario)

Entregable activo: **E0 · cerrar el día 1 de ORDENES** (#95, #96 y #100). E0 está terminado cuando se cumplen tres
condiciones:
- Los tres PR están en `main`.
- El CI de `main` está en verde con `tests.test_registro` (cero errores en el registro real), `tests.test_llamada` (cero
  llamadas con llave fuera de la lista con fecha) y `tests.test_schemas`.
- `docs/ESTADO.md` tiene el SHA.

#99 ya está construido y admite una sola corrección más; si vuelve a REVISE, pasa a `BACKLOG.md`.

| Día | Trabajo | Sesión | Criterio de salida | PASÓ → | REVISAR → | REVERTIR → |
|---|---|---|---|---|---|---|
| mar 03-nov | Veredictos de #95 y #100; comandos de merge de los que tengan dos PASS (#95 primero: choca con #96 en `SECURITY.md` y `mutar.py`) | C | `listo.sh` sale 0 en el head de cada PR entregado | día 2 | REVISE en #95 o #100: se corrige en el mismo PR ese día (B); consume el día 2 | un merge deja rojo el CI de `main`: `gh pr revert` de ese PR y el plan vuelve al día 1 para él |
| mié 04-nov | #96 rebasado sobre `main` con #95, re-auditado y entregado; #99 si tiene dos PASS | B, C | `gh pr view 95 96 100 --json state` = MERGED | día 3 | otra REVISE en el mismo PR: es la tercera; lista de amenazas o partirlo; consume el colchón del 06-nov | igual que el día 1 |
| jue 05-nov | Cierre de E0: CI de `main` en verde y `docs/ESTADO.md` con el SHA (PR de dos líneas) | B | `gh run list --workflow ci.yml --branch main -L 1` = success y `grep <sha> docs/ESTADO.md` en `main` | E0 terminado; E1 se toma en la puerta 1 | CI de `main` rojo: causa raíz y arreglo en un PR (B); consume el colchón | se revierte el último merge de E0 y E0 sigue activo |
| vie 06-nov | Colchón | — | — | — | — | — |
| sáb 07-nov | **Puerta 1**: medir y regenerar los tramos 2 a 12; tomar E1 si E0 está terminado | C | la medición con sus cuatro cifras en `docs/ESTADO.md` y el commit de regeneración | E1 activo | E0 sin terminar: E0 sigue activo y se regenera | — |

## Tramo 2 · dom 08 a jue 12-nov (colchón mié 11, puerta jue 12)

| Tramo | Trabajo | Sesión | Criterio de salida | PASÓ → | REVISAR → | REVERTIR → |
|---|---|---|---|---|---|---|
| 08 a 12-nov | **E1 · primer paquete verificado** (cadena crudo → texto → compuerta → paquete): #101 a `main` y primera corrida de `texto-mx` con texto publicado | B, C | #101 MERGED; `texto-mx` con conclusión success y texto publicado | tramo 3 | REVISE de #101 o falla de `texto-mx`: se corrige en el mismo PR o workflow; consume el colchón | #101 rompe la compuerta en `main`: revert y la compuerta vieja sigue; E1 sigue activo |

## Tramo 3 · vie 13 a mar 17-nov (colchón lun 16, puerta mar 17)

| Tramo | Trabajo | Sesión | Criterio de salida | PASÓ → | REVISAR → | REVERTIR → |
|---|---|---|---|---|---|---|
| 13 a 17-nov | E1: paquete de `RR-2026-11-02-nom035-autoauditoria` con `investigar.yml` y su compuerta | B, C | PR del paquete abierto con su `citas.jsonl` y sus dos veredictos | tramo 4 | una cita no verificada: se corrige el paquete, nunca la compuerta | el paquete trae una cita que no está en su crudo: se cierra el PR y se repite la corrida |

## Tramo 4 · mié 18 a dom 22-nov (colchón sáb 21, puerta dom 22)

| Tramo | Trabajo | Sesión | Criterio de salida | PASÓ → | REVISAR → | REVERTIR → |
|---|---|---|---|---|---|---|
| 18 a 22-nov | E1: casos dorados de la nota NOM-035 del DOF en `tests/aceptacion/mx.dof/` (regla 29: cuadra, descuadra y cuarentena, de bytes reales); merge del paquete; re-auditar #80 con la compuerta | A, B, C | `citas.jsonl` del paquete con 100% `verificada`; los tres casos en verde en el CI de `main`; cifra X/42 de #80 en su artefacto `packet-gate` | E1 terminado con `docs/ESTADO.md` y su SHA; E2 activo | igual que el tramo 3 | el paquete entra con una cita falsa: revert; E1 sigue activo |

## Tramo 5 · lun 23 a vie 27-nov (colchón jue 26, puerta vie 27)

| Tramo | Trabajo | Sesión | Criterio de salida | PASÓ → | REVISAR → | REVERTIR → |
|---|---|---|---|---|---|---|
| 23 a 27-nov | **E2 · OCR para OJN**: #93 partido en dos PR de 400 líneas o menos (aislamiento del lector con su prueba real; medición) | A, B, C | los dos PR MERGED; la prueba real de aislamiento en verde en el CI de `main` | tramo 6 | la prueba real falla en Linux: se arregla el código, no la prueba | el aislamiento rompe `preparar`: revert del PR de aislamiento y la medición espera |

## Tramo 6 · sáb 28-nov a mié 02-dic (colchón mar 01, puerta mié 02)

| Tramo | Trabajo | Sesión | Criterio de salida | PASÓ → | REVISAR → | REVERTIR → |
|---|---|---|---|---|---|---|
| 28-nov a 02-dic | E2: corrida de `ocr-medir` sobre 20 crudos del OJN; paquete de `RR-2026-11-02-arte-previo-ocr-ojn` | B, C | artefacto `ocr-medicion` con versión fijada de cada motor y confianza por página; paquete MERGED | tramo 7 | corrida incompleta: se repite con lo guardado | el paquete afirma una licencia no leída: se cierra y se repite |

## Tramo 7 · jue 03 a lun 07-dic (colchón dom 06, puerta lun 07)

| Tramo | Trabajo | Sesión | Criterio de salida | PASÓ → | REVISAR → | REVERTIR → |
|---|---|---|---|---|---|---|
| 03 a 07-dic | E2: decisión del dueño sobre el extractor; PR de OCR determinista con versión fijada, confianza por página y casos dorados de páginas reales del OJN | A, B, C | PR MERGED con sus casos dorados en verde | E2 terminado; E3 si llegó el `VerdictEvent`, si no E4 | decisión pendiente: los días cuentan como colchón | el OCR cambia texto ya publicado: revert; `mx/texto` no cambia |

## Tramo 8 · mar 08 a sáb 12-dic (colchón vie 11, puerta sáb 12)

| Tramo | Trabajo | Sesión | Criterio de salida | PASÓ → | REVISAR → | REVERTIR → |
|---|---|---|---|---|---|---|
| 08 a 12-dic | **E4 · presupuesto de lectura por fuente** (hueco 4): tope de caracteres por fuente en cada parte; el exceso va a `limitations` con su conteo | A, B | caso dorado hecho del paquete real de #80 en verde | tramo 9 | el tope recorta una cita: se corrige el tope, no la cita | revert; los paquetes salen como hoy |

## Tramo 9 · dom 13 a jue 17-dic (colchón mié 16, puerta jue 17)

| Tramo | Trabajo | Sesión | Criterio de salida | PASÓ → | REVISAR → | REVERTIR → |
|---|---|---|---|---|---|---|
| 13 a 17-dic | E4 a `main` y terminado | C | E4 MERGED con su caso dorado en verde y `docs/ESTADO.md` con el SHA | tramo 10 | lo que falte se corrige en el mismo PR | revert; E4 sigue activo |

## Tramo 10 · vie 18 a mar 22-dic (colchón lun 21, puerta mar 22)

| Tramo | Trabajo | Sesión | Criterio de salida | PASÓ → | REVISAR → | REVERTIR → |
|---|---|---|---|---|---|---|
| 18 a 22-dic | **E3 · `VerdictEvent` verificado** si ya llegó el primero de ZPPMND: verificación Sigstore en CI contra su workflow y `RESEARCH_CONTRACT.md` §3 abre el canal en el mismo PR. Si no llegó (lo esperado: el paso 6 es el 31-dic), se toma el siguiente de `COLA.md`: licencia leída de la fuente (hueco 2) | A, B | el `VerdictEvent` real verifica en CI y uno alterado falla; o el PR de licencias con su prueba | tramo 11 | BLOQUEADO: se trabaja lo independiente | la verificación acepta algo que no debe: revert; nada lee `verdicts/` |

## Tramo 11 · mié 23 a dom 27-dic (colchón sáb 26, puerta dom 27)

| Tramo | Trabajo | Sesión | Criterio de salida | PASÓ → | REVISAR → | REVERTIR → |
|---|---|---|---|---|---|---|
| 23 a 27-dic | Cierre del entregable del tramo 10 (`rg/precision.py` si fue E3) | B, C | MERGED con su caso dorado y `docs/ESTADO.md` con el SHA | tramo 12 | lo que falte se corrige en el mismo PR | revert; sigue activo |

## Tramo 12 · lun 28 a jue 31-dic (colchón mié 30, puerta jue 31)

| Tramo | Trabajo | Sesión | Criterio de salida | PASÓ → | REVISAR → | REVERTIR → |
|---|---|---|---|---|---|---|
| 28 a 31-dic | Se toma el siguiente de `COLA.md` solo si el activo está terminado. **Puerta final** el 31: medición del trimestre y regeneración | A, C | `ITINERARIO-2027-Q1.md` en un PR con la medición del trimestre | fin del trimestre | lo que no cerró pasa a 2027 con su causa | — |

## AMBIGÜEDADES (lo que supuse)

1. **Entregables.** En RG no existían `ENTREGABLE.md` ni `COLA.md`. Definí los entregables con `ORDENES-RG.md` §1 y §2 y
   con la decisión del dueño del 2026-11-02: primero la cadena crudo → texto → compuerta → paquete, con #75 y #73
   congelados.
2. **Casos dorados.** En RG son tres cosas: las pruebas que el entregable pone en verde en el CI de `main`, los casos de
   aceptación por fuente de la regla 29, y para un paquete, su `citas.jsonl` con el 100% de las citas `verificada`.
3. **Calendario.** La plantilla original excluía fines de semana y feriados. El dueño trabaja todos los días, así que
   cuentan los 59 días. Por eso las tablas van por tramo de puerta a puerta (5 días) y no por semana.
4. **Puertas.** Las puertas son trabajo de auditoría (sesión C). El día de puerta puede llevar trabajo del entregable si
   la medición sale bien.
5. **Marcas diarias.** Se escriben en este archivo con el PR del día, si hay uno. Si no lo hay, se juntan en el commit de
   la puerta, para no abrir un PR solo para marcar.
6. **Duraciones.** Las de E1 a E4 son HIPÓTESIS, sacadas de la última semana: 30 PR fusionados, 2 a 4 rondas de
   auditoría en un PR típico, y 10 a 11 rondas en #73 y #75.
7. **E3.** Depende de que ZPPMND emita un `VerdictEvent` firmado; si no llega, E4 se adelanta sin cambiar el resto.
8. **PR congelados.** #91, #77 y #89 no están en los tres entregables que siguen; quedan abiertos y congelados, y cuentan
   en el tope de 6 PR abiertos. #80 es parte de E1 y #93 de E2.
9. **Orden.** `ORDENES-RG.md` §1 ponía #75, #93 y #91 antes que la cadena. El dueño aprobó cambiarlo el 2026-11-02.
