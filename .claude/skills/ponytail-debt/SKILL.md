---
name: ponytail-debt
description: Cosechar los comentarios shortcut: en un registro de deuda con su techo y su disparador, para que "después" no se vuelva "nunca".
---

# /ponytail-debt — registro de deuda

Adaptado de commands/ponytail-debt.toml de github.com/DietrichGebert/ponytail (MIT, v5.3.2).

Buscar en todo el árbol los marcadores `shortcut:` (y los viejos `ponytail:`) en comentarios
(git grep -nE '(#|//|/[*]) ?(shortcut|ponytail):'), ignorando lo que .gitignore excluye. Una fila por marcador,
agrupada por archivo: <archivo>:<línea> — <qué se simplificó>. techo: <límite>. mejora: <disparador>.
Marcar sin-disparador los que no dicen cuándo mejorar. Cerrar con el conteo y cuántos no tienen disparador.
Si no hay: "Sin deuda de atajos." Solo reportar, no cambiar nada.
