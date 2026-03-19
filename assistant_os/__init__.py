"""
Assistant OS - Sistema de agentes con Command Router.

Uso:
    python -m assistant_os "CODE: crea módulo tensors"
    python -m assistant_os  # modo interactivo
"""

__version__ = "0.3.0"

from .contracts import Request, Response, make_ok, make_error
from .router import route_command, parse_command_to_request, route_request

__all__ = [
    "Request",
    "Response",
    "make_ok",
    "make_error",
    "route_command",
    "parse_command_to_request",
    "route_request",
]
