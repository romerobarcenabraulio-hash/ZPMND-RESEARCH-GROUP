# Cierre de huecos del NORTE

Parte B del documento único del dueño (2026-11-02). Es un documento de decisión, no de diseño.

**Reconciliación con lo que ya está en `main`.** Donde este texto y `ORDENES-RG.md` (parte A, "decisiones cerradas")
dicen cosas distintas, manda la parte A, que es posterior:
- RG no se congela. La regla 21 es "consumidor antes de `active`" (#95), no "alcance congelado hasta el primer
  veredicto". Lo que aquí se llama "congelar alcance" se cumple como "ninguna fuente pasa a `active` sin consumidor"
  (reglas 21 y 23, `rg/alcance.py`).
- El primer motor que se construye es `api`, con `mx.inegi-bie` como primer uso (#89). `volcado` va en el PR siguiente,
  con una fuente que tenga consumidor. No es "`volcado` primero".
- Los entregables y su orden vigente están en `COLA.md`, y su calendario en `ITINERARIO-2026-Q4.md`. La tabla del
  apartado 4 es el orden por hueco que escribió el dueño; el orden de ejecución es el de `COLA.md`.

Los ocho huecos están en `docs/NORTE.md` ("Pendiente de diseño, en orden", 2026-10-31). Aquí va por qué no cierran, qué
significa "cerrado", y qué cierre le toca a cada uno.

## 1. Por qué no cierran (cuatro causas, todas estructurales)

1. **Están escritos como capacidades, no como entregables.** "Linaje, deduplicación y resolución de entidades" no tiene
   cuadre. Lo que tiene cuadre cierra (el catálogo: 1,333 cuadres sin descuadre). Lo que no tiene cuadre no cierra
   porque no hay forma de saber que cerró. Los huecos 5, 6 y 8 no tienen definición de terminado.
2. **La superficie crece más rápido que el cierre.** Entre el 2026-10-31 y el 2026-11-02 entraron 143 fuentes de 16
   familias (#84), OpenAlex y Crossref (#88) y el descubrimiento por país (#86). Cada fuente nueva agranda los huecos 1,
   2, 6 y 7.
3. **Varios huecos no tienen consumidor.** Frescura, contradicción, explorador de capacidades, eventos de cambio: ningún
   `ResearchRequest` abierto los necesita. Un hueco sin consumidor no se cierra porque nada lo jala.
4. **El hueco 1 es una reescritura disfrazada de hueco.** "Que ninguna fuente nueva pida código" implicaba convertir
   siete adaptadores que funcionan en configuración. El criterio de aceptación ("un adaptador de México convertido") lo
   volvía una obra.

## 2. Qué significa "cerrado" (tres formas, las tres válidas)

| Forma | Qué es | Recibo |
|---|---|---|
| **A. Por código** | Un PR con prueba mecánica que falla sin el cambio | CI verde + mutante muerto + fila en `docs/ESTADO.md` |
| **B. Por frontera** | Lo viejo se declara permitido y lo nuevo obligado por el camino nuevo. No se reescribe nada | Prueba que rechaza lo nuevo por el camino viejo; lo viejo queda listado como `legacy` |
| **C. Por diferimiento** | Sale de la lista activa con una condición escrita de reapertura (un pedido que lo necesite) | Entrada en `BACKLOG.md` con la condición; no vuelve al NORTE hasta que se cumpla |

Lo que no es cerrado: "en progreso", "diseñado, en revisión", "parcial". Un hueco está en una de las tres formas o está
abierto, y abierto tiene fecha.

## 3. Decisión por hueco

| # | Hueco | Cierre | Qué se hace | Prueba mecánica | Tamaño |
|---|---|---|---|---|---|
| 1 | Adquisición declarativa por registro | **B + A** | Los 7 adaptadores de México son `legacy` en `sources/mx.json` y no se tocan (#95). Toda fuente nueva entra solo por `adquisicion`. Se construye **un** motor primero (`api`, con `mx.inegi-bie`; ver la reconciliación arriba); los demás esperan a una fuente que los pida (forma C) | `tests/test_registro.py` (#95): una fuente nueva sin consumidor ni `adquisicion` válida no puede ser `active`; el motor carga una fuente real de prueba con cuadre | 1 PR frontera (#95, en `main`) + 1 PR motor |
| 2 | Licencia leída de la fuente | **A** | Tabla fija por host en `sources/`: dónde se lee literalmente la licencia (LFDA art. 14 fr. VIII para textos legislativos; aviso de Banxico; términos de INEGI; CC-BY del dataset de HF). `SourceArtifact.license` se llena desde la tabla con `license_read_at` y cita; lo que no esté en la tabla sigue `NO VERIFICADA` | Toda fuente `active` tiene regla de licencia; un artefacto de fuente activa nunca sale `NO VERIFICADA` | 1 PR |
| 3 | Compuerta sin republicar el crudo | **A** | La compuerta vuelve a bajar el crudo por el mismo `Fetcher`, comprueba el sha256 contra el `SourceArtifact` y lee la cita ahí. Nada se publica (#101) | #80 repetido con fuentes solo-metadatos: 29 de 42 en la Mac con la re-descarga; las 13 restantes son páginas que cambian en cada petición y piden el crudo sellado al adquirirlo (`BACKLOG.md`) | 1 PR |
| 4 | Presupuesto de lectura por fuente | **A** | Tope de caracteres por fuente dentro de cada parte del análisis; lo que excede se corta y queda en `limitations` con cuántos caracteres se dejaron fuera | En la prueba de estrés las 8 fuentes aparecen leídas; el PDF de 1.37 M de caracteres no deja fuera a ninguna | 1 PR |
| 5 | Cambios como eventos | **A (acotado) + C** | Un solo vigía produce `ChangeEvent`: (a) linaje NOM, una nota nueva = evento; (b) leyes y reglamentos federales, ETag cambiado = evento con los dos sha256. Nada más (C: un pedido que necesite "qué cambió en X") | Una corrida con una nota NOM nueva y un ETag cambiado emite exactamente dos eventos válidos por esquema; una sin cambios emite cero | 1 PR |
| 6 | Linaje, deduplicación, entidades | **A (mínimo) + C** | Solo el esquema de identificadores canónicos, como datos: ley (id de Diputados), artículo (ley + número), linaje NOM, municipio (clave INEGI), fuente (id del registro). Nada de resolución entre fuentes ni casi-duplicados (C: un pedido que cruce dos fuentes sobre la misma entidad) | Todo registro del catálogo lleva `entity_id` válido; dos versiones de la misma ley comparten id y difieren en versión | 1 PR |
| 7 | Mapa de cobertura como código | **A** | `rg/cobertura.py` escribe `mx/cobertura.json` en cada corrida: fuente × jurisdicción × periodo con numerador y denominador del cuadre existente. Sin denominador, la celda dice `sin_denominador`, nunca un porcentaje | Cada celda con porcentaje tiene denominador > 0 citado del manifiesto; falla si aparece un porcentaje sin denominador | 1 PR |
| 8 | Frescura, búsqueda negativa, contradicción, capacidades | **A (dos) + C (dos)** | Frescura: campo `freshness` de lista fija en el registro (`estatica`, `periodica`, `alta`, `tiempo_real`), solo dato. Búsqueda negativa: `receipt.json` lleva `no_encontrado`. Contradicción y capacidades como flujo: C (un pedido con `desired_evidence` que las nombre). El explorador semanal de capacidades (`ORDENES-RG.md`) es un pedido recurrente, no un flujo | Toda fuente activa tiene `freshness`; un recibo de `investigar` sin `no_encontrado` falla el esquema | 2 PR chicos |

Resultado: 11 PR cierran los ocho huecos. Ninguno pasa de 400 líneas salvo el motor. Ninguno abre un frente nuevo.

## 4. Orden por hueco (el que escribió el dueño)

| Día | PR | Hueco | Por qué aquí |
|---|---|---|---|
| 1 | Frontera `legacy` y consumidor antes de `active` | 1 (B) | Detiene la banda (#95, en `main`) |
| 2 | Compuerta con re-descarga | 3 | El defecto más grave del recibo de #80: 0 de 42 citas (#101) |
| 3 | Presupuesto de lectura | 4 | Segundo defecto de #80 |
| 4 | Licencia por tabla | 2 | Chico; deja de salir `NO VERIFICADA` |
| 5 | Mapa de cobertura con denominador | 7 | El número que faltaba ver |
| 6 | Identificadores canónicos | 6 (mínimo) | Prerrequisito del día 7 |
| 7 | `ChangeEvent` acotado (NOM + ETag) | 5 | Usa los ids del día 6 |
| 8 | `freshness` + `no_encontrado` | 8 (parcial) | Dos PR chicos; el resto a `BACKLOG.md` |
| 9–10 | Motor `api` con `mx.inegi-bie` | 1 (A) | El único mediano; al final para que no bloquee a los chicos |
| 11 | `docs/ESTADO.md` con los huecos cerrados y `BACKLOG.md` | — | El ancla única (regla 24) |

Mientras dure el cierre: ninguna fuente pasa a `active` sin consumidor (regla 23) y no entran pedidos nuevos salvo los
del dueño de `ORDENES-RG.md` (NOM-035, los tres de arte previo y el explorador semanal).

## 5. Lo que sale de la lista (`BACKLOG.md`, con condición de reapertura)

| Qué | Condición para volver al NORTE |
|---|---|
| Motores `sitemap` y `rastreo` | Una fuente registrada con esa vía y un consumidor nombrado (regla 23) |
| Diff semántico y estructural del DOF; watchers fuera del DOF | Un pedido cuya pregunta sea "qué cambió en X entre d1 y d2" |
| Resolución de entidades entre fuentes; casi-duplicados; linaje de afirmaciones | Un pedido que cruce dos fuentes sobre la misma entidad y falle por no reconocerla |
| Caza de contradicciones como flujo | Un pedido con `desired_evidence` que pida evidencia en contra |
| Explorador de capacidades como flujo | Un `CapabilityDemand` emitido por ZPPMND |
| Artefactos privados con alcance por cliente (§59–61) | Reconciliación del contrato |

Sacarlos de la lista no es rendirse: lo que no tiene consumidor es HIPÓTESIS de que hará falta, y las hipótesis no
ocupan lugar en el plan.

## 6. Para que no vuelva a pasar

Regla 28 (`docs/REGLAS.md`): un hueco entra al NORTE solo con su forma de cierre (A, B o C), su prueba mecánica y su
consumidor. La lista activa no excede cinco. Lo que no cabe va a `BACKLOG.md` con condición. La hace cumplir
`tests/test_norte.py` (pendiente: entra en su PR).

## 7. Decisiones del dueño

Las tres preguntas de este documento ya tienen respuesta en `ORDENES-RG.md` (decisiones cerradas del 2026-11-02): forma
B para el hueco 1 (sí, los siete adaptadores son `legacy`); los seis diferidos van a `BACKLOG.md` con su condición (sí);
y el alcance no se congela, se ordena por consumidor (reglas 21 y 23).
