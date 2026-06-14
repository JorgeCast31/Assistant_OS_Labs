# FINAL_REPORT.schema — coordination/reports/<task-id>.FINAL_REPORT.md

Reporte de cierre de evidencia del **ejecutor**. Marca la transición a `EVIDENCE_READY`.
Sigue el formato de entrega del proyecto.

## Front-matter

```yaml
id: TASK-0001-...                 # required
agent: claude | codex              # required (ejecutor)
authority: proposed                # required (siempre 'proposed' para agente)
status_at_report: EVIDENCE_READY    # required
created_at: 2026-06-13              # required
```

## Secciones (required)

```
## 1. Estado del sistema        # qué funciona / qué no
## 2. Hallazgos                  # problemas detectados
## 3. Cambios realizados         # archivo + motivo + impacto (en rama agent/<id>)
## 4. Validaciones               # tests/comprobaciones, con resultado real
## 5. Riesgos residuales         # qué no se resolvió
## 6. Decisión propuesta         # GO | NO-GO | NEEDS_CHANGES  (authority=proposed)
```

## Reglas (fail-closed)

1. La "Decisión propuesta" es **propuesta**, nunca final. `authority=proposed`.
2. Sin éxito fabricado: si una validación no corrió o quedó `unavailable`, se dice explícitamente.
3. Cambios solo en rama `agent/<id>`; nunca afirma haber tocado `main` ni MSO/Police/Policy/Auth.
4. Debe referenciar el `WORKLOG` y la `evidence` que respaldan cada afirmación.
5. Producir este reporte habilita al revisor; no avanza por sí solo a `HUMAN_DECISION`.
