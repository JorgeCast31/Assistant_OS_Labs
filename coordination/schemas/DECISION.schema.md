# DECISION.schema — coordination/decisions/TASK-NNNN.DECISION.md — **v2**

Decisión **final humana**. **Solo Jorge** la escribe. Marca la transición a `HUMAN_DECISION`.
Nombre de archivo: `TASK-NNNN.DECISION.md`.

> **Nota de alcance:** este schema describe el artefacto; **ningún agente** crea `DECISION.md`. Este PR documental **no** crea ninguna `DECISION`.

## Front-matter

```yaml
id: TASK-NNNN-...                 # required
decided_by: jorge                  # required, debe ser 'jorge'
authority: human_final             # required, único lugar donde aparece human_final
decision: APPROVED                 # required, enum: APPROVED | REJECTED
resulting_status: HANDOFF_TO_MSO    # required: HANDOFF_TO_MSO (si APPROVED) | CLOSED_REJECTED (si REJECTED)
pr_ref: null                        # ref del PR aprobado/mergeado que materializa la decisión
decided_at: 2026-06-14              # required
```

## Cuerpo

```
## Decisión
## Justificación
## Condiciones / alcance autorizado
## Qué NO se autoriza
```

## Reglas (fail-closed) — críticas

1. **Solo Jorge.** `decided_by` debe ser `jorge`. Cualquier `DECISION.md` con `decided_by` distinto, o producido por un agente, es **inválido y nulo**.
2. `authority=human_final` es válido **únicamente** aquí y **únicamente** cuando lo produce Jorge.
3. **Enforcement real:** la decisión se materializa por **aprobación/merge del PR por Jorge** (control de acceso del repo). Un agente no tiene ese permiso, por lo que no puede producir el efecto aunque escriba el texto.
4. `APPROVED` ⇒ `resulting_status=HANDOFF_TO_MSO`: la tarea entra al flujo soberano normal. **La decisión NO ejecuta**; solo autoriza que MSO/Police evalúen y ejecuten si corresponde. El paso a `HANDOFF_TO_MSO` lo fija MSO.
5. `REJECTED` ⇒ `resulting_status=CLOSED_REJECTED`.
6. Ninguna decisión confiere autoridad de ejecución directa; `mso_executable` sigue siendo exclusivo de MSO.
