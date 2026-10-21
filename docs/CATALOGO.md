# Catálogo por país (México primero)

El catálogo extrae información oficial pública por país. La guarda **cruda**, **categorizada** y **ordenada**, y **nunca la resume ni la interpreta**. Es la etapa RAW → CLASIFICADO del handoff (§22); ZPMND decide qué se verifica y qué se promueve.

## Qué se extrae hoy (México, tier 1)

| Fuente | Qué es | Cómo se categoriza | Crudo |
|---|---|---|---|
| `mx.dof` (SIDOF, SEGOB) | Diario Oficial de la Federación, nota por nota | estructura oficial del día: edición, sección, poder, dependencia; tipo de documento con tabla fija sobre el título | HTML oficial de cada nota (`/notas/docFuente/<id>`) |
| `mx.leyes-federales` (Cámara de Diputados) | Constitución, leyes y códigos federales vigentes y abrogados | listado oficial: fechas impresas, estado impreso (VIGENTE/ABROGADO), historial de reformas | PDF del texto vigente (columna "TEXTO VIGENTE") |
| `mx.reglamentos-federales` (Cámara de Diputados) | Reglamentos de leyes federales | igual que las leyes | PDF del texto vigente |
| `mx.ojn-estatal` (Orden Jurídico Nacional, SEGOB) | Legislación de las 32 entidades, por poder | tipo oficial impreso por la fuente, poder, entidad, fechas, estatus de la ficha | documento oficial (mayormente .doc) |
| `mx.hf-tesis-scjn` (**fuente secundaria**, dataset de Hugging Face) | Tesis aisladas y jurisprudencia del Semanario Judicial de la Federación | lo que imprime cada tesis: época, instancia, materias, número de tesis, tipo (tabla fija), fecha de publicación impresa | el archivo del dataset (JSON de 3.6 GB), verificado contra su sha256 |

"Cálculo" (valores oficiales para calcular: tipo de cambio, INPC, UDIS, tasas, salarios mínimos, UMA) se publica en el DOF y queda en la categoría `INDICADOR ECONOMICO`. Las NOM y sus proyectos también salen del DOF.

## Normas Oficiales Mexicanas (NOM): linajes desde el DOF

Cada corrida escribe `mx/normas/nom.jsonl`: una línea por linaje (el código sin su año, p. ej. `NOM-137-SSA1`), con
todas las notas del DOF que lo nombran, ordenadas por fecha oficial. La etapa de cada nota (proyecto, consulta pública,
respuesta a comentarios, norma, aclaración, prórroga, cancelación…) sale de una tabla fija de aperturas del título;
sin coincidencia es `OTRO`. Las relaciones (`cancela`, `menciona`) se copian del propio título. No se calcula la
vigencia. El piso del DOF es 1993 (Ley Federal sobre Metrología y Normalización, 1992): SIDOF sirve esos días con el
mismo formato. Los textos de las notas que citan una NOM se descargan primero.

## Tesis de la SCJN: fuente secundaria (`mx.hf-tesis-scjn`)

El Semanario de la SCJN responde 403 a robots.txt y no se rodea. Mientras tanto las tesis entran desde el dataset
`ayaxrojo/tesis_scjn_v5_complete` de Hugging Face (CC-BY-4.0, con acceso condicionado). Es una fuente **secundaria**:
cada registro lleva su procedencia (`source_type: dataset`, `role: secondary` en el registro de fuentes) y se coteja con
la SCJN cuando la fuente primaria abra.

- **Acceso:** el token de solo lectura `HF_TOKEN` es un secreto del repo. Llega al paso del catálogo como variable de
  entorno y el `Fetcher` lo manda solo a `huggingface.co`. La redirección firmada a `us.aws.cdn.hf.co` va sin token, y
  su firma nunca se escribe en el manifiesto. Los dos hosts pasan por robots.txt: `huggingface.co` permite todo y
  `us.aws.cdn.hf.co` no publica robots.txt (404) (revisado el 2026-10-21).
- **Descarga:** un solo archivo JSON de 3,638,883,446 bytes. Es una exportación de Qdrant y trae un vector de 4096
  números por tesis. Se baja a disco por partes y se compara con el sha256 que publica la API del Hub. Se vuelve a bajar
  solo si cambia ese sha256 o si falta en el catálogo alguna tesis que produjo.
- **Lectura:** el archivo se lee como flujo, una tesis a la vez, y los campos se copian tal cual: registro digital →
  `native_id`, rubro → `title`, época → `edition`, materias → `section`, instancia → `issuer`, número de tesis →
  `list_marker`, tipo → `type_printed`. `doc_type` sale de una tabla fija sobre el tipo impreso (Aislada, Jurisprudencia;
  otro = OTRO). La única fecha es la impresa en "Esta tesis se publicó el …". Las de la Novena Época solo traen mes y
  año, así que quedan sin fecha.
- **Cuadre:** el `total_points` del propio archivo (59,678) debe ser igual a las filas leídas. Además, los registros
  digitales distintos deben ser iguales a los catalogados con ese archivo. Una fila repetida en la fuente se cuenta
  (`source_repeated_rows`) y se queda la primera.
- **Partición:** las ~60 mil tesis se guardan en `hf-tesis-scjn/<registro // 10000>.jsonl`. Un solo archivo pasaría el
  límite de 100 MB de GitHub.
