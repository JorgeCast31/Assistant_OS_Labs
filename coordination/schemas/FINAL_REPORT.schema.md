# FINAL_REPORT.schema — coordination/reports/TASK-NNNN.FINAL_REPORT.md — **v2**

Reporte de cierre de evidencia del **ejecutor**. Marca la transición a `EVIDENCE_READY` (caso normal) o documenta un **fallo/retracción** (caso de dogfood fallido).
Nombre de archivo: `TASK-NNNN.FINAL_REPORT.md`. Sigue el formato de entrega del proyecto.

## Front-matter

```yaml
id: TASK-NNNN-...                 # required
agent: claude | codex              # required (ejecutor)
authority: proposed                # required (siempre 'proposed' para agente)
status_at_report: EVIDENCE_READY    # required, enum: EVIDENCE_READY | BLOCKED | <last_legit_status retractado>
                                    #   admite reportes de fallo (v2, cierra B4/F5)
created_at: 2026-06-14              # required
```

## Secciones (required)

```
## 1. Estado del sistema        # qué funciona / qué no
## 2. Hallazgos                  # problemas detectados
## 3. Cambios realizados         # archivo + motivo + impacto (en rama coordination/task-NNNN)
## 4. Validaciones               # tests/comprobaciones, con resultado real
## 5. Riesgos residuales         # qué no se resolvió
## 6. Decisión propuesta         # GO | NO-GO | NEEDS_CHANGES  (authority=proposed)
```

### Banner de fallo/retracción (v2)
Si el reporte documenta un dogfood fallido o una retracción, encabezar con un banner que:
- declare que **NO es éxito** y **NO valida** el siguiente tramo;
- indique el `status` real tras la retracción y el `blocked_reason`;
- preserve abajo el análisis original como evidencia (sin borrarlo).

## Reglas (fail-closed)

1. La "Decisión propuesta" es **propuesta**, nunca final. `authority=proposed`.
2. Sin éxito fabricado: si una validación no corrió o quedó `unavailable`, se dice explícitamente.
3. Cambios solo en rama `coordination/task-NNNN`; nunca afirma haber tocado `main` ni MSO/Police/Policy/Auth.
4. Debe referenciar el `WORKLOG` y la `evidence` que respaldan cada afirmación.
5. Producir este reporte habilita al revisor; **no avanza por sí solo** a `HUMAN_DECISION` ni hace real ningún estado fuera de `main`.
6. **Admite reportes de fallo:** `status_at_report` no está hardcodeado a `EVIDENCE_READY`; un reporte puede cerrar en `BLOCKED` o reflejar una retracción (v2, corrige la rigidez de v1 que impedía documentar el fallo).
