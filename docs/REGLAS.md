# Reglas de trabajo de RESEARCH GROUP

Cada regla nace de un error real (casi todos del 2026-10-19). Cada una dice qué la hace cumplir. Una regla que solo
depende de que el modelo "se acuerde" no cuenta: necesita una prueba, un cuadre o una guarda.

| # | Regla | Origen | Qué la hace cumplir |
|---|---|---|---|
| 1 | Nada se da por bueno sin verificación mecánica: prueba, cuadre o recibo. "Terminado" sin recibo no existe | Cuatro defectos del parser que la revisión no vio y el cuadre sí | `run.py` (salida 3/4), suite de pruebas, delivery-check de Goodware |
| 2 | Toda fuente activa tiene un **conteo independiente** en la misma página oficial. Sin conteo independiente, la fuente no se activa | Día del DOF con 0 de 107 notas extraídas; leyes y reglamentos omitidos | `_cover()` en cada adaptador; `tests/test_catalog.py` |
| 3 | La categoría se **copia** de la estructura oficial o sale de una **tabla fija**. Sin coincidencia es `OTRO`; un nivel ausente es "sin dato en la fuente". Nunca se infiere | Diseño; 3,702 OTRO resueltos por la sección oficial, no por adivinanza | `categorize.py`, `recategorize()`, `build_tree()` |
| 4 | Las categorías derivadas se recalculan cada corrida desde los campos verbatim, para que una mejora a la tabla se aplique hacia atrás | Convocatorias clasificadas como OTRO | `recategorize()` |
| 5 | Una falla de red nunca tumba una corrida, y pase lo que pase se escribe lo reunido | Un `IncompleteRead` perdió 1.5 h de trabajo | reintentos en `fetch.py`; `try` en `main`; prueba de red |
| 6 | Paralelo solo **por servidor**; un sitio nunca recibe dos hilos. Lecturas concurrentes solo sobre copias con candado | Leyes y reglamentos comparten servidor; "dictionary changed size during iteration" | `host_groups()`, `Catalog.snapshot()`, pruebas de concurrencia |
| 7 | Decodificar según el estándar WHATWG (ISO-8859-1 = windows-1252). Los caracteres invisibles se quitan y se cuentan | Comillas 0x93/0x94 del OJN; U+FEFF en un título de la CDMX | `decode_html()`, `normalize_strings()`, esquema |
| 8 | robots.txt, términos, retos anti-bots y tokens **no se rodean**. Se registra la causa y se pide al operador o a Braulio | SRE (Radware), datos.gob.mx (`/api/`), SCJN y CONAMER (403) | `fetch.py`; `sources/mx.json` (`blocked_by`); `docs/SOLICITUDES.md` |
| 9 | Hasta la **exploración** pasa por robots.txt: nada de `curl` directo a rutas que no se han revisado | Una petición a `/api/` de datos.gob.mx durante la exploración (error propio) | explorar con `rg.collect` o el `Fetcher`, que revisan robots |
| 10 | Toda cita de un paquete existe **literal** en el crudo hasheado de la fuente que cita | Prevención de citas inventadas | `rg.quotes` (6/6 en el primer paquete) |
| 11 | Toda app, cuenta, token o conector se **solicita** a Braulio; RG nunca los crea | Instrucción de Braulio, 2026-10-19 | `docs/SOLICITUDES.md` |
| 12 | Entradas de usuario en CI van como variables de entorno validadas, nunca interpoladas en el script | Riesgo de inyección en `catalog-mx.yml` | revisión del flujo; `grep '${{' dentro de run:` vacío |
| 13 | Una prueba nunca corre sin límite (bucles, datos crecientes) | Prueba de concurrencia que tardaba más de 2 minutos | límites explícitos en las pruebas |
| 14 | Mientras un PR está en auditoría, su rama no se mueve; lo nuevo espera o va en otro PR contra `main` (regla 14b) | No mover lo que Braulio está revisando | el head auditado es el que se cita en el veredicto |
| 14b | **No apilar PR**: todo PR va contra `main`. Si algo depende de un PR abierto, se espera o se incluye, porque borrar la rama base **cierra** el PR dependiente | 2026-10-20: al fusionar #1 y borrar su rama, GitHub cerró #3 sin fusionar; #4 terminó en `catalog-mx` y no en `main` | base `main` en cada `gh pr create` |
| 15 | Cifras no medidas (precios, tiempos, tamaños) se etiquetan como HIPÓTESIS hasta medirlas | Costos de GPU sin verificar | redacción de paquetes y documentos |
| 16 | Los textos con derechos de autor (ISO, NMX de venta) y los datos personales (edictos) quedan **solo como metadatos** | Avisos judiciales del DOF | `metadata_only_branches`; `redistribution` en el esquema |
| 16b | Una prueba de mutación vale solo si la **línea base pasa** en la misma copia; la copia no tiene remoto | 2026-10-20: copia sin `.git`; una prueba usa `git ls-files`, la línea base fallaba y toda mutación contó como muerta | `scripts/mutar.py` verifica la línea base antes de mutar; corre en CI (job `mutation`) en cada PR |
| 17 | Con Braulio: en su idioma; leer la intención y pesarla contra la evidencia, sin tomar sus palabras como verdad literal; no preguntar lo que el contrato resuelve | Sus mensajes del 2026-10-19 | `CLAUDE.md` |
| 18 | robots.txt se lee como dice el RFC 9309, no como lo lee la biblioteca: hasta 5 redirecciones dentro de la lista de hosts, y los grupos del mismo agente se combinan | 2026-10-21: el robots.txt de Banxico redirige (302) y repite `User-agent: *`; la biblioteca de Python tomaba la redirección como bloqueo y se quedaba con el primer grupo (dejaba pasar `/ALEPH` y `/V`) | `_robots_for` y `_Robots` en `fetch.py`; `tests/test_catalog.py` FetchGuards con el robots.txt real |
| 19 | Un token va solo a su host y nunca se escribe: ni en la URL registrada (`<token>`), ni en el manifiesto, ni en un crudo | INEGI pone el token en la ruta de la URL (2026-10-21) | `secrets` del `Fetcher`, `redact_secrets` en `run.py`, paso de búsqueda en `indicadores-mx.yml`, `tests/test_indicadores.py` |

## Qué cambia en mi forma de trabajar

- **Antes de activar una fuente:** robots.txt revisado; formato leído en páginas reales guardadas como fixtures; conteo independiente definido; prueba de regresión sobre la página real.
- **Antes de afirmar algo:** recibo (`gw observe`, manifiesto o prueba) o la etiqueta HIPÓTESIS.
- **Al encontrar un error propio:** causa raíz, prueba que falla sin el arreglo, una fila en esta tabla.
