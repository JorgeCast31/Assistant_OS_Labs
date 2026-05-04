# Backend outcome demo

## Objetivo

Este demo smoke backend-only demuestra el flujo confirmado de outcome:

POST /host/action -> GET /confirm/pending -> POST /host/confirm -> GET /mso/outcome/status?plan_id=<PLAN_ID>

El script usa una accion HOST `create_directory` dentro del sandbox de escritura y no toca UI, navegador, proxy, Notion, Sheets ni servicios externos.

## Requisitos

- Backend local corriendo, por defecto en `http://127.0.0.1:8787`.
- Token de backend disponible en una variable de entorno.
- Sandbox de escritura HOST existente. Por defecto el script usa `WRITE_SANDBOX_DIRECTORIES[0]`.

## Comando

```powershell
$env:WEBHOOK_TOKEN = "<token-local>"
python scripts/demo_backend_outcome_flow.py
```

Opciones utiles:

```powershell
python scripts/demo_backend_outcome_flow.py --base-url http://127.0.0.1:8787
python scripts/demo_backend_outcome_flow.py --token-env ASSISTANT_TOKEN
python scripts/demo_backend_outcome_flow.py --sandbox-root "C:\Users\Jorge\Documents\assistant_sandbox"
python scripts/demo_backend_outcome_flow.py --dry-run
```

## Variables de entorno

- `WEBHOOK_TOKEN`: variable por defecto, alineada con el backend actual.
- `ASSISTANT_TOKEN`: puede usarse con `--token-env ASSISTANT_TOKEN`.

El script falla antes de llamar al backend si la variable elegida no existe o esta vacia.

## Flujo esperado

1. `POST /host/action` envia:

```json
{
  "action": "create_directory",
  "payload": {
    "path": "<sandbox_demo_path>",
    "confirmed": true
  }
}
```

2. La respuesta debe ser `plan_confirmation_required` y contener `plan_id`.
3. `GET /confirm/pending?limit=50` debe mostrar el `plan_id` pendiente.
4. `POST /host/confirm` confirma el plan.
5. `GET /mso/outcome/status?plan_id=<PLAN_ID>` debe devolver `found=true`, `outcome.status=completed` y `sources.task_registry=true`.

## Ejemplo de output

```text
[demo] submitting request to POST /host/action
[demo] request submitted
[demo] plan_id captured: 0d4c5c5f-3b9b-42bb-b71c-9f5f1d42a01d
[demo] checking GET /confirm/pending
[demo] pending confirmation found
[demo] submitting confirmation to POST /host/confirm
[demo] confirm submitted
[demo] outcome fetched
[demo] final outcome.status: completed
```

## Invariantes de seguridad

- Solo usa backend local configurable por `--base-url`.
- No abre apps, URLs, navegadores ni archivos.
- No borra nada.
- No modifica nada fuera del sandbox de escritura HOST.
- Usa un path unico por ejecucion: `backend_outcome_demo_<timestamp>_<suffix>`.
- No llama servicios externos.
- El endpoint de outcome es observacional; no concede autorizacion.

## Troubleshooting

- `Missing token`: exportar `WEBHOOK_TOKEN` o usar `--token-env ASSISTANT_TOKEN`.
- `Backend did not respond`: levantar el backend local y revisar `--base-url`.
- `plan_id did not appear`: revisar que `create_directory` siga siendo una accion confirmable.
- `pending confirmation not found`: revisar el store de confirmaciones y expiracion de planes.
- `confirm failed`: revisar token, control plane y si el plan fue consumido o expiro.
- `outcome did not reach completed`: revisar publicacion a task registry y el endpoint `/mso/outcome/status`.
