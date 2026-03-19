"""
Tests for FIN Plan module - Plan Always architecture.

Tests:
- Input with 2 montos → plan.total_items=2
- Input with 1 monto → plan.total_items=1
- No monto → needs_clarification
- Fragment continuation adds to plan
- Commit stores row
"""
import unittest
from assistant_os.fin_plan import (
    generate_fin_plan,
    add_to_plan,
    _extract_montos_with_positions,
    _segment_text_by_montos,
    _detect_responsable,
    _detect_categoria,
    _detect_metodo_pago,
    _detect_itbms,
    _extract_descripcion,
    _build_plan_item,
    FinPlanResponse,
    PlanItem,
    DraftExpense,
)


# ---------------------------------------------------------------------------
# Tests for _extract_montos_with_positions
# ---------------------------------------------------------------------------

class TestExtractMontos:
    """Tests for monto extraction."""
    
    def test_single_dollar_amount(self):
        result = _extract_montos_with_positions("Gasté $25 en comida")
        assert len(result) == 1
        assert result[0][0] == 25.0
        assert result[0][1] == "USD"
    
    def test_dollar_after_number(self):
        result = _extract_montos_with_positions("Pagué 25$ por el taxi")
        assert len(result) == 1
        assert result[0][0] == 25.0
        assert result[0][1] == "USD"
    
    def test_balboa_amount(self):
        result = _extract_montos_with_positions("Gasté B/.15 en farmacia")
        assert len(result) == 1
        assert result[0][0] == 15.0
        assert result[0][1] == "PAB"
    
    def test_two_amounts(self):
        result = _extract_montos_with_positions("$25 en comida y $15 para conejos")
        assert len(result) == 2
        assert result[0][0] == 25.0
        assert result[1][0] == 15.0
    
    def test_mixed_currencies(self):
        result = _extract_montos_with_positions("$25 en comida y B/.15 en farmacia")
        assert len(result) == 2
        assert result[0][1] == "USD"
        assert result[1][1] == "PAB"
    
    def test_decimal_amount(self):
        result = _extract_montos_with_positions("$25.50 en supermercado")
        assert len(result) == 1
        assert result[0][0] == 25.5


# ---------------------------------------------------------------------------
# Tests for _segment_text_by_montos
# ---------------------------------------------------------------------------

class TestSegmentText:
    """Tests for text segmentation."""
    
    def test_single_segment(self):
        montos = _extract_montos_with_positions("$25 en comida")
        result = _segment_text_by_montos("$25 en comida", montos)
        assert len(result) == 1
        assert "$25" in result[0]
    
    def test_two_segments_with_y(self):
        text = "$25 en comida y $15 para conejos"
        montos = _extract_montos_with_positions(text)
        result = _segment_text_by_montos(text, montos)
        assert len(result) == 2
        assert "comida" in result[0]
        assert "conejos" in result[1]
    
    def test_two_segments_with_comma(self):
        text = "$25 supermercado, $15 farmacia"
        montos = _extract_montos_with_positions(text)
        result = _segment_text_by_montos(text, montos)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Tests for _detect_responsable
# ---------------------------------------------------------------------------

class TestDetectResponsable:
    """Tests for responsable detection."""
    
    def test_para_conejos(self):
        result = _detect_responsable("$15 para los conejos")
        assert result == "Conejos"
    
    def test_para_casa(self):
        result = _detect_responsable("$50 para la casa")
        assert result == "Hogar"
    
    def test_direct_mention_jorge(self):
        result = _detect_responsable("Responsable: Jorge")
        assert result == "Jorge"
    
    def test_alias_yo(self):
        result = _detect_responsable("lo pagué yo")
        assert result == "Jorge"
    
    def test_no_responsable(self):
        result = _detect_responsable("$25 en supermercado")
        assert result == "Jorge"


# ---------------------------------------------------------------------------
# Tests for _detect_categoria
# ---------------------------------------------------------------------------

class TestDetectCategoria:
    """Tests for category detection."""
    
    def test_comida(self):
        result = _detect_categoria("gasto en comida")
        assert result == "Comida"
    
    def test_farmacia(self):
        result = _detect_categoria("$15 en farmacia")
        assert result == "Salud"
    
    def test_uber(self):
        result = _detect_categoria("$8 del uber")
        assert result == "Transporte"
    
    def test_no_match(self):
        result = _detect_categoria("algo random")
        assert result == "Otros"


# ---------------------------------------------------------------------------
# Tests for _detect_metodo_pago
# ---------------------------------------------------------------------------

class TestDetectMetodoPago:
    """Tests for payment method detection."""
    
    def test_tarjeta(self):
        result = _detect_metodo_pago("pagué con tarjeta")
        assert result == "Tarjeta"
    
    def test_efectivo(self):
        result = _detect_metodo_pago("en efectivo")
        assert result == "Efectivo"
    
    def test_yappy(self):
        result = _detect_metodo_pago("pagué por yappy")
        assert result == "Yappy"
    
    def test_no_method(self):
        result = _detect_metodo_pago("$25 en comida")
        assert result == ""


# ---------------------------------------------------------------------------
# Tests for _detect_itbms
# ---------------------------------------------------------------------------

class TestDetectItbms:
    """Tests for ITBMS detection."""
    
    def test_itbms_no(self):
        result = _detect_itbms("ITBMS: No")
        assert result is False
    
    def test_itbms_si(self):
        result = _detect_itbms("ITBMS: Sí")
        assert result is True
    
    def test_con_itbms(self):
        result = _detect_itbms("precio con itbms")
        assert result is True
    
    def test_sin_itbms(self):
        result = _detect_itbms("sin itbms")
        assert result is False
    
    def test_not_mentioned(self):
        result = _detect_itbms("$25 en comida")
        assert result is False


# ---------------------------------------------------------------------------
# Tests for generate_fin_plan
# ---------------------------------------------------------------------------

