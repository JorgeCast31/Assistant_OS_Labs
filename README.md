# Assistant OS

Multi-agent personal assistant system with natural language processing.

## Quick Start

1. Copy `.env.example` to `.env` and fill in required values
2. Install dependencies: `pip install -r requirements.txt`
3. Run server: `python -m assistant_os --server`

## Configuration

### Required Environment Variables

- `NOTION_TOKEN` - Notion API token
- `NOTION_WORK_DB_ID` - Notion database ID for WORK tasks
- `WEBHOOK_TOKEN` - Authentication token for webhook server
- `SHEETS_SPREADSHEET_ID` - Google Sheets ID for FIN expenses

### Optional: TEST Database

To avoid polluting your production WORK database with UI/development test tasks:

1. Create a new Notion database with the same structure as your WORK database
2. Copy the database ID from the URL
3. Add to `.env`:
   ```
   NOTION_WORK_TEST_DB_ID=your_test_database_id
   ```
4. Restart the server

**Usage:**
- Create test task: "Crea una tarea de prueba: [TEST] My test task"
- Alternative formats: "ui test: X", "smoke test: X"
- Reset test DB: "resetear tests" (archives all test tasks)

## API Endpoints

- `POST /command` - Execute commands
- `POST /command/summary` - Execute with human-readable summary
- `POST /classify` - Classify text intent

## Testing

```bash
python -m pytest tests/ -v
```

## Documentation

See [docs/CHAT.md](docs/CHAT.md) for chat UI documentation.
