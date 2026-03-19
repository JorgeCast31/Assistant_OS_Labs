"""
Google Drive integration for receipt uploads.

STUB: This module is prepared for future OCR integration.
Currently provides placeholder functions that will be implemented
when receipt photo processing is added.

Future flow:
1. User uploads receipt photo via /fin/receipt
2. upload_receipt() uploads to Drive folder
3. Returns file_id and webViewLink for Sheets row
4. OCR extracts monto/fecha/etc (future)
"""
from typing import TypedDict


class UploadResult(TypedDict):
    """Result from upload_receipt."""
    ok: bool
    file_id: str
    webViewLink: str
    error: str


# ---------------------------------------------------------------------------
# Configuration (future)
# ---------------------------------------------------------------------------
# GOOGLE_DRIVE_FOLDER_ID: str = ""  # Will be set in config.py when needed


# ---------------------------------------------------------------------------
# Stub Functions
# ---------------------------------------------------------------------------

def upload_receipt(
    file_bytes: bytes,
    filename: str,
    mime_type: str = "image/jpeg",
) -> UploadResult:
    """
    Upload a receipt image to Google Drive.
    
    STUB: Returns not-implemented error.
    Will be implemented when receipt photo upload feature is added.
    
    Args:
        file_bytes: Raw file content
        filename: Desired filename (e.g., "REC-2026-02-24-001.jpg")
        mime_type: MIME type (image/jpeg, image/png, application/pdf)
    
    Returns:
        UploadResult with file_id and webViewLink on success
    """
    # TODO: Implement when ready
    # 1. Initialize Drive API with service account
    # 2. Upload to configured folder
    # 3. Return file_id and shareable link
    
    return UploadResult(
        ok=False,
        file_id="",
        webViewLink="",
        error="Receipt upload not implemented yet. Coming soon.",
    )


def generate_receipt_id(fecha: str) -> str:
    """
    Generate a unique receipt ID.
    
    Format: REC-YYYY-MM-DD-XXXX where XXXX is sequential.
    
    Args:
        fecha: Date string in YYYY-MM-DD format
    
    Returns:
        Receipt ID string
    """
    import random
    # Simple implementation - in production, use sequential counter
    suffix = random.randint(1000, 9999)
    return f"REC-{fecha}-{suffix}"


def is_drive_available() -> bool:
    """
    Check if Google Drive integration is available.
    
    STUB: Returns False until implemented.
    """
    return False
