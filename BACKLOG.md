# Backlog de RESEARCH GROUP

Lo diferido, cada cosa con su condición de reapertura (forma C de `ORDENES-RG.md`). Nada de aquí se trabaja hasta que
su condición se cumpla y pase a `COLA.md`.

| Diferido | Origen | Se reabre cuando |
|---|---|---|
| Motores `sitemap` y `rastreo` | ORDENES-RG §2 | una fuente con `consumer` los pide (reglas 21 y 23) |
| Diff semántico del DOF y watchers externos | ORDENES-RG §2 | un pedido abierto necesita saber qué cambió dentro de una nota, no solo que cambió |
| Resolución de entidades entre fuentes y casi-duplicados | ORDENES-RG §2 | los identificadores canónicos (hueco 6) están en `main` y un pedido cruza dos fuentes |
| Caza de contradicciones | ORDENES-RG §2 | un paquete tiene hallazgos `conflicting` que su consumidor no puede resolver |
| Explorador de capacidades como flujo | ORDENES-RG §2 | un `CapabilityDemand` autorizado lo necesita |
| Artefactos privados con alcance por cliente (§59–61) | ORDENES-RG §2 | un consumidor con datos privados está en `requests/` |
| Crudo sellado en un almacén privado (R2) | #101: re-bajar del origen dio 29/42 en #80; 13 citas de páginas que cambian en cada petición | el dueño aprueba usar R2 |
| Migrar al módulo único las 17 llamadas con llave a terceros de la lista con fecha de #96 | #96, decisión del dueño 2026-11-02 | un consumidor necesita la fuente migrada; la lista solo baja |
| Cambios como eventos acotados: `ChangeEvent` por nota NOM nueva y por ETag cambiado (hueco 5) | `docs/CIERRE-HUECOS.md` §3 | uno de los cinco huecos activos de `docs/NORTE.md` cierra (regla 28), o un pedido necesita "qué cambió en X" |
| Identificadores canónicos mínimos: ley, artículo, linaje NOM, municipio, fuente (hueco 6) | `docs/CIERRE-HUECOS.md` §3 | uno de los cinco activos cierra; va antes que los cambios como eventos |
| `freshness` en el registro y `no_encontrado` en `receipt.json` (hueco 8, parte A) | `docs/CIERRE-HUECOS.md` §3 | uno de los cinco activos cierra |

