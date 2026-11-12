# Aportes por conversación (contrato)

**Estado: contrato, nada construido.** Ninguna garantía de este documento está vigente hasta que llegue su PR con sus
pruebas: `scripts/aporte_clase.py` (la regla de clases), la cuarentena del AX42 (extracción y clasificación sobre los
bytes, borrado siempre), `aportes.yml` (guardado en R2 desde main) y su enlace con `investigar.yml`. Hasta entonces, RG no acepta aportes.

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

## Tres clases, decididas sobre los bytes antes de que el archivo toque Git o R2

| Clase | Ejemplos | Destino |
|---|---|---|
| `PUBLIC_EXTERNAL` | leyes, NOM, reglamentos, decretos, publicaciones y estadísticas oficiales, manuales públicos, documentación técnica publicada, investigación abierta | corpus de RG, si la procedencia y los derechos lo permiten |
| `PRIVATE_ORGANIZATIONAL` | cotizaciones o contratos de clientes, facturas, finanzas internas, documentos internos, correos, bases de clientes, expedientes personales, credenciales | nunca entra a RG; se responde que no se incorpora y no se guarda nada de él |
| `MIXED_OR_UNVERIFIED` | oficial con datos personales, de circulación restringida, sin procedencia suficiente, público con anexos privados, con dudas de redistribución | cuarentena: no se sella ni va a Git ni a R2, no se guarda; se pide la decisión que falte |

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
3. **Clasificación sobre los bytes, antes de que el archivo toque Git o R2** (GPT en 5399912: un texto que el agente
   entrega no está atado a los bytes). El agente copia el adjunto por SSH a una carpeta de cuarentena del servidor de RG
   (AX42: sin llaves de GitHub ni de R2), donde `rg.text` lo extrae bajo T12, como usuario sin privilegios, y
   `scripts/aporte_clase.py` aplica la regla a ese texto y al pedido, sin red. El agente solo recibe la clase, los
   motivos y el sha256, y el archivo se borra del servidor con cualquier clase. Lo que el agente lea del adjunto en el
   chat sirve para avisar, nunca para decidir ni subir la clase. `PRIVATE_ORGANIZATIONAL` y `MIXED_OR_UNVERIFIED`
   terminan aquí: nada se sella y nada va a Git ni a R2.
4. **Duplicado:** si el sha256 ya es un crudo de RG (`RawStore`, `catalog_entry.versions` o un objeto sellado en R2),
   se relaciona con lo que ya hay y no se guarda otra copia.
5. **Preservar el original, solo si es `PUBLIC_EXTERNAL`:** se sella con la llave pública (`scripts/sobre.sh seal`,
   sin abrirlo) y se empuja a una rama `aporte/<sha>` con dos archivos y nada más: `aportes/<sha>.sobre` (cifrado) y
   `aportes/<sha>.json` (el registro del paso 6, sin texto del documento). `aportes.yml` corre con `workflow_dispatch`
   desde main: su código y sus scripts son siempre los de main y la rama solo aporta esos dos archivos como datos
   (nunca se ejecuta nada de ella). Comprueba nombres, tamaños y que el sha256 del sobre abierto sea el del registro
   (`scripts/sobre_partes.py externo`; la llave privada solo en ese paso, que no extrae ni parsea), guarda el sobre en
   R2 como cualquier crudo (`sealed/sha256/<aa>/<sha>/<sha256 de su URL>.sobre`, T31) con la llave de escritura en un
   solo paso y una escritura condicional, y borra la rama. Residual: quien puede empujar al repo puede guardar un sobre
   falso, como un fetch tomado; el lector de R2 vuelve a comprobar sha256 y URL al abrir.
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

recibido → clasificado (sobre sus bytes, en la cuarentena aislada) → incorporado → información extraída → paquete
candidato con formato, procedencia y citas comprobados → criterio promovido (solo ZPMND decide). Ni el gate ni los
auditores validan la verdad de un paquete: comprueban su forma, su procedencia y que cada cita esté en su fuente. Un aporte cuyos bytes no coinciden con una copia obtenida de la fuente oficial queda
como `aportado; procedencia declarada, no verificada por bytes` y nunca se presenta como fuente oficial verificada; si
la fuente oficial se puede bajar después, se comparan los sha256.

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

A y D–F se prueban con fixtures en `tests/`; B y C, con la cuarentena sobre una factura y un oficio con CURP: ninguno
produce sobre, rama ni registro, y el servidor no conserva el archivo. El aislamiento se prueba también: `aportes.yml`
no ejecuta nada de la rama `aporte/<sha>` y su llave privada no llega al paso que lee el registro.
