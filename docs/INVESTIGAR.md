# Investigación autónoma (`investigar.yml`)

Un ResearchRequest en `requests/` y su plan de fuentes revisado en `requests/plans/<RR>.json` se convierten, sin esta
conversación, en una rama `investigar/<RP>` con la carpeta del paquete. Corre en GitHub Actions con runners estándar,
que GitHub no cobra en repositorios públicos (documentación de facturación de GitHub Actions). El modelo usa la
suscripción de Claude del dueño (la misma credencial del auditor): HIPÓTESIS, sin medir todavía, que cada corrida solo
consume el uso incluido en el plan y no genera un cargo por token.

## Cómo se usa

1. Un PR agrega el plan: las URL https de las fuentes, con su editor, tipo, licencia, redistribución y si son
   primarias o secundarias. Un plan es todo de fuentes `redistribution: allowed` (sus crudos van al paquete) o todo de
   fuentes `metadata_only` (términos de servicio, precios, artículos: se citan, nunca se republican; el paquete guarda
   sus metadatos y citas de hasta 300 caracteres, sin crudo). El PR pasa por CI y por los dos auditores como cualquier
   cambio.
2. Ya en main: `gh workflow run investigar.yml -f request_id=<RR>`.
   Sin plan, con solo el pedido: `gh workflow run investigar.yml -f request_id=<RR> -f discover=true`. El trabajo
   `plan` le da el pedido, como datos, a la misma CLI con una sola herramienta, la búsqueda web (`--tools "WebSearch"`),
   desde una carpeta vacía y sin token de GitHub. La CLI responde por `DISCOVERY_SCHEMA`: familias de fuentes, búsquedas
   (oficiales, a favor, en contra, limitaciones), hasta 12 fuentes con su porqué, lo que no encontró y si terminó con
   `ENOUGH_FOR_PACKET` o `STOPPED_WITH_GAPS`. `plan_from_discovery` deja solo URL https de hosts públicos (ni IP, ni
   localhost, ni nombres internos, ni usuario o puerto) y vuelve **todas** `metadata_only`: una fuente descubierta se
   cita y nunca se republica sin revisión. El resto es el pipeline de siempre: el mismo Fetcher con robots.txt, la
   misma extracción, el análisis, la revisión y la compuerta. Una URL inventada o caída queda solo como fila del
   registro, nunca como evidencia, y el paquete lleva el descubrimiento entero en `receipt.json`.
3. Al terminar, el resumen de la corrida trae el comando `gh pr create` de la rama. El PR lo abre el dueño, porque una
   rama empujada con `GITHUB_TOKEN` no dispara flujos, y así corren CI y los dos auditores.

## Por qué es seguro (cada criterio tiene su prueba en `tests/test_investigar.py`)

