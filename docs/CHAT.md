# Chat — Assistant OS

Interfaz web para interactuar con Assistant OS desde el navegador.

## UI principal: Next.js (`ui/`)

La interfaz principal es la app Next.js ubicada en `ui/`.

### Iniciar

```powershell
# 1. Backend principal (AssistantOS webhook/chat)
python -m assistant_os --server

# 2. Code API (opcional, pero requerido para la vista de ejecuciones CODE)
python run_code_api.py

# 3. Frontend (Next.js)
cd ui
npm run dev
```

La UI queda disponible en `http://localhost:3100` (o en `http://<ip-tailscale>:3100` si el host está en Tailscale).

### Configuración (`ui/.env.local`)

```env
# URL pública del Code API (la consume el navegador)
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000

# URL pública del webhook (health checks y referencias visibles en UI)
NEXT_PUBLIC_WEBHOOK_BASE_URL=http://localhost:8787

# URL server-side del webhook para proxies Next.js
WEBHOOK_BASE_URL=http://localhost:8787

# Token de autenticación (debe coincidir con WEBHOOK_TOKEN en .env de backend)
ASSISTANT_TOKEN=tu_token_aqui
```

Copia `ui/.env.local.example` a `ui/.env.local` y ajusta los valores.

### Funcionalidades cubiertas

- Chat con FIN, WORK, CODE y ENERGY
- Sesiones persistentes (creación, historial, búsqueda)
- Acciones: confirm/cancel, formularios, selección
- Render de bloques de código, listas, texto enriquecido
- Auth inyectada server-side (el token nunca llega al cliente)
- Estado del sistema vía proxy interno `GET /api/system/runtime-state` -> webhook `GET /mso/state`

---

## Backend principal: webhook server (puerto 8787)

El webhook server expone la API que consume la UI. Sigue corriendo en el mismo puerto.

### Endpoints principales

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/health` | Estado del servidor |
| `GET` | `/auth/check` | Valida el token |
| `POST` | `/chat/process` | Procesa un mensaje |
| `GET` | `/chat/sessions` | Lista sesiones |
| `POST` | `/chat/sessions` | Crea sesión |
| `GET` | `/chat/sessions/{id}` | Detalle de sesión + mensajes |
| `PATCH` | `/chat/sessions/{id}` | Actualiza sesión |
| `DELETE` | `/chat/sessions/{id}` | Elimina sesión |
| `GET` | `/chat/search?q=...` | Búsqueda full-text |
| `GET` | `/chat/history` | Historial legacy (conversation_id) |
| `GET` | `/mso/state` | Estado operativo observable del sistema |
| `GET` | `/system/capabilities` | Capacidades/feature flags observables |
| `GET` | `/agents/registry` | Registro observable de agentes |

> `GET /` y `GET /chat` devuelven **410 Gone** — la UI HTML embebida fue retirada.

### Autenticación

Todos los endpoints (excepto `/health`) requieren el header:
```
X-Assistant-Token: <WEBHOOK_TOKEN>
```

La UI no llama directamente a `/mso/state`, `/system/capabilities` ni `/agents/registry` desde el navegador porque esos endpoints requieren token. Para el estado operativo usa un proxy interno de Next.js.

---

## Code API (puerto 8000)

El Code API es un servidor HTTP separado del webhook principal. La UI lo usa para:

- `GET /health`
- `GET /api/code/executions`
- `GET /api/code/executions/{id}`
- `POST /api/code/execute`
- acciones de review/rerun

No expone `/api/system/runtime-state` ni `/api/system/freeze`.

---

## Troubleshooting

### UI no conecta al backend

- Verifica que el backend esté corriendo: `curl http://127.0.0.1:8787/health`
- Verifica que el Code API esté corriendo: `curl http://127.0.0.1:8000/health`
- Verifica que `WEBHOOK_BASE_URL` en `ui/.env.local` apunta al puerto correcto
- Verifica que `NEXT_PUBLIC_API_BASE_URL` apunta al Code API correcto
- Verifica que `ASSISTANT_TOKEN` coincide con `WEBHOOK_TOKEN` en el backend

### Resetear el servidor (Windows)

```powershell
# Matar proceso en puerto 8787
Get-NetTCPConnection -LocalPort 8787 -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }

# Limpiar caches Python
Get-ChildItem -Recurse -Filter "__pycache__" -Directory | Remove-Item -Recurse -Force

# Reiniciar
python -m assistant_os --server --host 127.0.0.1 --port 8787
```

### Verificar autenticación

```powershell
# Sin token -> 401
curl.exe -s -o NUL -w "%{http_code}" http://127.0.0.1:8787/auth/check

# Con token -> 200
curl.exe -s -o NUL -w "%{http_code}" -H "X-Assistant-Token: <tu_token>" http://127.0.0.1:8787/auth/check
```
