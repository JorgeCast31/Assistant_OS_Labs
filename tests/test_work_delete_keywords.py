"""
Unit tests for WORK_DELETE keyword extraction.

Tests the _extract_keywords function to ensure robust parsing of:
- Quoted keywords: "confirmar" or 'confirmar'
- "que diga:" / "que digan:" / "que contenga:" / "que contengan:" patterns
- Noise phrase removal: "del muro", "que", etc.
"""
import unittest
from assistant_os.parsers.work_delete_parser import _extract_keywords, parse_work_delete_intent


class TestKeywordExtraction(unittest.TestCase):
    """Tests for _extract_keywords function."""
    
    def test_quoted_keyword_double_quotes(self):
        """Quoted keywords with double quotes should be extracted exactly."""
        text = 'elimina tareas que contengan "confirm"'
        keywords, op = _extract_keywords(text)
        self.assertEqual(keywords, ["confirm"])
        self.assertEqual(op, "OR")
    
    def test_que_diga_without_quotes(self):
        """'que diga:' pattern without quotes should extract keyword."""
        text = "elimina todas las tareas del muro que diga: confirmar"
        keywords, op = _extract_keywords(text)
        self.assertEqual(keywords, ["confirmar"])
        self.assertEqual(op, "OR")
    
    def test_que_digan_without_quotes(self):
        """'que digan' pattern without quotes should extract keyword."""
        text = "elimina tareas que digan confirmar"
        keywords, op = _extract_keywords(text)
        self.assertEqual(keywords, ["confirmar"])
        self.assertEqual(op, "OR")
    
    def test_que_contengan_without_quotes(self):
        """'que contengan' pattern without quotes should extract keyword."""
        text = "elimina tareas que contengan confirm"
        keywords, op = _extract_keywords(text)
        self.assertEqual(keywords, ["confirm"])
        self.assertEqual(op, "OR")
    
    def test_quoted_keyword_single_quotes(self):
        """Quoted keywords with single quotes should be extracted exactly."""
        text = "elimina tareas que diga: 'test UI'"
        keywords, op = _extract_keywords(text)
        self.assertEqual(keywords, ["test UI"])
        self.assertEqual(op, "OR")
    
    def test_multiple_keywords_or(self):
        """Multiple keywords with OR should be extracted."""
        text = "elimina tareas que contengan: UI OR test"
        keywords, op = _extract_keywords(text)
        self.assertEqual(set(keywords), {"UI", "test"})
        self.assertEqual(op, "OR")
    
    def test_noise_removal_del_muro(self):
        """Noise phrase 'del muro' should be removed."""
        text = "elimina tareas del muro que diga: confirmar"
        keywords, op = _extract_keywords(text)
        self.assertEqual(keywords, ["confirmar"])
        # Should NOT contain "del" or "muro"
        self.assertNotIn("del", keywords)
        self.assertNotIn("muro", keywords)


class TestParseWorkDeleteIntent(unittest.TestCase):
    """Integration tests for parse_work_delete_intent."""
    
    def test_delete_with_quoted_keyword(self):
        """Delete with quoted keyword should parse correctly."""
        result = parse_work_delete_intent('elimina tareas que contengan "confirm"')
        self.assertTrue(result["is_delete"])
        self.assertEqual(result["query"]["keywords"], ["confirm"])
        self.assertFalse(result["query"]["delete_all"])
        self.assertIsNone(result["validation_error"])
    
    def test_delete_que_diga_without_quotes(self):
        """Delete with 'que diga:' no quotes should parse correctly."""
        result = parse_work_delete_intent("elimina todas las tareas del muro que diga: confirmar")
        self.assertTrue(result["is_delete"])
        self.assertEqual(result["query"]["keywords"], ["confirmar"])
        self.assertFalse(result["query"]["delete_all"])
        self.assertIsNone(result["validation_error"])
    
    def test_delete_que_digan_without_quotes(self):
        """Delete with 'que digan' no quotes should parse correctly."""
        result = parse_work_delete_intent("elimina tareas que digan confirmar")
        self.assertTrue(result["is_delete"])
        self.assertEqual(result["query"]["keywords"], ["confirmar"])
        self.assertFalse(result["query"]["delete_all"])
    
    def test_delete_que_contengan_without_quotes(self):
        """Delete with 'que contengan' no quotes should parse correctly."""
        result = parse_work_delete_intent("elimina tareas que contengan confirm")
        self.assertTrue(result["is_delete"])
        self.assertEqual(result["query"]["keywords"], ["confirm"])
        self.assertFalse(result["query"]["delete_all"])
    
    def test_delete_all_risk_high(self):
        """Delete all should have delete_all=True and NO keywords."""
        result = parse_work_delete_intent("elimina todas las tareas")
        self.assertTrue(result["is_delete"])
        self.assertTrue(result["query"]["delete_all"])
        self.assertEqual(result["query"]["keywords"], [])
    
    def test_delete_with_keywords_not_delete_all(self):
        """Delete with keywords should NOT have delete_all=True."""
        result = parse_work_delete_intent("elimina todas las tareas que digan: test")
        self.assertTrue(result["is_delete"])
        self.assertEqual(result["query"]["keywords"], ["test"])
        self.assertFalse(result["query"]["delete_all"])  # Keywords present = NOT delete_all


if __name__ == "__main__":
    unittest.main()
