# Solicitudes de instalación (para Braulio)

RESEARCH GROUP no crea cuentas ni tokens, no acepta términos y no instala apps. Cada cosa que el proyecto necesita se
solicita aquí. La instala Braulio con el permiso mínimo indicado. Cuando una solicitud se atiende, se marca con la fecha y
con la verificación que lo confirma.

| # | Qué instalar | Para qué (qué desbloquea) | Permiso mínimo | Dónde se configura | Cómo se verifica |
|---|---|---|---|---|---|
| 1 | **Conector Hugging Face** (oficial, `https://huggingface.co/mcp`) | Buscar modelos, datasets y papers con respuestas estructuradas: menos tokens que leer JSON y páginas. Acelera los paquetes de investigación | Lectura | Ajustes de Claude → Conectores | Aparecen herramientas `hf_whoami` y `model_search` en la sesión |
| 2 | **Cuenta Hugging Face + acceso a `ayaxrojo/tesis_scjn_v5_complete`** | 59,678 tesis de la SCJN (CC-BY-4.0) como fuente secundaria, mientras la SCJN responde 403 a robots | Aceptar las condiciones del autor en la página del dataset; token *fine-grained* de **solo lectura** | Página del dataset en huggingface.co; token como secreto `HF_TOKEN` en el repo RG (Settings → Secrets → Actions) | Una corrida lista el archivo del dataset con el token |
| 3 | **Repo de dataset privado en Hugging Face** (ej. `<tu-usuario>/rg-catalogo-mx`) | Espejo del catálogo en Parquet y del índice semántico; ZPMND lo consume directo con `datasets` | Token *fine-grained* con escritura **solo** a ese repo | huggingface.co → New dataset (privado); secreto `HF_WRITE_TOKEN` | Una corrida publica la versión y su hash |
| 4 | **Clave de Anthropic dedicada a RG con límite de gasto** | Piloto de OpenClaw: 1–3 agentes, una pregunta | Clave nueva solo para RG; tope mensual de gasto | Consola de Anthropic → API keys / Limits; secreto `RG_MODEL_API_KEY` | `verify_config.sh` y una corrida del piloto con costo medido |
| 5 | **Token de Banxico SIE** (registro gratuito) | Indicadores para cálculo directo de la fuente (tipo de cambio FIX, TIIE, UDIS, INPC) | Token de consulta | banxico.org.mx (SIE API); secreto `BANXICO_TOKEN` | Una corrida descarga una serie y cuadra contra el DOF |
| 6 | **Token de INEGI** (API de indicadores, registro gratuito) | Series oficiales (INPC, UMA, población) para cálculo | Token de consulta | inegi.org.mx (API); secreto `INEGI_TOKEN` | Una corrida descarga una serie |

## Peticiones a operadores (correo o trámite de Braulio)

Estas fuentes están bloqueadas por sus propias reglas, y no se rodean:

| Operador | Qué pedir | Por qué |
|---|---|---|
| datos.gob.mx | Exportación masiva del catálogo, o permiso para `/api/` | Su robots.txt prohíbe la API a robots y pide 10 s entre peticiones |
| SRE (Consultoría Jurídica) | Exportación de "Tratados celebrados por México" | El sitio sirve un reto anti-bots (Radware) |
| SCJN | Acceso al Semanario Judicial para consulta automatizada | robots.txt responde 403 |
| CONAMER | Acceso al Catálogo Nacional de Regulaciones | robots.txt responde 403 |

## Cómputo (cuando haga falta)

Hoy no hace falta GPU. El cuello de botella es la cortesía con cada sitio (1 petición/s), no el cómputo. El índice de
títulos corre en CPU. Cuando exista la extracción de texto completo y el corpus esté al día, se medirá el tamaño. Con esa
medida se pedirá aquí la renta de GPU con horas y presupuesto estimados.
