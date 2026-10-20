---
name: ponytail-review
description: Revisión de los cambios actuales como el senior al que llaman cuando se rompe: bugs, riesgo, escala, lógica sin prueba, lentitud, código sobrante. No cambia código.
---

# /ponytail-review — revisión de cambios

Adaptado de commands/ponytail-review.toml de github.com/DietrichGebert/ponytail (MIT, v5.3.2).

Revisar lo que Braulio nombre; si no nombra nada, los cambios sin commit o el último commit. Primero leer lo que el cambio
toca: quién llama a cada función cambiada, qué llama, las pruebas. Buscar, en orden: bugs (resultado incorrecto, caída,
caso borde, un llamador roto), riesgo (seguridad, pérdida de datos, una guarda saltada), escala (carreras, trabajo repetido,
memoria que crece), lógica riesgosa sin prueba, lentitud, código sobrante (lo que ya existe, lo que da la stdlib).
Cada hallazgo con un caso concreto, releyendo las líneas. Un `shortcut:` con su límite es una decisión, no un hallazgo.
Arreglo más chico; preferir borrar. Español simple.
Formato: "Qué hace este cambio:" (2-3 frases y la carga supuesta); hallazgos numerados en Debe arreglarse / Debería /
Sería bueno, cada uno con título en negritas con archivo:líneas y cuatro viñetas (Qué es, Problema, Arreglo, Si no lo hacemos);
cerrar con "Veredicto:" y "No revisado:". Sin hallazgos: "Se ve bien. Adelante." No cambiar código.
