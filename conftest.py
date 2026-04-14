"""
conftest.py — Root test configuration for AssistantOS.

Sets required environment variables to stub values before any test module
imports assistant_os.  This prevents config.py from raising RuntimeError
during collection for tests that do not exercise Notion or external services.

Tests that need real credentials must skip themselves or use environment
overrides via pytest marks.
"""

import os

# ---------------------------------------------------------------------------
# Stub external credentials so config._validate_env() passes at import time.
# These values are intentionally invalid — tests must mock any real I/O.
# ---------------------------------------------------------------------------

# Only the two variables that config._validate_env() treats as required.
# Do NOT stub optional credentials (GITHUB_TOKEN, ANTHROPIC_API_KEY, etc.)
# because some tests explicitly assert behavior when those are absent.
os.environ.setdefault("NOTION_TOKEN",      "test-stub-notion-token")
os.environ.setdefault("NOTION_WORK_DB_ID", "test-stub-notion-db-id")
