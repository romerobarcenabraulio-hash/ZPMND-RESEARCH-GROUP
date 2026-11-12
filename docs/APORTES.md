# Aportes por conversación (contrato)

**Estado: contrato, nada construido.** Ninguna garantía de este documento está vigente hasta que llegue su PR con sus
pruebas: `scripts/aporte_clase.py` (la regla de clases), `aportes.yml` (desde main: vuelve a clasificar sobre los
bytes y solo entonces guarda en R2) y su enlace con `investigar.yml`. Hasta entonces, RG no acepta aportes.

Dueño, 2026-11-12: una persona puede ayudar a RG a adquirir un documento oficial **público** que RG no logra bajar solo
(robots.txt lo impide, el sitio responde 403, solo existe impreso). RG lo clasifica, lo preserva, lo estructura y lo
vuelve consultable. Esto **no** autoriza a RG a guardar información personal, privada u organizacional: RG investiga el
mundo externo; los datos privados se quedan en los sistemas del usuario y en el entorno de ZPMND.

Medido el 2026-11-12 en los 16 paquetes de familia: de 185 URLs, 42 no se bajaron; 38 por robots.txt, 3 por 403 y 1
por 429. Casi todas son páginas públicas de dependencias mexicanas (Banxico, CNBV, SCJN, CONAMER, Catálogo Mexicano de
Normas). Donde hay un canal legítimo automatizable (la API SIE de Banxico, la de INEGI) se usa ese canal, no un aporte.

## Cuatro dimensiones independientes

El **origen** del archivo (conversación), su **naturaleza** (pública, privada, restringida o desconocida), la
**autoridad** de la fuente (oficial, secundaria, no verificada) y la **autorización de uso** (permitida, limitada,
pendiente) no se infieren una de otra. Adjuntar un documento no le da autoridad oficial. No todo lo que produce un
gobierno es público.

## Tres clases: se deciden en la conversación antes de que salga un byte, y otra vez sobre los bytes antes de R2

| Clase | Ejemplos | Destino |
|---|---|---|
| `PUBLIC_EXTERNAL` | leyes, NOM, reglamentos, decretos, publicaciones y estadísticas oficiales, manuales públicos, documentación técnica publicada, investigación abierta | corpus de RG, si la procedencia y los derechos lo permiten |
| `PRIVATE_ORGANIZATIONAL` | cotizaciones o contratos de clientes, facturas, finanzas internas, documentos internos, correos, bases de clientes, expedientes personales, credenciales | nunca entra a RG; se responde que no se incorpora y no se guarda nada de él |
| `MIXED_OR_UNVERIFIED` | oficial con datos personales, de circulación restringida, sin procedencia suficiente, público con anexos privados, con dudas de redistribución | cuarentena: no sale de la conversación (nada se sella ni va a Git, a R2, a Actions o al servidor de RG); se pide la decisión que falte |

Regla de construcción: un archivo es `PUBLIC_EXTERNAL` solo si nombra una referencia oficial que RG pidió o tiene en su
catálogo (emisor, título, identificador o fecha) **y** no contiene datos personales ni marcas de documento privado
(factura, CFDI, RFC de receptor, firmas de contrato, encabezados internos). Cualquier duda lo deja en cuarentena; la
clasificación nunca sube de clase por omisión.

## El flujo (canal 1: el chat del dueño con el agente de RG)

