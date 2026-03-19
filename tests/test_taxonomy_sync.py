"""
Tests for taxonomy_sync module.

Tests:
- Cache loading/saving
- Schema extraction
- refresh_taxonomy() with mock
- get_valid_options() 
- validate_status/domain/proyecto
- Integration with chat_core
"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

from assistant_os import taxonomy_sync
from assistant_os.taxonomy_sync import (
    TaxonomyCache,
    refresh_taxonomy,
    get_valid_options,
    get_valid_statuses,
    get_valid_domains,
    get_valid_proyectos,
    validate_status,
    validate_domain,
    validate_proyecto,
    get_cache_status,
    _extract_options_from_schema,
    _is_cache_stale,
    _load_cache,
    _save_cache,
)


# ---------------------------------------------------------------------------
# Mock Schema Data (matches Notion API response format)
# ---------------------------------------------------------------------------

MOCK_NOTION_SCHEMA = {
    "Status": {
        "type": "select",
        "id": "status_id",
        "options": ["NEXT", "INBOX", "WAITING", "SCHEDULED", "DONE", "ARCHIVED"]
    },
    "Domain": {
        "type": "select",
        "id": "domain_id",
        "options": ["Consultoría", "CELLAB", "Tesis", "eiProta", "WORK", "Personal"]
    },
    "Proyecto": {
        "type": "multi_select",
        "id": "proyecto_id",
        "options": ["THCyE", "TTI - ECO", "Búsqueda laboral", "Tesis", "eiProta"]
    },
    "Name": {
        "type": "title",
        "id": "title_id"
    }
}


class TestSchemaExtraction(unittest.TestCase):
    """Test extraction of options from Notion schema."""
    
    def test_extract_status_options(self):
        """Should extract status options from schema."""
        cache = _extract_options_from_schema(MOCK_NOTION_SCHEMA)
        
        self.assertIn("NEXT", cache["status_options"])
        self.assertIn("INBOX", cache["status_options"])
        self.assertIn("WAITING", cache["status_options"])
        self.assertEqual(len(cache["status_options"]), 6)
    
    def test_extract_domain_options(self):
        """Should extract domain options from schema."""
        cache = _extract_options_from_schema(MOCK_NOTION_SCHEMA)
        
        self.assertIn("Consultoría", cache["domain_options"])
        self.assertIn("CELLAB", cache["domain_options"])
        self.assertIn("eiProta", cache["domain_options"])
    
    def test_extract_proyecto_options(self):
        """Should extract proyecto options from schema."""
        cache = _extract_options_from_schema(MOCK_NOTION_SCHEMA)
        
        self.assertIn("THCyE", cache["proyecto_options"])
        self.assertIn("TTI - ECO", cache["proyecto_options"])
        self.assertIn("Búsqueda laboral", cache["proyecto_options"])
    
    def test_extracts_timestamp(self):
        """Should add timestamp to cache."""
        cache = _extract_options_from_schema(MOCK_NOTION_SCHEMA)
        
        self.assertIn("timestamp", cache)
        # Should be valid ISO format
        datetime.fromisoformat(cache["timestamp"])
    
    def test_stores_raw_schema(self):
        """Should store raw schema for debugging."""
        cache = _extract_options_from_schema(MOCK_NOTION_SCHEMA)
        
        self.assertEqual(cache["schema_raw"], MOCK_NOTION_SCHEMA)


class TestCacheStaleness(unittest.TestCase):
    """Test cache staleness detection."""
    
    def test_fresh_cache_not_stale(self):
        """Fresh cache should not be stale."""
        cache = TaxonomyCache(
            timestamp=datetime.now().isoformat(),
            ttl_hours=24,
            status_options=["NEXT"],
            domain_options=["WORK"],
            proyecto_options=["Test"],
            schema_raw={},
        )
        
        self.assertFalse(_is_cache_stale(cache))
    
    def test_old_cache_is_stale(self):
        """Cache older than TTL should be stale."""
        old_time = datetime.now() - timedelta(hours=25)
        cache = TaxonomyCache(
            timestamp=old_time.isoformat(),
            ttl_hours=24,
            status_options=["NEXT"],
            domain_options=["WORK"],
            proyecto_options=["Test"],
            schema_raw={},
        )
        
        self.assertTrue(_is_cache_stale(cache))
    
    def test_respects_custom_ttl(self):
        """Should respect custom TTL setting."""
        # 2 hours ago with 1 hour TTL = stale
        old_time = datetime.now() - timedelta(hours=2)
        cache = TaxonomyCache(
            timestamp=old_time.isoformat(),
            ttl_hours=1,
            status_options=["NEXT"],
            domain_options=["WORK"],
            proyecto_options=["Test"],
            schema_raw={},
        )
        
        self.assertTrue(_is_cache_stale(cache))
        
        # Same with 24 hour TTL = not stale
        cache["ttl_hours"] = 24
        self.assertFalse(_is_cache_stale(cache))


class TestCacheIO(unittest.TestCase):
    """Test cache loading and saving."""
    
    def setUp(self):
        """Create temp directory for cache."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.original_cache_file = taxonomy_sync.TAXONOMY_CACHE_FILE
        taxonomy_sync.TAXONOMY_CACHE_FILE = self.temp_dir / "taxonomy_cache.json"
    
    def tearDown(self):
        """Restore original cache file path."""
        taxonomy_sync.TAXONOMY_CACHE_FILE = self.original_cache_file
        # Clean up temp files
        for f in self.temp_dir.glob("*"):
            f.unlink()
        self.temp_dir.rmdir()
    
    def test_save_and_load_cache(self):
        """Should save and load cache correctly."""
        cache = TaxonomyCache(
            timestamp=datetime.now().isoformat(),
            ttl_hours=24,
            status_options=["NEXT", "INBOX"],
            domain_options=["WORK", "CELLAB"],
            proyecto_options=["THCyE"],
            schema_raw={"test": "data"},
        )
        
        _save_cache(cache)
        loaded = _load_cache()
        
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["status_options"], ["NEXT", "INBOX"])
        self.assertEqual(loaded["domain_options"], ["WORK", "CELLAB"])
        self.assertEqual(loaded["proyecto_options"], ["THCyE"])
    
    def test_load_missing_cache_returns_none(self):
        """Should return None when cache file doesn't exist."""
        taxonomy_sync.TAXONOMY_CACHE_FILE = self.temp_dir / "nonexistent.json"
        
        result = _load_cache()
        
        self.assertIsNone(result)


