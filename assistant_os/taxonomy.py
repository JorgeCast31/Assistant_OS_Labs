"""
Taxonomy module for Domain/Proyecto/Project Key classification.

Handles:
- Parsing targets from user text (project, domain, key)
- Inferring taxonomy from title and existing properties
- Generating slugs for Project Key

NOTION DATA MODEL:
- Domain (multi-select, macro): Consultoría, CELLAB, Tesis, Crecimiento profesional, eiProta, TTI - ECO "…mens oritur", WORK
- Proyecto (multi-select, micro): Tesis, Búsqueda laboral, eiProta, TTI - ECO, THCyE, Cultura de Cadenas, Estado del Arte Pt.3, Evangelio III, ...
- Project Key (text): slug for matching and Docs integration
"""
import re
import unicodedata
from typing import TypedDict, Optional, Literal

# ---------------------------------------------------------------------------
# Normalization Helper (accent-insensitive matching)
# ---------------------------------------------------------------------------

def normalize_key(s: str) -> str:
    """
    Normalize string for accent-insensitive matching.
    
    - Lowercase
    - NFKD unicode normalization
    - Remove diacritical marks (accents)
    - Collapse whitespace
    
    Example: "Consultoría" -> "consultoria"
    """
    if not s:
        return s
    s = s.lower().strip()
    # NFKD: decompose characters (é -> e + combining acute)
    s = unicodedata.normalize('NFKD', s)
    # Remove combining characters (category 'Mn' = Mark, Nonspacing)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    # Collapse whitespace
    s = re.sub(r'\s+', ' ', s).strip()
    return s

# ---------------------------------------------------------------------------
# Type Definitions
# ---------------------------------------------------------------------------

TargetType = Literal["project", "domain", "key", "keyword", "none"]


class ParsedTarget(TypedDict):
    """Result of parsing a target from user text."""
    target_type: TargetType
    value: str
    raw_text: str  # Original text for audit
    has_explicit_prefix: bool  # True if user used explicit prefix like domain:, project:, key:


class TargetFilterResult(TypedDict, total=False):
    """Result of building filter from parsed target with audit info."""
    filter_type: str                    # "proyecto" | "domain" | "key" | "title_keyword" | "none" | "invalid"
    property_name: str                  # Notion property name
    filter_op: str                      # "contains" | "equals"
    filter_value: str                   # Value to filter by
    # Audit fields
    matched_taxonomy: bool              # True if value exists in live Notion taxonomy
    fallback_used: str                  # "text_search" | "none"
    original_target_type: str           # What user intended (before fallback)
    original_value: str                 # Original value before fallback
    validation_message: str             # Human-readable validation result
    suggested_values: list[str]         # Suggestions if invalid
    is_invalid_filter: bool             # True if explicit prefix used with invalid value


class InferredTaxonomy(TypedDict):
    """Result of taxonomy inference."""
    proyecto: list[str]       # Proyecto values to set
    domain: list[str]         # Domain values to set
    project_key: Optional[str]  # Slug if determinable


# ---------------------------------------------------------------------------
# Known Values (from Notion schema)
# ---------------------------------------------------------------------------

# Exact Domain options in Notion (must match Notion exactly including accents)
DOMAIN_OPTIONS = [
    "Consultoria",  # No accent (matches Notion)
    "CELLAB",
    "Tesis",
    "Crecimiento profesional",
    "eiProta",
    'TTI - ECO | "…mens oritur".',  # With pipe and period (matches Notion)
    "WORK",
]

# Exact Proyecto options in Notion
PROYECTO_OPTIONS = [
    "Tesis",
    "Búsqueda laboral",
    "eiProta",
    "TTI - ECO",
    "THCyE",
    "Cultura de Cadenas",
    "Estado del Arte Pt.3",
    "Evangelio III",
    "Consultoría",  # Added: consulting projects
    "Contenido Filosófico",
    "Teoría Informacional",
    "Estado del Arte Pt.2",
    # Add more as they appear in Notion
]

