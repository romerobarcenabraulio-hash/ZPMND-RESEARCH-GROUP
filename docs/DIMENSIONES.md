# Cómo se organiza el conocimiento: 5 dimensiones (propuesta, 2026-10-20)

Idea de Braulio: el motor de ZPMND es **consecuencialista**. Para prever escenarios y elegir el mejor estudio o cálculo
en cada caso, tiene que saber **qué se mueve cuando algo cambia**. Por eso el conocimiento no se ordena solo en carpetas.
Se ordena en dimensiones, y la última son las relaciones entre piezas.

| # | Dimensión | Qué responde | Qué ya captura RG |
|---|---|---|---|
| 1 | **Territorio** | ¿Dónde aplica? | País → estado → municipio (`mx/ARBOL.md`; registros de 32 estados y 892 municipios) |
| 2 | **Jerarquía normativa** | ¿Qué tanto manda? | Constitución → tratados → leyes → reglamentos → NOM → acuerdos y lineamientos (`doc_type`, tipo oficial del OJN) |
| 3 | **Tiempo** | ¿Desde cuándo y hasta cuándo? | Publicación con la fecha oficial de su edición (o la fecha impresa de la página; nunca el día pedido); reformas impresas; 468 instrumentos federales con versión hasheada. Las notas indexadas antes del 2026-10-20 se corrigen al releerse |
| 4 | **Materia o rubro** | ¿De qué trata? | Emisor y sección oficial; el mapa de demanda agrupa por rubro (fiscal, banca, laboral…) |
| 5 | **Consecuencia** (relaciones) | Si cambia X, ¿qué se afecta? | Primeras relaciones medibles: *reglamenta a*, *reforma a*, *cadena de una NOM* |

## Lo que ya se puede extraer sin inferir

Medido con `scripts/medir_dimensiones.py` (coincidencia exacta de títulos, sin inferencia) sobre el catálogo local de la
corrida 2026-10-20T152357Z (62,239 registros; entra a la rama `catalog` con la siguiente publicación). Las cifras de esta sección
salen de ese script. Recibo de Goodware `ev:349b7f6b6cec1d38aa30e9653b52aa114972d63ff7250189100cfac1a5da1f34`: ejecución
del script con salida (stdout) de sha256 `8407af1cdccfe59d9c2180e06fc9409ec46317222ceff87d1031ae2868d02036`.

- **Reglamenta a:** 122 de 150 reglamentos federales contienen el título exacto de una ley vigente.
- **Reforma a / menciona a:** 310 de 25,140 notas del DOF nombran una ley vigente por su título exacto. La más nombrada es
  el Código Fiscal de la Federación (68). Los títulos alcanzan para poco, porque los decretos citan artículos en el cuerpo
  del texto. La dimensión 5 necesita **extraer el texto de los crudos**.
- **Cadena de una NOM:** 60 códigos NOM en títulos del DOF; solo 2 aparecen en más de una nota dentro de la ventana
  actual. Se completa al llenar el rezago del DOF.

## Cuánto texto se puede extraer de los crudos (medición, 2026-10-21)

Medido con `scripts/medir_extraible.py` sobre el almacén local `work/raw` (solo lectura, sin red), con pypdf 6.19.0. La
salida (stdout) tiene sha256 `9f903db750d0951e0e4b5e2ce3e66a624a6ff0e54c6878923c93cc54c8879074`.

**Conteo completo (MEDICIÓN).** Hay 7,779 crudos. 28 no estaban en el disco porque iCloud los desalojó (17 PDF, 5 HTML,
4 DOC, 1 DOCX y 1 RTF), así que no se abrieron. De los 7,751 restantes:

| Formato | Archivos | Qué falta para tener el texto |
|---|---:|---|
| HTML | 4,008 | Quitar etiquetas. Solo 3 tienen menos de 200 caracteres visibles (mediana: 1,919) |
| PDF | 2,297 | Capa de texto u OCR (ver la muestra). Hay 4 `.bin` más que también son PDF |
| DOC | 1,422 | Nada de OCR: ya son texto. Por sus bytes iniciales, 917 son DOCX (zip), 499 son Word 97 (OLE2) y 6 son RTF |
| DOCX y RTF | 19 y 1 | Nada de OCR: ya son texto |