class TestGetValidOptions(unittest.TestCase):
    """Test get_valid_options function."""
    
    def setUp(self):
        """Create temp cache."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.original_cache_file = taxonomy_sync.TAXONOMY_CACHE_FILE
        taxonomy_sync.TAXONOMY_CACHE_FILE = self.temp_dir / "taxonomy_cache.json"
        
        # Save mock cache
        cache = TaxonomyCache(
            timestamp=datetime.now().isoformat(),
            ttl_hours=24,
            status_options=["NEXT", "INBOX", "WAITING"],
            domain_options=["WORK", "CELLAB"],
            proyecto_options=["THCyE", "TTI - ECO"],
            schema_raw={},
        )
        _save_cache(cache)
    
    def tearDown(self):
        """Restore and cleanup."""
        taxonomy_sync.TAXONOMY_CACHE_FILE = self.original_cache_file
        for f in self.temp_dir.glob("*"):
            f.unlink()
        self.temp_dir.rmdir()
    
    def test_get_status_options(self):
        """Should return status options from cache."""
        result = get_valid_options("status")
        
        self.assertEqual(result["source"], "cache")
        self.assertIn("NEXT", result["options"])
        self.assertIn("INBOX", result["options"])
    
    def test_get_domain_options(self):
        """Should return domain options from cache."""
        result = get_valid_options("domain")
        
        self.assertEqual(result["source"], "cache")
        self.assertIn("WORK", result["options"])
        self.assertIn("CELLAB", result["options"])
    
    def test_get_proyecto_options(self):
        """Should return proyecto options from cache."""
        result = get_valid_options("proyecto")
        
        self.assertEqual(result["source"], "cache")
        self.assertIn("THCyE", result["options"])
        self.assertIn("TTI - ECO", result["options"])
    
    def test_convenience_functions(self):
        """Should have convenience functions."""
        self.assertIn("NEXT", get_valid_statuses())
        self.assertIn("WORK", get_valid_domains())
        self.assertIn("THCyE", get_valid_proyectos())


class TestValidateStatus(unittest.TestCase):
    """Test status validation."""
    
    def setUp(self):
        """Create temp cache."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.original_cache_file = taxonomy_sync.TAXONOMY_CACHE_FILE
        taxonomy_sync.TAXONOMY_CACHE_FILE = self.temp_dir / "taxonomy_cache.json"
        
        cache = TaxonomyCache(
            timestamp=datetime.now().isoformat(),
            ttl_hours=24,
            status_options=["NEXT", "INBOX", "WAITING", "SCHEDULED", "DONE"],
            domain_options=["WORK", "CELLAB", "eiProta"],
            proyecto_options=["THCyE", "TTI - ECO"],
            schema_raw={},
        )
        _save_cache(cache)
    
    def tearDown(self):
        """Restore and cleanup."""
        taxonomy_sync.TAXONOMY_CACHE_FILE = self.original_cache_file
        for f in self.temp_dir.glob("*"):
            f.unlink()
        self.temp_dir.rmdir()
    
    def test_valid_status_exact(self):
        """Exact match should be valid."""
        is_valid, suggestion = validate_status("NEXT")
        
        self.assertTrue(is_valid)
        self.assertEqual(suggestion, "NEXT")
    
    def test_valid_status_case_insensitive(self):
        """Case insensitive match should be valid."""
        is_valid, suggestion = validate_status("next")
        
        self.assertTrue(is_valid)
        self.assertEqual(suggestion, "NEXT")  # Returns canonical
    
    def test_invalid_status_with_suggestion(self):
        """Invalid status with partial match should suggest."""
        is_valid, suggestion = validate_status("INBO")  # Partial of INBOX
        
        self.assertFalse(is_valid)
        self.assertEqual(suggestion, "INBOX")
    
    def test_completely_invalid_status(self):
        """Completely invalid status returns no suggestion."""
        is_valid, suggestion = validate_status("XYZZZ")
        
        self.assertFalse(is_valid)
        self.assertIsNone(suggestion)