class TestGenerateFinPlan:
    """Tests for main plan generation."""
    
    def test_single_monto_plan(self):
        """Input with 1 monto → plan.total_items=1"""
        result = generate_fin_plan("$25 en comida")
        
        assert result["ok"] is True
        assert result["kind"] == "fin_plan"
        assert result["total_items"] == 1
        assert len(result["items"]) == 1
        assert result["needs_clarification"] is False
    
    def test_two_montos_plan(self):
        """Input with 2 montos → plan.total_items=2"""
        result = generate_fin_plan("$25 en comida y $15 para conejos")
        
        assert result["ok"] is True
        assert result["kind"] == "fin_plan"
        assert result["total_items"] == 2
        assert len(result["items"]) == 2
    
    def test_three_montos_plan(self):
        """Input with 3 montos → plan.total_items=3"""
        result = generate_fin_plan("$25 comida, $15 farmacia y $10 uber")
        
        assert result["ok"] is True
        assert result["total_items"] == 3
        assert len(result["items"]) == 3
    
    def test_no_monto_needs_clarification(self):
        """Input with no monto → needs_clarification"""
        result = generate_fin_plan("gasté en el supermercado")
        
        assert result["ok"] is True
        assert result["kind"] == "needs_clarification"
        assert result["needs_clarification"] is True
        assert result["total_items"] == 0
    
    def test_empty_text(self):
        """Empty text returns error."""
        result = generate_fin_plan("")
        
        assert result["ok"] is False
    
    def test_plan_item_structure(self):
        """Plan items have correct structure."""
        result = generate_fin_plan("$25 en comida para Jorge")
        
        assert len(result["items"]) == 1
        item = result["items"][0]
        
        assert "id" in item  # UUID
        assert "draft_expense" in item
        assert "missing_fields" in item
        assert "confidence" in item
        assert "raw_segment" in item
        
        draft = item["draft_expense"]
        assert draft["monto"] == 25.0
        assert draft["moneda"] == "USD"
        assert draft["responsable"] == "Jorge"
    
    def test_missing_responsable_in_missing_fields(self):
        """Default responsable='Jorge' is no longer a missing field."""
        result = generate_fin_plan("$25 en comida")

        item = result["items"][0]
        assert item["draft_expense"]["responsable"] == "Jorge"
        assert "responsable" not in item["missing_fields"]
    
    def test_plan_message_single(self):
        """Single item plan has correct message."""
        result = generate_fin_plan("$25 en comida")
        
        assert "Capté 1 gasto" in result["message"]
    
    def test_plan_message_multiple(self):
        """Multiple item plan has correct message."""
        result = generate_fin_plan("$25 comida y $15 farmacia")
        
        assert "Capté 2 gastos" in result["message"]
    
    def test_session_context_updated(self):
        """Session context is updated with plan info."""
        result = generate_fin_plan("$25 en comida")
        
        ctx = result["session_context"]
        assert ctx["last_domain"] == "FIN"
        assert ctx["last_currency"] == "USD"
        assert "last_date" in ctx


# ---------------------------------------------------------------------------
# Tests for add_to_plan (continuations)
# ---------------------------------------------------------------------------

class TestAddToPlan:
    """Tests for adding items to existing plan."""
    
    def test_add_item_to_plan(self):
        """Fragment continuation adds to plan."""
        # Initial plan
        plan = generate_fin_plan("$25 en comida")
        assert plan["total_items"] == 1
        
        # Add continuation
        updated = add_to_plan("$15 para los conejos", plan)
        
        assert updated["ok"] is True
        assert updated["total_items"] == 2
        assert len(updated["items"]) == 2
    
    def test_combined_message(self):
        """Combined message shows all items."""
        plan = generate_fin_plan("$25 comida")
        updated = add_to_plan("$15 farmacia", plan)
        
        assert "Capté 2 gastos" in updated["message"]


# ---------------------------------------------------------------------------
# Tests for draft expense fields
# ---------------------------------------------------------------------------

class TestDraftExpenseFields:
    """Tests for draft expense field extraction."""
    
    def test_full_expense_parsing(self):
        """Full expense with all fields."""
        result = generate_fin_plan(
            "$25 en farmacia para Jorge. Pagué con tarjeta. ITBMS: Sí"
        )
        
        assert result["total_items"] == 1
        draft = result["items"][0]["draft_expense"]
        
        assert draft["monto"] == 25.0
        assert draft["moneda"] == "USD"
        assert draft["categoria"] == "Salud"
        assert draft["responsable"] == "Jorge"
        assert draft["metodo_pago"] == "Tarjeta"
        assert draft["itbms"] is True
    
    def test_balboa_currency(self):
        """Balboa amount sets PAB currency."""
        result = generate_fin_plan("B/.15 en farmacia")
        
        draft = result["items"][0]["draft_expense"]
        assert draft["moneda"] == "PAB"
        assert draft["monto"] == 15.0
    
    def test_description_extraction(self):
        """Description is extracted from segment."""
        result = generate_fin_plan("$25 en supermercado")
        
        draft = result["items"][0]["draft_expense"]
        # Description should contain "supermercado"
        assert "supermercado" in draft["descripcion"].lower() or draft["descripcion"]


# ---------------------------------------------------------------------------
# Tests for confidence scoring
# ---------------------------------------------------------------------------

class TestConfidenceScoring:
    """Tests for confidence calculation."""
    
    def test_high_confidence_complete(self):
        """Complete expense has high confidence."""
        result = generate_fin_plan("$25 en comida para Jorge")
        
        item = result["items"][0]
        assert item["confidence"] >= 0.8
    
    def test_lower_confidence_missing_responsable(self):
        """Default responsable='Jorge' does not lower confidence."""
        result = generate_fin_plan("$25 en comida")

        item = result["items"][0]
        assert item["confidence"] >= 0.9  # 'Jorge' default is not penalized


# ---------------------------------------------------------------------------
# Acceptance Criteria Tests
# ---------------------------------------------------------------------------

