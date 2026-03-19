# WORK Seed Import — `seed_work.py`

Importa items desde un archivo JSON (`schema_version: work_seed.v1`) a la **WORK_DB** de Notion.  
Soporta idempotencia total: no crea duplicados. No crea opciones nuevas en selects (falla por item con reason).

---

## Requisitos

```
pip install httpx python-dotenv
```

Variables de entorno en `.env` (en raíz del proyecto):

```env
NOTION_TOKEN=secret_...
NOTION_WORK_DB_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

---

## Uso

### Validar sin escribir (dry-run)
```bash
python -m assistant_os.scripts.seed_work --file seeds/work_seed.json --dry-run
```

### Importar de verdad
```bash
python -m assistant_os.scripts.seed_work --file seeds/work_seed.json --commit
```

---

## Comportamiento

| Situación | Resultado |
|---|---|
| Item nuevo, opciones válidas | `CREATED` |
| `external_id` ya existe en DB | `SKIP` (skipped_duplicates++) |
| Opción de select no existe en DB | `FAILED` con reason (no crea la opción) |
| `external_id` faltante en item | `FAILED` con reason |

---

## Salida final (JSON)

```json
{
  "mode": "COMMIT",
  "total_items": 22,
  "created": 20,
  "skipped_duplicates": 1,
  "failed": 1,
  "failures": [
    { "title": "...", "external_id": "...", "reason": "Opción inválida en 'Status': 'WAITING' no existe en la DB." }
  ]
}
```

---

## Mapping de campos (seed → Notion)

| Campo seed | Propiedad Notion |
|---|---|
| `title` | `Name` |
| `external_id` | `External_id` |
| `project` | `Proyecto` |
| `status` | `Status` |
| `load` | `Carga` |
| `priority` | `Priority Level` |
| `domain` | `Domain` |
| `due` | `Entrega` |
| `tags` | `Tags` / `Etiquetas` (auto-detectado) |
| `notes` | `Notes` / `Notas` (auto-detectado) o body paragraph |

Los valores faltantes en el item se completan con `defaults` del JSON seed.

---

## Schema del seed (`work_seed.v1`)

```json
{
  "schema_version": "work_seed.v1",
  "defaults": { "status": "INBOX", "load": "Media", "priority": "P2", "domain": "WORK" },
  "items": [
    {
      "title": "...",           
      "external_id": "...",    
      "project": "...",        
      "status": "...",         
      "load": "...",           
      "priority": "...",       
      "domain": "...",         
      "due": "YYYY-MM-DD",     
      "notes": "...",          
      "tags": ["..."]          
    }
  ]
}
```

`external_id` es el único campo obligatorio por item (además de `title`).