class TestValidateDomainProyecto(unittest.TestCase):
    """Test domain and proyecto validation."""
    
    def setUp(self):
        """Create temp cache."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.original_cache_file = taxonomy_sync.TAXONOMY_CACHE_FILE
        taxonomy_sync.TAXONOMY_CACHE_FILE = self.temp_dir / "taxonomy_cache.json"
        
        cache = TaxonomyCache(
            timestamp=datetime.now().isoformat(),
            ttl_hours=24,
            status_options=["NEXT"],
            domain_options=["Consultoría", "CELLAB", "eiProta"],
            proyecto_options=["THCyE", "TTI - ECO", "Búsqueda laboral"],
            schema_raw={},
        )
        _save_cache(cache)
    
    def tearDown(self):
        """Restore and cleanup."""
        taxonomy_sync.TAXONOMY_CACHE_FILE = self.original_cache_file
        for f in self.temp_dir.glob("*"):
            f.unlink()
        self.temp_dir.rmdir()
    
    def test_valid_domain(self):
        """Valid domain should pass."""
        is_valid, suggestion = validate_domain("eiProta")
        
        self.assertTrue(is_valid)
        self.assertEqual(suggestion, "eiProta")
    
    def test_domain_case_insensitive(self):
        """Domain validation should be case insensitive."""
        is_valid, suggestion = validate_domain("cellab")
        
        self.assertTrue(is_valid)
        self.assertEqual(suggestion, "CELLAB")
    
    def test_invalid_domain_with_suggestion(self):
        """Invalid domain should suggest similar."""
        is_valid, suggestion = validate_domain("Consul")  # Partial
        
        self.assertFalse(is_valid)
        self.assertEqual(suggestion, "Consultoría")
    
    def test_valid_proyecto(self):
        """Valid proyecto should pass."""
        is_valid, suggestion = validate_proyecto("THCyE")
        
        self.assertTrue(is_valid)
        self.assertEqual(suggestion, "THCyE")
    
    def test_proyecto_case_insensitive(self):
        """Proyecto validation should be case insensitive."""
        is_valid, suggestion = validate_proyecto("thcye")
        
        self.assertTrue(is_valid)
        self.assertEqual(suggestion, "THCyE")


class TestRefreshTaxonomy(unittest.TestCase):
    """Test refresh_taxonomy function."""
    
    def setUp(self):
        """Create temp cache dir."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.original_cache_file = taxonomy_sync.TAXONOMY_CACHE_FILE
        self.original_memory_dir = taxonomy_sync.MEMORY_DIR
        taxonomy_sync.TAXONOMY_CACHE_FILE = self.temp_dir / "taxonomy_cache.json"
        taxonomy_sync.MEMORY_DIR = self.temp_dir
    
    def tearDown(self):
        """Restore and cleanup."""
        taxonomy_sync.TAXONOMY_CACHE_FILE = self.original_cache_file
        taxonomy_sync.MEMORY_DIR = self.original_memory_dir
        for f in self.temp_dir.glob("*"):
            f.unlink()
        self.temp_dir.rmdir()
    
    @patch('assistant_os.integrations.notion.get_database_schema')
    @patch('assistant_os.integrations.notion.check_notion_available')
    def test_refresh_from_notion(self, mock_check, mock_schema):
        """Should refresh from Notion when available."""
        mock_check.return_value = True
        mock_schema.return_value = {
            "ok": True,
            "schema": MOCK_NOTION_SCHEMA,
        }
        
        result = refresh_taxonomy(force=True)
        
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "notion")
        self.assertEqual(result["stats"]["statuses"], 6)
    
    @patch('assistant_os.integrations.notion.check_notion_available')
    def test_refresh_returns_cache_when_fresh(self, mock_check):
        """Should not call Notion if cache is fresh."""
        # Create fresh cache
        cache = TaxonomyCache(
            timestamp=datetime.now().isoformat(),
            ttl_hours=24,
            status_options=["NEXT"],
            domain_options=["WORK"],
            proyecto_options=["Test"],
            schema_raw={},
        )
        _save_cache(cache)
        
        result = refresh_taxonomy(force=False)
        
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "cache")
        mock_check.assert_not_called()
    
    @patch('assistant_os.integrations.notion.check_notion_available')
    def test_handles_notion_unavailable(self, mock_check):
        """Should handle Notion being unavailable."""
        mock_check.return_value = False
        
        result = refresh_taxonomy(force=True)
        
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "Notion unavailable")