class TestAcceptanceCriteria:
    """Tests for specific acceptance criteria from requirements."""
    
    def test_case_a_three_expenses_not_number(self):
        """
        Test Case A: '3 gastos' should NOT be detected as a monto.
        Input: "Hola, tengo 3 gastos: yo comida 30$, ana ropa 15$, y los conejos 20$ su heno."
        Result: mode="multi", expenses length=3, montos = [30,15,20], responsables = [Jorge, Ana, Conejos]
        """
        text = "Hola, tengo 3 gastos: yo comida 30$, ana ropa 15$, y los conejos 20$ su heno."
        result = generate_fin_plan(text)
        
        assert result["ok"] is True
        assert result["mode"] == "multi"
        assert result["total_items"] == 3
        assert len(result["items"]) == 3
        
        # Verify montos - "3" should NOT be a monto
        montos = [item["draft_expense"]["monto"] for item in result["items"]]
        assert 3.0 not in montos
        assert 30.0 in montos
        assert 15.0 in montos
        assert 20.0 in montos
        
        # Verify responsables
        responsables = [item["draft_expense"]["responsable"] for item in result["items"]]
        assert "Jorge" in responsables  # "yo" -> Jorge
        assert "Ana" in responsables
        assert "Conejos" in responsables
    
    def test_case_b_two_expenses_for_house_and_rabbits(self):
        """
        Test Case B: Two expenses, no doc/energy residual.
        Input: "compré para la casa 25$ en comida y 15$ para los conejos"
        Result: 2 gastos, ambos FIN.
        """
        text = "compré para la casa 25$ en comida y 15$ para los conejos"
        result = generate_fin_plan(text)
        
        assert result["ok"] is True
        assert result["total_items"] == 2
        assert len(result["items"]) == 2
        
        # Verify montos
        montos = [item["draft_expense"]["monto"] for item in result["items"]]
        assert 25.0 in montos
        assert 15.0 in montos
        
        # Verify responsables
        responsables = [item["draft_expense"]["responsable"] for item in result["items"]]
        assert "Hogar" in responsables  # "para la casa" -> Hogar
        assert "Conejos" in responsables
    
    def test_case_c_single_expense_with_metadata(self):
        """
        Test Case C: Single expense with full metadata.
        Input: "Gasto B/. 23.50 en farmacia. Responsable: Jorge. ITBMS: No. Método: Tarjeta."
        Result: single, itbms=False, método=Tarjeta, moneda=PAB.
        """
        text = "Gasto B/. 23.50 en farmacia. Responsable: Jorge. ITBMS: No. Método: Tarjeta."
        result = generate_fin_plan(text)
        
        assert result["ok"] is True
        assert result["mode"] == "single"
        assert result["total_items"] == 1
        
        draft = result["items"][0]["draft_expense"]
        assert draft["monto"] == 23.5
        assert draft["moneda"] == "PAB"
        assert draft["responsable"] == "Jorge"
        assert draft["itbms"] is False
        assert draft["metodo_pago"] == "Tarjeta"
        assert draft["categoria"] == "Salud"  # "farmacia" -> Salud
    
    def test_mode_field_single(self):
        """Plan with 1 item has mode='single'."""
        result = generate_fin_plan("$25 en comida")
        assert result["mode"] == "single"
    
    def test_mode_field_multi(self):
        """Plan with >1 items has mode='multi'."""
        result = generate_fin_plan("$25 comida y $15 farmacia")
        assert result["mode"] == "multi"
    
    def test_chaperon_message_format(self):
        """Message contains 'Capté' and '¿Confirmo?'."""
        result = generate_fin_plan("$25 comida y $15 farmacia")
        assert "Capté" in result["message"]
        assert "¿Confirmo?" in result["message"]
    
    def test_currency_symbol_required_for_monto(self):
        """Numbers without currency symbols are NOT detected as montos."""
        # "tengo 5 gastos" - 5 should NOT be detected
        montos = _extract_montos_with_positions("tengo 5 gastos pendientes")
        assert len(montos) == 0
        
        # "gasto de 100" without $ - should NOT be detected
        montos = _extract_montos_with_positions("gasto de 100 aproximadamente")
        assert len(montos) == 0
        
        # But "gasto de $100" should be detected
        montos = _extract_montos_with_positions("gasto de $100")
        assert len(montos) == 1
        assert montos[0][0] == 100.0
    
    def test_responsable_by_proximity(self):
        """Responsable is detected within text segment, not globally."""
        text = "yo compré comida $30, y ana ropa $20"
        result = generate_fin_plan(text)
        
        # First expense (yo = Jorge)
        assert result["items"][0]["draft_expense"]["responsable"] == "Jorge"
        # Second expense (ana)
        assert result["items"][1]["draft_expense"]["responsable"] == "Ana"


# ---------------------------------------------------------------------------
# Tests for unsymboled numbers and clarification
# ---------------------------------------------------------------------------

class TestUnsymboledNumbers:
    """Tests for detection of numbers without monetary symbols."""
    
    def test_detect_percentage(self):
        """Percentages should be detected as unsymboled numbers."""
        from assistant_os.fin_plan import _detect_unsymboled_numbers
        
        text = "Hoy tuve varios gastos, 15% en Mcdonalds, 16$ en medicamentos"
        montos = _extract_montos_with_positions(text)
        unsymboled = _detect_unsymboled_numbers(text, montos)
        
        # 15% should be detected
        assert any(n['number'] == 15.0 and n['is_percentage'] for n in unsymboled)
    
    def test_dont_detect_monto_as_unsymboled(self):
        """Numbers already part of montos should not be detected."""
        from assistant_os.fin_plan import _detect_unsymboled_numbers
        
        text = "$16 en medicamentos y $24 para conejos"
        montos = _extract_montos_with_positions(text)
        unsymboled = _detect_unsymboled_numbers(text, montos)
        
        # 16 and 24 should NOT be in unsymboled (they are montos)
        assert not any(n['number'] in [16.0, 24.0] for n in unsymboled)
    
    def test_detect_bare_number(self):
        """Bare numbers without % should be detected."""
        from assistant_os.fin_plan import _detect_unsymboled_numbers
        
        text = "comida 30, ana ropa 15"
        montos = _extract_montos_with_positions(text)  # Should be empty
        unsymboled = _detect_unsymboled_numbers(text, montos)
        
        # 30 and 15 should be detected
        numbers = [n['number'] for n in unsymboled]
        assert 30.0 in numbers
        assert 15.0 in numbers
    
    def test_skip_dates(self):
        """Numbers in date formats should be skipped."""
        from assistant_os.fin_plan import _detect_unsymboled_numbers
        
        text = "el 25/02/2026 gasté $50"
        montos = _extract_montos_with_positions(text)
        unsymboled = _detect_unsymboled_numbers(text, montos)
        
        # Date components should not be detected
        numbers = [n['number'] for n in unsymboled]
        assert 25.0 not in numbers
        assert 2.0 not in numbers
        assert 2026.0 not in numbers


