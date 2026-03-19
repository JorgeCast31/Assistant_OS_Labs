"""
Tests for Google Sheets integration (mocked - no real API calls).

Tests:
- Row generation with correct 13-column format
- Mes derivation from Fecha
- Header mismatch detection
- ITBMS string conversion
"""
import unittest
from unittest.mock import patch, MagicMock

from assistant_os.config import SHEETS_EXPECTED_HEADER
from assistant_os.integrations.sheets import (
    append_expense_row,
    _derive_mes,
    get_sheets_client,
    reset_sheets_client,
    SheetsClient,
    AppendResult,
)


class TestDeriveMes(unittest.TestCase):
    """Tests for Mes derivation from Fecha (ISO format YYYY-MM)."""
    
    def test_standard_date(self):
        """2026-02-24 => 2026-02 (ISO month)."""
        self.assertEqual(_derive_mes("2026-02-24"), "2026-02")
    
    def test_january(self):
        """2026-01-15 => 2026-01 (ISO month)."""
        self.assertEqual(_derive_mes("2026-01-15"), "2026-01")
    
    def test_december(self):
        """2025-12-31 => 2025-12 (ISO month)."""
        self.assertEqual(_derive_mes("2025-12-31"), "2025-12")
    
    def test_short_date(self):
        """Short date (2026-02) => 2026-02."""
        self.assertEqual(_derive_mes("2026-02"), "2026-02")
    
    def test_empty_date(self):
        """Empty date returns empty string."""
        self.assertEqual(_derive_mes(""), "")


