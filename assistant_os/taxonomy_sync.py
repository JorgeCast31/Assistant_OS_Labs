"""
Taxonomy Sync - Sync and cache taxonomy options from Notion schema.

This module:
- Reads schema from Notion WORK DB (Domain, Proyecto, Status)
- Caches locally as JSON with timestamp
- Provides refresh_taxonomy() and get_valid_options()
- Enables dynamic validation without hardcoded values

The cache ensures:
- Offline fallback to last known values
- Fast access without API calls on every request
- Automatic refresh when stale (configurable TTL)
"""
import json
import logging
import unicodedata
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, TypedDict

from .config import MEMORY_DIR

# Logger
_log = logging.getLogger("taxonomy_sync")


# ---------------------------------------------------------------------------
# Normalization Helper (for accent-insensitive validation)
# ---------------------------------------------------------------------------

def _normalize_for_comparison(s: str) -> str:
    """
    Normalize string for accent-insensitive comparison.
    
    - Lowercase
    - NFKD unicode normalization
    - Remove diacritical marks (accents)
    """
    if not s:
        return s
    s = s.lower().strip()
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return s


# ---------------------------------------------------------------------------
# Type Definitions
# ---------------------------------------------------------------------------

class TaxonomyCache(TypedDict):
    """Cached taxonomy data from Notion schema."""
    timestamp: str                    # ISO format
    ttl_hours: int                    # Cache TTL in hours
    domain_options: list[str]         # Domain (select) options
    proyecto_options: list[str]       # Proyecto (multi-select) options
    status_options: list[str]         # Status (select/status) options
    schema_raw: dict                  # Full schema for debugging


class TaxonomyOptions(TypedDict):
    """Available options for a field."""
    options: list[str]
    source: str  # "cache" | "notion" | "default"
    timestamp: Optional[str]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TAXONOMY_CACHE_FILE = MEMORY_DIR / "taxonomy_cache.json"
DEFAULT_TTL_HOURS = 24  # Refresh cache every 24 hours

# Default fallback values (used when Notion unavailable and no cache)
DEFAULT_STATUS_OPTIONS = ["NEXT", "INBOX", "WAITING", "SCHEDULED", "DONE", "CANCELLED", "ARCHIVED"]
DEFAULT_DOMAIN_OPTIONS = ["Consultoría", "CELLAB", "Tesis", "Crecimiento profesional", "eiProta", "WORK"]
DEFAULT_PROYECTO_OPTIONS = ["Tesis", "Búsqueda laboral", "eiProta", "TTI - ECO", "THCyE", "Consultoría"]


# ---------------------------------------------------------------------------
# Cache Operations
# ---------------------------------------------------------------------------