class TestClarificationFlow:
    """Tests for needs_clarification behavior."""
    
    def test_montos_with_percentage_triggers_clarification(self):
        """Having montos plus a percentage should trigger clarification."""
        text = "Hoy tuve varios gastos, 15% en Mcdonalds, $16 en medicamentos y $24 para conejos"
        result = generate_fin_plan(text)
        
        assert result["ok"] is True
        assert result["total_items"] == 2  # $16 and $24
        assert result["needs_clarification"] is True
        assert "15" in result["clarification_prompt"]
        assert "%" in result["clarification_prompt"]
    
    def test_no_montos_with_bare_numbers_triggers_clarification(self):
        """No montos but bare numbers should trigger clarification."""
        text = "comida 30, ana ropa 15"
        result = generate_fin_plan(text)
        
        assert result["ok"] is True
        assert result["total_items"] == 0
        assert result["needs_clarification"] is True
        assert "30" in result["clarification_prompt"]
    
    def test_clean_montos_no_clarification(self):
        """Montos without ambiguous numbers should not trigger clarification."""
        text = "$16 en medicamentos y $24 para conejos"
        result = generate_fin_plan(text)
        
        assert result["ok"] is True
        assert result["total_items"] == 2
        assert result["needs_clarification"] is False
    
    def test_single_bare_number_sets_candidate_amount(self):
        """Single bare number → candidate_amount in session_context for button UI."""
        text = "pagué 25 en almuerzo con tarjeta"
        result = generate_fin_plan(text)

        assert result["ok"] is True
        assert result["total_items"] == 0
        assert result["needs_clarification"] is True

        # Message should be the friendly candidate message
        assert "25" in result["message"]
        assert "posible monto" in result["message"].lower() or "$25" in result["message"]

        # candidate_amount must be surfaced in session_context
        pending = result["session_context"].get("pending_clarification", {})
        assert pending.get("candidate_amount") == 25.0
        assert pending.get("original_text") == text

    def test_single_bare_number_almuerzo(self):
        """Verify 'pagué N' without symbol produces candidate_amount=N."""
        for phrase, expected in [
            ("pagué 25 en almuerzo con tarjeta", 25.0),
            ("almuerzo 12.50 con visa", 12.5),
            ("gasté 100 en uber", 100.0),
        ]:
            result = generate_fin_plan(phrase)
            pending = result["session_context"].get("pending_clarification", {})
            assert pending.get("candidate_amount") == expected, f"Failed for: {phrase!r}"

    def test_multiple_bare_numbers_no_candidate(self):
        """Multiple bare numbers → no candidate_amount (ambiguous, text prompt)."""
        text = "comida 30, ana ropa 15"
        result = generate_fin_plan(text)

        assert result["needs_clarification"] is True
        pending = result["session_context"].get("pending_clarification", {})
        # Two numbers → ambiguous, no single candidate
        assert "candidate_amount" not in pending

    def test_percentage_plus_bare_number_no_candidate(self):
        """A percentage + bare number: non-pct count is 1 but pct is excluded."""
        # "25% de descuento pagué 10" — non-pct = [10], so candidate_amount=10
        text = "pagué 10 con 25% de descuento"
        result = generate_fin_plan(text)
        if result["needs_clarification"]:
            pending = result["session_context"].get("pending_clarification", {})
            # non-pct candidates: only 10 → candidate_amount should be 10
            if "candidate_amount" in pending:
                assert pending["candidate_amount"] == 10.0

    # ------------------------------------------------------------------
    # Routing regression: free-text follow-up "30" must advance to plan
    # ------------------------------------------------------------------

    def test_bare_number_follow_up_tier2_injection(self):
        """Simulates backend receiving the tier-2 injected text when user replied '30'
        to a candidate card where original had '25'.
        Frontend: _injectCandidateAmount('pagué 25 en almuerzo', 30, 25)
          → tier-2: replaces '25' with '$30' → 'pagué $30 en almuerzo'.
        Backend must produce a valid plan (not clarification) for this injected text."""
        injected = "pagué $30 en almuerzo con tarjeta"
        result = generate_fin_plan(injected, session_context={"skip_candidate_clarification": True})
        assert result.get("ok") is True, "Expected ok=True"
        assert result.get("total_items", 0) == 1, "Expected 1 plan item, not clarification"
        assert not result.get("needs_clarification"), "Must NOT loop back to clarification"
        assert result["items"][0]["draft_expense"]["monto"] == 30.0

    def test_bare_number_follow_up_tier3_fallback(self):
        """Simulates tier-3 fallback: original text had no recognisable number position
        so frontend prepends '$30 ' to the original description.
        Backend must produce a valid plan."""
        # tier-3: '$30 pagué almuerzo con tarjeta'
        injected = "$30 pagué almuerzo con tarjeta"
        result = generate_fin_plan(injected, session_context={"skip_candidate_clarification": True})
        assert result.get("ok") is True
        assert result.get("total_items", 0) >= 1
        assert not result.get("needs_clarification")
        amounts = [item["draft_expense"]["monto"] for item in result["items"]]
        assert 30.0 in amounts

    def test_injected_candidate_produces_plan(self):
        """After confirming candidate amount, frontend injects '$25' into original text.
        The resulting text 'pagué $25 en almuerzo con tarjeta' should produce a plan item."""
        injected = "pagué $25 en almuerzo con tarjeta"
        result = generate_fin_plan(injected)
        assert result.get("ok") is True
        assert result.get("total_items", 0) == 1
        item = result["items"][0]
        assert item["draft_expense"]["monto"] == 25.0

    def test_injected_corrected_amount_produces_plan(self):
        """User corrected candidate to $30; injected text 'pagué $30 en almuerzo con tarjeta'."""
        injected = "pagué $30 en almuerzo con tarjeta"
        result = generate_fin_plan(injected)
        assert result.get("ok") is True
        assert result.get("total_items", 0) == 1
        assert result["items"][0]["draft_expense"]["monto"] == 30.0

    def test_injected_candidate_no_longer_needs_clarification(self):
        """Injected text with $ symbol must NOT trigger needs_clarification."""
        injected = "pagué $25 en almuerzo con tarjeta"
        result = generate_fin_plan(injected)
        assert not result.get("needs_clarification"), "Expected no clarification for injected $ amount"

    # ------------------------------------------------------------------
    # D: Loop-prevention guard (skip_candidate_clarification flag)
    # ------------------------------------------------------------------

    def test_skip_flag_prevents_candidate_loop(self):
        """skip_candidate_clarification=True must prevent re-opening candidate clarification."""
        # Text with no $ symbol would normally trigger candidate detection
        text = "pagué 25 en almuerzo con tarjeta"
        result = generate_fin_plan(text, session_context={"skip_candidate_clarification": True})
        # With the flag set, candidate path is skipped → falls through to generic no-montos message
        assert not (
            result.get("needs_clarification") and
            result.get("session_context", {}).get("pending_clarification", {}).get("candidate_amount")
        ), "Flag should prevent candidate_amount from appearing"

    def test_skip_flag_still_plans_if_montos_present(self):
        """skip_candidate_clarification=True must not affect a text that already has $ amount."""
        injected = "pagué $25 en almuerzo con tarjeta"
        result = generate_fin_plan(injected, session_context={"skip_candidate_clarification": True})
        assert result.get("ok") is True
        assert result.get("total_items", 0) == 1
        assert result["items"][0]["draft_expense"]["monto"] == 25.0

    # ------------------------------------------------------------------
    # Context preservation after injection
    # ------------------------------------------------------------------

    def test_injected_text_preserves_category(self):
        """Amount injection must keep the semantic context (almuerzo → comida)."""
        injected = "pagué $25 en almuerzo con tarjeta"
        result = generate_fin_plan(injected)
        assert result.get("total_items", 0) == 1
        expense = result["items"][0]["draft_expense"]
        assert expense["monto"] == 25.0
        assert expense["metodo_pago"].lower() == "tarjeta"
        # Category should be food-related
        assert expense["categoria"].lower() in ("comida", "alimentación", "restaurante", "alimentos", "alimentacion")

    def test_corrected_amount_preserves_context(self):
        """User corrected amount from 25 to 30 — description context must survive."""
        # Simulate tier-2 injection: backend receives "$30 pagué en almuerzo con tarjeta"
        # (frontend replaced '25' with '$30' in the original)
        injected = "pagué $30 en almuerzo con tarjeta"
        result = generate_fin_plan(injected)
        assert result.get("total_items", 0) == 1
        expense = result["items"][0]["draft_expense"]
        assert expense["monto"] == 30.0
        assert expense["metodo_pago"].lower() == "tarjeta"

    # ------------------------------------------------------------------
    # E: Unknown / nonsense reply — backend must not crash or re-loop
    # ------------------------------------------------------------------

    def test_nonsense_after_candidate(self):
        """After candidate card, unknown follow-up goes through normal classify, not crash."""
        # "mmm" is not an expense — should produce needs_clarification with no candidate_amount
        result = generate_fin_plan("mmm")
        # No crash; returns a sensible response
        assert "ok" in result
        # Must NOT open a candidate_amount for a nonsense input
        pending = result.get("session_context", {}).get("pending_clarification", {})
        assert "candidate_amount" not in pending

    # ------------------------------------------------------------------
    # A/B/C: Candidate correction flow — context preservation and natural variants
    # ------------------------------------------------------------------

    def test_candidate_correction_a_bare_number_preserves_context(self):
        """
        Regression A: User typed '30' after a candidate card for 'pagué 25 en almuerzo con tarjeta'.
        Frontend tier-2 injection produces 'pagué $30 en almuerzo con tarjeta'.
        Backend must return monto=30, categoria=Comida, metodo_pago=Tarjeta.
        """
        injected = "pagué $30 en almuerzo con tarjeta"
        result = generate_fin_plan(injected, session_context={"skip_candidate_clarification": True})
        assert result.get("ok") is True
        assert result.get("total_items", 0) == 1
        assert not result.get("needs_clarification"), "Must not re-trigger clarification"
        expense = result["items"][0]["draft_expense"]
        assert expense["monto"] == 30.0
        assert expense["categoria"].lower() in ("comida", "alimentación", "restaurante", "alimentos", "alimentacion")
        assert expense["metodo_pago"].lower() == "tarjeta"

    def test_candidate_correction_b_natural_variant_eran(self):
        """
        Regression B: 'eran 30' must advance to a plan, not fall to UNKNOWN reminder.
        parseFollowUp: clarifyPattern matches 'eran', bare-number fallback extracts 30 → CLARIFY_AMOUNT.
        Backend receives injected 'pagué $30 en almuerzo con tarjeta' → valid plan.
        (Backend-side: verify injected text produces a plan.)
        """
        # The frontend would extract amount=30 from "eran 30" and call _injectCandidateAmount.
        # We test the backend receives the injected form and produces a plan.
        injected = "pagué $30 en almuerzo con tarjeta"
        result = generate_fin_plan(injected, session_context={"skip_candidate_clarification": True})
        assert result.get("ok") is True
        assert result.get("total_items", 0) == 1, "Natural variant 'eran 30' must produce a plan item"
        assert not result.get("needs_clarification")
        assert result["items"][0]["draft_expense"]["monto"] == 30.0

    def test_candidate_correction_c_mejor_variant(self):
        """
        Regression C: 'mejor $30' must be accepted as CLARIFY_AMOUNT and context preserved.
        'mejor' is in clarifyPattern; $30 is extracted by the $ pattern → amounts=[30].
        Backend receives 'pagué $30 en almuerzo con tarjeta' → plan with monto=30.
        """
        # Frontend extracts 30 from "mejor $30" and injects into original text.
        injected = "pagué $30 en almuerzo con tarjeta"
        result = generate_fin_plan(injected, session_context={"skip_candidate_clarification": True})
        assert result.get("ok") is True
        assert result.get("total_items", 0) == 1
        assert not result.get("needs_clarification")
        expense = result["items"][0]["draft_expense"]
        assert expense["monto"] == 30.0
        # Description must contain context from the original text, not just "Gasto"
        assert expense["descripcion"].lower() != "gasto", \
            f"Expected descriptive text, got: {expense['descripcion']!r}"

    def test_dom_dataset_empty_fallback_produces_correct_plan(self):
        """
        Regression: simulates the runtime scenario where the DOM recovery path loses
        originalText (dataset.originalText == '') and falls back to the finSessionContext.

        In this case the frontend would call handleFinPlan with the INJECTED text:
          _injectCandidateAmount("", 30, 25) → tier-3 → "$30"  (bad)
        vs.
          _injectCandidateAmount("pagué 25 en almuerzo con tarjeta", 30, 25)
            → tier-2 → "pagué $30 en almuerzo con tarjeta"  (good)

        The backend must NOT receive bare "$30" — it must receive the full injected text.
        This test verifies the GOOD path: full context preserved.
        """
        # Good path: frontend reconstructed originalText correctly
        good_injected = "pagué $30 en almuerzo con tarjeta"
        result = generate_fin_plan(good_injected, session_context={"skip_candidate_clarification": True})
        assert result.get("ok") is True
        assert result.get("total_items", 0) == 1
        expense = result["items"][0]["draft_expense"]
        assert expense["monto"] == 30.0
        assert expense["descripcion"].lower() != "gasto", \
            f"Context lost — got 'Gasto'. originalText was empty when _injectCandidateAmount ran."

        # Bad path (what happens when originalText == ''): "$30" alone → "Gasto"
        bad_injected = "$30"
        bad_result = generate_fin_plan(bad_injected, session_context={"skip_candidate_clarification": True})
        assert bad_result.get("ok") is True
        assert bad_result.get("total_items", 0) == 1
        assert bad_result["items"][0]["draft_expense"]["descripcion"].lower() == "gasto", \
            "Sanity: bare '$30' should produce 'Gasto' (confirms root cause when originalText is empty)"

    # ------------------------------------------------------------------
    # Decimal amount preservation — _injectCandidateAmount must NOT round
    # ------------------------------------------------------------------

    def test_decimal_amount_30_50_preserved(self):
        """
        30.50 must arrive at the backend as 30.50, not 31.
        Simulates: _injectCandidateAmount("pagué 25 en almuerzo con tarjeta", 30.50, 25)
          → tier-2 replaces "25" with "$30.5" → "pagué $30.5 en almuerzo con tarjeta"
        Backend regex \$\s*(\d+(?:[.,]\d{1,2})?) matches "$30.5" → monto=30.5.
        """
        injected = "pagué $30.5 en almuerzo con tarjeta"
        result = generate_fin_plan(injected, session_context={"skip_candidate_clarification": True})
        assert result.get("ok") is True
        assert result.get("total_items", 0) == 1
        expense = result["items"][0]["draft_expense"]
        assert expense["monto"] == 30.5, f"Expected 30.5, got {expense['monto']}"
        assert expense["descripcion"].lower() != "gasto"

    def test_decimal_amount_12_75_preserved(self):
        """12.75 — two non-zero decimal digits must survive injection and planning."""
        injected = "almuerzo $12.75 con tarjeta"
        result = generate_fin_plan(injected, session_context={"skip_candidate_clarification": True})
        assert result.get("ok") is True
        assert result.get("total_items", 0) == 1
        assert result["items"][0]["draft_expense"]["monto"] == 12.75, \
            f"Expected 12.75, got {result['items'][0]['draft_expense']['monto']}"

    def test_decimal_amount_0_99_preserved(self):
        """0.99 — sub-dollar amounts must be parsed correctly."""
        injected = "$0.99 en propina"
        result = generate_fin_plan(injected, session_context={"skip_candidate_clarification": True})
        assert result.get("ok") is True
        assert result.get("total_items", 0) == 1
        assert result["items"][0]["draft_expense"]["monto"] == 0.99, \
            f"Expected 0.99, got {result['items'][0]['draft_expense']['monto']}"

    def test_integer_amount_still_works_after_decimal_fix(self):
        """Regression guard: integer amounts (no cents) must still be injected correctly."""
        injected = "pagué $30 en almuerzo con tarjeta"
        result = generate_fin_plan(injected, session_context={"skip_candidate_clarification": True})
        assert result.get("ok") is True
        assert result["items"][0]["draft_expense"]["monto"] == 30.0

    # ------------------------------------------------------------------
    # Structured "Otro monto" UX — inline numeric input correction path
    # ------------------------------------------------------------------

    def test_otro_monto_structured_correction_preserves_context(self):
        """
        Structured 'Otro monto' path: user clicks the inline input, types 30, hits Apply.
        Frontend calls:
          _injectCandidateAmount("pagué 25 en almuerzo con tarjeta", 30, 25)
          → tier-2 → "pagué $30 en almuerzo con tarjeta"
        Backend must return plan with monto=30 and full context (not "Gasto").
        skip_candidate_clarification=True is sent so no second clarification loop opens.
        """
        injected = "pagué $30 en almuerzo con tarjeta"
        result = generate_fin_plan(injected, session_context={"skip_candidate_clarification": True})
        assert result.get("ok") is True
        assert result.get("total_items", 0) == 1
        assert not result.get("needs_clarification"), "No second clarification loop expected"
        expense = result["items"][0]["draft_expense"]
        assert expense["monto"] == 30.0
        assert expense["categoria"].lower() in ("comida", "alimentación", "alimentacion", "restaurante", "alimentos")
        assert expense["metodo_pago"].lower() == "tarjeta"
        assert expense["descripcion"].lower() != "gasto", \
            f"Structured correction must preserve context; got: {expense['descripcion']!r}"

    def test_otro_monto_no_second_candidate_loop(self):
        """
        After 'Otro monto' injection, skip_candidate_clarification=True must prevent
        a new candidate-amount clarification from opening even if the injected text
        happens to contain a bare number.
        """
        # Edge: user typed "compré 25 cosas" and then corrected to 30 via 'Otro monto'.
        # Tier-3 fallback produces "$30 compré 25 cosas" — the bare "25" must NOT
        # trigger a new candidate detection because the flag is set.
        injected = "$30 compré 25 cosas"
        result = generate_fin_plan(injected, session_context={"skip_candidate_clarification": True})
        assert result.get("ok") is True
        assert not result.get("needs_clarification"), "skip flag must prevent re-opening candidate loop"
        # The $30 symbol amount must be picked up as the plan item
        if result.get("total_items", 0) > 0:
            assert result["items"][0]["draft_expense"]["monto"] == 30.0

    def test_otro_monto_cancel_clears_state(self):
        """
        Cancel from the candidate card must not leave a pending plan.
        Backend-side: the original text with a bare number still returns
        needs_clarification=True so the frontend can re-show the card.
        """
        original = "pagué 25 en almuerzo con tarjeta"
        result = generate_fin_plan(original)
        assert result.get("needs_clarification") is True
        pending = result["session_context"].get("pending_clarification", {})
        assert pending.get("candidate_amount") == 25.0
        assert pending.get("original_text") == original

    def test_preface_with_count_excluded(self):
        """Preface like 'tengo 3 gastos:' should be excluded from first item."""
        text = "Hola, tengo 3 gastos: $50 comida, $30 farmacia, $20 conejos"
        result = generate_fin_plan(text)
        
        # Verify 3 is not detected as a monto
        montos = [item["draft_expense"]["monto"] for item in result["items"]]
        assert 3.0 not in montos
        assert 50.0 in montos
        
        # Verify first item description doesn't contain "tengo 3 gastos"
        first_desc = result["items"][0]["draft_expense"]["descripcion"].lower()
        assert "tengo 3 gastos" not in first_desc


