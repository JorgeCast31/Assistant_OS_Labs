# M-OPERABILITY-ALFA-01 — Read-only Sovereign Control Room

## 1. Estado del milestone

Este milestone consolida superficies de observabilidad read-only en Sovereign Control Room.
La UI no ejecuta acciones operativas y no otorga permisos de ejecución.
El objetivo es visibilidad operativa, no control de ejecución desde frontend.

## 2. Superficies visibles

- Readiness/liveness
- Governance status
- Recent governance
- CODE readiness
- Confirm pending queue
- Authority Matrix
- System Assistant observations

## 3. Invariantes

- UI read-only
- No action buttons
- No POST desde UI para acciones
- No approve/deny/execute/apply/confirm desde UI
- No token exposure
- No Police Panel
- Authority status is posture, not execution permission
- Readiness is not permission
- Pending confirmation is not execution
- Governance BLOCK is not failure
- System Assistant is observer/interpreter, not executor

## 4. Que quedo fuera del milestone

- Outcome HTTP endpoint
- Outcome UI panel
- Backend-controlled execution demo
- UI execution
- Police formal module
- Temporary pass engine
- Environments enforcement
- RRHH-B

## 5. Siguiente milestone

M-OPERABILITY-ALFA-02 — Backend-controlled execution outcome visibility

Incluye:

- Outcome Status Endpoint read-only
- Outcome Panel UI read-only
- request -> plan -> confirm -> execute -> outcome observable
- sin execution desde UI todavia

## 6. Riesgos conocidos

- Outcome producer existe, pero todavia no esta expuesto por HTTP.
- Task/trace memory puede no ser durable.
- Confirm flow observable no implica que el resultado posterior sea consultable aun.
- UI no debe inventar estado si backend no lo expone.
- **Debt arquitectonica:** [Truthfulness Observability Gap Report](../operability/truthfulness-gap-report.md) documenta la falta de un shape unificado para los readiness probes.
