# Rama de datos `catalog` (RESEARCH GROUP)

Solo datos, nunca código: la escribe el flujo `catalog-mx` (cada 3 días) o una corrida local en la red aislada. El código
vive en `main` (`rg/catalog`, `sources/mx.json`, `docs/CATALOGO.md`).

- `mx/ARBOL.md` — navegación país → ámbito → estado → municipio → poder → dependencia → tipo, con conteos.
- `mx/INDEX.md`, `mx/index.json` — conteos por categoría.
- `mx/<fuente>.jsonl`, `mx/dof/<año>.jsonl`, `mx/ojn-estatal/<clave INEGI>.jsonl`, `mx/ojn-municipal/<clave>.jsonl` —
  un registro por instrumento o nota: título tal cual, categorías de la fuente, fechas impresas, url, sha256 del crudo.
- `mx/runs/` — manifiesto de cada corrida: cuadres de cobertura, errores, cuarentena, peticiones.
- Crudos: release `raw-mx`, archivos `.tar` con rutas `sha256/<2>/<sha256>.<ext>`.

Todo es CANDIDATO para ZPMND: crudo, categorizado y ordenado, nunca resumido ni interpretado.
