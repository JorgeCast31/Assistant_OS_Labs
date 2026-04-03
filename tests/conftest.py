"""
pytest conftest — sets required environment variables for local test runs.

These dummy values mirror what the GitHub Actions workflow provides so that
tests can be executed locally without a .env file.  They are not real
credentials and grant no access to any external service.
"""

import os

# Required by assistant_os.config._validate_env() at import time.
os.environ.setdefault("NOTION_TOKEN", "test_notion_token_not_real")
os.environ.setdefault("NOTION_WORK_DB_ID", "test_db_id_not_real")
os.environ.setdefault("WEBHOOK_TOKEN", "test_webhook_token_not_real")
os.environ.setdefault("SHEETS_SPREADSHEET_ID", "test_spreadsheet_id_not_real")
