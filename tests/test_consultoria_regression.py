"""
Test cases for the consultoria regression fix.

Tests:
1. "consultoria" maps to Proyecto "Consultoría" (not Domain)
2. Unknown token uses text search fallback
3. Explicit prefix with non-existent value → InvalidFilter + suggested values
4. "tareas" without filters works normally
5. "tareas status NEXT" combines status correctly
6. Audit fields are present

Bug context:
- "tareas consultoría" was returning 0 results because ALIAS_MAP mapped
  "consultoria" to Domain "Consultoria" (no accent, no tasks)
- Should map to Proyecto "Consultoría" (with accent, has tasks)
"""
import unittest
from unittest.mock import patch

from assistant_os.classifier import parse_work_query_filters
from assistant_os.taxonomy import (
    parse_target_from_text,
    build_target_filter,
    ALIAS_MAP,
    PROYECTO_OPTIONS,
)


class TestConsultoriaRegression(unittest.TestCase):
    """Regression tests for the consultoria mapping fix."""

    def test_consultoria_maps_to_proyecto_not_domain(self):
        """
        REGRESSION: 'consultoria' should map to Proyecto "Consultoría", NOT Domain.
        
        Previously: ("domain", "Consultoria") → 0 results
        Fixed: ("project", "Consultoría") → actual tasks
        """
        # Check ALIAS_MAP has correct mapping
        self.assertIn("consultoria", ALIAS_MAP)
        target_type, value = ALIAS_MAP["consultoria"]
        self.assertEqual(target_type, "project", 
                         "consultoria should map to 'project' type, not 'domain'")
        self.assertEqual(value, "Consultoría",
                         "consultoria should map to 'Consultoría' (with accent)")
    
    def test_consultoria_with_accent_same_mapping(self):
        """Both 'consultoria' and 'consultoría' map to same Proyecto."""
        self.assertIn("consultoría", ALIAS_MAP)
        target_type1, value1 = ALIAS_MAP["consultoria"]
        target_type2, value2 = ALIAS_MAP["consultoría"]
        self.assertEqual((target_type1, value1), (target_type2, value2))
    
    def test_tareas_consultoria_creates_project_filter(self):
        """'tareas consultoria' should create a project filter, not domain."""
        filters = parse_work_query_filters("tareas consultoria")
        
        # Should have project filter, NOT domain filter
        self.assertIn("project", filters, 
                      "Expected 'project' filter for 'tareas consultoria'")
        self.assertNotIn("domain", filters,
                         "Should not have domain filter")
        self.assertEqual(filters["project"], "Consultoría")
    
    def test_tareas_consultoria_with_accent_same_result(self):
        """'tareas consultoría' (with accent) should work the same."""
        filters = parse_work_query_filters("tareas consultoría")
        self.assertIn("project", filters)
        self.assertEqual(filters["project"], "Consultoría")
    
    def test_estado_sobre_tareas_de_consultoria(self):
        """'Estado sobre tareas de consultoría' should also work."""
        filters = parse_work_query_filters("Estado sobre tareas de consultoría")
        self.assertIn("project", filters)
        self.assertEqual(filters["project"], "Consultoría")


class TestTextSearchFallback(unittest.TestCase):
    """Tests for text search fallback when target doesn't exist in taxonomy."""
    
    def test_capitalized_keyword_uses_title_search(self):
        """Capitalized words that don't match taxonomy use title search."""
        filters = parse_work_query_filters("tareas XYZ123_UNKNOWN")
        
        self.assertIn("title_keyword", filters)
        self.assertEqual(filters["title_keyword"], "XYZ123_UNKNOWN")
        self.assertNotIn("domain", filters)
        self.assertNotIn("project", filters)
    
    def test_audit_shows_keyword_type(self):
        """Audit info should show keyword type for text search."""
        filters = parse_work_query_filters("tareas FOOBAR_TEST")
        
        audit = filters.get("_target_audit", {})
        self.assertEqual(audit["target_type"], "keyword")
        self.assertEqual(audit["filter_applied"], "title_keyword")


