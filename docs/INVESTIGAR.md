# Investigación autónoma (`investigar.yml`)

Un ResearchRequest en `requests/` y su plan de fuentes revisado en `requests/plans/<RR>.json` se convierten, sin esta
conversación, en una rama `investigar/<RP>` con la carpeta del paquete. Corre en GitHub Actions con runners estándar,
que GitHub no cobra en repositorios públicos (documentación de facturación de GitHub Actions). El modelo usa la
suscripción de Claude del dueño (la misma credencial del auditor): HIPÓTESIS, sin medir todavía, que cada corrida solo
consume el uso incluido en el plan y no genera un cargo por token.

## Cómo se usa

1. Un PR agrega el plan: las URL https de las fuentes, con su editor, tipo, licencia, redistribución y si son
   primarias o secundarias. Solo admite fuentes con `redistribution: allowed`, porque el repo y sus artefactos de
   Actions son públicos y todo lo que la corrida mueve queda redistribuido. Las fuentes que solo admiten metadatos se
   leen a mano, fuera de este flujo. El PR pasa por CI y por los dos auditores como cualquier cambio.
2. Ya en main: `gh workflow run investigar.yml -f request_id=<RR>`.
3. Al terminar, el resumen de la corrida trae el comando `gh pr create` de la rama. El PR lo abre el dueño, porque una
   rama empujada con `GITHUB_TOKEN` no dispara flujos, y así corren CI y los dos auditores.

## Por qué es seguro (cada criterio tiene su prueba en `tests/test_investigar.py`)

| Criterio | Cómo se cumple |
|---|---|
| Mínimo privilegio | Cuatro trabajos: `fetch` (lectura, sin secretos), `analyze` (lectura, solo la credencial del modelo y en un solo paso), `gate` (lectura) y `publish` (escritura, nada más) |
| Contenido hostil | El modelo corre sin ninguna herramienta (`--tools ""`), desde una carpeta vacía, sin servidores MCP y sin token de GitHub; los textos van dentro de su prompt, como datos. No puede leer un archivo, correr un comando ni abrir una URL, así que no tiene cómo llegar a la credencial con la que corre: solo puede responder. Lo que una página "ordene" es dato |
| CLI fijada | El Claude Code CLI se baja por versión exacta y se comprueba contra la integridad sha512 que publica npm para esa versión antes de desempacarlo; sin coincidencia no corre |
| Nada inventado | El pedido se valida contra su esquema (emitido por OWNER o ZPMND, PUBLIC o ABSTRACTED) antes de descargar nada. Artefactos, sha256, tamaños, licencias y el texto del pedido salen del registro de descarga y de main, nunca del modelo. Un hallazgo que cita algo no descargado detiene la corrida, y dos URL que entregan los mismos bytes también, para no perder una procedencia. Las fuentes del plan que el modelo no leyó quedan en `limitations`, escritas desde el registro |
| Citas comprobadas | `rg.packets` confirma que cada cita está, con los espacios plegados, en el texto que el extractor fijado sacó de su fuente. Si la extracción falla no hay texto y la cita no se da por buena: nunca se busca en los bytes crudos. Solo un formato de texto plano que `rg.text` no lee (JSON, CSV, XML, texto) se lee como UTF-8 estricto. Si una cita no está, no se publica nada |
| Derechos | El plan solo admite fuentes redistribuibles y `fetch` no descarga ninguna otra, aunque se le pase. La compuerta rechaza cualquier archivo que el paquete no declare: un crudo de más, una segunda copia, un enlace o una nota |
| Robots y cortesía | El `Fetcher` del catálogo: robots.txt, solo los hosts del plan, una petición por segundo por host, 60 MB por cuerpo |
| Archivos hostiles | El texto sale de `rg.text`, con un proceso por archivo y límites de tiempo, tamaño y memoria, en trabajos sin permiso de escritura |
| Superficie | Solo `workflow_dispatch` desde main; `publish` no analiza nada y solo agrega `research-packets/<RP>/` |
| Costo | Una llamada al modelo por pedido, con 2 turnos como máximo y a lo más 400 000 caracteres de texto; un plan más grande se divide. Los artefactos de Actions duran un día. Lo demás es código determinista |

## Qué no hace (todavía)

- No busca fuentes en la web abierta: el plan las nombra. Descubrir fuentes, que exige búsqueda y es el punto de mayor
  riesgo de inyección, queda para corridas acotadas y revisadas.
- No abre el PR solo. Para eso haría falta un token que cree el dueño; mientras, abrirlo es un comando.
