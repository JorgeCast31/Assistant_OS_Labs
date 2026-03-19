# Chat UI - Assistant OS

Interfaz web tipo chat para interactuar con Assistant OS desde el navegador.

## URL

```
http://<tailscale-ip>:8787/chat
```

Por ejemplo, si tu IP de Tailscale es `100.100.100.1`:
```
http://100.100.100.1:8787/chat
```

## Requisitos

1. **Tailscale ON**: La máquina debe estar conectada a tu red Tailscale
2. **Servidor corriendo**: `python -m assistant_os --server --host 0.0.0.0 --port 8787`
3. **Token**: Necesitas el valor de `WEBHOOK_TOKEN` de `assistant_os/config.py`

## Uso

### Primera vez

1. Abre `/chat` en el navegador
2. Aparecerá un modal pidiendo el token
3. Ingresa tu `WEBHOOK_TOKEN` y presiona "Guardar"
4. El token se guarda en `localStorage` del navegador
5. Se genera automáticamente un `conversation_id` (session)

### Enviar comandos

- Escribe un comando (ej: `CODE: crear módulo utils`)
- Presiona Enter o el botón enviar
- El asistente responderá con un resumen

### Prefijos disponibles

| Prefijo | Agente | Ejemplo |
|---------|--------|---------|
| `CODE:` | CodeAgent | `CODE: crear módulo math_utils` |
| `DOC:` | DocAgent | `DOC: generar README` |
| `JOBS:` | JobsAgent | `JOBS: buscar Python developer Madrid` |
| `BIZ:` | BizAgent | `BIZ: análisis de mercado SaaS` |

### Botones

- **Copy**: Copia el `conversation_id` al portapapeles (muestra toast "Copied!")
- **Join**: Abre modal para unirse a una sesión existente pegando su `conversation_id`
- **New**: Crea una nueva sesión (nuevo `conversation_id`)
- **Reload**: Recarga el historial desde el servidor
- **Export**: Descarga el historial del chat como JSON
- **Clear**: Limpia la conversación en UI (no borra logs del servidor)
- **Token**: Borra el token guardado y pide uno nuevo

### Ver detalles

Cada respuesta del asistente tiene dos botones:
- **Detalles**: Muestra el JSON estructurado de `details`
- **Raw**: Hace una llamada adicional con `?raw=1` para ver la respuesta completa

## Sesiones (conversation_id)

El chat usa un `conversation_id` único para agrupar mensajes de una misma conversación.

### Cómo funciona

1. **Auto-generado**: Al abrir `/chat` por primera vez, se genera un UUID
2. **Persistente**: Se guarda en `localStorage` como `assistant_os.conversation_id`
3. **Visible**: Se muestra en el header como "Session: `<8 chars>`"
4. **Historial**: Al recargar la página, se carga el historial desde el servidor

### Nueva sesión

Para iniciar una conversación nueva:
1. Click en botón **New**
2. Se genera un nuevo `conversation_id`
3. Se limpia la UI
4. Los mensajes anteriores quedan en el servidor (con su `conversation_id` original)

### Compartir sesión

Para compartir una sesión con otra persona o dispositivo:
1. Click en **Copy** para copiar el `conversation_id`
2. Aparece toast "Copied!" confirmando
3. Comparte el ID con quien quieras

### Unirse a sesión

Para unirse a una sesión existente:
1. Click en **Join**
2. Se abre modal pidiendo el `conversation_id`
3. Pega el ID (mínimo 7 caracteres)
4. Click "Unirse"
5. Se carga el historial de esa sesión

### Cargar historial

Si cierras el navegador y vuelves:
- La sesión se mantiene (mismo `conversation_id`)
- El historial se carga automáticamente al abrir `/chat`
- Click **Reload** para refrescar manualmente

## API: /chat/history

Endpoint para obtener el historial de una conversación.

### Request

