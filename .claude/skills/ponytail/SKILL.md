---
name: ponytail
description: Código mínimo antes de escribir código: hace falta, ya existe, lo da la stdlib, se modifica o borra algo; solo entonces lo mínimo con su prueba.
---

# /ponytail — el código más chico que funciona

Idea de github.com/DietrichGebert/ponytail (MIT, v5.3.2; ver THIRD_PARTY_NOTICES.md), reescrita para RESEARCH GROUP.

Escalera (parar en el primer peldaño que resuelve):
0. Leer el código y el flujo real que se toca.
1. ¿Hace falta? Si nadie lo pidió y el contrato no lo exige, no se escribe; se nombra en una línea.
2. ¿Ya existe en el repo (fetcher, store, categorize, schemas)? Reusar.
3. ¿Lo da la biblioteca estándar o una dependencia ya instalada? Usarla. Nunca una dependencia por unas líneas.
4. ¿Se resuelve modificando o borrando algo? Borrar gana a agregar.
5. Solo entonces lo mínimo, con la prueba que falla sin ello.

Atajo con límite conocido: comentario `shortcut: <el límite>, <cuándo mejorarlo>`.
Nunca se recorta: guardas del fetcher, cuadre de cobertura, procedencia (url, fecha, sha256), validación de esquemas,
manejo de errores que evita pérdida de datos, pruebas.