# Alias map: user input -> canonical name
# Key slugs (thcye, eda_pt3, etc.) map to target_type="key" for ProjectKey filtering
# Natural language aliases (cielos, cadenas, etc.) map to target_type="project" for Proyecto filtering
ALIAS_MAP: dict[str, tuple[TargetType, str]] = {
    # THCyE aliases - key slug uses ProjectKey, others use Proyecto
    "thcye": ("key", "thcye"),
    "hacia cielos": ("project", "THCyE"),
    "cielos y estrellas": ("project", "THCyE"),
    "cielos": ("project", "THCyE"),
    
    # Cultura de Cadenas aliases
    "cadenas": ("project", "Cultura de Cadenas"),
    "cultura cadenas": ("project", "Cultura de Cadenas"),
    "cultura de cadenas": ("key", "cultura_de_cadenas"),
    "cultura_de_cadenas": ("key", "cultura_de_cadenas"),
    
    # Estado del Arte aliases - key slug variants
    "estado del arte": ("project", "Estado del Arte Pt.3"),
    "eda": ("key", "eda_pt3"),
    "eda pt3": ("key", "eda_pt3"),
    "eda_pt3": ("key", "eda_pt3"),
    "edapt3": ("key", "eda_pt3"),
    
    # Evangelio aliases
    "evangelio": ("key", "evangelio_iii"),
    "evangelio iii": ("key", "evangelio_iii"),
    "evangelio 3": ("key", "evangelio_iii"),
    "evangelio_iii": ("key", "evangelio_iii"),
    
    # TTI-ECO aliases
    "tti": ("key", "tti_eco"),
    "tti eco": ("key", "tti_eco"),
    "tti-eco": ("key", "tti_eco"),
    "tti_eco": ("key", "tti_eco"),
    "tro": ("key", "tti_eco"),
    "mens oritur": ("domain", 'TTI - ECO | "…mens oritur".'),  # Matches Notion
    
    # eiProta aliases
    "eiprota": ("key", "eiprota"),
    "ei prota": ("project", "eiProta"),
    "protagonista": ("project", "eiProta"),
    "obras": ("domain", "eiProta"),  # "obras" = creative works = eiProta
    "mis obras": ("domain", "eiProta"),  # "mis obras" = eiProta domain
    
    # Tesis aliases
    "tesis": ("domain", "Tesis"),
    "tesis doctoral": ("domain", "Tesis"),
    "doctorado": ("domain", "Tesis"),
    
    # Búsqueda laboral aliases
    "busqueda laboral": ("project", "Búsqueda laboral"),
    "busqueda de trabajo": ("project", "Búsqueda laboral"),
    "trabajo": ("project", "Búsqueda laboral"),
    "empleo": ("project", "Búsqueda laboral"),
    
    # Consultoría aliases - FIXED: map to Proyecto "Consultoría" (with accent), NOT Domain
    # Domain "Consultoria" (no accent) has 0 tasks, Proyecto "Consultoría" has actual tasks
    "consultoria": ("project", "Consultoría"),  # Maps to Proyecto (multi_select)
    "consultoría": ("project", "Consultoría"),  # With accent also maps to Proyecto
    "consulting": ("project", "Consultoría"),
    
    # Other Domain aliases (must map to exact Notion values)
    "cellab": ("domain", "CELLAB"),
    "laboratorio": ("domain", "CELLAB"),
    "crecimiento": ("domain", "Crecimiento profesional"),
    "profesional": ("domain", "Crecimiento profesional"),
}

