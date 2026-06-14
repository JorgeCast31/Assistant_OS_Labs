# REVIEW.schema — coordination/reviews/<task-id>.REVIEW.md

Veredicto del **revisor** (distinto del ejecutor). Marca la transición a `UNDER_REVIEW`.

## Front-matter

```yaml
id: TASK-0001-...                 # required
agent: codex | claude              # required (revisor; ≠ ejecutor)
reviewed_report: reports/<id>.FINAL_REPORT.md   # required
authority: proposed                # required (siempre 'proposed')
proposed_decision: NEEDS_CHANGES    # required, enum: GO | NO-GO | NEEDS_CHANGES
created_at: 2026-06-13              # required
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
4. El revisor no puede mover la tarea a `HUMAN_DECISION`; como máximo deja `DECISION_PROPOSED`.
5. `NEEDS_CHANGES` devuelve la pelota al ejecutor; no es una orden, es una propuesta refutable técnicamente.
