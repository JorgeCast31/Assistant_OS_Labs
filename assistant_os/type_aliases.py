"""
Type aliases for HTTP helpers and responses.
"""
from typing import Dict, Tuple, Optional, Any

Headers = Dict[str, str]
JsonResponse = Dict[str, Any]
HttpResponse = Tuple[int, Headers, bytes]
JsonErrorResponse = Tuple[int, JsonResponse]

# For body reading helpers
ReadBodyResult = Tuple[bytes, Optional[JsonErrorResponse]]

# For authentication helpers
AuthErrorResponse = Optional[JsonErrorResponse]