# Project Key slug to key filter mapping
# Returns ("key", slug) to filter by ProjectKey property
PROJECT_KEY_MAP: dict[str, tuple[TargetType, str]] = {
    "thcye": ("key", "thcye"),
    "cultura_de_cadenas": ("key", "cultura_de_cadenas"),
    "eda_pt3": ("key", "eda_pt3"),
    "evangelio_iii": ("key", "evangelio_iii"),
    "tti_eco": ("key", "tti_eco"),
    "eiprota": ("key", "eiprota"),
    "tesis": ("key", "tesis"),
    "busqueda_laboral": ("key", "busqueda_laboral"),
    "consultoria": ("key", "consultoria"),
    "cellab": ("key", "cellab"),
}


# ---------------------------------------------------------------------------
# Inference Rules: Proyecto -> Domain
# ---------------------------------------------------------------------------

# Maps Proyecto values to inferred Domain values
PROYECTO_TO_DOMAIN: dict[str, list[str]] = {
    "THCyE": ["eiProta"],
    "Cultura de Cadenas": ["eiProta"],
    "Estado del Arte Pt.3": ["eiProta"],
    "Evangelio III": ["eiProta"],
    "Tesis": ["Tesis"],
    "Consultoría": ["Consultoría"],
    "Búsqueda laboral": ["Crecimiento profesional"],
    "TTI - ECO": ['TTI - ECO "…mens oritur"'],
    "eiProta": ["eiProta"],
}

# Keywords in title that suggest specific domains
KEYWORD_TO_DOMAIN: dict[str, str] = {
    "tti": 'TTI - ECO "…mens oritur"',
    "tro": 'TTI - ECO "…mens oritur"',
    "teoría informacional": 'TTI - ECO "…mens oritur"',
    "contenido filosófico": 'TTI - ECO "…mens oritur"',
    "matemática": 'TTI - ECO "…mens oritur"',
    "filosofía": 'TTI - ECO "…mens oritur"',
}

# Proyecto to Project Key slug mapping
PROYECTO_TO_KEY: dict[str, str] = {
    "THCyE": "thcye",
    "Cultura de Cadenas": "cultura_de_cadenas",
    "Estado del Arte Pt.3": "eda_pt3",
    "Evangelio III": "evangelio_iii",
    "TTI - ECO": "tti_eco",
    "eiProta": "eiprota",
    "Tesis": "tesis",
    "Búsqueda laboral": "busqueda_laboral",
}


# ---------------------------------------------------------------------------
# Target Parsing
# ---------------------------------------------------------------------------

