# M-OPERABILITY-ALFA-02 — Backend-controlled execution outcome visibility

## 1. Objetivo del milestone

Establecer visibilidad read-only de ciclo completo:

request -> plan -> confirm -> execute -> outcome observable.

Este milestone agrega observabilidad de outcome sin introducir ejecucion desde UI.

## 2. Componentes ya existentes

- Outcome Status Producer
- Outcome producer hardening tests
- Confirm pending queue
- Authority Matrix
- Governance status
- CODE readiness

## 3. Componentes en curso

- GET /mso/outcome/status

## 4. Componentes pendientes

- Next.js proxy read-only
- Outcome Panel UI read-only
- Visual correlation pending -> executed -> outcome
- Backend-only demo script/checklist

## 5. Invariantes

- UI read-only
- no execute button
- no approve/confirm/apply from UI
- outcome is observation, not permission
- authority remains PolicyDecision.execution_mode
- no token exposure
- no raw plan/raw_text/stdout/stderr/artifacts

## 6. NO-GO explicitos

- UI execution
- POST from UI
- /mso/tasks list endpoint
- Police formal module
- environment enforcement
- temporary pass engine
