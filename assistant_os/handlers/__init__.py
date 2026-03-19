"""
Handler modules for Assistant OS webhook endpoints.

Each module contains standalone handler functions that accept a WebhookHandler
instance as first argument. The WebhookHandler class in webhook_server.py
delegates to these functions via one-liner methods, keeping the class thin.

- work.py   : WORK domain handlers (query, create, delete, schema)
- fin.py    : FIN domain handlers (expense, chaperon, batch, etc.)
"""