1. RG identifica la necesidad y no puede bajar la fuente (una fila del registro en `bloqueada_por_robots` o un crudo
   `no_descargable` en el recibo de un paquete): pide el archivo con su referencia oficial ("Encontré la referencia
   oficial, pero no pude recuperar el archivo; adjúntalo para incorporarlo"). El pedido queda anotado con su pedido de
   investigación (RR), la URL oficial y lo que se sabe de emisor, título, identificador y fecha.
2. La persona lo adjunta en el chat. El agente lo reconoce como respuesta a ese pedido; no se pide una segunda subida,
   ni carpetas, ni scripts.
3. **Clasificación en la conversación, antes de que salga un byte** (GPT en a5bbb4f: copiar el adjunto a un servidor
   de RG para clasificarlo ya lo saca del entorno del aportante). El agente aplica `scripts/aporte_clase.py` (bajado de
   main con `gh api`, sin clonar; `python3 -I`, solo biblioteca estándar, sin red, el texto por stdin, nada escrito) al
   texto que leyó del adjunto y al pedido, y le declara las páginas sin texto; una página sin texto o cualquier duda es
   `MIXED_OR_UNVERIFIED`. El sha256 y el tamaño se calculan sin abrir el archivo. `PRIVATE_ORGANIZATIONAL` y
   `MIXED_OR_UNVERIFIED` terminan aquí: nada se sella y ningún byte va a Git, a R2, a Actions ni al servidor de RG; el
   agente no puede subir de clase lo que la regla bajó. Esta clase solo decide qué sale de la conversación; la que
   admite en R2 es la del paso 5.
4. **Duplicado:** si el sha256 ya es un crudo de RG (`RawStore`, `catalog_entry.versions` o un objeto sellado en R2),
   se relaciona con lo que ya hay y no se guarda otra copia.
5. **Ingreso, solo si el paso 3 dio `PUBLIC_EXTERNAL`: la clase se vuelve a decidir sobre los bytes** (GPT en
   a5bbb4f: una clase que declara el agente no está atada a lo que entra a R2). Se sella con la llave pública
   (`scripts/sobre.sh seal`, sin abrirlo) y se empuja a una rama `aporte/<sha>` con dos archivos y nada más:
   `aportes/<sha>.sobre` y `aportes/<sha>.json` (el registro del paso 6, sin texto del documento). `aportes.yml` corre
   con `workflow_dispatch` desde main (su código es siempre el de main; de la rama solo lee esos dos archivos, como
   datos) y no usa la clase del registro: abre el sobre en un paso que tiene `RG_ARTIFACT_KEY` y no parsea
   (`scripts/sobre_partes.py externo`), exige que el sha256 y el tamaño de lo abierto sean los del registro, extrae con
   `rg.text` bajo T12 en un paso sin llaves y aplica `scripts/aporte_clase.py` a esa extracción y al pedido. Solo si esa
   clase es `PUBLIC_EXTERNAL` y la extracción no tiene páginas sin texto (`pages_without_text` vacío), otro paso, el
   único con la llave de escritura de R2, guarda el sobre tal como llegó (`sealed/sha256/<aa>/<sha>/<sha256 de su
   URL>.sobre`, T31) con escritura condicional. Un registro ausente o inválido, unos bytes que no son los del registro o
   una clase que no es pública dejan R2 sin nada. Con cualquier resultado se borra la rama; el texto extraído muere con
   el runner y la corrida solo deja códigos, la clase y el sha256. Un sobre falso con texto público entra como aporte
   declarado (`verificacion: declarada`), nunca como fuente oficial verificada.
6. **Registro de procedencia, sin cambiar el esquema que lee ZPMND:** en el paquete, un `source_artifact` normal
   (emisor, título, versión, fecha de publicación, licencia y `redistribution` del registro de la fuente, `unknown` →
   `metadata_only`, `stored_at: none`), con `source_type: primary_official` solo si sus bytes coinciden con una copia
   bajada de la fuente oficial y `other` si no; en `receipt.json`, interno de RG, la entrada `aportes`: quién, cuándo,
   la URL oficial declarada, identificador, fecha de vigencia, jurisdicción, la clase, los motivos de
   `aporte_clase.py` y `verificacion: bytes_oficiales | declarada`.
7. **Versión:** si la referencia ya está en el catálogo con otro sha256, el aporte es una versión nueva:
   se agrega a `versions` (nunca reemplaza) y se emite un `change_event` CANDIDATE con señal de revalidación.
8. **Extracción:** `rg.text`, aislada como todo crudo hostil (T12), con su calidad registrada.
9. **Paquete candidato:** `investigar.yml` corre el pedido con ese crudo; el gate verifica cada cita contra él.

## Estados que no se confunden

recibido → clasificado (en la conversación) → incorporado (clasificado otra vez sobre sus bytes en `aportes.yml`) →
información extraída → paquete candidato con formato, procedencia y citas comprobados → criterio promovido (solo ZPMND
decide). Ni el gate ni los auditores validan la verdad de un paquete: comprueban su forma, su procedencia y que cada
cita esté en su fuente. Un aporte cuyos bytes no coinciden con una copia obtenida de la fuente oficial queda como
`aportado; procedencia declarada, no verificada por bytes` y nunca se presenta como fuente oficial verificada; si la
fuente oficial se puede bajar después, se comparan los sha256.

## Barrera de privacidad (la propiedad que prueba cada PR de implementación)

1. Un adjunto que la regla no da por `PUBLIC_EXTERNAL` en la conversación no sale de ella.
2. Nada entra a R2 por esta vía sin que `aportes.yml`, con el código de main, haya abierto esos mismos bytes, comprobado
   su sha256 y obtenido `PUBLIC_EXTERNAL` de su propia extracción.
3. Lo que el paso 5 rechaza no deja copia en R2 ni texto fuera del runner.

Residuales: la lectura del agente puede no ver lo que la extracción ve (un anexo con CURP que se le pasó); entonces el
sobre llegó a la rama antes de ser rechazado: solo texto cifrado a la llave de RG, borrado con la rama, aunque GitHub
puede servir un commit sin rama por su sha durante un tiempo. El agente actúa con la sesión de GitHub del dueño: uno que
se salte el paso 3 puede empujar cualquier archivo, cifrado o no, a cualquier rama, y ningún diseño de RG lo impide; lo
que RG garantiza entonces son 2 y 3. La regla es una lista de marcas: un documento privado que solo reproduce el texto
oficial pedido y no tiene ninguna pasa como público.

## Fuera de este contrato

- La extracción a artículos, fracciones, definiciones y tablas con vínculo al original: no existe en RG; es una
  demanda a ZPMND (decide si integra, adapta o construye). Nada de un MCP por PDF.
- El canal 2, adjuntos desde la conversación de ZPMND: ZPMND clasifica en su entorno y entrega a RG solo lo
  `PUBLIC_EXTERNAL`, con este mismo registro.
- Un campo nuevo en `source_artifact` para los aportes: cambiaría el contrato que ZPMND valida; si hace falta, se pide.

## Pruebas de aceptación (cada una, una prueba)

| Caso | Entrada | Resultado |
|---|---|---|
| A | documento oficial público pedido por RG | incorporado: sellado en R2, `source_artifact` aportado, extracción y paquete candidato |
| B | factura de una empresa | `PRIVATE_ORGANIZATIONAL`: no se incorpora, nada se sube ni se guarda |
| C | documento oficial con datos personales | `MIXED_OR_UNVERIFIED`: cuarentena, nada sale de la conversación |
| D | un documento que RG ya tiene | duplicado detectado por sha256: se relaciona, sin copia nueva |
| E | versión nueva de una disposición | versión agregada, historial intacto, `change_event` con revalidación |
| F | PDF que aparenta ser oficial sin origen verificable | si nombra la referencia pedida: `source_type: other`, `verificacion: declarada`, nunca fuente oficial verificada; si no nombra ninguna: cuarentena |
| G | rama de aporte sin registro o con uno inválido | nada en R2; rama borrada |
| H | registro de un documento público con otros bytes en el sobre | sha256 distinto: nada en R2; rama borrada |
| I | registro `PUBLIC_EXTERNAL` de bytes cuya extracción tiene una CURP o una página sin texto | manda la clase del ingreso: nada en R2; rama borrada |

A y D–I se prueban con fixtures en `tests/`; B y C, con `aporte_clase.py` sobre los textos de una factura y de un oficio
con CURP: ninguno produce sobre, rama ni registro. El aislamiento se prueba también: `aportes.yml` no ejecuta nada de la
rama `aporte/<sha>`, `RG_ARTIFACT_KEY` y la llave de escritura de R2 están en pasos distintos y ninguna en el que extrae.
