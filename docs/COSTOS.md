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

**Runner propio (`scripts/runner_setup.sh`, `scripts/runner_controller.sh`).** Corrección medida el 2026-10-30: RG es
público y sus minutos de GitHub cuestan $0 netos (18,381 minutos del 25 al 29 de octubre, API de facturación por
repositorio); el excedente que motivó rentar el servidor era de un repositorio privado. En RG el runner propio ya no
ahorra dinero: lo que da son corridas de hasta 23 horas (en GitHub el job se corta a las 6), día y noche; cada corrida
tiene su propio plazo (1320 minutos el catálogo, 1300 el texto) para publicar lo que encontró antes de ese tope, y la
unidad de systemd del job se corta a las 24 horas por fuera de ambos. En GitHub siguen los 300 minutos y la cadena. Se enciende con
la variable del repo `CATALOG_RUNS_ON` = `["self-hosted","rg-catalog"]`; sin ella todo corre en GitHub. Es seguro por
construcción (GPT en 2308494 mostró que un runner que vive entre jobs y comparte usuario con ellos puede ser copiado y
reemplazado por un job comprometido, así que aquí ningún runner vive más que su job):
- no hay runner permanente: un servicio de root (`rg-runner.service`) pide a GitHub un runner just-in-time solo cuando ve
  en la cola un job de `catalog-mx.yml` o `texto-mx.yml` de `main`, lanzado por `schedule` o por despacho; ese runner
  toma un solo job y GitHub lo borra;
- cada job corre como `rgjob`, sin sudo, en una unidad de systemd propia, con una copia nueva del runner, una carpeta
  vacía y un home vacío; al terminar se matan sus procesos y se borran las dos carpetas: nada de un job llega al
  siguiente (ni un proceso, ni un venv, ni un `.pth`); si un proceso sobrevive, o si no se puede matar o comprobar que no
  queda ninguno, el servicio se detiene sin borrar ni empezar nada;
- el guardia de root rechaza cualquier otro job antes de su primer paso;
- el token (fino, solo este repositorio, Administration escritura y Actions lectura) vive en `/etc/rg/auth-header`, de
  root y oculto para la unidad; nunca va en una línea de comandos.
Se instala así: `runner_setup.sh`, `runner_controller.sh` y `runner_reach.sh`, bajados por el commit exacto de `main` y
comprobados por su sha256, corren como root en el servidor y piden el token sin mostrarlo; antes de encender nada el
instalador prueba que `rgjob` no entra a `/etc/rg` ni escribe el runner, el controlador, el guardia ni el servicio, y si
esa prueba no puede terminar, falla; luego se fija `CATALOG_RUNS_ON`; un despacho de
`catalog-mx` corre en el servidor y uno de cualquier otro flujo nunca recibe runner (y si lo recibiera, el guardia lo
rechaza).

**Siguiente recorte (PR #20):** la evidencia del auditor corre solo los mutantes de `main` que el PR quitó o cambió.