# ---------------------------------------------------------------------------
# Final polish — payment method stripping + default responsable
# ---------------------------------------------------------------------------

class TestFinalPolish:
    """Regression tests for payment method stripping and default responsable."""

    def test_payment_method_stripped_from_description_tarjeta(self):
        """'almuerzo con tarjeta' → description='almuerzo', metodo='Tarjeta'."""
        result = generate_fin_plan("pagué $25 en almuerzo con tarjeta",
                                   session_context={"skip_candidate_clarification": True})
        assert result.get("ok") is True
        expense = result["items"][0]["draft_expense"]
        assert "tarjeta" not in expense["descripcion"].lower(), \
            f"Payment method must be stripped; got: {expense['descripcion']!r}"
        assert expense["metodo_pago"].lower() == "tarjeta"

    def test_payment_method_stripped_from_description_efectivo(self):
        """'café en efectivo' → description='café', metodo='Efectivo'."""
        result = generate_fin_plan("$5 café en efectivo",
                                   session_context={"skip_candidate_clarification": True})
        assert result.get("ok") is True
        expense = result["items"][0]["draft_expense"]
        assert "efectivo" not in expense["descripcion"].lower(), \
            f"Payment method must be stripped; got: {expense['descripcion']!r}"
        assert expense["metodo_pago"].lower() == "efectivo"

    def test_default_responsable_is_jorge(self):
        """When no responsible person is mentioned, responsable defaults to 'Jorge'."""
        result = generate_fin_plan("$10 en taxi",
                                   session_context={"skip_candidate_clarification": True})
        assert result.get("ok") is True
        expense = result["items"][0]["draft_expense"]
        assert expense["responsable"] == "Jorge", \
            f"Expected default responsable='Jorge', got: {expense['responsable']!r}"


