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

"Cálculo" (valores oficiales para calcular: tipo de cambio, INPC, UDIS, tasas, salarios mínimos, UMA) se publica en el DOF y queda en la categoría `INDICADOR ECONOMICO`. Las NOM y sus proyectos también salen del DOF. Los valores mismos, serie por serie, llegan de las API de Banxico e INEGI, las dos activas (sección siguiente).

## Indicadores para cálculo: Banxico SIE (`mx.banxico-sie`) e INEGI BIE (`mx.inegi-bie`), activas

Valores oficiales para calcular, tomados directo de la API de cada institución. Se guardan **tal como los sirve la
API**: sin cálculos, conversiones ni variaciones.

| Serie | Clave | Dónde está impresa la clave (leído el 2026-10-21) |
|---|---|---|
| Tipo de cambio FIX | `SF43718` | [catálogo de series de la API SIE](https://www.banxico.org.mx/SieAPIRest/service/v1/doc/catalogoSeries) ("Pesos por Dólar. FIX.") y [cuadro CF102](https://www.banxico.org.mx/SieInternet/consultarDirectorioInternetAction.do?accion=consultarCuadro&idCuadro=CF102&sector=6&locale=es) ("Fecha de determinación (FIX)", desde 12/11/1991) |
| UDIS | `SP68257` | [catálogo de series](https://www.banxico.org.mx/SieAPIRest/service/v1/doc/catalogoSeries) ("Valor de UDIS.") y el ejemplo de [metadatos](https://www.banxico.org.mx/SieAPIRest/service/v1/doc/consultaSeries) (desde 04/04/1995) |
| TIIE de fondeo a un día | `SF331451` | [cuadro CF101](https://www.banxico.org.mx/SieInternet/consultarDirectorioInternetAction.do?accion=consultarCuadro&idCuadro=CF101&sector=18&locale=es) ("TIIE de fondeo a un día", desde 02/01/2006) |
| TIIE a 28 días | `SF43783` | [cuadro CF101](https://www.banxico.org.mx/SieInternet/consultarDirectorioInternetAction.do?accion=consultarCuadro&idCuadro=CF101&sector=18&locale=es) ("TIIE a 28 días", desde 23/03/1995). El catálogo de la API lista además `SF60648` entre las series del servicio SOAP anterior; no aparece en los cuadros actuales y no se usa |
| INPC, índice general | `910392` | La [nota del INEGI en el DOF del 09/10/2026](https://sidof.segob.gob.mx/notas/docFuente/5800864) imprime el INPC de septiembre (146.075) y agosto (145.462) de 2026, con base en la segunda quincena de julio de 2018=100. Esta clave sirve esos mismos valores (`146.07499999999999000000`, `145.46199999999999000000`). Se pide con la fuente `BIE-BISE`: con `BIE` o `BISE` la API responde 400. La clave anterior, `628194`, sirve los mismos valores hasta 2024/07 y ahí termina |

- **Qué se guarda:** un registro por observación, en `banxico-sie/<serie>.jsonl` e `inegi-bie/<indicador>.jsonl`.
  `observation` lleva `date_printed`, `value_printed` y `unit_printed` exactamente como llegan. "N/E" se guarda tal
  cual, y los números se guardan como el texto de la respuesta, nunca como float. El título sale de la fuente: el
  `titulo` de Banxico; en INEGI, el título copiado de la nota oficial que confirmó la clave, porque `CL_INDICATOR` (el
  método de catálogo) responde 401 a nuestro token y no se pide. La unidad es `unidad` en los metadatos de
  Banxico y `UNIT` en INEGI, tal como llega. No se guarda ningún cálculo derivado.
- **Crudo:** cada respuesta 200 de la API (metadatos y datos) se guarda byte por byte en el `RawStore`.
  Un registro que no cambia conserva el crudo que lo sirvió primero, y un valor revisado agrega una versión.
- **Rango:** cada corrida pide la historia completa hasta hoy. En Banxico va de la fecha inicial que imprime el cuadro
  oficial hasta hoy. En INEGI se pide `false` (serie histórica completa), porque la API no tiene rango de fechas.
  - Banxico publica algunos valores antes de su fecha. En la corrida real, `fechaFin` de los metadatos era el
    25/10/2026 para las UDIS y el 22/10/2026 para la TIIE a 28 días, y se pidió hasta el 21/10/2026. Esos valores
    entran en una corrida posterior; no se pierden.
  - PROPUESTA: pedir hasta `fechaFin` cuando sea posterior a hoy.
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
- **Estado:**
  - `mx.banxico-sie` es `active` desde la corrida real 39709378896. La corrida programada (`catalog-mx`, cada 3 días)
    la pide.
  - `BANXICO_TOKEN` llega solo a dos pasos de `catalog-mx`: el del catálogo y un escaneo que busca el token en `data` y
    `raw` antes de subir crudos y de hacer commit. Si lo encuentra, o no puede leer una carpeta, no se sube nada.
  - `mx.inegi-bie` sigue `trial`. Corre solo si se nombra en `--sources` (workflow `indicadores-mx`), e `INEGI_TOKEN`
    nunca llega a `catalog-mx`.
  - Una fuente `trial` pasa a `active` solo con bytes reales. Sus fixtures `CONSTRUIDO_DE_DOCS` se reemplazan por los
    crudos de una corrida real, y una prueba impide `active` mientras quede alguna. Otra prueba impide `active`
    mientras alguna serie no tenga `confirmed_by`.
  - La corrida real se lanza con `gh workflow run indicadores-mx.yml`. Sube como artefacto los crudos, las filas y el
    manifiesto. Antes de subir, un paso busca los tokens en todo lo que se sube.
- **Confirmado con bytes reales (Banxico):** la forma de cada respuesta, y que los días sin dato llegan como "N/E"
  (en SF43783).
- **HIPÓTESIS (INEGI, todavía sin bytes reales):**
  - la clave `628194`, la fuente `BIE` (los ejemplos documentados usan `BISE`) y el área `00`;
  - el formato de `TIME_PERIOD`.

### Primera corrida real (2026-10-22)

Workflow `indicadores-mx`, corrida 39709378896 (2026-10-22 02:06 UTC, artefacto `indicadores-mx-39709378896-1`).

**Banxico cuadra completo.** En cada serie, las observaciones servidas son iguales a las catalogadas:

| Serie | Servidas = catalogadas | "N/E" | Unidad servida |
|---|---|---|---|
| `SF43718` (FIX) | 8,783 | 0 | Pesos por Dólar |
| `SP68257` (UDIS) | 11,524 | 0 | Unidades de Inversión |
| `SF331451` (TIIE de fondeo) | 5,231 | 0 | Porcentajes |
| `SF43783` (TIIE a 28 días) | 7,943 | 200, del 24/03/1995 al 27/03/1996 | Sin Unidad |

- En total fueron 33,481 observaciones y ninguna quedó en cuarentena.
- Se guardaron 5 crudos (metadatos y 4 series, 1,338,609 bytes) con 7 peticiones a Banxico: robots.txt con su 302,
  metadatos y una por serie.

**Lo que los bytes reales cambiaron frente a las fixtures construidas:**
- El FIX (`SF43718`) no trae "N/E", porque la API sirve solo días hábiles. El ejemplo de la documentación sí los
  traía. "N/E" aparece solo en `SF43783` y se guarda tal cual.
- El JSON llega compacto. Todo `dato` es texto JSON (4 decimales; las UDIS, 6), nunca número. `parse_float=str` queda
  como guarda por si una respuesta trae números.
- Los metadatos llegan en su propio orden (`SP68257` primero), no en el pedido, y traen además `versionada`. La unidad
  se toma por `idSerie`, nunca por posición.
- Los títulos son los de la API, no los del cuadro:
  - `SF43718` trae 42 espacios seguidos entre "Tipo de cambio" y "Pesos por dólar", y se guarda tal cual;
  - `SF331451` es "TIIE de Fondeo a Un Día Hábil Bancario, Mediana ponderada por volumen";
  - `SF43783` es "TIIE a 28 días Tasa de interés en por ciento anual".
- El parser no tenía supuestos equivocados. Lo equivocado estaba en las fixtures construidas: "N/E" en el FIX, títulos
  con un solo espacio, JSON con sangría y metadatos en el orden pedido.

**Fixtures de Banxico ahora.** Son dos archivos copiados sin editar del crudo de esa corrida. Una prueba fija su sha256:
- `banxico_sie_metadatos_2026-10-22.json`: 1,058 bytes, sha256 `6a05641d…71268c4`.
- `banxico_sie_datos_SF43783_2026-10-22.json`: 311,383 bytes, sha256 `d98bcf18…e40a3d`. Se eligió `SF43783` porque es
  la única respuesta real con "N/E".

**Tamaño en el catálogo.**
- Las 4 series ocupan unos 61 MB de `.jsonl`. La mayor, `SP68257.jsonl`, pesa 20.5 MB, por debajo del límite de
  100 MB por archivo de GitHub.
- Cada corrida baja la historia completa: unos 1.34 MB de crudo por corrida en `raw-mx`.
- HIPÓTESIS: si las respuestas cambian en cada corrida (un dato nuevo al día), son unos 160 MB al año.

**Pendiente para el dueño (INEGI).**
- `CL_INDICATOR` respondió HTTP 401 "No autorizado" (ErrorCode 110).
- `INDICATOR/628194` respondió HTTP 400 "No se encontraron resultados" (ErrorCode 100).
- No se guardó nada y la fuente sigue `trial`.
- HIPÓTESIS: el 401 apunta al token. El 400 puede venir del mismo token o de la combinación clave `628194`, fuente
  `BIE` y área `00`.
- Acción: volver a poner el secreto `INEGI_TOKEN` y correr
  `gh workflow run indicadores-mx.yml -f sources=mx.inegi-bie`.

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

Cuando el catálogo llegó a 1993 (corrida del 2026-10-29) aparecieron 88 títulos con impresiones viejas. Una tercera rama
las lee solo si traen un rasgo viejo, así que nunca lee lo que ya lee la primera:
- año de dos dígitos de los noventa: `NOM-051-SSA1-93` es 1993, y ningún otro año de dos dígitos se lee;
- espacio en vez de guion: `NOM-EM-004 FITO-1994`;
- último carácter del emisor tras un espacio: `SSA I` queda como `SSAI`, nunca `SSA1`;
- número de cuatro dígitos: `NOM-1811-SCFI-1993`;
- espacio tras la barra: `NOM-025/ 1-NUCL-2000`.

Sobre los 844,383 títulos del DOF, ningún código ya leído cambió y se leen 81 más. Los 7 que no traen año o emisor
(`NOM-034-STPS`, `PROY-NOM-013-2004`…) quedan en `REVIEWED`, cada uno con el sha256 de su título.

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
- Texto de los crudos: manifiesto en `mx/texto/` (un estado por crudo) y textos en el release `text-mx`. Lo produce el flujo manual `texto-mx.yml`; formatos, estados y la brecha de OCR están en [TEXTO.md](TEXTO.md).
- Cada registro lleva url, fecha de recuperación, sha256, tamaño, tipo, licencia y la ruta de su crudo. Las versiones de leyes y ordenamientos estatales se acumulan; nunca se borran.

## Base de datos (Postgres en Supabase: `rg/catalog/db.py`, flujo `db-mx.yml`)

El catálogo también vive en una base de datos Postgres (Supabase, plan Pro, contratado por Braulio el 2026-10-29), en el
esquema `catalogo`. Se carga en un runner de GitHub tras cada corrida del catálogo, o a mano (`gh workflow run db-mx.yml`),
desde la rama `catalog`. Se reconstruye entera cada vez: las filas de la rama siguen siendo el registro y la base es una
vista de ellas que cualquier agente o app puede consultar.

Cómo está organizada:
- `documento`: un renglón por documento oficial (nota del DOF, ley, reglamento, ordenamiento estatal, tesis), con sus
  coordenadas: país, ámbito, estado, municipio, poder, dependencia y tipo; sus fechas y su estado impreso; su url y su
  crudo. `listing` va entero como JSON. `titulo_busqueda` es el título sin acentos para buscar
  (`to_tsvector('simple', titulo_busqueda)`); nunca se lee de regreso como dato.
- `fuente`: las fuentes registradas en `sources/mx.json`, con su estado, licencia y redistribución.
- `version`: cada versión de texto recuperada de un documento. `observacion`: cada valor de indicador como lo sirvió
  la API (texto, nunca número).
- `nom`, `nom_nota`, `nom_relacion`: cada NOM con sus notas por etapa y sus relaciones (`cancela`, `menciona`).
  `tratado`, `tratado_nota`: cada tratado con sus decretos por etapa.
- `corrida`, `cobertura`: el manifiesto de cada corrida y sus cuadres.
- `arbol`: la vista de conteos por nivel.

Nada se calcula ni se clasifica al cargarla: cada columna se copia de una fila, de una vista o de un manifiesto. Un
campo nuevo del esquema que no tenga columna detiene la carga (una prueba fija que cada campo tiene lugar).

Se carga en un esquema aparte (`catalogo_nuevo`) y entra en vivo, en una sola transacción, solo si pasan estos chequeos;
si no, el catálogo en vivo se queda como estaba, el cargado queda como `catalogo_rechazado` para revisarlo y la corrida
sale en rojo (código 3):
- **Cuenta independiente:** renglones por fuente en la base contra líneas por fuente en disco, contadas sin parsear
  ninguna fila; ningún `entry_id` repetido.
- **Ida y vuelta:** cada fila en disco contra la entrada que la base devuelve para su id (por huella sha256). Un campo
  ausente y uno nulo se leen igual ("sin dato en la fuente").
- **Vistas completas:** cada tabla de NOM, tratados, corridas y cobertura tiene los renglones que su vista declara.
- **Referencias:** ninguna nota, versión u observación apunta a un documento que falte, y ningún documento ni cuadre
  de cobertura es de una fuente sin registrar (un cuadre sin fuente cuenta como "(sin fuente)").
- **Nunca menos:** ninguna fuente tiene menos renglones que en el catálogo en vivo (las filas solo crecen; un checkout
  parcial o un archivo truncado se rechaza). Una carga sin una sola fila ni siquiera toca la base (GPT en 358b5d8).

**Lectores.** El rol `zppmnd_lectura` (pedido de ZPPMND, 2026-10-29) entra con contraseña y solo puede hacer `SELECT`
sobre `catalogo`: sin otros esquemas, sin escritura, sin crear nada, sesiones de solo lectura con límite de 60 s por
consulta y 5 a la vez. Sus permisos se dan sobre el esquema nuevo antes del intercambio, así que ninguna carga se los
quita, y nunca sobre `catalogo_rechazado`. `modo: lector` del flujo crea o actualiza el rol con `RG_LECTURA_PASSWORD`
(la contraseña viaja a la base solo como su verificador SCRAM) y corre su prueba de aceptación como el propio rol: un
`SELECT` a `catalogo` funciona, un `INSERT` falla y un `SELECT` a otro esquema falla. Límite: como todo rol de
Postgres, puede leer `pg_catalog` e `information_schema` (nombres de esquemas y tablas, no sus filas) y crear tablas
temporales de su sesión.

**TLS.** Toda conexión a un host que no sea local verifica al servidor por nombre (`sslmode=verify-full`) contra la
raíz de Supabase incluida en el repo (`rg/catalog/supabase-prod-ca-2021.crt`, "Supabase Root 2021 CA", sha256
`700723581420dd1ac98fd7e9ac529f0ef210eadcaf87fc868a3ad7d114c2f3b7`; verificó tres session poolers el 2026-10-30). Una
URI que trae sus propias opciones TLS o `hostaddr` se rechaza. Quien lea con `zppmnd_lectura` necesita esa misma raíz.

La conexión es el secreto `RG_DB_URL` (la URI del Session pooler de Supabase); solo el paso que carga lo recibe, por su
entorno; `RG_LECTURA_PASSWORD` llega a ese paso solo en `modo: lector`. `python -m rg.catalog.db ping` (o el flujo con `modo: ping`) dice si conecta y la versión del servidor, nunca
la URI; un error de conexión imprime solo su tipo. Una prueba impide que una URI con contraseña para un host remoto
entre al repo. Las pruebas corren en CI contra un Postgres desechable.

## Tratados internacionales: vista derivada del DOF

Cada corrida escribe `mx/tratados/tratados.jsonl`, justo después del catálogo, sin tocar el sitio de la SRE (su reto
anti-bots no se rodea). Todo tratado vigente en México pasa por el DOF: el decreto del Senado que lo aprueba
("Decreto por el que se aprueba el Convenio…") y el decreto que lo promulga ("Decreto Promulgatorio del Tratado…").
- **Selección y etapa:** tabla fija de aperturas del título (`rg/catalog/tratados.py`): acto, artículo y una palabra de
  instrumento (Tratado, Convenio, Convención, Acuerdo, Protocolo, Enmienda; desde 2026-10-29 también Arreglo, Estatuto,
  Decisión, Resolución, Memorándum, Notas, Reserva, la Constitución de un organismo…). Etapas: `promulgacion`,
  `aprobacion_senado`, `enmienda`, `retiro_o_denuncia`, `fe_de_erratas`, `aclaracion`. Gana la apertura más larga
  seguida de un instrumento.
- **Nombre:** se copia del título, desde después del artículo hasta la cláusula de conclusión (", adoptado en",
  ", firmado en", ", hecho en", ", suscrito en"), o hasta el final sin el punto.
- **Agrupación y orden:** una línea por nombre exacto plegado (sin acentos, mayúsculas, espacios simples), con sus notas
  ordenadas por fecha oficial. No se calcula vigencia, no se adivinan partes y no se unen nombres distintos.
- **Chequeo independiente:** una regex más laxa debe seleccionar exactamente los mismos títulos que la tabla. Pide
  "decreto" con "promulgatorio" o "de promulgación", una aprobación que nombre un instrumento en cualquier parte del
  título, o una cláusula de conclusión. No cuenta lo que "se importe al amparo de" un tratado, que es una medida
  arancelaria. Cualquier diferencia, en un sentido o en el otro, queda en `coverage` (`mx.tratados`) y la corrida sale
  con código 3.
- **Chequeo por emisor:** el DOF archiva cada nota bajo su emisor (`category.issuer`), un dato que no sale del título.
  Todo decreto de la SRE que promulga, aprueba, deja sin efectos o denuncia algo tiene que estar en la tabla, salvo un
  programa que la SRE aprueba. Si falta uno, la corrida sale con código 3.
- **Desde 1993 (corrida del 2026-10-29: 1484 contra 1561).** Al llegar a 1993 aparecieron formas viejas:
  - "DECRETO de Promulgación…", con 202 notas;
  - terminaciones ("se deja sin efectos…", y "por el cual el Convenio…" o "se determina que…" solo en la forma fija que
    imprimen las 13 notas reales: ", quedará sin efectos en los Estados Unidos Mexicanos | en México | entre los Estados
    Unidos Mexicanos y …, a partir del…"; "sin efectos" en otro lugar, como "se modifica para dejar sin efectos su
    artículo 2", no es terminación y el cuadre lo reporta);
  - "Reglamento" es también forma jurídica mexicana: cuenta solo como uno de los nombres de la tabla fija `NAMED` (los
    de la UPAEP, `mx.dof:4906649` y `4863279`); "se aprueba el Reglamento Interior de la Secretaría de Salud" queda
    fuera y el cuadre lo reporta;
  - "el texto de…", adhesiones y ajustes;
  - "Fe de errata" en singular;
  - erratas de impresión del propio DOF ("Decreto por que se aprueba").

  Cada forma nueva cita una nota que lee. Se leen solo formas y palabras que no cambian lo ya leído: ARTICULO
  renombraba 19 enmiendas, así que no es instrumento. Sobre los 844,383 títulos del DOF, cuadran las dos
  verificaciones. Respecto de antes cambian tres notas:
  - un "Convenio Amistoso" de límites entre estados (art. 46 constitucional, `mx.dof:4720018`) deja la vista porque es
    doméstico;
  - dos enmiendas a la Constitución de la OIM quedan bajo esa Constitución.

  Nueve notas sin una forma fija quedan en `REVIEWED` con el sha256 de su título.
- La carpeta es una vista: `Catalog` nunca la lee como registros (`store.DERIVED`).

## Programación

`.github/workflows/catalog-mx.yml` corre cada 3 días a las 05:00 de la Ciudad de México. Antes de tocar una fuente corre las pruebas. Escribe solo la rama de datos y el release: el bot nunca toca el código.

En cada corrida:
- **DOF:** vuelve a leer los últimos 3 días (por notas tardías) e indexa hacia atrás hasta el piso configurado (`backfill_floor`).
- **Leyes y reglamentos:** usa descarga condicional por ETag; lo que no cambió no se baja.
- **OJN:** relista los 32 estados y vuelve a bajar lo que cambió de fecha de última reforma.
- **Banxico SIE:** pide la historia completa de las 4 series (5 peticiones, más robots.txt). Después, un paso busca
  `BANXICO_TOKEN` en `data` y `raw`. Si lo encuentra, o no puede leer, no sube crudos ni hace commit.

## Fuentes registradas que esperan (tier 2) y por qué

Están en `sources/mx.json` con su causa observada:
- datos.gob.mx: robots prohíbe `/api/`.
- SCJN: robots responde 403. Mientras tanto, las tesis entran por la fuente secundaria `mx.hf-tesis-scjn`.
- Catálogo de NOM: el dominio ya no resuelve; las NOM se cubren desde el DOF.
- CONAMER: robots responde 403 y el dominio no resuelve.
- Periódicos oficiales estatales y congresos locales: 32 formatos distintos.
- INEGI (más allá del INPC): estadística y geografía; por ahora solo el INPC entra, en prueba. Su primera corrida
  real respondió 401 y 400 (pendiente para el dueño, arriba).
- Tratados de la SRE: es una aplicación con JavaScript; falta revisar sus reglas.

Nada de esto se rodea: o se abre por la vía permitida o queda bloqueado con su causa.

## Agregar otro país

1. Crear `sources/<cc>.json` con sus fuentes oficiales: host permitido, licencia y categoría base.
2. Escribir un adaptador por *formato de sitio* (no por documento), con su conteo independiente para el cuadre.
3. Agregar fixtures reales y pruebas, y un flujo `catalog-<cc>.yml`.
