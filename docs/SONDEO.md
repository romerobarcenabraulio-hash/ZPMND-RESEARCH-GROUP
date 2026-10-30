# Sondeo del registro de fuentes

Braulio, 2026-10-30: el tablero tenía 200 de 234 subáreas "por medir"; las cifras las debe poner el dato, no la mano, y el
registro debe llegar al detalle (qué libros, qué bases de datos), de más a menos: RG mapea el mundo entero y ZPMND lo
recorta para cada cliente y país (campos `alcance` e `idiomas`).

**Registro** (`sources/registro/<letra>.json`, una familia de NORTE §3 por archivo). Cada fuente candidata dice su
subárea del tablero (`subarea`, A01..P99), su clase (libro, base de datos, API, catálogo, dataset, repositorio, portal
oficial, diario oficial, revista, video, foro, curso, documentación, registro), su editor, su URL base, sus hosts, su
alcance, sus idiomas y su licencia. Todo es candidato (`status: candidate`) hasta que el sondeo la alcanza. Las fuentes
de México que ya adquiere el catálogo viven en `sources/mx.json`; un id nombra una sola fuente en todo RG.

**Vía** (obligatoria): la ruta más rápida que ofrece la fuente, de mejor a peor: `volcado` (millones de registros en
una descarga), `api`, `sitemap`, `rastreo` (página por página) o `manual` (compra o persona). La adquisición se planea en
ese orden y el resumen del sondeo las cuenta por familia (Braulio, 2026-10-30: "extraer información mucho más rápido").
El registro incluye las clasificaciones oficiales que son el esqueleto del mapa: CIIU, CPC, NAICS y SCIAN (industrias y
productos), CIUO, ESCO, O*NET y SINCO (ocupaciones), M49 (países).

**Contador.** Solo si la fuente declara su tamaño en un lugar fijo: `json` (un número entero en una ruta de su respuesta
JSON, o con `medida: longitud` cuántos elementos tiene la lista en esa ruta) o, solo para índices de texto o XML sin JSON,
`contar` (cuántas veces aparece un texto fijo, por ejemplo `<rfc-entry>`, dentro de un documento que trae su `marca`, por
ejemplo `<rfc-index`). Una página que no es el documento esperado (mantenimiento, un reto) o un conteo de texto en cero es
`ilegible`, nunca un cero medido. Sin contador, el sondeo pide la URL base y guarda solo su respuesta HTTP (`accesible`
con un 200): acredita esa URL, no la obra; por eso cada libro apunta a su propia página, no a la portada del editor.
La corrida para de preguntar a los 40 minutos, guarda después de cada fuente y publica aunque se corte: lo que no alcanzó
queda `pendiente`.

**Corrida.** `sondeo.yml` cada lunes y a mano, con el código de `main`, sin secretos. Escribe `sondeo/<fecha>.json` y
`sondeo/ultimo.json` en la rama `sondeo`: por fuente, estado (`medido`, `accesible`, `http`, `rechazado`, `ilegible`,
`error`, `pendiente`), valor, unidad, URL, estado HTTP, bytes, sha256 y fecha; y un resumen por familia. Claude pasa esas cifras al
tablero (pestaña Desglose). Lo que pide llave (Banxico, INEGI, DENUE) llega en un PR aparte, con el secreto solo en su
paso.

**Crecer el registro** es solo datos: un PR por familia o grupo de familias, cada uno bajo el tope de lectura del revisor
GPT, que agrega fuentes con nombre (libros, bases, APIs, catálogos) y su contador cuando la fuente lo tiene.
