# Texto de los crudos (`rg.text`)

El contrato de #12 pide que cada cita de un ChangeEvent o de una relación exista literal en el texto que da un
extractor fijado (`nombre==versión`) para el crudo con ese sha256. Un PDF o un DOC no son texto: este extractor los
convierte. No resume, no interpreta y no hace OCR.

## Formato por bytes, extractor por formato

El formato sale de los bytes iniciales, nunca de la extensión. #12 midió que 917 archivos ".doc" son DOCX, 6 son RTF,
algunos ".bin" son PDF y un ".pdf" era HTML.

| Bytes iniciales | Formato | Extractor | Qué hace |
|---|---|---|---|
| `PK\x03\x04` con `word/document.xml` | docx | `rg-docx==1` | zipfile y ElementTree (stdlib): cuerpo, notas al pie y notas finales. Omite el texto borrado o movido, los códigos de campo y la copia de respaldo del contenido alterno |
| `%PDF-` en los primeros 1024 bytes | pdf | `rg-pdf==1+pypdf.6.21.1` | pypdf, página por página; guarda dónde empieza y acaba cada página |
| marcado HTML | html | `rg-html==1` | html.parser (stdlib). Quita script y style; los bloques cortan línea y las celdas se separan con tabulador. Charset: BOM UTF-8; si no, UTF-8 válido; si no, el declarado (salvo que diga UTF-8 y no lo sea); si no, windows-1252. Decodifica con `decode_html` del catálogo |
| OLE2 (Word 97), `{\rtf`, otro zip, JSON, lo demás | ole2, rtf, zip, json, otro | `rg-sniff==1` | sin texto |

Después, todo texto pierde los caracteres invisibles (`clean_text` del catálogo, contados en `invisibles_removed`),
queda con a lo más una línea en blanco seguida y se normaliza a NFC. Fuera de los invisibles solo cambia el espacio en
blanco, así que el texto plegado contra el que se buscan las citas no cambia.

**Versiones.** La versión de un extractor sube cada vez que su salida puede cambiar. `tests/test_texto.py` fija el
sha256 del texto de cinco fixtures (`GOLDEN`) y falla hasta que se suba. Las líneas con una versión anterior se rehacen
en la siguiente corrida. Cada paquete hecho guarda las versiones con que se hizo; si una versión sube, el paquete vuelve
a estar pendiente aun con `bundles: nuevos`.

## Estados

| Estado | Cuándo | Texto guardado |
|---|---|---|
| `ok` | HTML y DOCX leídos. PDF con capa de texto en al menos el 90 % de sus páginas. Una página tiene texto si da 30 caracteres no blancos o más, la misma regla de la medición de #12 | sí |
| `necesita_ocr` | PDF con menos del 90 % de páginas con texto. DOCX con menos de 30 caracteres y con imágenes | el de las páginas que sí tienen capa; ninguno si no hay ninguna |
| `formato_no_soportado` | Word 97, RTF, zip que no es DOCX, JSON, otro | no |
| `fallo` | archivo roto, PDF con contraseña, tiempo agotado, proceso caído o más de 200 MB | no; `error` dice por qué |

Word 97 y RTF no se leen: no hay una vía solo con stdlib que sea confiable. Son 499 y 7 archivos según #12.

## Por qué pypdf

| | pypdf | pdfminer.six |
|---|---|---|
| Licencia | BSD-3-Clause | MIT |
| Dependencias | ninguna en Python 3.11 o mayor | charset-normalizer y cryptography (compilada) |
| Medido aquí | sí: la medición de #12 usó pypdf | no |

Se fija `pypdf==6.21.1` en `requirements-dev.txt`, que CI ya instala. Es puro Python y es la misma biblioteca de la
medición. 6.21.1 corrige todas las alertas que GitHub publicó contra pypdf hasta el 2026-10-21; la última es
GHSA-5hx5-vpf9-5wcv, que afecta a versiones anteriores a 6.21.1. El nombre del extractor lleva la versión, y una prueba
exige que la versión instalada sea la fijada. Sin `cryptography`, un PDF cifrado con AES queda en `fallo`. No se ha
medido cuántos hay (HIPÓTESIS); cada corrida los cuenta.

## Aislamiento

Cada crudo se lee, se hashea y se extrae en un proceso propio (forkserver). Tiene un límite de tiempo de 300 s
(HIPÓTESIS hasta medirlo), uno de tamaño de 200 MB (un crudo más grande no se lee entero) y uno de memoria: el espacio
de direcciones de cada proceso se limita a 2 GB (HIPÓTESIS hasta medirlo), y no corren más procesos de los que caben en
la memoria de la máquina a ese límite, dejando una parte para el proceso padre. Un PDF chico que se expande sin fin
muere solo, como `fallo`, y el padre escribe lo demás. Así, un archivo hostil o roto solo puede fallarse a sí mismo. Del 16 de junio al 21 de octubre de 2026, GitHub publicó al menos 30 alertas
contra pypdf, casi todas por bucles infinitos, tiempo o memoria; el límite de tiempo es la defensa por construcción. Los bytes que no coinciden con su nombre no reciben
línea.