Además, un `.pdf` resultó ser HTML. **El extractor debe decidir el formato por los bytes iniciales, no por la extensión.**
Los PDF salen de cuatro fuentes: OJN municipal (1,004), OJN estatal (837), leyes federales (307) y reglamentos federales
(149). Las notas del DOF son HTML.

**Muestra de 300 PDF, semilla 20261021 (HIPÓTESIS para el total, porque es una muestra).** Una página "tiene texto"
cuando su capa da al menos 30 caracteres no blancos. De cada PDF se leen hasta 40 páginas repartidas.

| Clase | PDF | Páginas |
|---|---:|---:|
| Con capa de texto legible | 293 | 9,960 |
| Escaneados (10 % de páginas con texto o menos) | 5 | 163 |
| Mixtos | 2 | 306 |
| Texto ilegible (mapa de fuentes roto) o error al abrir | 0 | 0 |

- Necesitan OCR 7 de 300 (2.3 %; IC 95 %: 1.1 % a 4.7 %). Los 7 vienen del OJN (3 estatales y 4 municipales). Los 52
  federales de la muestra (39 leyes y 13 reglamentos) traen texto.
- Llevado a los 2,297 PDF, serían unos 54 PDF (entre 26 y 109) y unas 1,800 páginas sin capa de texto.
- **Lectura (INTERPRETACIÓN).** El OCR no es el cuello de botella: el 98 % de los PDF ya trae texto. Con unas 1,800
  páginas, no hace falta reservar GPU esta noche. El tiempo y el costo de hacer ese OCR con CPU siguen siendo HIPÓTESIS
  hasta medirlos. Lo que sí falta es el extractor determinista (HTML, PDF con capa, DOCX, Word 97 y RTF), con nombre y
  versión fijos para el campo `extractor` del contrato.
- **Límites.** Una capa de texto no garantiza el orden de lectura (columnas, tablas, palabras cortadas); eso se mide
  cuando exista el extractor. No se midió si los DOC y DOCX traen imágenes escaneadas adentro.

## División del trabajo

- **RESEARCH GROUP** extrae las relaciones de forma **determinista**, del texto oficial y con su cita (fuente, fecha,
  sha256). Cada relación es un dato CANDIDATO; ninguna se infiere.
- **ZPMND** corre el razonamiento consecuencialista sobre ellas: escenarios, propagación del cambio y elección del mejor
  estudio o cálculo.

## Leyes, estándares, academia, cálculo

- **Leyes:** dónde estamos parados. *En curso* (federal, estatal y municipal).
- **Estándares:** cómo se cumple. Siguen:
  - la cadena completa de NOM desde el DOF;
  - el catálogo de NMX (solo metadatos cuando el texto se vende);
  - normas internacionales ISO/IEC (solo metadatos).
- **Academia:** cómo se resuelven los problemas. Fuentes de acceso abierto con licencia verificada: SciELO México, Redalyc,
  DOAJ, repositorios universitarios y arXiv.
- **Cálculo:** cómo se mide. Siguen:
  - metodologías oficiales (INEGI, Banxico, CONEVAL, SAT);
  - libros de texto abiertos (OpenStax, LibreTexts);
  - los libros comerciales quedan solo como referencias.

Cada fuente entra con las reglas de siempre: robots.txt, licencia, conteo independiente y prueba sobre páginas reales.

## Dónde vive esto en el Goodware

Citas a `goodware/canon/PREZIP_DESIGN_CLOSED_SOURCE.md`, §24 (líneas 1466–1597), y a `PRODUCT_NORTH_SOURCE.md:9`.
La palabra "dimensiones" no aparece en el canon: la búsqueda en sus 5 archivos da 0 resultados. La idea sí está, repartida en
objetos que ZPMND ya define en §24 (Impact Graph, Change Intelligence, Evidence Compiler, ciclo de vida y World Learning
Agenda). Esos objetos fijan la forma en que RG debe alimentarlo.

| Dimensión | Objeto del canon que la recibe | Campo |
|---|---|---|
| Territorio | Evidence Compiler | `applicability` |
| Materia o rubro | Evidence Compiler | `applicability` |
| Jerarquía normativa | Evidence Compiler | `source_authority` |
| Tiempo | ChangeEvent, Evidence Compiler y ciclo de vida | `published_at` y `effective_at`; `temporal_validity`; estados ACTIVE, STALE, SUPERSEDED, REVOKED… |
| Consecuencia | DependencyGraph → Impact Compiler → ImpactSet | aristas; `downstream_dependents[]` |
| Cálculo ("cómo se mide") | Evidence Compiler | `transformations / calculations` |