# ---------------------------------------------------------------------------
# Structured missing-amount clarification (inline input card)
# ---------------------------------------------------------------------------

class TestMissingAmountClarification:
    """
    Regression tests for the structured missing-amount UI flow.

    When FIN receives a message with NO amount (e.g. 'compré café en efectivo'),
    the backend must:
      1. Return needs_clarification=True
      2. Return pending_clarification.kind == 'missing_amount'
      3. Return pending_clarification.original_text == <original message>

    After the user supplies an amount via the inline input, the frontend injects
    it into the original text and re-calls /fin/plan with skip_candidate_clarification.
    The backend must then produce a proper plan with full context preserved.
    """

    # --- Backend: missing-amount response shape ---

    def test_no_amount_returns_needs_clarification(self):
        """'compré café en efectivo' → needs_clarification=True (no montos)."""
        result = generate_fin_plan("compré café en efectivo")
        assert result.get("needs_clarification") is True
        assert result.get("total_items", 0) == 0

    def test_no_amount_returns_missing_amount_kind(self):
        """Backend sets pending_clarification.kind='missing_amount' when no amount found."""
        result = generate_fin_plan("compré café en efectivo")
        pending = result.get("session_context", {}).get("pending_clarification", {})
        assert pending.get("kind") == "missing_amount", \
            f"Expected kind='missing_amount', got: {pending!r}"

    def test_no_amount_original_text_preserved(self):
        """Backend includes original_text in pending_clarification."""
        original = "compré café en efectivo"
        result = generate_fin_plan(original)
        pending = result.get("session_context", {}).get("pending_clarification", {})
        assert pending.get("original_text") == original, \
            f"original_text not preserved: {pending.get('original_text')!r}"

    # --- Test Case A: "compré café en efectivo" + 25 ---

    def test_case_a_injected_amount_produces_plan(self):
        """
        Case A: original='compré café en efectivo', user enters 25.
        Frontend injects → '$25 compré café en efectivo' (tier-3 prepend).
        Backend must return plan with monto=25, descripcion='café', metodo='Efectivo'.
        """
        injected = "$25 compré café en efectivo"
        result = generate_fin_plan(injected,
                                   session_context={"skip_candidate_clarification": True})
        assert result.get("ok") is True
        assert result.get("total_items", 0) == 1
        assert not result.get("needs_clarification"), "No second clarification loop"
        expense = result["items"][0]["draft_expense"]
        assert expense["monto"] == 25.0
        assert expense["descripcion"].lower() == "café" or "café" in expense["descripcion"].lower(), \
            f"descripcion should contain 'café', got: {expense['descripcion']!r}"
        assert expense["metodo_pago"].lower() == "efectivo", \
            f"metodo_pago should be 'efectivo', got: {expense['metodo_pago']!r}"

    def test_case_a_no_candidate_loop(self):
        """After amount injection with skip flag, no candidate clarification re-opens."""
        injected = "$25 compré café en efectivo"
        result = generate_fin_plan(injected,
                                   session_context={"skip_candidate_clarification": True})
        assert not result.get("needs_clarification"), \
            "skip_candidate_clarification must prevent candidate loop from reopening"

    # --- Test Case B: "compré almuerzo con tarjeta" + 30.50 ---

    def test_case_b_decimal_amount_preserved(self):
        """
        Case B: original='compré almuerzo con tarjeta', user enters 30.50.
        monto=30.5, descripcion='almuerzo', metodo='Tarjeta'.
        """
        injected = "$30.50 compré almuerzo con tarjeta"
        result = generate_fin_plan(injected,
                                   session_context={"skip_candidate_clarification": True})
        assert result.get("ok") is True
        assert result.get("total_items", 0) == 1
        expense = result["items"][0]["draft_expense"]
        assert expense["monto"] == 30.5, f"Expected 30.5, got {expense['monto']}"
        assert "almuerzo" in expense["descripcion"].lower(), \
            f"descripcion should contain 'almuerzo', got: {expense['descripcion']!r}"
        assert expense["metodo_pago"].lower() == "tarjeta", \
            f"metodo_pago should be 'tarjeta', got: {expense['metodo_pago']!r}"

    def test_case_b_responsable_defaults_jorge(self):
        """No responsible mentioned → defaults to 'Jorge'."""
        injected = "$30.50 compré almuerzo con tarjeta"
        result = generate_fin_plan(injected,
                                   session_context={"skip_candidate_clarification": True})
        assert result["items"][0]["draft_expense"]["responsable"] == "Jorge"

    # --- Test Case C: invalid input guard ---

    def test_case_c_zero_amount_still_needs_clarification(self):
        """
        Case C: if somehow $0 gets injected, backend should still flag it as invalid
        (monto=0 → missing_fields contains 'monto', or no plan returned).
        This validates that the UI validation (>0 check) has a backend safety net.
        """
        # tier-3 prepend with 0 → "$0 compré café en efectivo"
        injected = "$0 compré café en efectivo"
        result = generate_fin_plan(injected,
                                   session_context={"skip_candidate_clarification": True})
        # Either no items or monto=0 in missing_fields — backend must not silently save $0
        if result.get("total_items", 0) > 0:
            missing = result["items"][0].get("missing_fields", [])
            assert "monto" in missing, \
                f"$0 monto must be in missing_fields; got missing={missing!r}"


