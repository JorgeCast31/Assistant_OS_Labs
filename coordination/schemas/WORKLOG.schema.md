# WORKLOG.schema — coordination/worklogs/TASK-NNNN.WORKLOG.md — **v2**

Bitácora **append-only** del ejecutor. Cada entrada es inmutable una vez escrita (no se reescribe historia; correcciones = nueva entrada).
Nombre de archivo: `TASK-NNNN.WORKLOG.md` (slug solo en el `id` del front-matter).

## Front-matter

```yaml
id: TASK-NNNN-...        # required, igual al TASK
agent: claude | codex     # required, autor del worklog (ejecutor)
created_at: 2026-06-14     # required
```

## Entradas (append-only)

Cada entrada:

```
### <timestamp ISO> — <agent>
- action: qué se hizo (verificable)
- result: resultado observado (sin éxito fabricado; si no ejecutó, decirlo)
- files: archivos tocados en rama coordination/task-NNNN
- evidence: rutas/refs (diffs, salidas de test, etc.)
- next: siguiente paso
```

### Entrada de retracción (v2)

Cuando se corrige un avance ilegítimo, se **añade** una entrada nueva (no se borra ni edita lo previo):

```
### <timestamp ISO> — <agent> — RETRACCIÓN
- action: qué avance se retracta y por qué fue ilegítimo
- result: status devuelto a <last_legit_status> (o BLOCKED); blocked=true con motivo
- files: TASK-NNNN.md (campos status/blocked/blocked_reason/last_legit_status/next_action)
- evidence: referencia a la entrada/decisión que motivó la retracción
- next: siguiente paso legítimo
```

## Reglas (fail-closed)

1. **Append-only:** prohibido editar o borrar entradas previas. La corrección/retracción es una entrada nueva.
2. **Veracidad operativa:** si algo no ejecutó, no se reporta como hecho. `result` refleja la realidad observada.
3. Solo el `assigned_agent` (ejecutor) escribe aquí. El revisor lo **lee**, no lo edita.
4. Toda afirmación importante debe ser trazable a evidencia (`evidence`).
5. Sin secretos, tokens ni credenciales en el texto.
6. **No se borra evidencia de fallo:** un dogfood fallido se preserva en el WORKLOG como registro auditable.
