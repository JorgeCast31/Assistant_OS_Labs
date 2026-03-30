# Chat — Assistant OS

Interfaz web para interactuar con Assistant OS desde el navegador.

## UI principal: Next.js (`ui/`)

La interfaz principal es la app Next.js ubicada en `ui/`.

### Iniciar

```powershell
# 1. Backend (webhook server)
python -m assistant_os --server --host 0.0.0.0 --port 8787

# 2. Frontend (Next.js)
cd ui
npm run dev
```

La UI queda disponible en `http://localhost:3000` (o en `http://<ip-tailscale>:3000` si el host está en Tailscale).

### Configuración (`ui/.env.local`)

```env
# URL del webhook server (ajustar si usas otro puerto/host)
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

---

## Backend: webhook server (puerto 8787)

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

> `GET /` y `GET /chat` devuelven **410 Gone** — la UI HTML embebida fue retirada.

### Autenticación

Todos los endpoints (excepto `/health`) requieren el header:
```
X-Assistant-Token: <WEBHOOK_TOKEN>
```

---

## Troubleshooting

### UI no conecta al backend

- Verifica que el backend esté corriendo: `curl http://127.0.0.1:8787/health`
- Verifica que `WEBHOOK_BASE_URL` en `ui/.env.local` apunta al puerto correcto
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