**Lectura (INTERPRETACIÓN).** En el canon, cuatro dimensiones son **atributos** de cada pieza y la quinta es el **grafo** que
las une. No es un cubo de cinco ejes: son nodos con cuatro coordenadas y aristas con evidencia. La ecuación núcleo
`REFERENCE × STATE → DELTA` lo acomoda así: leyes, estándares, academia y cálculo son la REFERENCE; la organización es el
STATE; el DELTA lo calcula ZPMND.

### Lo que el canon le exige a RG

- **Un cambio sin dependencia demostrada no se propaga.** Por eso cada arista lleva su cita literal en el crudo hasheado
  (regla 10) y ninguna se infiere (regla 3).
- **Si una fuente cambia, se invalida solo el subgrafo afectado.** Cada pieza necesita identidad estable y versión. Ya
  existe: `entry_id` y `versions[]` con sha256 por corrida.
- **Si el cambio entra en vigor después, la agenda se arma por `effective_at`.** Hay que extraer la entrada en vigor de los
  artículos transitorios. Hoy no la tenemos.
- **La web nunca pasa directo a verdad.** RG entrega crudo no confiable y candidatos; ZPMND evalúa y promueve.

## Cómo sale RG para encajar (PROPUESTA)

| Campo de RG hoy | Objeto y campo del canon | Estado |
|---|---|---|
| `category.jurisdiction`, `locality`, `municipality` | `applicability` (territorio) | Existe. PROPUESTA: claves INEGI de entidad y municipio por tabla fija |
| `category.issuer`, `section`, `branch` | `applicability` (materia) | Existe, copiado de la fuente |
| `category.doc_type` y orden de gobierno | `source_authority` | Existe. El rango entre tipos lo decide ZPMND (INTERPRETACIÓN jurídica, art. 133 constitucional) |
| `dates.published` (fecha oficial de la edición), `original_publication`, `last_reform_printed` | ChangeEvent `published_at` | Existe; la fecha del DOF se corrigió en #6 |
| (falta) | ChangeEvent `effective_at` | FALTA el extractor; el contrato ya existe (`effective_at` con la cita de su transitorio) |
| `versions[]` (sha256 por corrida) | ChangeEvent `before_ref` / `after_ref` | Existe; el primer cambio aparece en la siguiente corrida |
| `status_printed` (VIGENTE, ABROGADA…) | evidencia para el ciclo de vida | Existe. RG no asigna el estado |
| Aristas *reglamenta*, *reforma*, *abroga* y *cita*, cada una con su cita | DependencyGraph | 122 *reglamenta* por título exacto; el resto necesita el texto completo |
| `retrieved_at` | `knowledge_freshness` de la capability | Existe |
| "(sin dato en la fuente)" y `blocked_by` | Unknown Registry | Existe |
| (no aplica) | ChangeEvent `semantic_delta` | **No es de RG**: es razonamiento y lo hace ZPMND |

### Orden de construcción que sale de aquí

1. Emitir ChangeEvent candidatos cuando cambia el sha256 de una ley o un reglamento. Es determinista y los datos ya están.
2. Extraer el texto de los crudos para obtener `effective_at` (transitorios) y las aristas, cada una con su cita. El
   extractor ya existe ([TEXTO.md](TEXTO.md)); falta leer transitorios y aristas sobre ese texto.
3. Claves INEGI de territorio por tabla fija, con su fuente oficial revisada (robots y licencia) antes de activarla.

El contrato ya está escrito: `schemas/change_event.schema.json` y `schemas/relation.schema.json`, validados por
`rg.schemas` (pruebas en `tests/test_contrato_texto.py`). Entra a `main` antes que el código que los produce. Cada cita
lleva el sha256 de su crudo y el extractor fijado (`nombre==versión`): los bytes de un PDF o de un DOC no son texto, y la
regla 10 solo se puede revisar si la aduana de ZPMND corre el mismo extractor sobre el mismo crudo.