class TestChatCoreIntegration(unittest.TestCase):
    """Test integration with chat_core for dynamic validation."""
    
    def setUp(self):
        """Create temp cache."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.original_cache_file = taxonomy_sync.TAXONOMY_CACHE_FILE
        taxonomy_sync.TAXONOMY_CACHE_FILE = self.temp_dir / "taxonomy_cache.json"
        
        cache = TaxonomyCache(
            timestamp=datetime.now().isoformat(),
            ttl_hours=24,
            status_options=["NEXT", "INBOX", "WAITING", "SCHEDULED"],
            domain_options=["WORK"],
            proyecto_options=["Test"],
            schema_raw={},
        )
        _save_cache(cache)
    
    def tearDown(self):
        """Restore and cleanup."""
        taxonomy_sync.TAXONOMY_CACHE_FILE = self.original_cache_file
        for f in self.temp_dir.glob("*"):
            f.unlink()
        self.temp_dir.rmdir()
    
    @patch('assistant_os.integrations.notion.query_work_db')
    @patch('assistant_os.integrations.notion.check_notion_available')
    def test_invalid_status_returns_suggestions(self, mock_check, mock_query):
        """Invalid status should still process query (validation is informational)."""
        from assistant_os.chat_core import _process_work_query
        from assistant_os.contracts import ChatSession
        
        mock_check.return_value = True
        mock_query.return_value = {"ok": True, "items": []}
        
        session: ChatSession = {"context_id": "test", "last_domain": None}
        
        # Invalid status values are passed through; validation is informational only
        result = _process_work_query(
            text="tareas status BLOQUEAD",  # Invalid but similar to NEXT
            session=session,
            classify_result={},
            trace_id="test"
        )
        
        # Query proceeds (status validation doesn't block)
        self.assertEqual(result["intent"], "query")
        self.assertIn("filters", result["audit"])


if __name__ == "__main__":
    unittest.main()
