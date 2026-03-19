"""
FIN Normalization — v1

Pure field-level canonicalization helpers for FIN expense data.

No HTTP transport logic.
No Sheets append logic.
No DomainResult construction.

Public API
----------
canonicalize_commit_expense(expense_data: dict) -> dict
    Given a raw expense dict from a /fin/commit request body,
    return a canonicalized ParsedExpense-compatible dict ready for Sheets append.
"""

from __future__ import annotations


def canonicalize_commit_expense(expense_data: dict) -> dict:
    """
    Canonicalize raw expense_data from a /fin/commit body into a ParsedExpense dict.

    Applies:
    - RESPONSABLES_CANONICAL lookup for responsable
    - CATEGORIA_CANONICAL lookup (with default) for categoria
    - METODO_PAGO_CANONICAL lookup for metodo_pago
    - mes derived from fecha[:7]
    - monto cast to float

    Args:
        expense_data: Raw expense dict as received from the client.

    Returns:
        A ParsedExpense-compatible dict with canonicalized fields.
    """
    from ..fin_expense import (
        RESPONSABLES_CANONICAL,
        CATEGORIA_CANONICAL,
        CATEGORIA_DEFAULT,
        METODO_PAGO_CANONICAL,
    )

    # Canonicalize responsable
    resp_raw = expense_data.get("responsable", "unknown")
    resp_lower = resp_raw.lower() if isinstance(resp_raw, str) else "unknown"
    responsable = RESPONSABLES_CANONICAL.get(resp_lower, resp_raw)

    # Canonicalize categoria
    cat_raw = expense_data.get("categoria", "Otros")
    cat_lower = cat_raw.lower() if isinstance(cat_raw, str) else "otros"
    categoria = CATEGORIA_CANONICAL.get(cat_lower, cat_raw if cat_raw else CATEGORIA_DEFAULT)

    # Canonicalize metodo_pago
    metodo_raw = expense_data.get("metodo_pago", "")
    metodo_lower = metodo_raw.lower() if isinstance(metodo_raw, str) else ""
    metodo_pago = METODO_PAGO_CANONICAL.get(metodo_lower, metodo_raw if metodo_raw else "")

    # Build fecha and mes
    fecha = expense_data.get("fecha", "")
    mes = fecha[:7] if len(fecha) >= 7 else ""

    return {
        "fecha": fecha,
        "monto": float(expense_data.get("monto", 0)),
        "moneda": expense_data.get("moneda", "USD"),
        "descripcion": expense_data.get("descripcion", ""),
        "responsable": responsable,
        "itbms": expense_data.get("itbms", False),
        "itbms_pct": 7.0 if expense_data.get("itbms", False) else None,
        "categoria": categoria,
        "proveedor": expense_data.get("proveedor", ""),
        "metodo_pago": metodo_pago,
        "raw_text": expense_data.get("raw_segment", ""),
        "mes": mes,
        "factura": "",
        "notas": "",
        "fuente": "chat",
        "link_archivo": "",
    }