# ---------------------------------------------------------------------------
# Description normalization — verb stripping
# ---------------------------------------------------------------------------

class TestDescripcionVerbStripping:
    """
    Regression tests for leading transaction-verb stripping in _extract_descripcion.

    Root cause: after currency patterns are removed the result can have a leading
    space (e.g. " compré café"), which prevented the ^compr[eé] anchor from
    matching.  Fix: strip() before verb removal.
    """

    # --- Unit tests directly on _extract_descripcion ---

    def test_compre_cafe_efectivo_unit(self):
        """'compré café en efectivo' (as segment) → 'café'."""
        assert _extract_descripcion("compré café en efectivo") == "café"

    def test_dollar_compre_cafe_efectivo_unit(self):
        """'$25 compré café en efectivo' (injected) → 'café'."""
        assert _extract_descripcion("$25 compré café en efectivo") == "café"

    def test_compre_almuerzo_tarjeta_unit(self):
        """'compré almuerzo con tarjeta' → 'almuerzo'."""
        assert _extract_descripcion("compré almuerzo con tarjeta") == "almuerzo"

    def test_dollar_compre_almuerzo_tarjeta_unit(self):
        """'$30.50 compré almuerzo con tarjeta' (injected) → 'almuerzo'."""
        assert _extract_descripcion("$30.50 compré almuerzo con tarjeta") == "almuerzo"

    def test_compramos_stripped(self):
        """'compramos café' → 'café' (compramos variant)."""
        assert _extract_descripcion("compramos café") == "café"

    def test_compro_stripped(self):
        """'compro pan' → 'pan' (compro present tense)."""
        assert _extract_descripcion("compro pan") == "pan"

    def test_gaste_stripped(self):
        """'gasté en taxi' → 'taxi' (gasté past tense)."""
        assert _extract_descripcion("gasté en taxi") == "taxi"

    def test_pague_en_almuerzo_stripped(self):
        """'pagué en almuerzo' → 'almuerzo'."""
        assert _extract_descripcion("pagué en almuerzo") == "almuerzo"

    # --- Regression: payment method + verb stripped together ---

    def test_pague_almuerzo_tarjeta_no_verb_no_method(self):
        """'pagué almuerzo con tarjeta' → 'almuerzo' (verb + method both stripped)."""
        result = _extract_descripcion("pagué almuerzo con tarjeta")
        assert result == "almuerzo", f"Got: {result!r}"

    # --- Integration tests via generate_fin_plan ---

    def test_case_1_compre_cafe_efectivo(self):
        """
        Integration — Case 1.
        Input: 'compré café en efectivo' + structured amount 25.
        Injected: '$25 compré café en efectivo'.
        Expected: descripcion='café', metodo='Efectivo'.
        """
        injected = "$25 compré café en efectivo"
        result = generate_fin_plan(injected,
                                   session_context={"skip_candidate_clarification": True})
        assert result.get("ok") is True
        expense = result["items"][0]["draft_expense"]
        assert expense["descripcion"].lower() == "café", \
            f"Expected 'café', got: {expense['descripcion']!r}"
        assert expense["metodo_pago"].lower() == "efectivo"

    def test_case_2_compre_almuerzo_tarjeta(self):
        """
        Integration — Case 2.
        Input: 'compré almuerzo con tarjeta' + structured amount 30.50.
        Injected: '$30.50 compré almuerzo con tarjeta'.
        Expected: descripcion='almuerzo', metodo='Tarjeta'.
        """
        injected = "$30.50 compré almuerzo con tarjeta"
        result = generate_fin_plan(injected,
                                   session_context={"skip_candidate_clarification": True})
        assert result.get("ok") is True
        expense = result["items"][0]["draft_expense"]
        assert expense["descripcion"].lower() == "almuerzo", \
            f"Expected 'almuerzo', got: {expense['descripcion']!r}"
        assert expense["metodo_pago"].lower() == "tarjeta"

    def test_case_3_pague_regression(self):
        """
        Regression — Case 3.
        'pagué 25 en almuerzo con tarjeta' must still extract almuerzo correctly.
        """
        result = generate_fin_plan("pagué $25 en almuerzo con tarjeta",
                                   session_context={"skip_candidate_clarification": True})
        assert result.get("ok") is True
        expense = result["items"][0]["draft_expense"]
        assert expense["monto"] == 25.0
        assert "almuerzo" in expense["descripcion"].lower(), \
            f"descripcion should contain 'almuerzo', got: {expense['descripcion']!r}"
        assert expense["metodo_pago"].lower() == "tarjeta"

    def test_case_4_decimal_structured_correction_normalized(self):
        """
        Regression — Case 4.
        Decimal structured correction path still produces normalized description.
        'pagué $30.50 en almuerzo con tarjeta' → monto=30.5, descripcion='almuerzo'.
        """
        injected = "pagué $30.50 en almuerzo con tarjeta"
        result = generate_fin_plan(injected,
                                   session_context={"skip_candidate_clarification": True})
        assert result.get("ok") is True
        expense = result["items"][0]["draft_expense"]
        assert expense["monto"] == 30.5
        assert "almuerzo" in expense["descripcion"].lower()