def parse_target_from_text(text: str) -> ParsedTarget:
    """
    Parse target from user text for query filtering.
    
    Resolution order:
    1. Explicit key: prefix (key:xxx, k:xxx)
    2. Explicit domain: prefix (domain:xxx, d:xxx)
    3. Explicit project: prefix (proyecto:xxx, p:xxx, project:xxx)
    4. Alias map lookup (checked FIRST for user-friendly terms)
    5. Exact match against Proyecto options (case-insensitive, word boundary)
    6. Exact match against Domain options (case-insensitive, word boundary)
    7. Project Key map lookup
    8. Keyword extraction (last resort)
    
    Args:
        text: User input like "tareas de THCyE" or "tareas key:thcye"
    
    Returns:
        ParsedTarget with target_type, value, raw_text, and has_explicit_prefix
    """
    text_lower = text.lower().strip()
    
    # Remove common prefixes (with word boundaries to avoid consuming part of target words)
    # E.g., "tareas consultoria" should NOT match "con" from "consultoria"
    clean_text = re.sub(r"^(tareas?|tasks?|pendientes?|status|estado)\s+(?:(de|del|para|en|con|sobre)\s+)?", "", text_lower, flags=re.IGNORECASE)
    clean_text = re.sub(r"^(tareas?|tasks?)\s+(?:(de|del|para|en|con)\s+)?", "", clean_text, flags=re.IGNORECASE)  # Handle nested "sobre tareas de"
    clean_text = clean_text.strip()
    
    # Normalize for accent-insensitive matching
    clean_text_normalized = normalize_key(clean_text)
    
    # 1. Check explicit key: prefix (project_key:xxx, key:xxx, k:xxx)
    key_match = re.search(r"\b(?:project_key|key|k):(\S+)", text_lower)
    if key_match:
        key_val = key_match.group(1).strip()
        # Resolve key to canonical name if exists
        if key_val in PROJECT_KEY_MAP:
            target_type, canonical = PROJECT_KEY_MAP[key_val]
            return ParsedTarget(target_type="key", value=key_val, raw_text=text, has_explicit_prefix=True)
        return ParsedTarget(target_type="key", value=key_val, raw_text=text, has_explicit_prefix=True)
    
    # 2. Check explicit domain: prefix  
    domain_match = re.search(r"\b(?:domain|d|dominio):(\S+)", text_lower)
    if domain_match:
        domain_val = domain_match.group(1).strip()
        # Try to match against known domains
        for opt in DOMAIN_OPTIONS:
            if opt.lower() == domain_val or opt.lower().startswith(domain_val):
                return ParsedTarget(target_type="domain", value=opt, raw_text=text, has_explicit_prefix=True)
        return ParsedTarget(target_type="domain", value=domain_val, raw_text=text, has_explicit_prefix=True)
    
    # 3. Check explicit project: prefix
    project_match = re.search(r"\b(?:project[o]?|proyecto|p):(\S+)", text_lower)
    if project_match:
        project_val = project_match.group(1).strip()
        # Try to match against known projects
        for opt in PROYECTO_OPTIONS:
            if opt.lower() == project_val or opt.lower().startswith(project_val):
                return ParsedTarget(target_type="project", value=opt, raw_text=text, has_explicit_prefix=True)
        return ParsedTarget(target_type="project", value=project_val, raw_text=text, has_explicit_prefix=True)
    
    # 4. Alias map lookup (checked BEFORE exact matches for user-friendly terms)
    # Sort by length descending to match longer aliases first (avoid partial matches)
    # Use normalized comparison for accent-insensitive matching
    sorted_aliases = sorted(ALIAS_MAP.items(), key=lambda x: len(x[0]), reverse=True)
    for alias, (target_type, canonical) in sorted_aliases:
        # Normalize alias for comparison
        alias_normalized = normalize_key(alias)
        # Use word boundary matching for exact alias match
        if re.search(r"\b" + re.escape(alias_normalized) + r"\b", clean_text_normalized):
            return ParsedTarget(target_type=target_type, value=canonical, raw_text=text, has_explicit_prefix=False)
    
    # 5. Exact match against Proyecto options (with word boundaries)
    # Sort by length descending to match longer names first
    sorted_proyectos = sorted(PROYECTO_OPTIONS, key=len, reverse=True)
    for opt in sorted_proyectos:
        opt_normalized = normalize_key(opt)
        # Use word boundary matching to avoid partial substring matches
        if re.search(r"\b" + re.escape(opt_normalized) + r"\b", clean_text_normalized):
            return ParsedTarget(target_type="project", value=opt, raw_text=text, has_explicit_prefix=False)
    
    # 6. Exact match against Domain options (with word boundaries)
    for opt in DOMAIN_OPTIONS:
        opt_normalized = normalize_key(opt)
        # Handle special case for TTI - ECO which has quotes
        opt_simple = re.sub(r'[""…|.]', '', opt_normalized).strip()
        if re.search(r"\b" + re.escape(opt_normalized) + r"\b", clean_text_normalized) or \
           re.search(r"\b" + re.escape(opt_simple) + r"\b", clean_text_normalized):
            return ParsedTarget(target_type="domain", value=opt, raw_text=text, has_explicit_prefix=False)
    
    # 7. Project Key map lookup with slug normalization
    # Normalize: remove separators between words (edapt3 → eda_pt3 pattern)
    normalized_text = re.sub(r"[\s\-]+", "_", clean_text_normalized)  # spaces/hyphens → underscore
    normalized_text = re.sub(r"_+", "_", normalized_text)  # collapse multiple underscores
    
    for key_slug, (target_type, key_value) in PROJECT_KEY_MAP.items():
        # Match normalized slug patterns
        if re.search(r"\b" + re.escape(key_slug) + r"\b", normalized_text):
            return ParsedTarget(target_type="key", value=key_value, raw_text=text, has_explicit_prefix=False)
        # Also try matching without underscores (e.g., "edapt3" matches "eda_pt3")
        slug_no_sep = key_slug.replace("_", "")
        if re.search(r"\b" + re.escape(slug_no_sep) + r"\b", normalized_text.replace("_", "")):
            return ParsedTarget(target_type="key", value=key_value, raw_text=text, has_explicit_prefix=False)
    
    # 8. Keyword extraction: look for capitalized words that might be project names
    cap_match = re.search(r"\b([A-Z][A-Za-z0-9_-]+(?:\s+[A-Z][A-Za-z0-9_-]+)*)\b", text)
    if cap_match:
        keyword = cap_match.group(1)
        # Exclude common words
        if keyword.upper() not in {"QUE", "HOY", "LOS", "LAS", "UNA", "CON", "POR", "MIS", "TUS", "PARA", "STATUS", "NEXT", "INBOX", "WAITING", "SCHEDULED"}:
            return ParsedTarget(target_type="keyword", value=keyword, raw_text=text, has_explicit_prefix=False)
    
    return ParsedTarget(target_type="none", value="", raw_text=text, has_explicit_prefix=False)