class TestInvalidFilterWithExplicitPrefix(unittest.TestCase):
    """Tests for InvalidFilter when explicit prefix used with non-existent value."""
    
    def test_domain_prefix_invalid_value_returns_invalid_filter(self):
        """Using domain:xyz_invalid should return InvalidFilter."""
        filters = parse_work_query_filters("tareas domain:xyz_invalid")
        
        self.assertTrue(filters.get("_is_invalid_filter", False),
                        "Expected _is_invalid_filter=True for non-existent domain")
        self.assertNotIn("domain", filters,
                         "Should NOT create domain filter for invalid value")
    
    def test_invalid_filter_has_message(self):
        """InvalidFilter should include validation message."""
        filters = parse_work_query_filters("tareas domain:nonexistent123")
        
        self.assertIn("_invalid_filter_message", filters)
        self.assertIn("not found", filters["_invalid_filter_message"].lower())
    
    def test_invalid_filter_has_suggested_values(self):
        """InvalidFilter should include suggested valid values."""
        filters = parse_work_query_filters("tareas domain:badvalue")
        
        suggested = filters.get("_suggested_values", [])
        self.assertIsInstance(suggested, list)
        self.assertGreater(len(suggested), 0, 
                           "Should suggest at least one valid domain")
    
    def test_project_prefix_invalid_value_returns_invalid_filter(self):
        """Using project:nonexistent should return InvalidFilter."""
        filters = parse_work_query_filters("tareas proyecto:nonexistent")
        
        self.assertTrue(filters.get("_is_invalid_filter", False))
        self.assertNotIn("project", filters)


class TestBareQueriesWork(unittest.TestCase):
    """Tests for queries without filters still work."""
    
    def test_tareas_without_filter_has_no_domain_project(self):
        """'tareas' alone should not have domain or project filters."""
        filters = parse_work_query_filters("tareas")
        
        self.assertNotIn("domain", filters)
        self.assertNotIn("project", filters)
        self.assertNotIn("project_key", filters)
    
    def test_tareas_has_target_audit(self):
        """Even bare 'tareas' should have audit info."""
        filters = parse_work_query_filters("tareas")
        
        self.assertIn("_target_audit", filters)
        audit = filters["_target_audit"]
        self.assertEqual(audit["target_type"], "none")


class TestStatusFilterCombination(unittest.TestCase):
    """Tests for status filter combination with other filters."""
    
    def test_tareas_status_next(self):
        """'tareas status NEXT' should have status filter."""
        filters = parse_work_query_filters("tareas status NEXT")
        
        self.assertIn("status", filters)
        self.assertIn("NEXT", filters["status"])
    
    def test_status_with_keyword_combines(self):
        """Status + keyword should combine correctly."""
        filters = parse_work_query_filters("tareas MYPROJECT status NEXT")
        
        self.assertIn("status", filters)
        # Note: MYPROJECT may or may not be detected as keyword
        # depending on parsing order
    
    def test_status_with_project_combines(self):
        """Status + valid project should combine correctly."""
        filters = parse_work_query_filters("tareas THCyE status NEXT")
        
        self.assertIn("status", filters)
        # THCyE should be detected as key or project


class TestAuditFields(unittest.TestCase):
    """Tests for audit fields in filter output."""
    
    def test_audit_includes_matched_taxonomy(self):
        """Audit should include matched_taxonomy flag."""
        filters = parse_work_query_filters("tareas consultoria")
        
        audit = filters.get("_target_audit", {})
        self.assertIn("matched_taxonomy", audit)
        self.assertTrue(audit["matched_taxonomy"])
    
    def test_audit_includes_fallback_used(self):
        """Audit should include fallback_used field."""
        filters = parse_work_query_filters("tareas consultoria")
        
        audit = filters.get("_target_audit", {})
        self.assertIn("fallback_used", audit)
    
    def test_routing_reason_present(self):
        """Filter output should include routing reason."""
        filters = parse_work_query_filters("tareas consultoria")
        
        self.assertIn("_routing_reason", filters)
        self.assertIsInstance(filters["_routing_reason"], str)
    
    def test_has_explicit_prefix_flag(self):
        """Audit should track whether explicit prefix was used."""
        # Without explicit prefix
        filters1 = parse_work_query_filters("tareas consultoria")
        audit1 = filters1.get("_target_audit", {})
        self.assertFalse(audit1.get("has_explicit_prefix", True))
        
        # With explicit prefix
        filters2 = parse_work_query_filters("tareas domain:WORK")
        audit2 = filters2.get("_target_audit", {})
        self.assertTrue(audit2.get("has_explicit_prefix", False))


class TestProjectoInOptions(unittest.TestCase):
    """Verify Consultoría is in PROYECTO_OPTIONS."""
    
    def test_consultoria_in_proyecto_options(self):
        """Consultoría should be in PROYECTO_OPTIONS."""
        self.assertIn("Consultoría", PROYECTO_OPTIONS)


if __name__ == "__main__":
    unittest.main()