- **Qué no se usa:** las estadísticas de la ficha del dataset no coinciden con las filas (las filas muestreadas son de
  la Novena y la Décima Época). Solo se usan las filas.

## Reglas que no se negocian

- **Sin LLM.** Las categorías se copian de la estructura de la fuente o salen de una tabla fija (`rg/catalog/categorize.py`). Lo que no coincide es `OTRO`; nunca se adivina.
- **Cuadre de cobertura en cada corrida.** Lo extraído se compara contra un conteo independiente de la misma página: la clase oficial de nota en el DOF, todos los PDF del listado de Diputados, el total que imprime el OJN. Si no cuadra, la corrida sale con código 3 y la falla queda en el manifiesto. Así se encontraron cuatro defectos el 2026-10-19:
  - un día sin pestañas de edición (0 de 107 notas extraídas);
  - leyes con título que no empieza con "LEY" (Ordenanza, Presupuesto);
  - un reglamento cuyo "texto vigente" era en realidad una versión histórica;
  - filas abrogadas que se saltaban.
- **Esquema en cada registro** (`schemas/catalog_entry.schema.json`). Un registro inválido va a cuarentena: se lista en el manifiesto, conserva su última fila válida si la tenía, el resto se escribe y la corrida sale con código 4.
- **Fetcher con guardas** (`rg/catalog/fetch.py`):
  - solo hosts de la lista de cada fuente;
  - TLS verificado;
  - robots.txt respetado;
  - al menos 1 s entre peticiones por host, o el Crawl-delay del sitio si es mayor;
  - redirecciones solo dentro de la lista;
  - tope de tamaño y presupuesto de peticiones por corrida y por fuente.
- **Dónde corre.** En local, en la red aislada (`substrate/runtime`, servicio `catalog`): sale solo por el proxy, que bloquea direcciones internas. La corrida programada corre en un runner de GitHub con las mismas guardas del `Fetcher`, sin token de escritura en disco mientras lee páginas.
- **Datos personales:** los avisos judiciales y generales del DOF (edictos, convocatorias de particulares) quedan solo como metadatos, sin crudo.
- **Derechos:** los textos legislativos, reglamentarios, administrativos y judiciales no tienen protección de derecho de autor (LFDA art. 14 fr. VIII). Las normas privadas con derechos (ISO, NMX de venta) quedan solo como metadatos.

## Dónde quedan los datos

- Catálogo: rama `catalog` del repo, carpeta `mx/`:
  - `dof/<año>.jsonl`, `leyes-federales.jsonl`, `reglamentos-federales.jsonl`, `ojn-estatal/<clave INEGI>.jsonl`;
  - `INDEX.md` e `index.json` con conteos por categoría;
  - `ARBOL.md` y `arbol.json`: la vista para navegar, **país → ámbito → estado → municipio → poder → dependencia → tipo**,
    con conteos. Un nivel que la fuente no publica aparece como "(sin dato en la fuente)": el OJN no da la dependencia
    estatal y los municipios todavía no se recolectan;
  - `runs/<id>.json` con el manifiesto de cada corrida;
  - `_state.json` con lo ya indexado, para que cada corrida sea incremental.
- Crudos: release `raw-mx`, un `.tar` por corrida con los archivos nuevos. Las rutas son direcciones por contenido (`sha256/<2>/<sha256>.<ext>`), así que el hash es la ruta.
- Cada registro lleva url, fecha de recuperación, sha256, tamaño, tipo, licencia y la ruta de su crudo. Las versiones de leyes y ordenamientos estatales se acumulan; nunca se borran.

## Programación

`.github/workflows/catalog-mx.yml` corre cada 3 días a las 05:00 de la Ciudad de México. Antes de tocar una fuente corre las pruebas. Escribe solo la rama de datos y el release: el bot nunca toca el código.

En cada corrida:
- **DOF:** vuelve a leer los últimos 3 días (por notas tardías) e indexa hacia atrás hasta el piso configurado (`backfill_floor`).
- **Leyes y reglamentos:** usa descarga condicional por ETag; lo que no cambió no se baja.
- **OJN:** relista los 32 estados y vuelve a bajar lo que cambió de fecha de última reforma.

## Fuentes registradas que esperan (tier 2) y por qué

Están en `sources/mx.json` con su causa observada:
- datos.gob.mx: robots prohíbe `/api/`.
- SCJN: robots responde 403. Mientras tanto, las tesis entran por la fuente secundaria `mx.hf-tesis-scjn`.
- Catálogo de NOM: el dominio ya no resuelve; las NOM se cubren desde el DOF.
- CONAMER: robots responde 403 y el dominio no resuelve.
- Periódicos oficiales estatales y congresos locales: 32 formatos distintos.
- INEGI y Banxico: requieren token, que es decisión de Braulio.
- Tratados de la SRE: es una aplicación con JavaScript; falta revisar sus reglas.

Nada de esto se rodea: o se abre por la vía permitida o queda bloqueado con su causa.

## Agregar otro país

1. Crear `sources/<cc>.json` con sus fuentes oficiales: host permitido, licencia y categoría base.
2. Escribir un adaptador por *formato de sitio* (no por documento), con su conteo independiente para el cuadre.
3. Agregar fixtures reales y pruebas, y un flujo `catalog-<cc>.yml`.
