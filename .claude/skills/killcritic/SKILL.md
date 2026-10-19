---
name: killcritic
description: Crítico implacable antes de entregar: 3 fallas probables (fuente inventada, cobertura incompleta, categoría inferida), corregir lo obvio, declarar lo no revisado.
---

# /killcritic — crítico implacable antes de entregar

Origen: modo de Goodware, adaptado. Se lee "crítico asesino", no "matar al crítico".

Cómo se aplica:
1. Nombrar las 3 fallas más probables de lo que se entrega. En investigación, las de siempre:
   - una fuente o cita que no se recuperó de verdad (sin url, fecha y sha256 no existe);
   - cobertura incompleta que parece completa (sin cuadre contra el listado oficial no se afirma "todo");
   - una categoría inferida en vez de copiada de la estructura oficial o de una tabla fija.
2. Lo obvio se corrige antes de presentarlo.
3. Lo que no se puede cerrar se declara UNKNOWN o BLOCKED, con su porqué.

Límite: es autocrítica; no reemplaza las pruebas ni el cuadre independiente.
