# La bandeja de salida es Git

RG publica y quien consume jala. RG no escribe en el repositorio del consumidor ni sabe quién es. Esta página es el
contrato del lado de RG. Cómo lo importe ZPMND y qué signifique es asunto suyo; aquí no se declara cerrado ese puente.

## Qué cuenta como aceptado

Un paquete está aceptado cuando su `research-packets/<RP>/packet.json` está en `main`. Llega ahí por un PR: lo fusiona el
dueño, o `automerge.yml` si es solo de datos, viene de su propia rama `investigar/<RP>` y las corridas confiables de CI y
del auditor (con `pass-both`, los dos veredictos PASS) pasaron en ese head (SECURITY T15). Estar en `main` no prueba más
que eso: qué compuertas pasó cada PR está en sus checks, no en el paquete. Un paquete publicado no
cambia: `automerge.yml` solo fusiona archivos de paquete agregados, nunca modificados ni borrados, y el consumidor solo
toma un paquete cuya carpeta entera tiene un único commit en `main`, el que agregó su `packet.json`. Si después cambia o
se borra cualquier archivo de la carpeta (el paquete, el recibo o un crudo), el consumidor lo reporta y no lo toma. Una corrección es otro paquete, con otro `research_id`. Su `status`
sigue siendo `CANDIDATE`: aceptado quiere decir "pasó las compuertas de RG", no "es verdad".

## Qué sale de Git, sin manifiesto aparte

`scripts/consumidor.py` es un consumidor de ejemplo. Usa solo la API REST de GitHub, ningún módulo de RG:

| Lo que el consumidor necesita | De dónde sale |
|---|---|
| paquetes nuevos o cambiados desde un cursor | los commits de la historia de `research-packets/` que la comparación `<cursor>...main` nombra (todos, contados contra el total de GitHub), y los archivos de cada uno, página por página |
| commit de publicación | el único commit de `main` en la historia de `research-packets/<RP>/`, que agrega su `packet.json` |
| `research_id`, `request_id`, `status` | `packet.json` en ese commit |
| bytes exactos | `packet.json` y `receipt.json` en ese commit, con su sha256 (un paquete hecho a mano no trae recibo) |
| identidad del esquema | sha256 de `schemas/research_packet.schema.json` y `schemas/source_artifact.schema.json` en ese commit |
| artefactos | `artifacts` del paquete: id, sha256 declarado, redistribución, URL y la ruta del crudo cuando el repositorio lo guarda, del árbol git completo de `raw/` (si GitHub lo da truncado, la lectura se detiene sin cursor; el consumidor no recalcula el hash del crudo; quien lo descargue lo compara) |
| siguiente cursor | el commit de `main` que se leyó |

## Compatibilidad: falla cerrada

El consumidor declara los pares de digests de esquema que acepta (`--accept <research_packet>:<source_artifact>`). Un
paquete validado con otro par sale como `schema_not_accepted`, con sus digests, para que el consumidor lo revise antes de
tomarlo. No hay registro de esquemas aparte: el commit de publicación lo fija.

Lo que `CLAUDE.md` llama manifiesto con hashes es esto: `packet.json` (el sha256 de cada artefacto) y `receipt.json`,
fijados por su commit de publicación. Ya no hay carpeta `manifests/`.

## Cuando GitHub no contesta o contesta a medias

Una lectura que GitHub no pudo contestar ahora (5xx, límite 403/429, red, una respuesta cortada o ilegible) detiene todo: salida 75, ni una línea ni
cursor, y la siguiente llamada lee el mismo rango otra vez. Un rango que GitHub solo listaría en parte (el cursor no está
detrás de `main`, el conteo de commits no cuadra, un commit con 3000 archivos o más) también se detiene: salida 3, sin
cursor. Una respuesta permanente sobre un paquete (un 404 de su `packet.json`, un `research_id` que no es su carpeta)
es su rechazo y los demás siguen. Un `packet.json` que no se puede leer como JSON se vuelve a leer: en `main` pasó la
compuerta, así que llegó cortado. El token, si hace falta, sale de `GH_TOKEN` o `GITHUB_TOKEN`, nunca de la línea de
comandos; una redirección solo se sigue a https, y el token se quita si lleva a otro host.

## Constancia de origen

Cada archivo de `research-packets/` en `main` lleva una constancia firmada (Sigstore, la de GitHub) por
`.github/workflows/constancia.yml`, corrida desde `main` en un runner de GitHub (SECURITY T20). Con ella el consumidor
comprueba por su cuenta, sin creerle a RG, que un archivo es byte por byte el que publicó `main`:

```
gh attestation verify research-packets/<RP>/packet.json -R romerobarcenabraulio-hash/ZPMND-RESEARCH-GROUP \
  --signer-workflow romerobarcenabraulio-hash/ZPMND-RESEARCH-GROUP/.github/workflows/constancia.yml \
  --source-ref refs/heads/main --deny-self-hosted-runners
```

Pasa con el archivo publicado y falla con una copia a la que le cambió un solo byte; cada corrida del flujo hace esas dos
pruebas al final y se pone en rojo si alguna no da. Solo `-R` ya prueba que lo firmó un flujo de este repositorio; los
otros tres fijan cuál (este), desde dónde (`main`) y en qué máquina (las de GitHub). La constancia llega minutos después
del merge (al empujar a `main`, al terminar `automerge.yml`, y cada día por si se escapó alguno): un archivo que todavía no
la tiene falla la verificación, y se vuelve a intentar después. Prueba origen e integridad, no verdad: el paquete sigue
siendo `CANDIDATE`.

## Probarlo

```
python3 scripts/consumidor.py --repo romerobarcenabraulio-hash/ZPMND-RESEARCH-GROUP --since <commit>
```