## Cobertura

Funciona como en el catálogo. Cada crudo que el catálogo referencia (en `raw_path` y en cada versión) y cada archivo
del almacén tienen exactamente una línea. El conteo se hace aparte del ciclo que extrae: el manifiesto se vuelve a leer
del disco. La corrida sale con 3 si hay un crudo sin estado, una línea repetida, una línea hecha por un extractor anterior de su
formato, bytes que no coinciden con su nombre, un texto que no coincide con su sha256, o un paquete de raw-mx que no
pasa su sha256. Un paquete solo se da por hecho cuando todos sus crudos tienen línea del extractor vigente: si una
subida de versión se corta por el plazo, el paquete sigue pendiente y la siguiente corrida lo vuelve a abrir.

## Dónde queda

- **Manifiesto**, en la rama `catalog`: `mx/texto/<primer hex del sha del crudo>.jsonl`, una línea por crudo con
  `raw_sha256`, `bytes`, `format`, `status`, `extractor`, `text_sha256`, `chars` e `invisibles_removed`. Según el caso
  lleva también `charset`, `pages`, `pages_without_text` o `error`. `pages` son pares [inicio, fin) en puntos de código
  del texto. `store.DERIVED` incluye `texto`, así que el catálogo nunca lee estas líneas como registros.
- `mx/texto/bundles.json`: los paquetes de raw-mx ya hechos. `mx/texto/runs/<id>.json`: el reporte de cada corrida,
  con los conteos por estado leídos del disco.
- **Textos**, en el release `text-mx`: un tar por corrida con los textos nuevos, en partes de 1.9 GB, cada una con su
  `.sha256`. Se suben antes del commit. La ruta es el sha256 del texto en UTF-8: `sha256/<2>/<sha>.txt`. El texto no
  cabe en la rama de datos.

## Flujo `texto-mx.yml`

Corre solo a mano (`workflow_dispatch`). La entrada `bundles` acepta `nuevos` (por omisión) o `todos`; `todos` sirve
tras subir la versión de un extractor o para reintentar los `fallo`.

1. Corre las pruebas.
2. Baja de raw-mx los paquetes pendientes. Cada uno se verifica contra su `.sha256`, que puede traer el tar entero, sus
   partes concatenadas o cada parte por separado (raw-mx tiene las tres formas).
3. Desempaca sin token. Solo escribe archivos regulares con nombre `sha256/<2>/<sha>.<ext>`. Un miembro de más de
   200 MB, o de más de lo que queda del presupuesto de la corrida (40 GB entre todos los paquetes, HIPÓTESIS), detiene
   su paquete antes de escribirse; los demás paquetes siguen.
4. Extrae el texto.
5. Sube los textos nuevos.
6. Hace commit solo de `mx/texto`, con rebase sobre lo que catalog-mx haya escrito mientras tanto.

Las acciones van fijadas por SHA y no usa más secreto que `GITHUB_TOKEN`. Usa la variable `CATALOG_RUNS_ON` con las
mismas guardas de runner propio que propone #19. Si #19 entra, `tests/test_costos.py` tiene que aceptar también
`texto-mx.yml`.

## Revisar una cita

```
python -m rg.text.quote relation rel.json --manifest data/mx/texto --text texto
```

El comando:

1. valida el documento con `rg.schemas`;
2. busca la línea del crudo y exige el mismo extractor;
3. verifica el sha256 del texto;
4. busca la cita con el mismo plegado de espacios que el contrato.

Dice dónde la encontró: desplazamientos y página. No está dentro de `rg.schemas`, porque el contrato (#12) valida un
documento solo, sin almacén de texto, y la aduana de ZPMND corre el extractor por su cuenta.

**Medido en el fixture.** pypdf parte palabras: en la página 4 del Reglamento de la LIEPS da "Especial s obre
Producción". La cita se copia del texto extraído, no de la página impresa. No se ha medido cuánto pasa en todo el
corpus (HIPÓTESIS).

## La brecha de OCR: el disparador para rentar cómputo

Aquí no hay OCR. Lo escaneado queda en `necesita_ocr` y cada corrida lo cuenta. #12 estimó, con una muestra, unos 54 PDF
(entre 26 y 109) y unas 1,800 páginas sin capa de texto; es HIPÓTESIS para el total. La primera corrida de `texto-mx`
da el conteo real (`status` en el reporte), y **ese conteo es el disparador para rentar cómputo**. Cuando las páginas
sin capa justifiquen el gasto, se renta CPU o GPU para el OCR. El OCR entra como un extractor nuevo con versión propia
(por ejemplo `rg-ocr==1+<motor>`) y no toca las líneas `ok`. El costo y el tiempo son HIPÓTESIS hasta medirlos.
