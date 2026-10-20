# Cómo se organiza el conocimiento: 5 dimensiones (propuesta, 2026-10-20)

Idea de Braulio: el motor de ZPMND es **consecuencialista**. Para prever escenarios y elegir el mejor estudio o cálculo
en cada caso, tiene que saber **qué se mueve cuando algo cambia**. Por eso el conocimiento no se ordena solo en carpetas.
Se ordena en dimensiones, y la última son las relaciones entre piezas.

| # | Dimensión | Qué responde | Qué ya captura RG |
|---|---|---|---|
| 1 | **Territorio** | ¿Dónde aplica? | País → estado → municipio (`mx/ARBOL.md`; 32 estados, 1,052 municipios) |
| 2 | **Jerarquía normativa** | ¿Qué tanto manda? | Constitución → tratados → leyes → reglamentos → NOM → acuerdos y lineamientos (`doc_type`, tipo oficial del OJN) |
| 3 | **Tiempo** | ¿Desde cuándo y hasta cuándo? | Publicación con la fecha oficial de su edición; reformas impresas; 468 instrumentos federales con versiones hasheadas |
| 4 | **Materia o rubro** | ¿De qué trata? | Emisor y sección oficial; el mapa de demanda agrupa por rubro (fiscal, banca, laboral…) |
| 5 | **Consecuencia** (relaciones) | Si cambia X, ¿qué se afecta? | Primeras relaciones medibles: *reglamenta a*, *reforma a*, *cadena de una NOM* |

## Lo que ya se puede extraer sin inferir (catálogo del 2026-10-20)

- **Reglamenta a:** 121 de 150 reglamentos federales se ligan a su ley por el título exacto.
- **Reforma a / menciona a:** 187 de 17,527 notas del DOF nombran una ley vigente por su título exacto. Las más tocadas
  son el CFF (55) y la Ley General de Mecanismos de Desarrollo y Fortalecimiento Patrimonial (33). Los títulos alcanzan
  para poco, porque los decretos citan artículos en el cuerpo del texto. La dimensión 5 necesita **extraer el texto de los
  crudos**.
- **Cadena de una NOM:** 46 códigos NOM en títulos del DOF; solo 1 con más de un eslabón (proyecto, respuesta a comentarios,
  norma) dentro de la ventana actual. Se completa al llenar el rezago del DOF.

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
