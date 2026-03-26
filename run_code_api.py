#!/usr/bin/env python
"""
run_code_api.py — Start the AssistantOS CODE execution API.

Usage:
    python run_code_api.py [--port 8000]

The server listens on http://localhost:PORT and exposes:
    POST /api/code/execute   — trigger a CODE execution
    GET  /health             — liveness check

Environment variables (optional):
    CODE_API_PORT  — port to listen on (default: 8000)
    CODE_API_KEY   — if set, requests must carry X-API-KEY: <value>

Example .env addition:
    CODE_API_KEY=my-secret-key
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Make sure the project root is on sys.path when running directly.
PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load .env into the environment (simple, no python-dotenv required).
_ENV_FILE = PROJECT_ROOT / ".env"
if _ENV_FILE.exists():
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Only set if not already in environment (explicit env vars win).
            if key and key not in os.environ:
                os.environ[key] = value

from assistant_os.api.code_api import PORT, run  # noqa: E402 — after sys.path setup


def main() -> None:
    parser = argparse.ArgumentParser(description="AssistantOS CODE API server")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("CODE_API_PORT", PORT)),
        help=f"Port to listen on (default: {PORT})",
    )
    args = parser.parse_args()
    run(port=args.port)


if __name__ == "__main__":
    main()
