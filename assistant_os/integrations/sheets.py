"""
Google Sheets integration for expense tracking.

Uses gspread with service account authentication (preferred for server-to-server).
Requires:
- gspread
- google-auth

Setup:
1. Create a Google Cloud project
2. Enable Google Sheets API
3. Create a service account and download JSON key
4. Set GOOGLE_SERVICE_ACCOUNT_JSON_PATH in config.py
5. Share the spreadsheet with the service account email

Header EXACTO (13 columnas):
Fecha, Descripción, Factura, Responsable, Monto, Moneda, ITBMS, Categoría, 
Método de Pago, Notas, Fuente, Link/Archivo, Mes
"""
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional, Any, TypedDict

# Conditional imports - gracefully degrade if not installed
GSPREAD_AVAILABLE = False
GSPREAD_VERSION = "not installed"
try:
    import gspread
    from gspread.exceptions import APIError, SpreadsheetNotFound, WorksheetNotFound
    GSPREAD_AVAILABLE = True
    GSPREAD_VERSION = gspread.__version__
except ImportError:
    gspread = None  # type: ignore
    APIError = Exception  # type: ignore
    SpreadsheetNotFound = Exception  # type: ignore
    WorksheetNotFound = Exception  # type: ignore

from ..config import (
    MEMORY_DIR,
    LOG_FILE,
    SHEETS_SPREADSHEET_ID,
    SHEETS_TAB_NAME,
    GOOGLE_SERVICE_ACCOUNT_JSON_PATH,
    SHEETS_EXPECTED_HEADER,
)
from ..contracts import now_iso


# ---------------------------------------------------------------------------
# Global Error Tracking
# ---------------------------------------------------------------------------

class SheetsError(TypedDict, total=False):
    """Error information for sheets status."""
    type: str           # missing_gspread | missing_json | permission_denied | tab_not_found | api_disabled | unknown_error
    message: str        # Human-readable error message
    traceback: str      # Full traceback if available


_SHEETS_LAST_ERROR: Optional[SheetsError] = None


def _set_sheets_error(error_type: str, message: str, tb: Optional[str] = None) -> None:
    """Set the global sheets error."""
    global _SHEETS_LAST_ERROR
    _SHEETS_LAST_ERROR = SheetsError(type=error_type, message=message)
    if tb:
        _SHEETS_LAST_ERROR["traceback"] = tb


def _clear_sheets_error() -> None:
    """Clear the global sheets error."""
    global _SHEETS_LAST_ERROR
    _SHEETS_LAST_ERROR = None


