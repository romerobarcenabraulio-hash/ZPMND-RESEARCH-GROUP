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
igual. El job `chain` solo tiene `actions: write` y despacha este mismo flujo desde `main` con una corrida menos. No
corre si la corrida se rompió: si truena (salida 1), si el escaneo encuentra un token o si falla la subida o el push (sin
`published`). Un hallazgo de datos (salida 3, cobertura; 4, cuarentena) sigue marcando la corrida en rojo y queda en su
manifiesto, pero ya no detiene la puesta al día: el 2026-10-27 un solo título de NOM sin código leído, entre 218,376
registros, la tenía parada desde el 21. Riesgo aceptado: si un despacho programado llega mientras una corrida encadenada espera, la
reemplaza y la cadena termina; la corrida programada sigue el trabajo. El job `run` solo corre en `main`.

**Runner propio (`scripts/runner_setup.sh`).** El rastreo es casi todo espera y un servidor propio no cobra por minuto
(Braulio renta uno en Vultr desde 2026-10-21). `catalog-mx.yml` y `texto-mx.yml` corren ahí cuando la variable del repo
`CATALOG_RUNS_ON` vale `["self-hosted","rg-catalog"]`; sin ella, en los runners de GitHub. Lo endurece el script, por
construcción:
- los jobs corren como el usuario `rg`, sin sudo y con contraseña bloqueada;
- el árbol del runner (`/opt/actions-runner`) es de root y de solo lectura para `rg`: ningún job puede cambiar el runner,
  su configuración ni el guardia; `rg` solo escribe su carpeta de trabajo, los logs y sus propios archivos de registro;
- un guardia de root (`/opt/rg/runner_guard.sh`) corre antes de cada job y lo rechaza si no es `catalog-mx.yml` o
  `texto-mx.yml` de `refs/heads/main`, lanzado por `schedule` o por despacho: una rama o un PR pueden traer su propia
  copia de un flujo que nombre las etiquetas del runner, y el guardia es lo que lo impide;
- el runner va fijado por versión y sha256, sin autoactualización: actualizarlo es correr el script otra vez con el pin
  nuevo (un PR);
- el token de registro (una hora) se pide sin mostrarlo y llega a `config.sh` por su entrada de entorno, nunca como
  argumento.
Se instala y se verifica así: el script, bajado por el commit exacto de `main` y comprobado por su sha256, corre como root
en el servidor; GitHub muestra el runner en línea; un despacho de `catalog-mx` corre ahí y uno de cualquier otro flujo es
rechazado por el guardia.

**Siguiente recorte (PR #20):** la evidencia del auditor corre solo los mutantes de `main` que el PR quitó o cambió.
