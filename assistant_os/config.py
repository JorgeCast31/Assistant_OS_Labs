"""
Configuración central de Assistant OS.
Constantes: workspace root, comandos permitidos, timeouts, límites.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Cargar variables de entorno desde .env en la raíz del proyecto
# override=True asegura que siempre se lee el .env aunque existan vars de entorno previas
load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env", override=True)

# Raíz del workspace (directorio del repo, padre del paquete)
WORKSPACE_ROOT: Path = Path(__file__).parent.parent.resolve()

# Directorio de memoria (dentro del paquete)
MEMORY_DIR: Path = Path(__file__).parent / "memory"

# Archivos de estado y log
STATE_FILE: Path = MEMORY_DIR / "state.json"
LOG_FILE: Path = MEMORY_DIR / "log.ndjson"

# Timeout para ejecución de comandos (segundos)
TIMEOUT_SECONDS: int = 30

# Máximo de iteraciones por agente (para futura lógica iterativa)
MAX_ITERATIONS: int = 10

# ---------------------------------------------------------------------------
# Webhook Server Configuration
# ---------------------------------------------------------------------------
# WEBHOOK_TOKEN: Required for production. Falls back to test token only for development.
# In production, ALWAYS set WEBHOOK_TOKEN environment variable!
_WEBHOOK_TOKEN_FALLBACK = "TEST_TOKEN_NOT_FOR_PRODUCTION_USE"
WEBHOOK_TOKEN: str = os.environ.get("WEBHOOK_TOKEN", _WEBHOOK_TOKEN_FALLBACK)
WEBHOOK_HOST: str = os.environ.get("WEBHOOK_HOST", "0.0.0.0")
WEBHOOK_PORT: int = int(os.environ.get("WEBHOOK_PORT", "8787"))
CONTROL_PLANE_HOST: str = os.environ.get("CONTROL_PLANE_HOST", "127.0.0.1")
CONTROL_PLANE_PORT: int = int(os.environ.get("CONTROL_PLANE_PORT", "8788"))
CONTROL_PLANE_SCHEDULER_ENABLED: bool = os.environ.get("CONTROL_PLANE_SCHEDULER_ENABLED", "true").lower() == "true"
CONTROL_PLANE_SCHEDULER_INTERVAL_SECONDS: int = int(os.environ.get("CONTROL_PLANE_SCHEDULER_INTERVAL_SECONDS", "60"))
CONTROL_PLANE_TOKEN_DEFAULT_TTL_MINUTES: int = int(os.environ.get("CONTROL_PLANE_TOKEN_DEFAULT_TTL_MINUTES", "60"))
CONTROL_PLANE_TOKEN_MAX_TTL_MINUTES: int = int(os.environ.get("CONTROL_PLANE_TOKEN_MAX_TTL_MINUTES", "480"))
CONTROL_PLANE_MAX_ACTIVE_TOKENS_PER_OPERATOR: int = int(os.environ.get("CONTROL_PLANE_MAX_ACTIVE_TOKENS_PER_OPERATOR", "3"))
WEBHOOK_MAX_BYTES: int = 16384  # 16KB for text endpoints
WEBHOOK_MAX_BYTES_RECEIPT: int = 3145728  # 3MB for receipt uploads
WEBHOOK_INCLUDE_RAW_DEFAULT: bool = False  # Include raw response in /command/summary

# Admin API token for localhost access (from .env)
ASSISTANT_API_TOKEN: str | None = os.environ.get("ASSISTANT_API_TOKEN")

# ---------------------------------------------------------------------------
# Claude / Anthropic (CODE module — read-only executor)
# ---------------------------------------------------------------------------
# API key loaded from .env / environment.  Required for real CODE_EXPLAIN/REVIEW.
ANTHROPIC_API_KEY: str | None = os.environ.get("ANTHROPIC_API_KEY")
# Claude model used for CODE_EXPLAIN and CODE_REVIEW.
# Default: claude-haiku-4-5-20251001 — fast and cost-effective for read-only analysis.
CODE_REVIEW_MODEL: str = os.environ.get(
    "CODE_REVIEW_MODEL", "claude-haiku-4-5-20251001"
)
# Maximum tokens for code analysis responses (keep concise for UI display).
CODE_REVIEW_MAX_TOKENS: int = int(os.environ.get("CODE_REVIEW_MAX_TOKENS", "1024"))
# Claude model used for CODE_FIX / CODE_CREATE preview generation.
# Default: claude-haiku-4-5-20251001.  Set to claude-sonnet-4-6 for higher quality diffs.
CODE_PROPOSE_MODEL: str = os.environ.get(
    "CODE_PROPOSE_MODEL", "claude-haiku-4-5-20251001"
)
# Maximum tokens for proposal responses (more room than analysis — includes a diff).
CODE_PROPOSE_MAX_TOKENS: int = int(os.environ.get("CODE_PROPOSE_MAX_TOKENS", "2048"))

# ---------------------------------------------------------------------------
# MSO / Local LLM Preparation (disabled-by-default, no behavior wired yet)
# ---------------------------------------------------------------------------
MSO_ENABLED: bool = os.environ.get("MSO_ENABLED", "false").lower() == "true"
LOCAL_LLM_PROVIDER: str = os.environ.get("LOCAL_LLM_PROVIDER", "").strip()
LOCAL_LLM_BASE_URL: str = os.environ.get("LOCAL_LLM_BASE_URL", "").strip()
LOCAL_LLM_MODEL: str = os.environ.get("LOCAL_LLM_MODEL", "").strip()
LOCAL_LLM_TIMEOUT_SECONDS: float = float(os.environ.get("LOCAL_LLM_TIMEOUT_SECONDS", "4.0"))

# ---------------------------------------------------------------------------
# Google Sheets Integration (FIN module)
# ---------------------------------------------------------------------------
# Service account credentials JSON file path (from .env)
GOOGLE_SERVICE_ACCOUNT_JSON_PATH: str | None = os.environ.get(
    "GOOGLE_SERVICE_ACCOUNT_JSON_PATH",
    str(Path(__file__).resolve().parents[1] / "secrets" / "service-account.json")
)
# Spreadsheet ID (from the URL: docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/...)
SHEETS_SPREADSHEET_ID: str | None = os.environ.get("SHEETS_SPREADSHEET_ID")
# Tab/sheet name within the spreadsheet
SHEETS_TAB_NAME: str = os.environ.get("SHEETS_TAB_NAME", "Gastos")

# Expected header columns (exact order and names)
SHEETS_EXPECTED_HEADER: list[str] = [
    "Fecha",
    "Descripción",
    "Factura",
    "Responsable",
    "Monto",
    "Moneda",
    "ITBMS",
    "Categoría",
    "Método de Pago",
    "Notas",
    "Fuente",
    "Link/Archivo",
    "Mes",
]

# ---------------------------------------------------------------------------
# FIN Module - Responsables
# ---------------------------------------------------------------------------
# Canonical list of responsible parties for expenses.
# These exact strings are used in UI, parsing, validation, and Sheets.
FIN_RESPONSIBLES: list[str] = [
    "Jorge",      # ← index 0 = default when none detected
    "Ana",
    "Conejos",
    "eiProta",
    "Proyectos",
    "Hogar",
]

# Comandos permitidos (whitelist)
# SEGURIDAD: Solo se permite ejecutar tests generados, nada más.
# Cada entrada es una tupla EXACTA del comando completo (no prefijos).
ALLOWED_COMMANDS: list[tuple[str, ...]] = [
    ("python", "-m", "unittest", "discover", "-v", "-s", "tests_generated"),
]

# ---------------------------------------------------------------------------
# Notion Integration (WORK module)
# ---------------------------------------------------------------------------

# Notion API token (from .env, required)
NOTION_TOKEN: str | None = os.environ.get("NOTION_TOKEN")
# Notion WORK database ID (from .env, required)
NOTION_WORK_DB_ID: str | None = os.environ.get("NOTION_WORK_DB_ID")

print("[CONFIG] NOTION_WORK_DB_ID =", NOTION_WORK_DB_ID, flush=True)

# ---------------------------------------------------------------------------
# Validación de variables de entorno requeridas
# ---------------------------------------------------------------------------
def _validate_env() -> None:
    """Valida que las variables de entorno requeridas estén definidas."""
    missing = []
    if not NOTION_TOKEN:
        missing.append("NOTION_TOKEN")
    if not NOTION_WORK_DB_ID:
        missing.append("NOTION_WORK_DB_ID")
    if missing:
        raise RuntimeError(
            f"Variables de entorno requeridas no definidas: {', '.join(missing)}. "
            "Crea un archivo .env en la raíz del proyecto."
        )

_validate_env()

# Debug: mostrar solo primeros 6 caracteres del token
def get_notion_token_preview() -> str:
    """Retorna los primeros 6 caracteres del token para debug."""
    return NOTION_TOKEN[:6] + "..." if NOTION_TOKEN else "(no definido)"

# Expected property names in WORK database
# Maps internal field names to Notion property names (normalized, no trailing spaces)
NOTION_WORK_PROPERTY_MAP: dict[str, str] = {
    "title": "Name",           # title property
    "status": "Status",        # status type in Notion
    "project": "Proyecto",     # multi-select (Spanish) - micro level
    "domain": "Domain",        # multi-select - macro level
    "project_key": "Project Key",  # text - slug for matching/docs integration
    "load": "Carga",           # select: Alta, Media, Baja (Spanish)
    "impact": "Impact",        # select: Estructural, Económico, Operativo, Intelectual, Emocional
    "due": "Entrega",          # date (Spanish)
    "next_action": "Next Action",  # text (optional)
}

# Default active statuses for queries
NOTION_WORK_ACTIVE_STATUSES: list[str] = ["NEXT", "SCHEDULED", "WAITING", "INBOX"]

# ---------------------------------------------------------------------------
# CodeOps Configuration
# ---------------------------------------------------------------------------
# Allowlist of repositories that CodeOps can operate on.
# Empty list = allow all repos (TODO: lock down in production)
# Format: ["owner/repo", "owner/repo2"]
CODEOPS_ALLOWED_REPOS: list[str] = os.environ.get(
    "CODEOPS_ALLOWED_REPOS", ""
).split(",") if os.environ.get("CODEOPS_ALLOWED_REPOS") else []

# Maximum payload size for CodeOps endpoints
CODEOPS_MAX_BYTES: int = 32768  # 32KB

# Whether to allow CodeOps to execute actual git/GitHub operations
# Set to True only when fully implemented and tested
CODEOPS_LIVE_MODE: bool = os.environ.get("CODEOPS_LIVE_MODE", "false").lower() == "true"


def is_repo_allowed(repo: str) -> bool:
    """
    Check if a repository is in the CodeOps allowlist.
    
    Args:
        repo: Repository in "owner/repo" format
    
    Returns:
        True if allowed (empty allowlist = allow all)
    """
    if not CODEOPS_ALLOWED_REPOS:
        # Empty list = allow all (development mode)
        return True
    return repo in CODEOPS_ALLOWED_REPOS


# ---------------------------------------------------------------------------
# Sandbox / Runner — controlled code execution (CODE domain apply path)
# ---------------------------------------------------------------------------
# Execution mode for CODE domain apply operations.
#   "stub" (default) — no real execution, current stub behavior preserved.
#   "real"           — route to RunnerAPI / ContainerBackend (requires Docker).
# Default MUST remain "stub" so existing tests and production runs are unaffected.
APPLY_EXECUTION_MODE: str = os.environ.get("APPLY_EXECUTION_MODE", "stub")

# Hard timeout for container executions (seconds).
RUNNER_TIMEOUT_SECONDS: int = int(os.environ.get("RUNNER_TIMEOUT_SECONDS", "30"))

# Docker resource caps per container.
RUNNER_MEMORY_LIMIT: str = os.environ.get("RUNNER_MEMORY_LIMIT", "128m")
RUNNER_CPU_LIMIT: str = os.environ.get("RUNNER_CPU_LIMIT", "0.5")

# Base image — fixed, no dynamic builds.
RUNNER_BASE_IMAGE: str = os.environ.get("RUNNER_BASE_IMAGE", "python:3.11-slim")

# ---------------------------------------------------------------------------
# HOST domain executor selection
# ---------------------------------------------------------------------------
# Phase 1 status: scaffold/fallback-only.
# Execution backend for the canonical HOST pipeline.
#   "native"   (default) — existing host_agent executor
#   "openclaw"          — attempt eligible HOST actions through the OpenClaw
#                          scaffold adapter first
#
# The HOST pipeline remains the only execution seam; this flag does NOT create
# any alternate entrypoint or bypass.
# Important: the OpenClaw wire client/protocol is NOT implemented yet in this
# repository. When HOST_EXECUTOR="openclaw", eligible actions currently fall
# back to the native executor on adapter/protocol failure.
HOST_EXECUTOR: str = os.environ.get("HOST_EXECUTOR", "native").strip().lower() or "native"

# Local OpenClaw WebSocket gateway endpoint for the future documented client.
# In phase 1 scaffold mode, this value is only configuration metadata; the
# adapter does not yet implement a live gateway client.
OPENCLAW_GATEWAY_URL: str = os.environ.get(
    "OPENCLAW_GATEWAY_URL",
    "ws://127.0.0.1:18789",
).strip()

# Hard timeout reserved for the future documented OpenClaw round-trip.
# In phase 1 scaffold mode this is carried as adapter config only.
OPENCLAW_TIMEOUT_SECONDS: float = float(
    os.environ.get("OPENCLAW_TIMEOUT_SECONDS", "5.0")
)


def is_command_allowed(cmd: list[str]) -> bool:
    """
    Verifica si un comando está en la whitelist.
    
    SEGURIDAD: Comparación EXACTA del comando completo.
    No se permiten prefijos ni comandos arbitrarios.
    """
    if not cmd:
        return False
    
    cmd_tuple = tuple(cmd)
    return cmd_tuple in ALLOWED_COMMANDS


def is_path_in_workspace(path: Path) -> bool:
    """Verifica que un path esté dentro del workspace."""
    try:
        path.resolve().relative_to(WORKSPACE_ROOT)
        return True
    except ValueError:
        return False
