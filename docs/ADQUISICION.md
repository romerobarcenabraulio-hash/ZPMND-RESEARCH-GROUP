# Adquisición declarativa (contrato)

Primer hueco de diseño del estado verificado (docs/NORTE.md, 2026-10-31): RG eran dos sistemas, el catálogo de México con
un adaptador en código por fuente y `investigar` para una pregunta a la vez. Este contrato es el puente: **una fuente se
carga por lo que declara en el registro, sin código propio.** Se acepta cuando una fuente nueva de cada vía entra sin
escribir una línea y cuando uno de los adaptadores de México se vuelve solo configuración.

## Qué declara una fuente

En `sources/registro/<letra>.json` (y, al migrar, en `sources/mx.json`), además de lo que ya pide el sondeo, un bloque
`adquisicion` con la forma de `schemas/adquisicion.schema.json`. `rg/sondeo.py` lo valida al cargar el registro: la forma,
que su `via` sea la de la fuente y que cada URL del bloque vaya a uno de sus `allowed_hosts`.

| Vía | Para qué | Lo que declara |
|---|---|---|
| `volcado` | Una descarga trae millones de registros: lo más rápido | `archivos` (URL, formato, compresión, checksum) o un `indice` que los lista (se toman los enlaces que terminan en un `sufijo` fijo); dónde está cada registro y su identificador nativo; tope de bytes |
| `api` | La fuente pagina sus registros | URL, tipo de paginación (cursor, página, desplazamiento), dónde están los registros y el siguiente cursor, `max_paginas` obligatorio |
| `sitemap` | La fuente lista sus páginas | URL del sitemap, `prefijo` de las páginas que cuentan, `max_urls` |
| `rastreo` | No hay nada de lo anterior | Semillas, `prefijo` del que nunca se sale, profundidad (máximo 5), `max_paginas` |
| `manual` | Compra o persona | Quién y qué |

Todas declaran `frecuencia` y pueden declarar `licencia_url`: la página de licencia o términos se baja con la fuente y
se guarda junto a su crudo (hueco 2: la licencia leída de la fuente, no supuesta).

## Lo que cada motor garantiza (cuando se construya)

- **El Fetcher de siempre** (`rg/catalog/fetch.py`): https, los hosts de la fuente, robots.txt, solo direcciones
  públicas, presupuesto, tope de tamaño y la pausa por host compartida de la corrida.
- **Robots manda sobre la vía.** Si robots prohíbe la ruta declarada, la fuente queda `bloqueada_por_robots` y hay que
  declarar otra vía (el sondeo del 2026-10-31 lo mostró: NCBI prohíbe E-utilities a robots, y PubMed se carga por su
  volcado `baseline`). Nunca se rodea.
- **Crudo primero** (§6): cada archivo o página al `RawStore` por su sha256, con la URL, la fecha, los encabezados y su
  checksum declarado comprobado. Un checksum que no cuadra es un fallo de esa fuente, no de la corrida.
- **Archivos hostiles**: la descompresión con los topes de T12 (tamaño por miembro y por corrida, sin rutas fuera del
  destino, sin enlaces); XML sin entidades externas ni expansión (el nombre del `elemento` ya no admite `<!`); un cursor
  que se repite o un `max_paginas` alcanzado terminan esa fuente con su motivo.
- **Cuadre**: cada corrida compara los registros leídos con lo que la fuente declara en el sondeo; la diferencia queda en
  el manifiesto, como hoy el cuadre por fuente del catálogo.
- **Plazo y guardado** como el sondeo: plazo propio menor al del job, guardado tras cada archivo o página, publicación
  aunque se corte.

## Motor `api` (rg/adquirir.py, workflow adquirir.yml)

Construido el 2026-11-01. Además de lo de arriba, la vía `api` admite:
- `paginacion.inicio`: el primer valor del cursor (OpenAlex: `*`). Sin él, una página empieza en 1 y un offset en 0.
- `credencial.secreto`: el nombre de un secreto del repo que el workflow pone en el entorno de un solo paso. La llave
  viaja solo en el encabezado `Authorization: Bearer`, solo al host de `url` (el Fetcher se niega a mandarla a otro), y
  nunca va en una URL, un manifiesto ni un mensaje. Una página que la contenga se rechaza entera. Sin la llave declarada
  no se pide nada.
Cada fuente termina en `completo` solo si llegó a su última página y sus registros distintos son los que declara su
`contador` (`no_cuadra` si difieren, `sin_conteo` si no declara tamaño). Cualquier otro final dice su motivo
(`max_paginas`, `cursor repetido`, `ilegible`, `bloqueada_por_robots`, `pendiente` al plazo). Los registros y el
manifiesto van a la rama `adquisicion`; las páginas crudas, al artefacto de la corrida (90 días), con su sha256 en el
manifiesto. Primer uso: la clasificación de OpenAlex (dominios, campos, subcampos, temas), que el registro declara en
`sources/registro/I.json`.

## Orden de construcción

1. `volcado` (más conocimiento por hora), probado con fuentes reales que ya publican volcados (índice de RFC, licencias
   SPDX, baseline de PubMed).
2. `api`, probado con OpenAlex o Crossref.
3. `sitemap`, y luego migrar un adaptador de México (Leyes Federales de la Cámara de Diputados) a pura configuración.
4. `rastreo`, el último y el más acotado.

Cada motor es un PR bajo el tope de lectura del revisor, con sus fixtures, sus pruebas de comportamiento y sus mutantes.
