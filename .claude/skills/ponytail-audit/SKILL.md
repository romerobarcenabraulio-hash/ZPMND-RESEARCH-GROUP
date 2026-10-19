---
name: ponytail-audit
description: Auditoría de calidad de todo el repo como quien lo acaba de heredar: bugs, seguridad, escala, pruebas, velocidad, código sobrante. No cambia código.
---

# /ponytail-audit — auditoría del repo

Adaptado de commands/ponytail-audit.toml de github.com/DietrichGebert/ponytail (MIT, v5.3.2).

Mapear primero: README, contrato, seguridad, dependencias, puntos de entrada (rg.catalog.run, rg.advisories,
rg.openclaw_policy), pruebas y flujos de CI; la carga esperada. Leer completas las rutas con entrada externa (fetcher,
parsers), escrituras de datos y trabajos programados. Buscar en orden: bugs, riesgo, escala, lógica riesgosa sin prueba,
lentitud, código sobrante. Antes de llamar algo "sin uso", buscar en todo el árbol, pruebas y configuración incluidas.
Cada hallazgo con caso concreto; arreglo más chico; preferir borrar.
Formato: "Qué hace este repo:" y la carga supuesta; máximo 20 hallazgos en Debe / Debería / Sería bueno con las cuatro
viñetas; "Veredicto:", "Ligero: -N líneas, -M dependencias posibles." y "No revisado:". No cambiar código.
