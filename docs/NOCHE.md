# La noche (`noche.yml`)

RG trabaja mientras el dueño duerme sin que nadie despache, transporte ni abra PRs. Git y el estado de GitHub son la cola:
no hay base de datos ni servicio.

## Despachar (23:30, Ciudad de México)

`scripts/noche.py despachar` lee los `requests/RR-*.json` de `main`. Un pedido queda pendiente salvo que:

- un paquete en `main` ya lo responda (el `request_id` de su `packet.json`, se llame como se llame la carpeta);
- exista la rama `investigar/RP-…` o un PR abierto desde ella;
- haya una corrida de `investigar` para él en cola o corriendo (se reconoce por su nombre, `investigar RR-…`);
- una corrida suya haya terminado sin éxito (fallida, cancelada, vencida) en los últimos 3 días, contados desde que
  terminó y no desde que se creó: espera a una persona en vez de
  gastar el modelo cada noche. Las corridas de antes de que existiera el nombre `investigar RR-…` no se reconocen: un pedido
  que falló entonces se intenta una vez más;
- exista `requests/terminal/RR-….json`, que lo marca cerrado a mano;
- no sea `PUBLIC` ni `ABSTRACTED` (nunca sale a investigar).

Los pendientes van por prioridad (P0 primero), luego el más antiguo y luego el id. Arrancan a lo más 4 (HIPÓTESIS:
se sube solo con una noche medida), con `discover` si el pedido no tiene plan revisado. El registro se toma antes del
primer envío y guarda el pedido en vuelo antes de cada envío y cada arranque al momento: si un envío falla, los demás quedan registrados, el job termina en rojo y el
registro se sube igual. Cada corrida arrancada se espera (30 s de reloj por corrida) hasta que GitHub la lista, así un despachador
posterior la ve y no la arranca dos veces; la que no aparece queda como `unconfirmed` y el job termina en rojo. Si se perdió la
respuesta de un envío pero GitHub lista la corrida, cuenta como arrancada. Un duplicado que aun así pasara publicaría con
el mismo nombre de paquete, y la rama de `investigar` solo se crea: no publica dos veces. El paso de despacho tiene su
propio límite de tiempo dentro del job, así que el registro se sube aunque GitHub esté lento. Una prueba (`dry_run`) se llama
`noche despachar (prueba)` y el resumen nunca la toma.

## El PR sin manos

`investigar.yml` termina con el job `pr`. Es el único que tiene un token de la GitHub App del repositorio: dura poco,
solo `pull-requests: write` y `contents: read`, y su llave está en el entorno `rg-pr`, que solo puede usar `main`. Se
emite después de que la compuerta pasó y la rama se publicó. El job no lee código ni crudos y solo abre el PR; desde ahí
siguen CI, los dos auditores y `automerge.yml` si el PR es solo de datos. Sin la App configurada no abre nada y lo dice.
Un PR abierto con `GITHUB_TOKEN` no arranca ningún flujo, por eso hace falta la App.

## Resumen (07:00)

`scripts/noche.py resumen` toma el registro del último despacho y escribe `noche.json` y `noche.md` como artefacto y en
el resumen del job:

- pendientes al empezar, despachadas, iniciadas, terminadas y fallidas;
- paquetes producidos y cuáles terminaron `STOPPED_WITH_GAPS`. Un recibo que no se pudo leer (429, 500, red, JSON
  inválido) no cuenta como paquete sin huecos: queda en `stop_unread`, el Markdown dice que la cuenta está incompleta
  y el paso sale en rojo, con el registro subido igual. Solo un 404 (la cabeza no tiene recibo) es "sin etapa";
  se lee el recibo de cada paquete publicado esa noche, tenga PR o no (la App puede faltar o el PR no abrirse): el
  paquete se halla por el commit que hace publish ("Paquete <RP> (investigar.yml, corrida <id>)") en su rama o en su
  PR, y una corrida cuyo paquete no se halla queda en `stop_unread` como `corrida <id>`. Si GitHub falla a la mitad
  (también un cuerpo cortado, `IncompleteRead`), `noche.json` y `noche.md` dicen que el resumen no se completó y el paso
  sale en rojo;
- el registro del despacho: si GitHub no lista las corridas del despacho, o la corrida hallada no deja un registro
  legible, `noche.json` lo dice (`despacho_problem`), la noche se cuenta con lo que GitHub lista (las últimas 24 horas)
  y el paso sale en rojo. El paso escribe un registro provisional antes de todo, así que aunque falle antes de leer la
  noche siempre se sube uno que dice que la noche no se conoce;
- PRs abiertos, auditorías pasadas (el job `pass-both` de la corrida confiable más nueva de `auditor.yml`, la de
  `pull_request_target` en esa cabeza y esa rama, porque GitHub vacía la lista de PRs de la corrida al fusionarse; un
  check con ese nombre de otro origen no cuenta) y paquetes fusionados;
- envíos que fallaron y corridas que GitHub no llegó a listar;
- intervenciones manuales: PRs que abrió una persona;
- tiempo de cada etapa de cada corrida.
