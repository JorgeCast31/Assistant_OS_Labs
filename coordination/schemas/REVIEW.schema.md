# REVIEW.schema — coordination/reviews/TASK-NNNN.REVIEW.md — **v2**

Veredicto del **revisor** (distinto del ejecutor). Marca la transición a `IN_REVIEW` y, según el resultado, a `CHANGES_REQUESTED` o `DECISION_PROPOSED`.
Nombre de archivo: `TASK-NNNN.REVIEW.md`.

## Front-matter

```yaml
id: TASK-NNNN-...                 # required
agent: codex | claude              # required (revisor; ≠ ejecutor)
acting_as: reviewer | reviewer_delegate   # required; si delegate, debe estar registrado in-file en TASK
reviewed_report: reports/TASK-NNNN.FINAL_REPORT.md   # required
authority: proposed                # required (siempre 'proposed')
proposed_decision: NEEDS_CHANGES    # required, enum: GO | NO-GO | NEEDS_CHANGES
resulting_status: CHANGES_REQUESTED  # required, enum: IN_REVIEW | CHANGES_REQUESTED | DECISION_PROPOSED
created_at: 2026-06-14              # required
```

## Secciones (required)

```
## 1. Alcance revisado            # qué evidencia/archivos se revisaron
## 2. Verificaciones              # qué se comprobó y resultado (verificable, no "looks good")
## 3. Objeciones                  # técnicas, concretas, refutables; vacío explícito si no hay
## 4. Riesgos no cubiertos
## 5. Veredicto propuesto         # GO | NO-GO | NEEDS_CHANGES + justificación
```

## Reglas (fail-closed)

1. El revisor **no edita** el WORKLOG/FINAL_REPORT del ejecutor; los referencia.
2. Veredicto es **propuesto** (`authority=proposed`); no es decisión humana.
3. Las objeciones deben ser **verificables**, no estilísticas vagas. "Aprobado sin más" no es revisión válida si había superficie que verificar.
4. El revisor no puede mover la tarea a `HUMAN_DECISION`; como máximo deja `DECISION_PROPOSED` (o `CHANGES_REQUESTED` para devolver al ejecutor).
5. `NEEDS_CHANGES` / `CHANGES_REQUESTED` devuelven la pelota al ejecutor; no es una orden, es una propuesta refutable técnicamente.
6. **No auto-review:** el `agent` del REVIEW debe ser distinto del `assigned_agent`. Si `acting_as: reviewer_delegate`, ese delegate debe estar registrado **in-file (en `main`) antes** del REVIEW; si no, el REVIEW es **inválido**.
