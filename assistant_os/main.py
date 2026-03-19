#!/usr/bin/env python3
"""
Assistant OS - Command Router MVP (Paso 4)

How to run:
-----------
1. Comando directo:
   python -m assistant_os "CODE: crea módulo tensors"

2. Modo interactivo:
   python -m assistant_os

3. Modo servidor HTTP:
   python -m assistant_os --server
   python -m assistant_os --server --host 127.0.0.1 --port 8787

4. Tests:
   python -m unittest discover -v tests

Prefijos válidos: CODE:, DOC:, JOBS:, BIZ: (case-insensitive)
"""
import argparse
import json
import sys

try:
    # Import relativo cuando se ejecuta como paquete
    from .router import route_command, parse_command_to_request, route_request
    from .webhook_server import run_server
    from .config import WEBHOOK_HOST, WEBHOOK_PORT
except ImportError:
    # Import absoluto para ejecución directa (fallback)
    from router import route_command, parse_command_to_request, route_request
    from webhook_server import run_server
    from config import WEBHOOK_HOST, WEBHOOK_PORT


def print_response(response: dict) -> None:
    """Imprime la respuesta en JSON formateado."""
    print(json.dumps(response, indent=2, ensure_ascii=False))


def interactive_mode() -> None:
    """Modo interactivo: lee comandos del usuario en loop."""
    print("=" * 60)
    print("  Assistant OS - Command Router")
    print("=" * 60)
    print("Prefijos: CODE: | DOC: | JOBS: | BIZ:")
    print("Escribe 'exit' o 'quit' para salir.\n")
    
    while True:
        try:
            command = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n¡Hasta luego!")
            break
        
        if command.lower() in ("exit", "quit", "q"):
            print("¡Hasta luego!")
            break
        
        if not command:
            continue
        
        response = route_command(command)
        print_response(response)
        print()


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for CLI."""
    parser = argparse.ArgumentParser(
        description="Assistant OS - Multi-agent command router",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m assistant_os "CODE: crea módulo tensors"
  python -m assistant_os --server
  python -m assistant_os --server --port 9000
        """,
    )
    
    parser.add_argument(
        "command",
        nargs="?",
        default=None,
        help="Command to execute (e.g., 'CODE: create module')",
    )
    
    parser.add_argument(
        "--server",
        action="store_true",
        help="Start HTTP webhook server",
    )
    
    parser.add_argument(
        "--host",
        type=str,
        default=WEBHOOK_HOST,
        help=f"Server bind address (default: {WEBHOOK_HOST})",
    )
    
    parser.add_argument(
        "--port",
        type=int,
        default=WEBHOOK_PORT,
        help=f"Server port (default: {WEBHOOK_PORT})",
    )
    
    return parser


def main() -> None:
    """Punto de entrada principal."""
    from .executors.startup import setup_all_code_executors
    statuses = setup_all_code_executors()
    review_status = statuses["review"]
    propose_status = statuses["propose"]

    parser = create_parser()
    args = parser.parse_args()

    # Modo servidor — run_server() also calls setup (idempotent); banner shows status
    if args.server:
        run_server(host=args.host, port=args.port)
        return

    # Non-server modes: two compact lines so the operator knows executor state
    if review_status["live"]:
        print(f"[CODE read    : LIVE  ({review_status['model']})]")
    else:
        print(f"[CODE read    : STUB  — {review_status['note']}]")
    if propose_status["live"]:
        print(f"[CODE preview : LIVE  ({propose_status['model']})]")
    else:
        print(f"[CODE preview : STUB  — {propose_status['note']}]")

    # Modo comando directo
    if args.command:
        response = route_command(args.command)
        print_response(response)
        return

    # Modo interactivo (sin argumentos)
    interactive_mode()


if __name__ == "__main__":
    main()
