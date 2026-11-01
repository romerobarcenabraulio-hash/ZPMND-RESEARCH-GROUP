# Descubrimiento del mapa del mundo

Braulio, 2026-10-31: RG es de todo el mundo (cada país, cada industria, cada trabajo) y debe extraer información mucho
más rápido. El primer cuello es saber **dónde** publica cada país lo que necesitamos. Braulio conectó su API de
Perplexity; Perplexity encuentra, RG verifica.

**Mapa** (`sources/cobertura.json`). Los 193 Estados miembros de la ONU (lista oficial, cotejada el 2026-11-01, con sus
códigos ISO 3166-1) por las capas de los tres ejes por país del tablero: derecho (7 capas), estándares (2) y datos
públicos (3). Son 2,316 celdas. Cada capa trae su consulta fija, por ejemplo `{pais} official gazette`. Industrias
(CIIU) y ocupaciones (CIUO) vienen después, con sus propias capas.

**Búsqueda** (`python -m rg.descubrir buscar`). Una búsqueda por celda con la Search API de Perplexity
(`POST https://api.perplexity.ai/search`, documentación consultada el 2026-11-01): devuelve resultados rankeados (URL,
título, extracto, fecha), no una respuesta escrita por un modelo, así que no hay nada inventado que filtrar. Precio
publicado: $5 por cada 1,000 búsquedas con `search_type: web` y $1 con `fast`; el mapa completo cuesta unos $11.60 en
`web`. La consulta solo lleva el nombre del país y la redacción fija de la capa: ninguna pregunta de ZPMND sale de RG.
Un país empieza solo si todas las capas que le faltan caben en el tope de búsquedas y en el plazo. Una capa que ya
contestó se guarda y nunca se vuelve a pedir ni a pagar; un país con alguna capa fallida queda `completo: false` y la
siguiente corrida pide solo esas. Un 401, 402, 403 o 429 (llave rechazada, sin crédito, límite de uso) detiene la
corrida y escribe lo que ese país ya reunió (GPT en 698a5b7). Ningún archivo que contenga la llave se escribe, venga como venga (literal, escapada o unida al limpiar), y cada respuesta tiene un plazo para leerse entera. El push a la rama de datos se intenta tres veces; si falla las tres, se pierden los resultados de esa corrida y la siguiente vuelve a pagar a lo sumo esas búsquedas (GPT en cb11715: un mecanismo de recuperación más complejo abría más huecos de los que cerraba).

**Verificación** (`python -m rg.descubrir verificar`, sin llave). Los dos primeros candidatos de cada capa se piden una
vez con el `Fetcher` del catálogo: https, solo su host y su gemelo `www`, robots.txt, direcciones públicas, tope de
tamaño. Se guarda el estado HTTP, los bytes y el sha256 (`accesible` con un 200), nunca el contenido. Que una página
conteste no dice qué contiene: un candidato entra al registro (`sources/registro/`) por PR, con su vía y su licencia
leídas de la fuente, y una celda solo cuenta como cubierta cuando sus fuentes están cargadas y cuadradas con evidencia.

**Corrida.** `descubrir.yml` diario (120 búsquedas, unos $0.60, hasta terminar el mapa) y a mano (12 a 2,400 búsquedas;
2,316 recorren todo). Escribe `descubrimiento/<ISO3>.json` y `descubrimiento/resumen.json` (por capa: países buscados y
países con un candidato que contesta) en la rama `descubrimiento`.

**Tope de gasto.** El tope por corrida lo pone el código (2,400 búsquedas, unos $12 en `web`). El tope mensual real lo
pone Braulio en la consola de Perplexity (crédito sin recarga automática o un límite de gasto): RG no puede pasarlo.

**Límites conocidos.** Las consultas van en inglés con el país como filtro (`country`); un país que publica solo en su
idioma puede quedar mal servido y se revisa en el resumen. La API no informa el costo en su respuesta, así que el gasto
se cuenta por búsquedas pagadas (`busquedas` en la salida de cada corrida).