| Criterio | Cómo se cumple |
|---|---|
| Mínimo privilegio | Cuatro trabajos: `fetch` (lectura, sin secretos), `analyze` (lectura, solo la credencial del modelo y solo en los dos pasos que corren la CLI), `gate` (lectura) y `publish` (escritura, nada más) |
| Contenido hostil | El modelo corre sin ninguna herramienta (`--tools ""`), desde una carpeta vacía, sin servidores MCP y sin token de GitHub; los textos van dentro de su prompt, como datos. No puede leer un archivo, correr un comando ni abrir una URL, así que no tiene cómo llegar a la credencial con la que corre: solo puede responder. Lo que una página "ordene" es dato. Responde a través del esquema (`--json-schema`): solo se lee esa salida estructurada, nunca su texto libre |
| CLI fijada | El Claude Code CLI se baja por versión exacta y se comprueba contra la integridad sha512 que publica npm para esa versión antes de desempacarlo; sin coincidencia no corre |
| Nada inventado | El pedido se valida contra su esquema (emitido por OWNER o ZPMND, PUBLIC o ABSTRACTED) antes de descargar nada. Artefactos, sha256, tamaños, licencias y el texto del pedido salen del registro de descarga y de main, nunca del modelo. Un hallazgo que cita algo no descargado detiene la corrida, y dos URL que entregan los mismos bytes también, para no perder una procedencia. Las fuentes del plan que el modelo no leyó quedan en `limitations`, escritas desde el registro |
| Citas comprobadas | Antes de la compuerta, un hallazgo cuya cita no aparece tal cual (con los espacios plegados) en el texto de la fuente que cita sale del paquete: queda en `receipt.json` y `limitations` dice cuántos. Si se van más de la cuarta parte, la respuesta no se guarda (corridas 40533852150 y 40533858356 se perdían enteras por una cita de 57 y de 52). `rg.packets` confirma que cada cita está, con los espacios plegados, en el texto que el extractor fijado sacó de su fuente. Si la extracción falla no hay texto y la cita no se da por buena: nunca se busca en los bytes crudos. Solo un formato de texto plano que `rg.text` no lee (JSON, CSV, XML, texto) se lee como UTF-8 estricto. Si una cita no está, no se publica nada |
| Afirmación = cita | Una segunda llamada a la misma CLI, igual de aislada y desde su propia carpeta vacía, ve cada hallazgo confirmado junto a su cita y al título y la dirección, tomados del registro de descarga, de la fuente citada cuyo texto contiene la cita (solo nombran el documento; no aportan licencia, fecha, número ni condición), y nada más (ni el texto de la fuente ni el pedido), así que no puede rellenar un hueco con la fuente: si la afirmación dice algo que su cita no dice, la recorta a lo que la cita dice. Lo recortado no tiene cita: queda en `receipt.json`, fuera de los hallazgos, y `limitations` dice cuántas se recortaron. Un hallazgo `conflicting` nombra un desacuerdo y cita un solo lado, así que siempre dice más que su cita: es una señal para quien lee y no se revisa. Una revisión que omite, repite o inventa un hallazgo detiene la corrida; una que no deja nada de una afirmación saca solo ese hallazgo, y una que reescribe sin decir qué cortó deja la reescritura (corrida 40548398494). Si la llamada al modelo falla, el registro dice por qué con la estructura del resultado (tipo, subtipo, error sí o no, turnos, duración) y el código de salida, sin nada de su texto (GPT, #53) (corrida 40548392438) (corridas 40441646106 y 40441654246: con la regla de un hecho por hallazgo en el prompt, cerca de una de cada tres afirmaciones seguía diciendo más que su cita) |
| Sobre cerrado | El repo y sus artefactos de Actions son públicos: la carpeta de trabajo (cuerpos y textos) viaja entre trabajos cifrada (`scripts/sobre.sh`: AES-256 con una llave nueva por corrida y HMAC-SHA256 con otra, ambas selladas con RSA-OAEP a `keys/rg-artifacts.pub.pem`). `fetch` sella sin ningún secreto y sube solo el sobre; `analyze` y `gate` abren en un paso propio, el único con la llave privada `RG_ARTIFACT_KEY`, antes de leer nada. Al abrir, la llave privada sale del entorno antes de que corra otro programa (`tar` nunca la ve), el HMAC se comprueba antes de descifrar y lo descifrado se extrae solo completo: un sobre alterado o cortado no escribe nada |
| Derechos | El plan no mezcla fuentes redistribuibles con fuentes de solo metadatos, y `fetch` no descarga una de licencia desconocida aunque se le pase. La compuerta rechaza cualquier archivo que el paquete no declare: un crudo de más, una segunda copia, un enlace o una nota |
| Robots y cortesía | El `Fetcher` del catálogo: robots.txt, solo los hosts del plan, una petición por segundo por host, 60 MB por cuerpo |
| Archivos hostiles | El texto sale de `rg.text`, con un proceso por archivo y límites de tiempo, tamaño y memoria, en trabajos sin permiso de escritura |
| Superficie | Solo `workflow_dispatch` desde main; `publish` no analiza nada, solo agrega `research-packets/<RP>/` y solo crea su rama: el push lleva una condición atómica de que la rama no exista, así que una rama existente no se mueve ni por avance directo y el head de un PR en auditoría no cambia |
| Registro | Pase lo que pase en `fetch` (descarga o extracción), `fuentes.json` se escribe con lo reunido, cada URL entra al registro antes de pedirse, y el artefacto se sube aunque el paso falle |
| Costo | Dos llamadas al modelo por pedido (la lectura y la revisión, que solo lleva afirmaciones y citas), con 3 turnos como máximo y a lo más 600 000 caracteres de texto por llamada. Si las fuentes juntas pasan de ahí, se leen completas en partes (`partitions`: ventanas que se traslapan 1 000 caracteres para que ninguna cita quede partida; a lo más `MAX_PARTS`, 4, llamadas a la vez) y `reduce` une las respuestas sin reescribir ni inventar nada; solo si ni así caben, cada texto conserva una parte justa (`shares`: los cortos completos, los largos leídos desde su inicio hasta un tope común); el paquete nombra las fuentes recortadas en sus limitaciones y en `receipt.json` (`cut`), y cada cita se comprueba contra el texto completo. Los artefactos de Actions duran un día. Lo demás es código determinista |

## Qué no hace (todavía)

- Las fuentes descubiertas no se revisan a mano antes de bajarlas: por eso todas son `metadata_only` y pasan por los
  mismos guardas. Una fuente descubierta que convendría republicar (`allowed`) necesita un plan revisado.
- No reintenta ni amplía la búsqueda si lo hallado no alcanza: termina en `STOPPED_WITH_GAPS` y lo dice.
- No abre el PR solo. Para eso haría falta un token que cree el dueño; mientras, abrirlo es un comando.