# ---------------------------------------------------------------------------
# Taxonomy Inference
# ---------------------------------------------------------------------------

def infer_taxonomy(
    title: str,
    proyecto_list: Optional[list[str]] = None,
    domain_list: Optional[list[str]] = None,
    existing_key: Optional[str] = None,
) -> InferredTaxonomy:
    """
    Infer taxonomy from title and existing properties.
    
    Used when creating or updating tasks to auto-fill Domain/Proyecto/Key.
    
    Rules:
    1. If Proyecto includes eiProta works -> Domain includes "eiProta"
    2. If Proyecto includes "Tesis" -> Domain includes "Tesis"
    3. If Proyecto includes "Consultoría" -> Domain includes "Consultoría"
    4. If Proyecto includes "Búsqueda laboral" -> Domain includes "Crecimiento profesional"
    5. If Proyecto includes "TTI - ECO" or title has TTI keywords -> Domain includes "TTI - ECO "…mens oritur""
    6. Project Key: derive from Proyecto, Domain, or title slug. Never overwrite existing.
    
    Args:
        title: Task title
        proyecto_list: Current Proyecto values (if any)
        domain_list: Current Domain values (if any)
        existing_key: Current Project Key (if any, will not be overwritten)
    
    Returns:
        InferredTaxonomy with proyecto, domain, project_key to set
    """
    proyecto_list = proyecto_list or []
    domain_list = domain_list or []
    title_lower = title.lower()
    
    inferred_domains: set[str] = set(domain_list)
    inferred_proyectos: set[str] = set(proyecto_list)
    inferred_key: Optional[str] = existing_key
    
    # Rule 1-4: Infer Domain from Proyecto
    for proyecto in proyecto_list:
        if proyecto in PROYECTO_TO_DOMAIN:
            inferred_domains.update(PROYECTO_TO_DOMAIN[proyecto])
    
    # Rule 5: TTI keywords in title -> TTI domain
    for keyword, domain in KEYWORD_TO_DOMAIN.items():
        if keyword in title_lower:
            inferred_domains.add(domain)
    
    # Rule 6: Project Key derivation (only if not already set)
    if not inferred_key:
        # Try to derive from Proyecto first
        for proyecto in proyecto_list:
            if proyecto in PROYECTO_TO_KEY:
                inferred_key = PROYECTO_TO_KEY[proyecto]
                break
        
        # If no key yet, try to derive from Domain
        if not inferred_key:
            for domain in domain_list:
                slug = _slugify(domain)
                if slug:
                    inferred_key = slug
                    break
        
        # Last resort: slugify title
        if not inferred_key and title:
            inferred_key = _slugify(title)[:30]  # Cap at 30 chars
    
    return InferredTaxonomy(
        proyecto=list(inferred_proyectos),
        domain=list(inferred_domains),
        project_key=inferred_key,
    )


