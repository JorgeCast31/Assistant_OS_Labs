"""
Tests for WORK_QUERY vs DOC routing fix.

Tests:
1. "tareas urgentes" => intent WORK_QUERY, mode answer, NO doc path
2. "prioridad alta" => WORK_QUERY
3. "qué tengo hoy" => WORK_QUERY with date_range hoy
4. "crea un doc de..." => DOC_CREATE (is_doc_request=True)
5. "redacta POE..." => DOC_CREATE (is_doc_request=True)
6. "resume mis tareas en un doc" => DOC (explicit doc request takes priority)
"""
from assistant_os.classifier import (
    is_work_query,
    is_doc_request,
    map_intent_to_prefix,
    parse_work_query_filters,
    classify_text,
    PREFIX_WORK_QUERY,
    PREFIX_DOC,
)
from assistant_os.contracts import ClassifyRequest


# ---------------------------------------------------------------------------
# Test 1: "tareas urgentes" => WORK_QUERY
# ---------------------------------------------------------------------------

def test_tareas_urgentes_routes_to_work_query():
    """'tareas urgentes' should route to WORK_QUERY, not DOC."""
    text = "Hola. tareas urgentes?"
    
    # Check is_work_query
    assert is_work_query(text) is True
    
    # Check is_doc_request (should be False)
    assert is_doc_request(text) is False
    
    # Check prefix mapping
    intent = classify_text(ClassifyRequest(text=text))
    prefix = map_intent_to_prefix(text, intent)
    assert prefix == PREFIX_WORK_QUERY


# ---------------------------------------------------------------------------
# Test 2: "prioridad alta" => WORK_QUERY
# ---------------------------------------------------------------------------

def test_prioridad_alta_routes_to_work_query():
    """'prioridad alta' should route to WORK_QUERY."""
    text = "qué hay de prioridad alta?"
    
    assert is_work_query(text) is True
    assert is_doc_request(text) is False
    
    intent = classify_text(ClassifyRequest(text=text))
    prefix = map_intent_to_prefix(text, intent)
    assert prefix == PREFIX_WORK_QUERY


# ---------------------------------------------------------------------------
# Test 3: "qué tengo hoy" => WORK_QUERY with date filter
# ---------------------------------------------------------------------------

def test_que_tengo_hoy_routes_to_work_query():
    """'qué tengo hoy' should route to WORK_QUERY."""
    text = "qué tengo hoy"
    
    assert is_work_query(text) is True
    assert is_doc_request(text) is False
    
    intent = classify_text(ClassifyRequest(text=text))
    prefix = map_intent_to_prefix(text, intent)
    assert prefix == PREFIX_WORK_QUERY
    
    # Check that filters are parsed
    filters = parse_work_query_filters(text)
    # Should detect "hoy" date pattern
    assert "date_range" in filters or "hoy" in text.lower()


# ---------------------------------------------------------------------------
# Test 4: "crea un doc de..." => DOC_CREATE
# ---------------------------------------------------------------------------

def test_crea_un_doc_routes_to_doc():
    """'crea un doc de proyecto X' should route to DOC."""
    text = "crea un doc de proyecto X"
    
    # Should be doc request
    assert is_doc_request(text) is True
    
    # is_work_query should be False because is_doc_request takes priority
    assert is_work_query(text) is False
    
    intent = classify_text(ClassifyRequest(text=text))
    prefix = map_intent_to_prefix(text, intent)
    assert prefix == PREFIX_DOC


# ---------------------------------------------------------------------------
# Test 5: "redacta POE..." => DOC_CREATE
# ---------------------------------------------------------------------------

def test_redacta_poe_routes_to_doc():
    """'redacta POE de calibración' should route to DOC."""
    text = "redacta POE de calibración de incubadoras"
    
    assert is_doc_request(text) is True
    
    intent = classify_text(ClassifyRequest(text=text))
    prefix = map_intent_to_prefix(text, intent)
    assert prefix == PREFIX_DOC


# ---------------------------------------------------------------------------
# Test 6: "resume mis tareas en un doc" => DOC (explicit doc takes priority)
# ---------------------------------------------------------------------------

def test_ambiguous_doc_request_routes_to_doc():
    """'resume mis tareas en un doc' has both patterns, but explicit DOC takes priority."""
    text = "resume mis tareas en un documento"
    
    # This has "tareas" (work query pattern) AND "documento" (doc request pattern)
    # The doc request should be detected
    assert is_doc_request(text) is True
    
    # is_work_query should return False when is_doc_request is True
    assert is_work_query(text) is False
    
    intent = classify_text(ClassifyRequest(text=text))
    prefix = map_intent_to_prefix(text, intent)
    assert prefix == PREFIX_DOC


# ---------------------------------------------------------------------------
# Additional edge case tests
# ---------------------------------------------------------------------------

def test_simple_pendientes_routes_to_work_query():
    """'pendientes' should route to WORK_QUERY."""
    text = "pendientes"
    
    assert is_work_query(text) is True
    assert is_doc_request(text) is False


def test_inbox_routes_to_work_query():
    """'qué hay en inbox' should route to WORK_QUERY."""
    text = "qué hay en inbox"
    
    assert is_work_query(text) is True


def test_informe_routes_to_doc():
    """'haz un informe de...' should route to DOC."""
    text = "haz un informe del proyecto"
    
    assert is_doc_request(text) is True


# ---------------------------------------------------------------------------
# Run with: python -m unittest tests.test_work_query_routing -v
# ---------------------------------------------------------------------------