def _load_cache() -> Optional[TaxonomyCache]:
    """Load taxonomy cache from disk."""
    try:
        if TAXONOMY_CACHE_FILE.exists():
            with open(TAXONOMY_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return TaxonomyCache(**data)
    except Exception as e:
        _log.warning(f"[TAXONOMY_SYNC] Failed to load cache: {e}")
    return None


def _save_cache(cache: TaxonomyCache) -> bool:
    """Save taxonomy cache to disk."""
    try:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        with open(TAXONOMY_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
        _log.info(f"[TAXONOMY_SYNC] Cache saved: {len(cache['status_options'])} statuses, "
                  f"{len(cache['domain_options'])} domains, {len(cache['proyecto_options'])} proyectos")
        return True
    except Exception as e:
        _log.error(f"[TAXONOMY_SYNC] Failed to save cache: {e}")
        return False


def _is_cache_stale(cache: TaxonomyCache) -> bool:
    """Check if cache is stale (older than TTL)."""
    try:
        cached_time = datetime.fromisoformat(cache["timestamp"].replace("Z", "+00:00"))
        now = datetime.now(cached_time.tzinfo) if cached_time.tzinfo else datetime.now()
        ttl_hours = cache.get("ttl_hours", DEFAULT_TTL_HOURS)
        age_hours = (now - cached_time).total_seconds() / 3600
        return age_hours > ttl_hours
    except Exception:
        return True  # Assume stale if can't parse


# ---------------------------------------------------------------------------
# Schema Extraction
# ---------------------------------------------------------------------------

def _extract_options_from_schema(schema: dict) -> TaxonomyCache:
    """Extract taxonomy options from Notion schema."""
    domain_options: list[str] = []
    proyecto_options: list[str] = []
    status_options: list[str] = []
    
    for prop_name, prop_info in schema.items():
        prop_type = prop_info.get("type", "")
        options = prop_info.get("options", [])
        
        # Match property names (case-insensitive)
        name_lower = prop_name.lower()
        
        if name_lower == "domain" or name_lower == "dominio":
            domain_options = options
        elif name_lower == "proyecto" or name_lower == "project":
            proyecto_options = options
        elif name_lower == "status" or name_lower == "estado":
            status_options = options
    
    return TaxonomyCache(
        timestamp=datetime.now().isoformat(),
        ttl_hours=DEFAULT_TTL_HOURS,
        domain_options=domain_options,
        proyecto_options=proyecto_options,
        status_options=status_options,
        schema_raw=schema,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def refresh_taxonomy(force: bool = False) -> dict:
    """
    Refresh taxonomy cache from Notion.
    
    Args:
        force: If True, refresh even if cache is not stale
    
    Returns:
        dict with ok, message, and taxonomy preview
    """
    from .integrations.notion import get_database_schema, check_notion_available
    
    # Check if refresh needed
    cache = _load_cache()
    if cache and not force and not _is_cache_stale(cache):
        return {
            "ok": True,
            "message": "Cache is fresh, no refresh needed",
            "source": "cache",
            "timestamp": cache["timestamp"],
            "stats": {
                "statuses": len(cache["status_options"]),
                "domains": len(cache["domain_options"]),
                "proyectos": len(cache["proyecto_options"]),
            }
        }
    
    # Check Notion availability
    if not check_notion_available():
        _log.warning("[TAXONOMY_SYNC] Notion unavailable, using existing cache or defaults")
        return {
            "ok": False,
            "message": "Notion unavailable",
            "source": "cache" if cache else "default",
            "timestamp": cache["timestamp"] if cache else None,
        }
    
    # Fetch schema from Notion
    result = get_database_schema()
    if not result.get("ok"):
        _log.error(f"[TAXONOMY_SYNC] Failed to get schema: {result.get('error')}")
        return {
            "ok": False,
            "message": f"Failed to get schema: {result.get('error')}",
            "source": "cache" if cache else "default",
        }
    
    # Extract and save new cache
    schema = result.get("schema", {})
    new_cache = _extract_options_from_schema(schema)
    _save_cache(new_cache)
    
    _log.info(f"[TAXONOMY_SYNC] Refreshed from Notion: {len(new_cache['status_options'])} statuses, "
              f"{len(new_cache['domain_options'])} domains, {len(new_cache['proyecto_options'])} proyectos")
    
    return {
        "ok": True,
        "message": "Taxonomy refreshed from Notion",
        "source": "notion",
        "timestamp": new_cache["timestamp"],
        "stats": {
            "statuses": len(new_cache["status_options"]),
            "domains": len(new_cache["domain_options"]),
            "proyectos": len(new_cache["proyecto_options"]),
        },
        "preview": {
            "statuses": new_cache["status_options"][:5],
            "domains": new_cache["domain_options"][:5],
            "proyectos": new_cache["proyecto_options"][:5],
        }
    }


def get_valid_options(field: str) -> TaxonomyOptions:
    """
    Get valid options for a taxonomy field.
    
    Args:
        field: One of "status", "domain", "proyecto"
    
    Returns:
        TaxonomyOptions with list of valid values
    """
    cache = _load_cache()
    
    field_lower = field.lower()
    
    # Map field to cache key
    field_map = {
        "status": ("status_options", DEFAULT_STATUS_OPTIONS),
        "estado": ("status_options", DEFAULT_STATUS_OPTIONS),
        "domain": ("domain_options", DEFAULT_DOMAIN_OPTIONS),
        "dominio": ("domain_options", DEFAULT_DOMAIN_OPTIONS),
        "proyecto": ("proyecto_options", DEFAULT_PROYECTO_OPTIONS),
        "project": ("proyecto_options", DEFAULT_PROYECTO_OPTIONS),
    }
    
    if field_lower not in field_map:
        return TaxonomyOptions(
            options=[],
            source="unknown",
            timestamp=None,
        )
    
    cache_key, defaults = field_map[field_lower]
    
    if cache and cache.get(cache_key):
        return TaxonomyOptions(
            options=cache[cache_key],
            source="cache",
            timestamp=cache["timestamp"],
        )
    
    return TaxonomyOptions(
        options=defaults,
        source="default",
        timestamp=None,
    )


def get_valid_statuses() -> list[str]:
    """Get list of valid status values (convenience function)."""
    return get_valid_options("status")["options"]


def get_valid_domains() -> list[str]:
    """Get list of valid domain values (convenience function)."""
    return get_valid_options("domain")["options"]


def get_valid_proyectos() -> list[str]:
    """Get list of valid proyecto values (convenience function)."""
    return get_valid_options("proyecto")["options"]


def validate_status(value: str) -> tuple[bool, Optional[str]]:
    """
    Validate a status value against known options.
    
    Args:
        value: Status value to validate
    
    Returns:
        Tuple of (is_valid, suggested_value or None)
    """
    valid_statuses = get_valid_statuses()
    value_upper = value.upper()
    
    # Exact match (case-insensitive)
    for status in valid_statuses:
        if status.upper() == value_upper:
            return True, status  # Return canonical form
    
    # Fuzzy match - find closest
    for status in valid_statuses:
        if value_upper in status.upper() or status.upper() in value_upper:
            return False, status  # Suggest similar
    
    return False, None


def validate_domain(value: str) -> tuple[bool, Optional[str]]:
    """
    Validate a domain value against known options.
    
    Uses accent-insensitive comparison.
    
    Args:
        value: Domain value to validate
    
    Returns:
        Tuple of (is_valid, suggested_value or None)
    """
    valid_domains = get_valid_domains()
    value_normalized = _normalize_for_comparison(value)
    
    # Exact match (accent-insensitive)
    for domain in valid_domains:
        if _normalize_for_comparison(domain) == value_normalized:
            return True, domain  # Return canonical form
    
    # Fuzzy match - find closest
    for domain in valid_domains:
        domain_norm = _normalize_for_comparison(domain)
        if value_normalized in domain_norm or domain_norm in value_normalized:
            return False, domain  # Suggest similar
    
    return False, None


def validate_proyecto(value: str) -> tuple[bool, Optional[str]]:
    """
    Validate a proyecto value against known options.
    
    Uses accent-insensitive comparison.
    
    Args:
        value: Proyecto value to validate
    
    Returns:
        Tuple of (is_valid, suggested_value or None)
    """
    valid_proyectos = get_valid_proyectos()
    value_normalized = _normalize_for_comparison(value)
    
    # Exact match (accent-insensitive)
    for proyecto in valid_proyectos:
        if _normalize_for_comparison(proyecto) == value_normalized:
            return True, proyecto  # Return canonical form
    
    # Fuzzy match - find closest
    for proyecto in valid_proyectos:
        proyecto_norm = _normalize_for_comparison(proyecto)
        if value_normalized in proyecto_norm or proyecto_norm in value_normalized:
            return False, proyecto  # Suggest similar
    
    return False, None


def get_cache_status() -> dict:
    """Get current cache status for debugging."""
    cache = _load_cache()
    if not cache:
        return {
            "cached": False,
            "using_defaults": True,
        }
    
    return {
        "cached": True,
        "timestamp": cache["timestamp"],
        "stale": _is_cache_stale(cache),
        "ttl_hours": cache.get("ttl_hours", DEFAULT_TTL_HOURS),
        "counts": {
            "statuses": len(cache["status_options"]),
            "domains": len(cache["domain_options"]),
            "proyectos": len(cache["proyecto_options"]),
        }
    }


def ensure_taxonomy_loaded() -> None:
    """
    Ensure taxonomy is loaded (from cache or Notion).
    
    Called on startup to ensure we have valid options.
    Does not block if cache exists, only refreshes if stale.
    """
    cache = _load_cache()
    if cache and not _is_cache_stale(cache):
        _log.debug("[TAXONOMY_SYNC] Using cached taxonomy")
        return
    
    # Try to refresh in background (non-blocking)
    try:
        refresh_taxonomy()
    except Exception as e:
        _log.warning(f"[TAXONOMY_SYNC] Failed to refresh taxonomy: {e}")
