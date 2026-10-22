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

"Cálculo" (valores oficiales para calcular: tipo de cambio, INPC, UDIS, tasas, salarios mínimos, UMA) se publica en el DOF y queda en la categoría `INDICADOR ECONOMICO`. Las NOM y sus proyectos también salen del DOF. Los valores mismos, serie por serie, llegan de las API de Banxico e INEGI (sección siguiente, en prueba).

## Indicadores para cálculo: Banxico SIE e INEGI BIE (`mx.banxico-sie`, `mx.inegi-bie`, en prueba)

Valores oficiales para calcular, tomados directo de la API de cada institución. Se guardan **tal como los sirve la
API**: sin cálculos, conversiones ni variaciones.

| Serie | Clave | Dónde está impresa la clave (leído el 2026-10-21) |
|---|---|---|
| Tipo de cambio FIX | `SF43718` | [catálogo de series de la API SIE](https://www.banxico.org.mx/SieAPIRest/service/v1/doc/catalogoSeries) ("Pesos por Dólar. FIX.") y [cuadro CF102](https://www.banxico.org.mx/SieInternet/consultarDirectorioInternetAction.do?accion=consultarCuadro&idCuadro=CF102&sector=6&locale=es) ("Fecha de determinación (FIX)", desde 12/11/1991) |
| UDIS | `SP68257` | [catálogo de series](https://www.banxico.org.mx/SieAPIRest/service/v1/doc/catalogoSeries) ("Valor de UDIS.") y el ejemplo de [metadatos](https://www.banxico.org.mx/SieAPIRest/service/v1/doc/consultaSeries) (desde 04/04/1995) |
| TIIE de fondeo a un día | `SF331451` | [cuadro CF101](https://www.banxico.org.mx/SieInternet/consultarDirectorioInternetAction.do?accion=consultarCuadro&idCuadro=CF101&sector=18&locale=es) ("TIIE de fondeo a un día", desde 02/01/2006) |
| TIIE a 28 días | `SF43783` | [cuadro CF101](https://www.banxico.org.mx/SieInternet/consultarDirectorioInternetAction.do?accion=consultarCuadro&idCuadro=CF101&sector=18&locale=es) ("TIIE a 28 días", desde 23/03/1995). El catálogo de la API lista además `SF60648` entre las series del servicio SOAP anterior; no aparece en los cuadros actuales y no se usa |
| INPC, índice general | `628194` | **HIPÓTESIS**: ninguna página oficial estática la imprime. Las páginas del INEGI se arman con JavaScript, y el constructor de consultas usa un token interno que no es nuestro. La primera corrida guarda la respuesta de `CL_INDICATOR`, el método oficial de catálogo, como evidencia |

- **Qué se guarda:** un registro por observación, en `banxico-sie/<serie>.jsonl` e `inegi-bie/<indicador>.jsonl`.
  `observation` lleva `date_printed`, `value_printed` y `unit_printed` exactamente como llegan. "N/E" se guarda tal
  cual, y los números se guardan como el texto de la respuesta, nunca como float. El título sale de la fuente: el
  `titulo` de Banxico o la `Description` del catálogo `CL_INDICATOR` de INEGI. La unidad es `unidad` en los metadatos de
  Banxico y `UNIT` en INEGI, tal como llega. No se guarda ningún cálculo derivado.
- **Crudo:** cada respuesta 200 de la API (metadatos, datos, `CL_INDICATOR`) se guarda byte por byte en el `RawStore`.
  Un registro que no cambia conserva el crudo que lo sirvió primero, y un valor revisado agrega una versión.
- **Rango:** cada corrida pide la historia completa. En Banxico va de la fecha inicial que imprime el cuadro oficial
  hasta hoy. En INEGI se pide `false` (serie histórica completa), porque la API no tiene rango de fechas.
- **Cuadre:** ninguna de las dos API imprime un total. Lo servido se cuenta en los bytes crudos, aparte del parser: una
  clave de fecha por observación (`"fecha"` en Banxico, `"TIME_PERIOD"` en INEGI). Ese conteo debe ser igual a los
  registros catalogados de la serie. Si no, sale con código 3. Así fallan cero observaciones, una fecha repetida o
  ilegible, una clave JSON repetida y una observación que la API dejó de servir.
- **Tokens:** `BANXICO_TOKEN` va solo a `www.banxico.org.mx`, en el encabezado `Bmx-Token`. `INEGI_TOKEN` va solo a
  `www.inegi.org.mx`, como el segmento de ruta que documenta INEGI.
  - El `Fetcher` recibe cada token atado a su host y se niega a mandarlo a otro, en un encabezado o en la URL, también
    tras una redirección.
  - Toda URL que se registra lleva `<token>` en su lugar. Una respuesta que contenga el token no se guarda.
  - El manifiesto y el log pasan por una redacción final.
  - Un token con algo más que letras, dígitos y guiones no se usa.
- **robots.txt:** `www.banxico.org.mx/robots.txt` responde 302 a `anterior.banxico.org.mx/robots.txt`.
  - El `Fetcher` sigue hasta 5 redirecciones de robots.txt dentro de la lista de hosts (RFC 9309 §2.3.1.2). Aplica esas
    reglas al primer host y deja la URL final en el manifiesto (`robots`). Una sexta redirección se lee como
    inalcanzable: todo queda prohibido.
  - Ese archivo repite grupos `User-agent: *` (`/dyn`, `/ALEPH`, `/V`), y ahora se combinan (RFC 9309 §2.2.1). La
    biblioteca estándar de Python se quedaba solo con el primero y dejaba pasar `/ALEPH` y `/V`.
  - INEGI permite `/app`.
- **Cortesía:** 5 peticiones a Banxico y 2 a INEGI por corrida, más robots. Es muy poco frente a los límites
  documentados de Banxico: 200 consultas históricas en 5 minutos y 80 de metadatos por minuto.
- **Derechos:** Banxico autoriza reproducir o usar su información si se cita la fuente y su dirección de Internet. INEGI
  permite copiar, distribuir y publicar sin alterar metadatos, con el crédito "Fuente: INEGI". Por eso
  `redistribution: allowed`, con la atribución en `license`.
- **Estado `trial`:** el formato de las respuestas se leyó en la documentación. Las fixtures de las pruebas llevan
  `CONSTRUIDO_DE_DOCS` en el nombre y son HIPÓTESIS hasta la primera corrida real.
  - Una fuente `trial` corre solo si se nombra en `--sources`; la corrida programada no la toca.
  - La corrida real se lanza con `gh workflow run indicadores-mx.yml`. Sube como artefacto los crudos, las filas y el
    manifiesto. Antes de subir, un paso busca los tokens en todo lo que se sube.
  - Con esos bytes, otro PR reemplaza las fixtures, confirma la clave de INEGI y pasa las fuentes a `active`.
  - Una prueba impide `active` mientras alguna serie no tenga `confirmed_by`.
- **HIPÓTESIS hasta la primera corrida real:**
  - la forma exacta de cada respuesta;
  - que Banxico sirva los días sin dato como "N/E", como en su ejemplo;
  - la clave `628194`, la fuente `BIE` (los ejemplos documentados usan `BISE`) y el área `00` de INEGI;
  - el formato de `TIME_PERIOD`.

## Normas Oficiales Mexicanas (NOM): linajes desde el DOF

Cada corrida escribe `mx/normas/nom.jsonl`: una línea por linaje (el código sin su año, p. ej. `NOM-137-SSA1`), con
todas las notas del DOF que lo nombran, ordenadas por fecha oficial. La etapa de cada nota (proyecto, consulta pública,
respuesta a comentarios, norma, aclaración, prórroga, cancelación…) sale de una tabla fija de aperturas del título;
sin coincidencia es `OTRO`. Las relaciones (`cancela`, `menciona`) se copian del propio título. No se calcula la
vigencia. El piso del DOF es 1993 (Ley Federal sobre Metrología y Normalización, 1992): SIDOF sirve esos días con el
mismo formato. Los textos de las notas que citan una NOM se descargan primero.

El código se lee tal como se imprime. La corrida 39691250207 encontró dos títulos reales que no se leían:
`PROY-NOM-020-SCT2/-2020` (`mx.dof:5638496`, dos separadores antes del año) y `PROY-NOM-016ENER2024`
(`mx.dof:5763083`, sin ningún separador). La forma sin separador se lee solo si el emisor es de puras letras, entre un
número de 2 o 3 dígitos y un año de 4: letras y dígitos no se mezclan, así que el corte es único. Un emisor que termina
en dígito (`SSA12024`: ¿SSA1 + 2024 o SSA + 12024?) no se adivina. Queda en la cobertura `titulos con NOM sin codigo
leido` y la corrida sale con código 3.

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
  (`source_repeated_rows`) y se queda la primera. Cada fila leída cae en una sola cuenta: filas leídas = registros
  distintos catalogados + repetidas + sin registro + sin rubro.
- **Filas que no se pueden citar:** una fila sin registro digital o sin rubro (vacío después de normalizar los
  espacios) no entra al catálogo. No hay con qué citarla ni con qué nombrarla, y nada se completa adivinando.
  - Se cuenta en `source_rows_without_registro` o en `source_rows_without_rubro`, una sola vez (primero el registro).
  - El manifiesto lleva hasta 20 ids de punto de Qdrant por cuenta (`source_rows_without_registro_point_ids`,
    `source_rows_without_rubro_point_ids`). No se guarda nada del contenido de la fila.
  - El tamaño del número de registro nunca se juzga: una fila con rubro y registro entra, sea cual sea su registro.
- **Corrida 39691250207 (2026-10-21):** 2,876 registros de esta fuente fueron a cuarentena con `title: '' should be
  non-empty`. Sus ids nativos se ven como `1`, `10`, `100`, `1000`, y uno está vacío (`mx.hf-tesis-scjn:`).
  - La cuarentena los quitaba del catálogo. Así, los registros distintos ya no cuadraban con los catalogados: cada
    corrida volvía a bajar los 3.6 GB y salía con código 4, y eso también detenía la cadena automática del catálogo.
  - Ahora esas filas se cuentan a la vista en el manifiesto; no se esconden ni se filtran por el tamaño del registro.
  - **HIPÓTESIS** hasta la próxima corrida completa: cuántas filas son y cómo se reparten entre sin rubro y sin
    registro. 2,876 es el número de ids distintos en cuarentena, y las filas con el mismo id (por ejemplo, todas las de
    registro vacío) se juntaban en uno solo.
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

## Tratados internacionales: vista derivada del DOF

Cada corrida escribe `mx/tratados/tratados.jsonl`, justo después del catálogo, sin tocar el sitio de la SRE (su reto
anti-bots no se rodea). Todo tratado vigente en México pasa por el DOF: el decreto del Senado que lo aprueba
("Decreto por el que se aprueba el Convenio…") y el decreto que lo promulga ("Decreto Promulgatorio del Tratado…").
- **Selección y etapa:** tabla fija de aperturas del título (`rg/catalog/tratados.py`): acto, artículo y una palabra de
  instrumento (Tratado, Convenio, Convención, Acuerdo, Protocolo, Enmienda). Etapas: `promulgacion`,
  `aprobacion_senado`, `enmienda`, `retiro_o_denuncia`, `fe_de_erratas`, `aclaracion`. Gana la apertura más larga
  seguida de un instrumento.
- **Nombre:** se copia del título, desde después del artículo hasta la cláusula de conclusión (", adoptado en",
  ", firmado en", ", hecho en", ", suscrito en"), o hasta el final sin el punto.
- **Agrupación y orden:** una línea por nombre exacto plegado (sin acentos, mayúsculas, espacios simples), con sus notas
  ordenadas por fecha oficial. No se calcula vigencia, no se adivinan partes y no se unen nombres distintos.
- **Chequeo independiente:** una regex más laxa ("decreto" con "promulgatorio" o con cláusula de conclusión) debe
  seleccionar exactamente los mismos títulos que la tabla. Cualquier diferencia, en un sentido o en el otro, queda en
  `coverage` (`mx.tratados`) y la corrida sale con código 3.
- La carpeta es una vista: `Catalog` nunca la lee como registros (`store.DERIVED`).

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
- INEGI (más allá del INPC): estadística y geografía; por ahora solo el INPC entra, en prueba.
- Tratados de la SRE: es una aplicación con JavaScript; falta revisar sus reglas.

Nada de esto se rodea: o se abre por la vía permitida o queda bloqueado con su causa.

## Agregar otro país

1. Crear `sources/<cc>.json` con sus fuentes oficiales: host permitido, licencia y categoría base.
2. Escribir un adaptador por *formato de sitio* (no por documento), con su conteo independiente para el cuadre.
3. Agregar fixtures reales y pruebas, y un flujo `catalog-<cc>.yml`.
