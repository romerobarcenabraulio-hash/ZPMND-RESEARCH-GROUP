# Cómo se organiza el conocimiento: 5 dimensiones (propuesta, 2026-10-20)

Idea de Braulio: el motor de ZPMND es **consecuencialista**. Para prever escenarios y elegir el mejor estudio o cálculo
en cada caso, tiene que saber **qué se mueve cuando algo cambia**. Por eso el conocimiento no se ordena solo en carpetas.
Se ordena en dimensiones, y la última son las relaciones entre piezas.

| # | Dimensión | Qué responde | Qué ya captura RG |
|---|---|---|---|
| 1 | **Territorio** | ¿Dónde aplica? | País → estado → municipio (`mx/ARBOL.md`; 32 estados, 1,052 municipios) |
| 2 | **Jerarquía normativa** | ¿Qué tanto manda? | Constitución → tratados → leyes → reglamentos → NOM → acuerdos y lineamientos (`doc_type`, tipo oficial del OJN) |
| 3 | **Tiempo** | ¿Desde cuándo y hasta cuándo? | Publicación con la fecha oficial de su edición (o la fecha impresa de la página; nunca el día pedido); reformas impresas; 468 instrumentos federales con versión hasheada. Las notas indexadas antes del 2026-10-20 se corrigen al releerse |
| 4 | **Materia o rubro** | ¿De qué trata? | Emisor y sección oficial; el mapa de demanda agrupa por rubro (fiscal, banca, laboral…) |
| 5 | **Consecuencia** (relaciones) | Si cambia X, ¿qué se afecta? | Primeras relaciones medibles: *reglamenta a*, *reforma a*, *cadena de una NOM* |

## Lo que ya se puede extraer sin inferir

Medido con `scripts/medir_dimensiones.py` (coincidencia exacta de títulos, sin inferencia) sobre el catálogo local de la
corrida 2026-10-20T152357Z (62,239 registros; entra a la rama `catalog` con la siguiente publicación). Recibo
`ev:46a91165a1dc28a63aa3d00b13ed625b0e39cf962e34332d2d1f07d3b112c1ae`.

- **Reglamenta a:** 122 de 150 reglamentos federales contienen el título exacto de una ley vigente.
- **Reforma a / menciona a:** 310 de 25,140 notas del DOF nombran una ley vigente por su título exacto. La más nombrada es
  el Código Fiscal de la Federación (68). Los títulos alcanzan para poco, porque los decretos citan artículos en el cuerpo
  del texto. La dimensión 5 necesita **extraer el texto de los crudos**.
- **Cadena de una NOM:** 60 códigos NOM en títulos del DOF; solo 2 aparecen en más de una nota dentro de la ventana
  actual. Se completa al llenar el rezago del DOF.

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
| (falta) | ChangeEvent `effective_at` | FALTA: transitorios del texto completo |
| `versions[]` (sha256 por corrida) | ChangeEvent `before_ref` / `after_ref` | Existe; el primer cambio aparece en la siguiente corrida |
| `status_printed` (VIGENTE, ABROGADA…) | evidencia para el ciclo de vida | Existe. RG no asigna el estado |
| Aristas *reglamenta*, *reforma*, *abroga* y *cita*, cada una con su cita | DependencyGraph | 121 *reglamenta* por título exacto; el resto necesita el texto completo |
| `retrieved_at` | `knowledge_freshness` de la capability | Existe |
| "(sin dato en la fuente)" y `blocked_by` | Unknown Registry | Existe |
| (no aplica) | ChangeEvent `semantic_delta` | **No es de RG**: es razonamiento y lo hace ZPMND |

### Orden de construcción que sale de aquí

1. Emitir ChangeEvent candidatos cuando cambia el sha256 de una ley o un reglamento. Es determinista y los datos ya están.
2. Extraer el texto de los crudos para obtener `effective_at` (transitorios) y las aristas, cada una con su cita.
3. Claves INEGI de territorio por tabla fija, con su fuente oficial revisada (robots y licencia) antes de activarla.

El esquema de ChangeEvent y el de las aristas entran como contrato en `main` antes de escribir el código que los produce.
