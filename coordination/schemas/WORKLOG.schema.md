# WORKLOG.schema — coordination/worklogs/<task-id>.WORKLOG.md

Bitácora **append-only** del ejecutor. Cada entrada es inmutable una vez escrita (no se reescribe historia; correcciones = nueva entrada).

## Front-matter

```yaml
id: TASK-0001-...        # required, igual al TASK
agent: claude | codex     # required, autor del worklog (ejecutor)
created_at: 2026-06-13     # required
```

## Entradas (append-only)

Cada entrada:

```
### <timestamp ISO> — <agent>
- action: qué se hizo (verificable)
- result: resultado observado (sin éxito fabricado; si no ejecutó, decirlo)
- files: archivos tocados en rama agent/<id>
- evidence: rutas/refs (diffs, salidas de test, etc.)
- next: siguiente paso
```

## Reglas (fail-closed)

1. **Append-only:** prohibido editar o borrar entradas previas.
2. **Veracidad operativa:** si algo no ejecutó, no se reporta como hecho. `result` refleja la realidad observada.
3. Solo el `assigned_agent` (ejecutor) escribe aquí. El revisor lo **lee**, no lo edita.
4. Toda afirmación importante debe ser trazable a evidencia (`evidence`).
5. Sin secretos, tokens ni credenciales en el texto.
