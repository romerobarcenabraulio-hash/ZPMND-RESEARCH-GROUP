# Costos: dónde se gastan los minutos y cómo se recortan

Braulio, 2026-10-21: "siempre buscar dónde podemos reducir costos lo más posible". El costo es una entrada de diseño
permanente, igual que la seguridad: se mide, se recorta por construcción y nunca a costa de una compuerta.

**Medido (API de facturación, 2026-10-21):** plan Pro con 3,000 minutos de Actions incluidos. En octubre van 12,232
minutos y $49.98 de excedente, a ~$0.006 por minuto. Una corrida del catálogo de 4 horas cuesta ~$1.44.

| Gasto | Antes | Recorte |
|---|---|---|
| Mutación al empujar a `main` | 4 runners × ~7 min por merge | Solo en PRs: el head ya se probó ahí |
| Puesta al día manual | Alguien lanza cada corrida | `chain` relanza sola, con tope de 30 corridas y solo si quedó trabajo |

**`chain`.** Una corrida "deja trabajo" si su propio manifiesto (el que escribió después de empezar, nunca uno anterior)
dice `request budget reached`; eso cubre también el corte por tiempo (`--deadline-minutes`), que el `Fetcher` reporta
igual. El job `chain` solo tiene `actions: write`, despacha este mismo flujo desde `main` con una corrida menos, y no
corre si la corrida falló. Riesgo aceptado: si un despacho programado llega mientras una corrida encadenada espera, la
reemplaza y la cadena termina; la corrida programada sigue el trabajo. El job `run` solo corre en `main`.

**Runner propio (PR aparte).** El rastreo es casi todo espera y un servidor propio no cobra por minuto (Braulio renta
uno, 2026-10-21). Antes de usarlo hace falta endurecerlo por construcción: árbol del runner de root y solo lectura para el
usuario de los jobs, guardia de ejecución en un archivo de root, y actualizaciones verificadas. Va en su propio PR para no
mezclar ese riesgo con estos recortes.

**Siguiente recorte (PR #20):** la evidencia del auditor corre solo los mutantes de `main` que el PR quitó o cambió.
