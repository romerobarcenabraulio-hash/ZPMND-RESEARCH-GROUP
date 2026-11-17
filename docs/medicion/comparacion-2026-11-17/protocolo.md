# Comparación RG contra investigación directa con un LLM · protocolo fijado el 2026-11-17

Directiva del dueño del 2026-11-17, §7: dos casos fuera del ámbito fiscal, criterios fijados antes de ver un
resultado. Este archivo no cambia después de la primera corrida; una corrección va como adenda fechada al final, sin
reescribir lo de arriba, y el informe dice qué resultados vio antes de escribirla.

## Casos

| Caso | Pedido | Qué pone a prueba |
|---|---|---|
| A · ingeniería | `requests/RR-2026-11-17-pgvector-indice.json` | documentación primaria, parámetros, restricciones, pruebas |
| B · operaciones | `requests/RR-2026-11-17-costo-inferencia-llm.json` | precios con fecha, fuentes comparables, cálculo reproducible |

## Brazos

Los tres reciben el mismo texto: `question` y `desired_evidence` del pedido.

- **A · directo.** Un LLM de la misma gama que el analista de RG (Claude Sonnet), en una sesión nueva con búsqueda y
  lectura web y nada más. Entrega una lista `{claim, url, quote}`, sus cálculos, desconocidos y limitaciones.
- **A+V · directo con la capa de verificación de RG.** La respuesta de A sin tocar. La capa baja cada URL una vez,
  guarda los bytes por su sha256 y quita la afirmación cuya cita no está tal cual en ellos. Usa el mismo comparador que
  la compuerta: mayúsculas, espacios y marcas de formato aparte.
- **RG.** `investigar.yml` con `discover` sobre el pedido en `main`, sin plan revisado a mano. Pasa por descubrimiento,
  descarga con sha256, extracción, analista, revisión, conciliación y compuerta. El paquete es su respuesta.

Los tres corren dentro de las mismas 24 horas, porque los precios del caso B cambian.

## Forma común antes de juzgar

Cada respuesta se lleva a la lista `{id, claim, url, quote}` sin cambiar una palabra. Los ids se barajan y el juez no
ve de qué brazo viene cada lista.

## Métricas

- **M1 · citas válidas.** Afirmaciones cuya cita está tal cual en su fuente, sobre afirmaciones con cita. En A, contra
  una bajada del día. En RG, contra los bytes que guardó y, aparte, contra una bajada del mismo día.
- **M2 · cobertura.** Puntos de la lista del caso (abajo) cubiertos por al menos una afirmación con cita válida que el
  juez dé por fiel, sobre el total de puntos.
- **M3 · errores.** Afirmaciones que el juez da por más amplias que su cita o contradichas por ella, más cálculos que
  no cuadran, sobre afirmaciones. Un cálculo no cuadra si difiere más de 1 % del que rehace un script con los precios
  citados y los supuestos escritos.
- **M4 · tiempo.** De la orden a la respuesta: el despacho hasta el PR del paquete, o el mensaje hasta la respuesta.
  La espera de una persona se cuenta aparte.
- **M5 · costo.** USD de las llamadas: en RG, el que imprime cada llamada en el registro del workflow; en A, los tokens
  de la sesión al precio de API publicado. Se informa también el costo marginal con suscripción.
- **M6 · reutilización.** Cinco sí o no:
  - bytes guardados con sha256;
  - fecha de consulta por fuente;
  - verificable más tarde sin volver a preguntar;
  - valida contra `schemas/research_packet.schema.json`;
  - otro pedido puede reusar las fuentes.
- **M7 · intervención humana.** Acciones de una persona hasta tener la respuesta: merges, comentarios, correcciones y
  re-despachos.

## Lista de cobertura

Caso A:

1. Compromiso entre HNSW e IVFFlat según la documentación primaria.
2. Parámetros de construcción de HNSW y sus valores por defecto.
3. Parámetro de consulta de HNSW y su efecto.
4. Guía de `lists` y `probes` de IVFFlat.
5. Cuándo crear cada índice respecto a los datos.
6. Memoria y paralelismo de la construcción.
7. Filtrado con un índice aproximado.
8. Dimensiones máximas indexables y tipos alternativos.
9. Criterio o benchmark para pasar a un motor dedicado, con la fuente marcada.
10. Pruebas: recall@10 contra búsqueda exacta, latencia p95, tiempo de construcción y memoria.
11. Recomendación para el escenario, con sus supuestos escritos.

Caso B:

1. Precio de entrada y de salida de dos modelos por proveedor, con cita y fecha.
2. Precio de caché por modelo, o que no existe.
3. Descuento por lotes por proveedor, o que no existe.
4. Por qué los modelos elegidos son comparables.
5. Cálculo mensual sin caché, reproducible.
6. Cálculo con caché, reproducible, con su supuesto de aciertos escrito.
7. Cálculo por lotes, donde exista.
8. Desconocidos declarados: mínimos de caché, vigencia y niveles por volumen.

## Juez

Un modelo en una sesión nueva, sin herramientas, con esta regla fija. Por afirmación da FIEL, MÁS_AMPLIA, CONTRADICE
o SIN_CITA frente a su cita. Por punto de la lista dice qué ids lo cubren.

HIPÓTESIS de sesgo: el juez es de la misma familia que los tres brazos. Un segundo juez de otra familia entra solo si
el dueño autoriza su llave; si no, queda como limitación. M1 y el cálculo no dependen de ningún juez.

## Regla de decisión, por función

- **La capa V vale** si en los dos casos M1(A+V) ≥ M1(A) + 0.15, o M3(A+V) ≤ M3(A) / 2.
- **El resto de RG vale sobre A+V** si, en los dos casos, se cumplen las tres condiciones:
  - M2(RG) ≥ M2(A+V) + 0.15, o M3(RG) ≤ M3(A+V) / 2;
  - M1(RG) ≥ M1(A+V) − 0.05;
  - M5(RG) ≤ 5 × M5(A+V).
- **Lo que se recomienda según el resultado:**
  - si vale RG: conservarlo para investigación compleja o reutilizable;
  - si solo vale V: lo directo con V para consultas puntuales, y retirar o delegar el resto;
  - si no vale ninguna: delegar al proveedor.
- **Un caso de cada lado:** EVIDENCIA INSUFICIENTE para esa función. Con dos casos el resultado es un indicio, no una
  prueba general.

## Lo que este protocolo no decide

Qué promueve ZPMND-FINAL ni si un paquete es verdad: pasar los validadores lo hace bien formado, no cierto
(`RESEARCH_CONTRACT.md` §3).