def get_sheets_last_error() -> Optional[SheetsError]:
    """Get the last sheets error."""
    return _SHEETS_LAST_ERROR


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log_sheets_event(
    action: str,
    ok: bool,
    expense_id: str = "",
    row_num: int = 0,
    error_message: str = "",
) -> None:
    """Log a sheets operation to log.ndjson."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    
    event: dict = {
        "ts": now_iso(),
        "type": "sheets",
        "action": action,
        "ok": ok,
    }
    
    if expense_id:
        event["expense_id"] = expense_id
    if row_num > 0:
        event["row_num"] = row_num
    if error_message:
        event["error"] = error_message
    
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Google Sheets Client
# ---------------------------------------------------------------------------

class AppendResult(TypedDict):
    """Result from append_expense_row."""
    ok: bool
    row_number: int
    error: str


class SheetsClient:
    """Google Sheets client using gspread with header validation and expense mapping."""
    
    SCOPES = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    
    def __init__(self):
        self._gclient: Any = None          # gspread.Client
        self._spreadsheet: Any = None      # gspread.Spreadsheet
        self._worksheet: Any = None        # gspread.Worksheet
        self._initialized = False
        self._header_validated = False
        self._init_error: Optional[str] = None
    
    def _init_service(self) -> tuple[bool, str]:
        """
        Initialize the gspread client and verify access to the spreadsheet and worksheet.
        
        Returns:
            (success, error_message)
        """
        # If already initialized successfully, return cached result
        if self._initialized:
            if self._gclient is not None and self._worksheet is not None:
                _clear_sheets_error()
                return True, ""
            else:
                # Return the cached error
                return False, self._init_error or "Initialization failed"
        
        # Mark as initialized (even if it fails, to cache the error)
        self._initialized = True
        
        # Step 1: Check gspread is available
        if not GSPREAD_AVAILABLE:
            error = "gspread library not installed. Run: pip install gspread"
            self._init_error = error
            _set_sheets_error("missing_gspread", error)
            _log_sheets_event("init", ok=False, error_message=error)
            print(f"[SHEETS] INIT FAIL — gspread not installed (pip install gspread)", flush=True)
            return False, error

        # Step 2: Check config path is set
        if not GOOGLE_SERVICE_ACCOUNT_JSON_PATH:
            error = "GOOGLE_SERVICE_ACCOUNT_JSON_PATH not configured in config.py"
            self._init_error = error
            _set_sheets_error("missing_json", error)
            _log_sheets_event("init", ok=False, error_message=error)
            print(f"[SHEETS] INIT FAIL — GOOGLE_SERVICE_ACCOUNT_JSON_PATH not set", flush=True)
            return False, error

        # Step 3: Check JSON file exists
        json_path = Path(GOOGLE_SERVICE_ACCOUNT_JSON_PATH)
        print(f"[SHEETS] credentials path: {json_path} — exists: {json_path.exists()}", flush=True)
        if not json_path.exists():
            error = f"Service account JSON file not found: {GOOGLE_SERVICE_ACCOUNT_JSON_PATH}"
            self._init_error = error
            _set_sheets_error("missing_json", error)
            _log_sheets_event("init", ok=False, error_message=error)
            print(f"[SHEETS] INIT FAIL — credentials file missing: {json_path}", flush=True)
            return False, error

        # Step 4: Initialize gspread client
        try:
            self._gclient = gspread.service_account(filename=str(json_path))
            print(f"[SHEETS] gspread client initialized OK (gspread {GSPREAD_VERSION})", flush=True)
        except Exception as e:
            tb = traceback.format_exc()
            error = f"Failed to authenticate with service account: {e}"
            self._init_error = error
            _set_sheets_error("permission_denied", error, tb)
            _log_sheets_event("init", ok=False, error_message=error)
            print(f"[SHEETS] INIT FAIL — gspread auth error: {e}", flush=True)
            return False, error
        
        # Step 5: Open spreadsheet by key
        if not SHEETS_SPREADSHEET_ID:
            error = "SHEETS_SPREADSHEET_ID not configured in config.py"
            self._init_error = error
            _set_sheets_error("unknown_error", error)
            _log_sheets_event("init", ok=False, error_message=error)
            return False, error
        
        try:
            self._spreadsheet = self._gclient.open_by_key(SHEETS_SPREADSHEET_ID)
        except SpreadsheetNotFound:
            error = f"Spreadsheet not found or not shared with service account. ID: {SHEETS_SPREADSHEET_ID}"
            self._init_error = error
            _set_sheets_error("permission_denied", error)
            _log_sheets_event("init", ok=False, error_message=error)
            return False, error
        except APIError as e:
            tb = traceback.format_exc()
            error_msg = str(e)
            if "PERMISSION_DENIED" in error_msg or "403" in error_msg:
                if "has not been used" in error_msg or "it is disabled" in error_msg:
                    error = f"Google Sheets API is not enabled for this project. Enable it at: https://console.developers.google.com/apis/api/sheets.googleapis.com"
                    self._init_error = error
                    _set_sheets_error("api_disabled", error, tb)
                else:
                    error = f"Permission denied accessing spreadsheet. Ensure the sheet is shared with the service account email. Error: {e}"
                    self._init_error = error
                    _set_sheets_error("permission_denied", error, tb)
            else:
                error = f"API error opening spreadsheet: {e}"
                self._init_error = error
                _set_sheets_error("unknown_error", error, tb)
            _log_sheets_event("init", ok=False, error_message=error)
            return False, error
        except Exception as e:
            tb = traceback.format_exc()
            error = f"Failed to open spreadsheet: {e}"
            self._init_error = error
            _set_sheets_error("unknown_error", error, tb)
            _log_sheets_event("init", ok=False, error_message=error)
            return False, error
        
        # Step 6: Get the worksheet/tab
        try:
            self._worksheet = self._spreadsheet.worksheet(SHEETS_TAB_NAME)
        except WorksheetNotFound:
            error = f"Worksheet/tab '{SHEETS_TAB_NAME}' not found in spreadsheet"
            self._init_error = error
            _set_sheets_error("tab_not_found", error)
            _log_sheets_event("init", ok=False, error_message=error)
            return False, error
        except Exception as e:
            tb = traceback.format_exc()
            error = f"Failed to access worksheet: {e}"
            self._init_error = error
            _set_sheets_error("unknown_error", error, tb)
            _log_sheets_event("init", ok=False, error_message=error)
            return False, error
        
        # Success!
        _clear_sheets_error()
        _log_sheets_event("init", ok=True)
        return True, ""
    
    def is_available(self) -> bool:
        """Check if Sheets API is available and configured."""
        success, _ = self._init_service()
        return success
    
    def get_header_row(self) -> tuple[bool, list[str], str]:
        """
        Get the header row (row 1) from the spreadsheet.
        
        Returns:
            (success, header_values, error_message)
        """
        success, error = self._init_service()
        if not success:
            return False, [], error
        
        try:
            row = self._worksheet.row_values(1)
            if row and len(row) > 0:
                return True, row, ""
            else:
                return False, [], "No header row found (row 1 is empty)"
                
        except APIError as e:
            tb = traceback.format_exc()
            _set_sheets_error("unknown_error", f"API error reading header: {e}", tb)
            return False, [], f"Sheets API error: {e}"
        except Exception as e:
            tb = traceback.format_exc()
            _set_sheets_error("unknown_error", f"Error reading header: {e}", tb)
            return False, [], f"Error reading header: {e}"
    
    def ensure_header_matches(self, expected_headers: list[str]) -> tuple[bool, str]:
        """
        Validate that row 1 matches the expected headers exactly.
        
        Args:
            expected_headers: List of expected column names in exact order
        
        Returns:
            (matches, error_message) - matches=True if header is correct
        """
        success, actual_header, error = self.get_header_row()
        if not success:
            return False, error
        
        # Trim whitespace from actual header
        actual_trimmed = [str(h).strip() for h in actual_header]
        
        # Compare
        if len(actual_trimmed) < len(expected_headers):
            missing = expected_headers[len(actual_trimmed):]
            return False, f"Header mismatch: missing columns {missing}. Expected {len(expected_headers)} columns, found {len(actual_trimmed)}."
        
        mismatches = []
        for i, (expected, actual) in enumerate(zip(expected_headers, actual_trimmed)):
            if expected != actual:
                mismatches.append(f"Column {i+1}: expected '{expected}', found '{actual}'")
        
        if mismatches:
            return False, f"Header mismatch: {'; '.join(mismatches)}"
        
        self._header_validated = True
        return True, ""
    
    def append_row(
        self,
        values: list[Any],
        expense_id: str = "",
    ) -> AppendResult:
        """
        Append a row to the configured spreadsheet.
        
        Args:
            values: List of values for the row (must be exactly 13 columns)
            expense_id: Optional ID for logging
        
        Returns:
            AppendResult with ok, row_number, error
        """
        success, error = self._init_service()
        if not success:
            return AppendResult(ok=False, row_number=0, error=error)
        
        # Validate header on first append
        if not self._header_validated:
            header_ok, header_error = self.ensure_header_matches(SHEETS_EXPECTED_HEADER)
            if not header_ok:
                return AppendResult(ok=False, row_number=0, error=header_error)
        
        # Ensure exactly 13 columns
        if len(values) != 13:
            return AppendResult(
                ok=False, 
                row_number=0, 
                error=f"Expected 13 columns, got {len(values)}"
            )
        
        try:
            # gspread append_row returns the result with the added row info
            result = self._worksheet.append_row(
                values,
                value_input_option='USER_ENTERED',
                insert_data_option='INSERT_ROWS'
            )
            
            # Extract row number from the response
            row_num = 0
            if result and 'updates' in result:
                updated_range = result['updates'].get('updatedRange', '')
                if updated_range:
                    import re
                    match = re.search(r'(\d+)$', updated_range.split(':')[0])
                    if match:
                        row_num = int(match.group(1))
            
            _log_sheets_event("append", ok=True, expense_id=expense_id, row_num=row_num)
            
            return AppendResult(ok=True, row_number=row_num, error="")
            
        except APIError as e:
            tb = traceback.format_exc()
            error_msg = str(e)
            _set_sheets_error("unknown_error", f"API error appending row: {e}", tb)
            _log_sheets_event("append", ok=False, expense_id=expense_id, error_message=error_msg)
            return AppendResult(ok=False, row_number=0, error=f"Sheets API error: {error_msg}")
        except Exception as e:
            tb = traceback.format_exc()
            error_msg = str(e)
            _set_sheets_error("unknown_error", f"Error appending row: {e}", tb)
            _log_sheets_event("append", ok=False, expense_id=expense_id, error_message=error_msg)
            return AppendResult(ok=False, row_number=0, error=f"Error: {error_msg}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Global client instance
_sheets_client: Optional[SheetsClient] = None


def get_sheets_client() -> SheetsClient:
    """Get or create the global Sheets client."""
    global _sheets_client
    if _sheets_client is None:
        _sheets_client = SheetsClient()
    return _sheets_client


def reset_sheets_client() -> None:
    """Reset the global Sheets client (for testing or re-initialization)."""
    global _sheets_client
    _sheets_client = None
    _clear_sheets_error()


# Spanish month abbreviations (uppercase)
_MES_ABREVIACIONES = [
    "ENE", "FEB", "MAR", "ABR", "MAY", "JUN",
    "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"
]


def _format_fecha_for_sheets(fecha: str) -> str:
    """
    Validate and return fecha in ISO format (YYYY-MM-DD) for Sheets storage.
    
    Args:
        fecha: Date string in YYYY-MM-DD format
    
    Returns:
        Date string in YYYY-MM-DD format (ISO standard)
    """
    # Return as-is if already ISO format; storage uses ISO
    return fecha if fecha else ""


def _derive_mes(fecha: str) -> str:
    """
    Derive Mes in ISO format (YYYY-MM) from fecha (YYYY-MM-DD).
    
    Args:
        fecha: Date string in YYYY-MM-DD format
    
    Returns:
        Month string in YYYY-MM format (ISO standard)
    """
    if not fecha or len(fecha) < 7:
        return ""
    
    # Extract YYYY-MM (first 7 chars of ISO date)
    return fecha[:7]


def append_expense_row(
    fecha: str,
    descripcion: str,
    factura: str,
    responsable: str,
    monto: float,
    moneda: str,
    itbms: bool,
    categoria: str,
    metodo_pago: str = "",
    notas: str = "",
    fuente: str = "Texto",
    link_archivo: str = "",
    expense_id: str = "",
) -> AppendResult:
    """
    Append an expense row to Google Sheets with exact 13-column mapping.
    
    Header order:
    Fecha, Descripción, Factura, Responsable, Monto, Moneda, ITBMS, Categoría,
    Método de Pago, Notas, Fuente, Link/Archivo, Mes
    
    Args:
        fecha: YYYY-MM-DD format
        descripcion: Description of expense
        factura: Invoice/receipt ID (empty if none)
        responsable: One of FIN_RESPONSIBLES
        monto: Amount as float
        moneda: "USD" or "PAB"
        itbms: Whether ITBMS tax applies
        categoria: Category string
        metodo_pago: Payment method (optional)
        notas: Additional notes (optional)
        fuente: "Texto" or "Receipt"
        link_archivo: Link to receipt file (optional)
        expense_id: ID for logging
    
    Returns:
        AppendResult with ok, row_number, error
    """
    client = get_sheets_client()
    
    # Keep fecha in ISO format for storage (YYYY-MM-DD)
    fecha_formatted = _format_fecha_for_sheets(fecha)
    
    # Derive Mes in ISO format (YYYY-MM)
    mes = _derive_mes(fecha)
    
    # Build row with exactly 13 columns in exact order
    values = [
        fecha_formatted, # Fecha (YYYY-MM-DD ISO)
        descripcion,     # Descripción
        factura,         # Factura
        responsable,     # Responsable
        monto,           # Monto
        moneda,          # Moneda
        "Sí" if itbms else "No",  # ITBMS
        categoria,       # Categoría
        metodo_pago,     # Método de Pago
        notas,           # Notas
        fuente,          # Fuente
        link_archivo,    # Link/Archivo
        mes,             # Mes (YYYY-MM ISO)
    ]
    
    return client.append_row(values, expense_id=expense_id)


# Legacy function for backward compatibility
def append_expense_to_sheets(
    fecha: str,
    monto: float,
    moneda: str,
    descripcion: str,
    categoria: str,
    responsable: str,
    itbms: bool,
    proveedor: str = "",
    metodo_pago: str = "",
    fuente: str = "Texto",
    link: str = "",
    expense_id: str = "",
) -> tuple[bool, str]:
    """
    Legacy wrapper for append_expense_row.
    
    Returns:
        (success, message) tuple
    """
    result = append_expense_row(
        fecha=fecha,
        descripcion=descripcion,
        factura="",  # Not provided in legacy API
        responsable=responsable,
        monto=monto,
        moneda=moneda,
        itbms=itbms,
        categoria=categoria,
        metodo_pago=metodo_pago,
        notas=proveedor,  # Map proveedor to notas
        fuente=fuente,
        link_archivo=link,
        expense_id=expense_id,
    )
    
    if result["ok"]:
        return True, f"Guardado en Sheets (fila {result['row_number']})"
    else:
        return False, result["error"]


def check_sheets_available() -> bool:
    """Check if Google Sheets integration is available."""
    return get_sheets_client().is_available()


def validate_sheets_header() -> tuple[bool, str]:
    """
    Validate that the Sheets header matches expected format.
    
    Returns:
        (valid, error_message)
    """
    client = get_sheets_client()
    return client.ensure_header_matches(SHEETS_EXPECTED_HEADER)


class SheetsStatus(TypedDict, total=False):
    """Full status information for the Sheets integration."""
    ok: bool                  # True if sheets are fully operational
    sheets_available: bool
    config_path: str
    config_exists: bool
    spreadsheet_id: str
    tab_name: str
    sheet_title: str          # Spreadsheet title (if accessible)
    header_ok: bool           # True if header matches expected
    last_error: Optional[SheetsError]
    interpreter: str
    gspread_version: str


def get_sheets_status() -> SheetsStatus:
    """
    Get comprehensive status information about the Sheets integration.
    
    This function checks each step of the initialization and reports
    detailed status information useful for debugging.
    
    Returns:
        SheetsStatus dict with all diagnostic information
    """
    json_path = Path(GOOGLE_SERVICE_ACCOUNT_JSON_PATH) if GOOGLE_SERVICE_ACCOUNT_JSON_PATH else None
    
    # Check basic availability
    sheets_avail = check_sheets_available()
    
    # Try to get spreadsheet title if available
    sheet_title = ""
    header_ok = False
    
    if sheets_avail:
        client = get_sheets_client()
        # Get title from spreadsheet
        if client._spreadsheet:
            try:
                sheet_title = client._spreadsheet.title
            except Exception:
                pass
        # Check header
        try:
            header_valid, _ = client.ensure_header_matches(SHEETS_EXPECTED_HEADER)
            header_ok = header_valid
        except Exception:
            pass
    
    status = SheetsStatus(
        ok=sheets_avail and header_ok,
        sheets_available=sheets_avail,
        config_path=GOOGLE_SERVICE_ACCOUNT_JSON_PATH or "",
        config_exists=json_path.exists() if json_path else False,
        spreadsheet_id=SHEETS_SPREADSHEET_ID or "",
        tab_name=SHEETS_TAB_NAME or "",
        sheet_title=sheet_title,
        header_ok=header_ok,
        last_error=get_sheets_last_error(),
        interpreter=sys.executable,
        gspread_version=GSPREAD_VERSION,
    )
    
    return status