def _slugify(text: str) -> str:
    """Convert text to slug format."""
    # Normalize unicode, remove accents
    import unicodedata
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    # Lowercase, replace spaces/special chars with underscore
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[\s-]+", "_", text).strip("_")
    return text


# ---------------------------------------------------------------------------
# Filter Building for Notion Query
# ---------------------------------------------------------------------------

def build_target_filter(parsed: ParsedTarget, validate_live: bool = True) -> TargetFilterResult:
    """
    Build Notion filter conditions from parsed target WITH live validation.
    
    IMPORTANT CHANGES:
    - Now validates target values against LIVE Notion taxonomy (via taxonomy_sync)
    - If value doesn't exist in live taxonomy AND no explicit prefix:
      → Falls back to text search in title (title_keyword)
    - If explicit prefix AND value doesn't exist:
      → Returns is_invalid_filter=True with suggested values for UI
    
    Args:
        parsed: ParsedTarget from parse_target_from_text()
        validate_live: If True, validate against Notion schema (default True)
    
    Returns:
        TargetFilterResult with filter conditions and detailed audit info
    """
    from .taxonomy_sync import validate_domain, validate_proyecto, get_valid_domains, get_valid_proyectos
    
    if parsed["target_type"] == "none":
        return TargetFilterResult(
            filter_type="none",
            matched_taxonomy=False,
            fallback_used="none",
            original_target_type="none",
            original_value="",
            validation_message="No target detected",
        )
    
    target_type = parsed["target_type"]
    value = parsed["value"]
    has_explicit_prefix = parsed.get("has_explicit_prefix", False)
    
    # ---------------------------------------------------------------------------
    # PROJECT KEY - Always use as-is (text match, no taxonomy validation)
    # ---------------------------------------------------------------------------
    if target_type == "key":
        # For project_key, we don't validate against taxonomy - it's free-form text
        # But we DO validate if explicitly prefixed and want suggestions
        return TargetFilterResult(
            filter_type="key",
            property_name="Project Key",
            filter_op="equals",
            filter_value=value,
            matched_taxonomy=True,  # Keys are always valid (free-form)
            fallback_used="none",
            original_target_type="key",
            original_value=value,
            validation_message=f"Project Key filter: '{value}'",
            is_invalid_filter=False,
        )
    
    # ---------------------------------------------------------------------------
    # DOMAIN - Validate against live taxonomy
    # ---------------------------------------------------------------------------
    elif target_type == "domain":
        if validate_live:
            is_valid, suggestion = validate_domain(value)
            
            if is_valid:
                return TargetFilterResult(
                    filter_type="domain",
                    property_name="Domain",
                    filter_op="equals",  # select type uses equals
                    filter_value=suggestion or value,  # Use canonical form
                    matched_taxonomy=True,
                    fallback_used="none",
                    original_target_type="domain",
                    original_value=value,
                    validation_message=f"Domain '{suggestion or value}' found in taxonomy",
                    is_invalid_filter=False,
                )
            else:
                # Domain NOT found in live taxonomy
                if has_explicit_prefix:
                    # Explicit prefix used (domain:xxx) - return InvalidFilter
                    valid_domains = get_valid_domains()
                    return TargetFilterResult(
                        filter_type="invalid",
                        matched_taxonomy=False,
                        fallback_used="none",
                        original_target_type="domain",
                        original_value=value,
                        validation_message=f"Domain '{value}' not found in Notion taxonomy",
                        suggested_values=valid_domains[:5],
                        is_invalid_filter=True,
                    )
                else:
                    # No explicit prefix - fallback to text search
                    return TargetFilterResult(
                        filter_type="title_keyword",
                        property_name="Name",
                        filter_op="contains",
                        filter_value=value,
                        matched_taxonomy=False,
                        fallback_used="text_search",
                        original_target_type="domain",
                        original_value=value,
                        validation_message=f"Domain '{value}' not in taxonomy, using text search",
                        is_invalid_filter=False,
                    )
        else:
            # Skip validation, use as-is
            return TargetFilterResult(
                filter_type="domain",
                property_name="Domain",
                filter_op="equals",
                filter_value=value,
                matched_taxonomy=True,
                fallback_used="none",
                original_target_type="domain",
                original_value=value,
                is_invalid_filter=False,
            )
    
    # ---------------------------------------------------------------------------
    # PROJECT - Validate against live taxonomy
    # ---------------------------------------------------------------------------
    elif target_type == "project":
        if validate_live:
            is_valid, suggestion = validate_proyecto(value)
            
            if is_valid:
                return TargetFilterResult(
                    filter_type="proyecto",
                    property_name="Proyecto",
                    filter_op="contains",  # multi_select uses contains
                    filter_value=suggestion or value,  # Use canonical form
                    matched_taxonomy=True,
                    fallback_used="none",
                    original_target_type="project",
                    original_value=value,
                    validation_message=f"Proyecto '{suggestion or value}' found in taxonomy",
                    is_invalid_filter=False,
                )
            else:
                # Project NOT found in live taxonomy
                if has_explicit_prefix:
                    # Explicit prefix used (project:xxx) - return InvalidFilter
                    valid_proyectos = get_valid_proyectos()
                    return TargetFilterResult(
                        filter_type="invalid",
                        matched_taxonomy=False,
                        fallback_used="none",
                        original_target_type="project",
                        original_value=value,
                        validation_message=f"Proyecto '{value}' not found in Notion taxonomy",
                        suggested_values=valid_proyectos[:5],
                        is_invalid_filter=True,
                    )
                else:
                    # No explicit prefix - fallback to text search
                    return TargetFilterResult(
                        filter_type="title_keyword",
                        property_name="Name",
                        filter_op="contains",
                        filter_value=value,
                        matched_taxonomy=False,
                        fallback_used="text_search",
                        original_target_type="project",
                        original_value=value,
                        validation_message=f"Proyecto '{value}' not in taxonomy, using text search",
                        is_invalid_filter=False,
                    )
        else:
            # Skip validation, use as-is
            return TargetFilterResult(
                filter_type="proyecto",
                property_name="Proyecto",
                filter_op="contains",
                filter_value=value,
                matched_taxonomy=True,
                fallback_used="none",
                original_target_type="project",
                original_value=value,
                is_invalid_filter=False,
            )
    
    # ---------------------------------------------------------------------------
    # KEYWORD - Already text search, no validation needed
    # ---------------------------------------------------------------------------
    elif target_type == "keyword":
        return TargetFilterResult(
            filter_type="title_keyword",
            property_name="Name",
            filter_op="contains",
            filter_value=value,
            matched_taxonomy=False,  # Keywords don't match taxonomy
            fallback_used="none",  # This IS text search, not a fallback
            original_target_type="keyword",
            original_value=value,
            validation_message=f"Keyword search in title: '{value}'",
            is_invalid_filter=False,
        )
    
    return TargetFilterResult(
        filter_type="none",
        matched_taxonomy=False,
        fallback_used="none",
    )


# Legacy function for backward compatibility
def build_target_filter_legacy(parsed: ParsedTarget) -> dict:
    """
    Legacy version of build_target_filter for backward compatibility.
    
    Returns a simplified dict without validation.
    """
    result = build_target_filter(parsed, validate_live=False)
    return {
        "filter_type": result.get("filter_type", "none"),
        "property_name": result.get("property_name", ""),
        "filter_op": result.get("filter_op", ""),
        "filter_value": result.get("filter_value", ""),
    }