```
GET /chat/history?conversation_id=<uuid>&limit=<n>
```

**Headers requeridos:**
```
X-Assistant-Token: <token>
```

**Parámetros:**
| Param | Requerido | Default | Max | Descripción |
|-------|-----------|---------|-----|-------------|
| `conversation_id` | Sí | - | - | UUID de la conversación |
| `limit` | No | 50 | 200 | Número máximo de items |

### Response

```json
{
  "ok": true,
  "conversation_id": "abc12345-...",
  "items": [
    {
      "ts": "2024-01-15T10:30:00Z",
      "role": "user",
      "text": "CODE: crear módulo math",
      "context_id": "CTX-123"
    },
    {
      "ts": "2024-01-15T10:30:01Z",
      "role": "assistant",
      "title": "OK · code",
      "summary": "Module: math_utils\nPath: src/math_utils.py",
      "details": null,
      "context_id": "CTX-123"
    }
  ]
}
```

## Indicador de estado

El punto junto a "Assistant OS" indica:
- 🟢 Verde: Servidor online (`/health` OK)
- 🔴 Rojo: Servidor offline o error

El estado se actualiza automáticamente cada 30 segundos.

## Seguridad

- El token **nunca** se hardcodea en el HTML
- Se almacena en `localStorage` del navegador
- Se envía como header `X-Assistant-Token` en cada request
- El `conversation_id` **no** es secreto (solo agrupa mensajes)
- Los logs **nunca** contienen el token

## localStorage Keys

| Key | Descripción |
|-----|-------------|
| `assistant_token` | Token de autenticación |
| `assistant_os.conversation_id` | UUID de la sesión actual |

## Troubleshooting

### "Token inválido"
- Verifica que el token coincide exactamente con `WEBHOOK_TOKEN` en `config.py`
- Borra el token (botón "Token") e ingrésalo de nuevo

### Historial no carga
- Verifica que tienes el mismo `conversation_id` (no presionaste "New")
- Los logs de servidor (`memory/log.ndjson`) deben existir

### Nueva sesión no funciona
- El navegador debe soportar `localStorage`
- Verifica que no estás en modo incógnito con localStorage bloqueado

### Indicador rojo
- Verifica que el servidor esté corriendo
- Verifica conectividad Tailscale

### No carga
- Verifica que la URL incluye el puerto (`:8787`)
- Verifica firewall de Windows permite el puerto

---

## Dev: Reset Server (Windows)

Si experimentas problemas con caché, múltiples instancias, o glitches de autenticación:

### 1. Matar proceso por puerto 8787

```powershell
# Encontrar y matar proceso usando puerto 8787
Get-NetTCPConnection -LocalPort 8787 -ErrorAction SilentlyContinue | 
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

### 2. Limpiar cachés

```powershell
# Eliminar __pycache__ recursivamente
Get-ChildItem -Recurse -Filter "__pycache__" -Directory | Remove-Item -Recurse -Force

# Eliminar .pytest_cache
Remove-Item -Recurse -Force .pytest_cache -ErrorAction SilentlyContinue
```

### 3. Reiniciar servidor

```powershell
python -m assistant_os --server --host 127.0.0.1 --port 8787
```

### 4. Verificar

```powershell
# Sin token -> 401
curl.exe -s -o NUL -w "%{http_code}" http://127.0.0.1:8787/auth/check

# Con token -> 200
curl.exe -s -o NUL -w "%{http_code}" -H "X-Assistant-Token: TEST_TOKEN_NOT_FOR_PRODUCTION_USE" http://127.0.0.1:8787/auth/check

# UI accesible -> 200
curl.exe -s -o NUL -w "%{http_code}" http://127.0.0.1:8787/
```

### Debug en Browser

Abrir DevTools (F12) > Console para ver logs:
- `[Auth] token_present=true, token_prefix=TEST...`
- `[Auth] status=200, token_prefix=TEST...`