class TestExpectedHeader(unittest.TestCase):
    """Tests for header configuration."""
    
    def test_header_has_13_columns(self):
        """Expected header must have exactly 13 columns."""
        self.assertEqual(len(SHEETS_EXPECTED_HEADER), 13)
    
    def test_header_order(self):
        """Header columns must be in exact order."""
        expected = [
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
        self.assertEqual(SHEETS_EXPECTED_HEADER, expected)


class TestRowGeneration(unittest.TestCase):
    """Tests for expense row generation with mocked API."""
    
    def setUp(self):
        """Reset sheets client before each test."""
        reset_sheets_client()
    
    @patch.object(SheetsClient, '_init_service')
    @patch.object(SheetsClient, 'ensure_header_matches')
    @patch.object(SheetsClient, 'append_row')
    def test_row_has_13_columns(self, mock_append, mock_header, mock_init):
        """append_expense_row generates exactly 13 columns."""
        # Setup mocks
        mock_init.return_value = (True, "")
        mock_header.return_value = (True, "")
        mock_append.return_value = AppendResult(ok=True, row_number=5, error="")
        
        result = append_expense_row(
            fecha="2026-02-24",
            descripcion="Cena en restaurante",
            factura="",
            responsable="Jorge",
            monto=50.0,
            moneda="USD",
            itbms=True,
            categoria="comida",
            metodo_pago="tarjeta",
            notas="",
            fuente="Texto",
            link_archivo="",
        )
        
        # Verify append_row was called with 13 values
        mock_append.assert_called_once()
        values = mock_append.call_args[0][0]  # First positional arg
        self.assertEqual(len(values), 13)
    
    @patch.object(SheetsClient, '_init_service')
    @patch.object(SheetsClient, 'ensure_header_matches')
    @patch.object(SheetsClient, 'append_row')
    def test_column_order_correct(self, mock_append, mock_header, mock_init):
        """Columns are in exact header order."""
        mock_init.return_value = (True, "")
        mock_header.return_value = (True, "")
        mock_append.return_value = AppendResult(ok=True, row_number=5, error="")
        
        append_expense_row(
            fecha="2026-02-24",
            descripcion="Uber al trabajo",
            factura="REC-001",
            responsable="Ana",
            monto=15.50,
            moneda="PAB",
            itbms=False,
            categoria="transporte",
            metodo_pago="efectivo",
            notas="Viaje matutino",
            fuente="Receipt",
            link_archivo="https://drive.google.com/file/abc",
        )
        
        values = mock_append.call_args[0][0]
        
        # Verify exact column order (Fecha and Mes in ISO format)
        self.assertEqual(values[0], "2026-02-24")      # Fecha (YYYY-MM-DD ISO)
        self.assertEqual(values[1], "Uber al trabajo") # Descripción
        self.assertEqual(values[2], "REC-001")         # Factura
        self.assertEqual(values[3], "Ana")             # Responsable
        self.assertEqual(values[4], 15.50)             # Monto
        self.assertEqual(values[5], "PAB")             # Moneda
        self.assertEqual(values[6], "No")              # ITBMS
        self.assertEqual(values[7], "transporte")      # Categoría
        self.assertEqual(values[8], "efectivo")        # Método de Pago
        self.assertEqual(values[9], "Viaje matutino")  # Notas
        self.assertEqual(values[10], "Receipt")        # Fuente
        self.assertEqual(values[11], "https://drive.google.com/file/abc")  # Link
        self.assertEqual(values[12], "2026-02")        # Mes (YYYY-MM ISO)
    
    @patch.object(SheetsClient, '_init_service')
    @patch.object(SheetsClient, 'ensure_header_matches')
    @patch.object(SheetsClient, 'append_row')
    def test_mes_derived_correctly(self, mock_append, mock_header, mock_init):
        """Mes column is derived from Fecha."""
        mock_init.return_value = (True, "")
        mock_header.return_value = (True, "")
        mock_append.return_value = AppendResult(ok=True, row_number=5, error="")
        
        append_expense_row(
            fecha="2025-12-31",
            descripcion="Test",
            factura="",
            responsable="Hogar",
            monto=10.0,
            moneda="USD",
            itbms=False,
            categoria="otros",
        )
        
        values = mock_append.call_args[0][0]
        self.assertEqual(values[12], "2025-12")  # Mes derived from fecha (YYYY-MM ISO)
    
    @patch.object(SheetsClient, '_init_service')
    @patch.object(SheetsClient, 'ensure_header_matches')
    @patch.object(SheetsClient, 'append_row')
    def test_itbms_si(self, mock_append, mock_header, mock_init):
        """ITBMS True => 'Sí'."""
        mock_init.return_value = (True, "")
        mock_header.return_value = (True, "")
        mock_append.return_value = AppendResult(ok=True, row_number=5, error="")
        
        append_expense_row(
            fecha="2026-02-24",
            descripcion="Test",
            factura="",
            responsable="Jorge",
            monto=10.0,
            moneda="USD",
            itbms=True,
            categoria="otros",
        )
        
        values = mock_append.call_args[0][0]
        self.assertEqual(values[6], "Sí")
    
    @patch.object(SheetsClient, '_init_service')
    @patch.object(SheetsClient, 'ensure_header_matches')
    @patch.object(SheetsClient, 'append_row')
    def test_itbms_no(self, mock_append, mock_header, mock_init):
        """ITBMS False => 'No'."""
        mock_init.return_value = (True, "")
        mock_header.return_value = (True, "")
        mock_append.return_value = AppendResult(ok=True, row_number=5, error="")
        
        append_expense_row(
            fecha="2026-02-24",
            descripcion="Test",
            factura="",
            responsable="Jorge",
            monto=10.0,
            moneda="USD",
            itbms=False,
            categoria="otros",
        )
        
        values = mock_append.call_args[0][0]
        self.assertEqual(values[6], "No")


class TestHeaderValidation(unittest.TestCase):
    """Tests for header mismatch detection."""
    
    def setUp(self):
        reset_sheets_client()
    
    @patch.object(SheetsClient, '_init_service')
    @patch.object(SheetsClient, 'get_header_row')
    def test_header_match_success(self, mock_get_header, mock_init):
        """Matching header returns success."""
        mock_init.return_value = (True, "")
        mock_get_header.return_value = (True, SHEETS_EXPECTED_HEADER, "")
        
        client = get_sheets_client()
        ok, error = client.ensure_header_matches(SHEETS_EXPECTED_HEADER)
        
        self.assertTrue(ok)
        self.assertEqual(error, "")
    
    @patch.object(SheetsClient, '_init_service')
    @patch.object(SheetsClient, 'get_header_row')
    def test_header_mismatch_wrong_name(self, mock_get_header, mock_init):
        """Wrong column name triggers clear error."""
        mock_init.return_value = (True, "")
        wrong_header = SHEETS_EXPECTED_HEADER.copy()
        wrong_header[1] = "Description"  # Wrong: should be "Descripción"
        mock_get_header.return_value = (True, wrong_header, "")
        
        client = get_sheets_client()
        ok, error = client.ensure_header_matches(SHEETS_EXPECTED_HEADER)
        
        self.assertFalse(ok)
        self.assertIn("Header mismatch", error)
        self.assertIn("Column 2", error)
        self.assertIn("Descripción", error)
        self.assertIn("Description", error)
    
    @patch.object(SheetsClient, '_init_service')
    @patch.object(SheetsClient, 'get_header_row')
    def test_header_mismatch_missing_columns(self, mock_get_header, mock_init):
        """Missing columns triggers clear error."""
        mock_init.return_value = (True, "")
        short_header = SHEETS_EXPECTED_HEADER[:10]  # Only 10 columns
        mock_get_header.return_value = (True, short_header, "")
        
        client = get_sheets_client()
        ok, error = client.ensure_header_matches(SHEETS_EXPECTED_HEADER)
        
        self.assertFalse(ok)
        self.assertIn("missing columns", error)
    
    @patch.object(SheetsClient, '_init_service')
    @patch.object(SheetsClient, 'get_header_row')
    def test_header_whitespace_trimmed(self, mock_get_header, mock_init):
        """Whitespace in header is trimmed before comparison."""
        mock_init.return_value = (True, "")
        # Header with extra whitespace
        padded_header = [" " + h + " " for h in SHEETS_EXPECTED_HEADER]
        mock_get_header.return_value = (True, padded_header, "")
        
        client = get_sheets_client()
        ok, error = client.ensure_header_matches(SHEETS_EXPECTED_HEADER)
        
        self.assertTrue(ok)


class TestServiceAccountValidation(unittest.TestCase):
    """Tests for service account JSON validation."""
    
    def setUp(self):
        reset_sheets_client()
    
    @patch('assistant_os.integrations.sheets.GSPREAD_AVAILABLE', True)
    @patch('assistant_os.integrations.sheets.GOOGLE_SERVICE_ACCOUNT_JSON_PATH', '')
    def test_missing_json_path_error(self):
        """Missing JSON path returns clear error."""
        client = SheetsClient()
        client._initialized = False  # Reset state
        success, error = client._init_service()
        
        self.assertFalse(success)
        self.assertIn("GOOGLE_SERVICE_ACCOUNT_JSON_PATH", error)
    
    @patch('assistant_os.integrations.sheets.GSPREAD_AVAILABLE', True)
    @patch('assistant_os.integrations.sheets.GOOGLE_SERVICE_ACCOUNT_JSON_PATH', '/nonexistent/path.json')
    def test_missing_json_file_error(self):
        """Missing JSON file returns clear error."""
        client = SheetsClient()
        client._initialized = False  # Reset state
        success, error = client._init_service()
        
        self.assertFalse(success)
        self.assertIn("not found", error)


if __name__ == "__main__":
    unittest.main()
