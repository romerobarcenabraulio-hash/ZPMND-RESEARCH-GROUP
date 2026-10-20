# Estado de RESEARCH GROUP (2026-10-19)

Página única para saber qué hay, dónde está y qué sigue. Se actualiza en cada entrega.

## Dónde está cada cosa

| Qué | Dónde |
|---|---|
| Código, reglas, contrato | rama `main` (al fusionar #1, #3 y #4); modos de trabajo en #2 |
| Catálogo de México (datos) | rama `catalog`, carpeta `mx/`. Para navegar: `mx/ARBOL.md` |
| Crudos (bytes originales) | release `raw-mx`, `.tar` con rutas `sha256/<2>/<sha256>.<ext>` y su `.sha256` |
| Paquetes para ZPMND | `research-packets/` (primero: `RP-2026-10-19-hf-zpmnd`) |
| Lo que RG propone investigar | `knowledge-demand/` (mapa priorizado, validado contra el esquema) |
| Fuentes y su estado | `sources/mx.json` (activas, planeadas y bloqueadas con su causa) |
| Lo que necesito que instales | `docs/SOLICITUDES.md` |
| Reglas de trabajo | `docs/REGLAS.md` |
| Local (no va a git) | `work/`: `catalog`, `raw`, `index`, `catalog-branch` (clon de la rama de datos), `logs`, `_pruebas` |

## Catálogo de México: primera corrida

| Fuente | Registros | Crudo |
|---|---:|---|
| Leyes federales (Diputados) | 318 | 318 almacenados |
| Reglamentos federales (Diputados) | 150 | 150 almacenados |
| DOF vía SIDOF | 9,915 (107 días: 2026-05-22 a 2026-10-19) | 4,068 avisos solo metadatos; el resto en descarga |
| Legislación estatal (OJN, 32 estados) | 29,944 | 1,924 almacenados; el resto en descarga progresiva |
| Normatividad municipal (OJN, 1,052 municipios) | 6,687 | 1,453 almacenados; el resto en descarga progresiva |

1,333 cuadres de cobertura sin descuadre.

## Qué corre solo

Al fusionar #3 en `main`, `catalog-mx.yml` corre cada 3 días (días 1, 4, 7… a las 05:00 de la Ciudad de México):
- releer los días recientes del DOF;
- bajar solo lo que cambió (ETag);
- avanzar el rezago con el presupuesto de cada fuente;
- publicar en `catalog` y `raw-mx`.

Para ponerse al día más rápido: `gh workflow run catalog-mx.yml -f budget=12000`.

## Bloqueado (no se rodea)

| Fuente | Causa | Qué lo destraba |
|---|---|---|
| SCJN | robots.txt responde 403 | petición al operador, o tesis vía Hugging Face (SOLICITUDES #2) |
| SRE (tratados) | reto anti-bots | petición al operador |
| datos.gob.mx | robots.txt prohíbe `/api/` | petición de exportación |
| CONAMER | robots.txt responde 403 | petición al operador |
| Catálogo de NOM (SINEC) | el dominio no resuelve | las NOM se cubren desde el DOF |
| INEGI y Banxico | requieren token | SOLICITUDES #5 y #6 |

## Qué sigue, en orden

1. Que Braulio fusione #1 → #3 → #4 y #2, e instale las SOLICITUDES 1–6.
2. Ponerse al día: el DOF hacia atrás hasta 2024-01-01 y los documentos estatales y municipales pendientes.
3. Índice semántico (bge-m3) publicado junto al catálogo, con medición de tokens ahorrados.
4. Extracción de texto de los crudos (PDF y DOC) para vincular las reformas del DOF con la ley que reforman.
5. Las fuentes P0 del mapa de demanda: banca (CNBV, circulares de Banxico) y fiscal (Resolución Miscelánea), con su conteo independiente.
6. Piloto de OpenClaw (1–3 agentes) cuando exista la clave dedicada (SOLICITUDES #4).
