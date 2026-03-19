"""
Tests for Pending Resolver functionality.

These tests verify the heuristic follow-up parsing in the UI.
Since parseFollowUp is a JavaScript function, we test the regex patterns
that should match using Python equivalents.

Manual Test Scenarios:
T1: input FIN → aparece card → sin confirmar: "ana y conejos separados" 
    → debe seguir en FIN y actualizar el plan o pedir precisión.
T2: con pending: "cancelar" → cerrar pending, no commit.
T3: con pending: "confirmar" → commit de items del plan, luego clear pending.
T4: escape: con pending: "cambiar de tema: …" → clear pending y clasificar normal.
"""

import re
import unittest


# Python equivalents of the JavaScript regex patterns
def parse_follow_up(text: str) -> dict:
    """
    Parse user message as follow-up when there's a pending plan.
    Python equivalent of the JS parseFollowUp function.
    
    Returns: { action: 'CANCEL'|'CONFIRM'|'EDIT_SPLIT'|'ESCAPE'|'UNKNOWN', data: any }
    """
    lower = text.lower().strip()
    
    # CANCEL patterns
    if re.match(r'^(cancelar|cancela|olvida|borra todo|descartar|olv[ií]dalo|no|nope)$', lower, re.IGNORECASE):
        return {'action': 'CANCEL', 'data': None}
    
    # CONFIRM patterns
    if re.match(r'^(confirmar|confirmo|ok|s[ií]|si|yes|dale|guardar|listo|confirma)$', lower, re.IGNORECASE):
        return {'action': 'CONFIRM', 'data': None}
    
    # ESCAPE patterns (explicit topic change)
    if re.match(r'^(cambiar de tema|nuevo tema|olvida eso|otra cosa|cambio de tema)', lower, re.IGNORECASE):
        return {'action': 'ESCAPE', 'data': None}
    
    # EDIT_SPLIT patterns: "separa X y Y", "X y Y separados", "ana y conejos separados"
    split_match = re.match(r'sep[aá]ra?r?\s+(.+?)\s+y\s+(.+)', lower, re.IGNORECASE) or \
                  re.match(r'(.+?)\s+y\s+(.+?)\s+sep[aá]rad[oa]s?', lower, re.IGNORECASE)
    if split_match:
        return {'action': 'EDIT_SPLIT', 'data': {'entity1': split_match.group(1).strip(), 'entity2': split_match.group(2).strip()}}
    
    # CLARIFY_AMOUNT patterns: "era $15", "fueron $30", "eran 15$", "$X" anywhere
    has_money = bool(re.search(r'\$\s*\d+|\d+\s*\$|b/\.?\s*\d+|\d+\s*d[oó]lare?s?', text, re.IGNORECASE))
    clarify_start = bool(re.match(r'^(era|eran|fueron?|fue|el monto (fue|era)|no[\s,]+|s[ií][\s,]+)', lower, re.IGNORECASE))
    
    if has_money or clarify_start:
        amounts = []
        patterns = [
            r'\$\s*(\d+(?:[.,]\d{1,2})?)',
            r'(\d+(?:[.,]\d{1,2})?)\s*\$',
            r'b/\.?\s*(\d+(?:[.,]\d{1,2})?)',
            r'(\d+(?:[.,]\d{1,2})?)\s*d[oó]lare?s?'
        ]
        for pat in patterns:
            for m in re.finditer(pat, text, re.IGNORECASE):
                amounts.append(float(m.group(1).replace(',', '.')))
        
        if amounts:
            return {'action': 'CLARIFY_AMOUNT', 'data': {'amounts': amounts, 'originalText': text}}
    
    # UNKNOWN - could still be a clarification or edit
    return {'action': 'UNKNOWN', 'data': {'text': text}}


class TestParseFollowUp(unittest.TestCase):
    """Test the parseFollowUp heuristic patterns."""
    
    # -------------------------------------------------------------------------
    # CANCEL patterns
    # -------------------------------------------------------------------------
    
    def test_cancel_cancelar(self):
        result = parse_follow_up("cancelar")
        self.assertEqual(result['action'], 'CANCEL')
    
    def test_cancel_cancela(self):
        result = parse_follow_up("cancela")
        self.assertEqual(result['action'], 'CANCEL')
    
    def test_cancel_olvida(self):
        result = parse_follow_up("olvida")
        self.assertEqual(result['action'], 'CANCEL')
    
    def test_cancel_borra_todo(self):
        result = parse_follow_up("borra todo")
        self.assertEqual(result['action'], 'CANCEL')
    
    def test_cancel_descartar(self):
        result = parse_follow_up("descartar")
        self.assertEqual(result['action'], 'CANCEL')
    
    def test_cancel_no(self):
        result = parse_follow_up("no")
        self.assertEqual(result['action'], 'CANCEL')
    
    def test_cancel_nope(self):
        result = parse_follow_up("nope")
        self.assertEqual(result['action'], 'CANCEL')
    
    def test_cancel_case_insensitive(self):
        result = parse_follow_up("CANCELAR")
        self.assertEqual(result['action'], 'CANCEL')
    
    # -------------------------------------------------------------------------
    # CONFIRM patterns
    # -------------------------------------------------------------------------
    
    def test_confirm_confirmar(self):
        result = parse_follow_up("confirmar")
        self.assertEqual(result['action'], 'CONFIRM')
    
    def test_confirm_confirmo(self):
        result = parse_follow_up("confirmo")
        self.assertEqual(result['action'], 'CONFIRM')
    
    def test_confirm_ok(self):
        result = parse_follow_up("ok")
        self.assertEqual(result['action'], 'CONFIRM')
    
    def test_confirm_si(self):
        result = parse_follow_up("sí")
        self.assertEqual(result['action'], 'CONFIRM')
    
    def test_confirm_si_no_accent(self):
        result = parse_follow_up("si")
        self.assertEqual(result['action'], 'CONFIRM')
    
    def test_confirm_yes(self):
        result = parse_follow_up("yes")
        self.assertEqual(result['action'], 'CONFIRM')
    
    def test_confirm_dale(self):
        result = parse_follow_up("dale")
        self.assertEqual(result['action'], 'CONFIRM')
    
    def test_confirm_guardar(self):
        result = parse_follow_up("guardar")
        self.assertEqual(result['action'], 'CONFIRM')
    
    def test_confirm_listo(self):
        result = parse_follow_up("listo")
        self.assertEqual(result['action'], 'CONFIRM')
    
    def test_confirm_confirma(self):
        result = parse_follow_up("confirma")
        self.assertEqual(result['action'], 'CONFIRM')
    
    # -------------------------------------------------------------------------
    # ESCAPE patterns
    # -------------------------------------------------------------------------
    
    def test_escape_cambiar_de_tema(self):
        result = parse_follow_up("cambiar de tema")
        self.assertEqual(result['action'], 'ESCAPE')
    
    def test_escape_nuevo_tema(self):
        result = parse_follow_up("nuevo tema")
        self.assertEqual(result['action'], 'ESCAPE')
    
    def test_escape_olvida_eso(self):
        result = parse_follow_up("olvida eso")
        self.assertEqual(result['action'], 'ESCAPE')
    
    def test_escape_otra_cosa(self):
        result = parse_follow_up("otra cosa")
        self.assertEqual(result['action'], 'ESCAPE')
    
    def test_escape_with_continuation(self):
        """Escape should work even with text after the escape phrase."""
        result = parse_follow_up("cambiar de tema: nueva pregunta")
        self.assertEqual(result['action'], 'ESCAPE')
    
    # -------------------------------------------------------------------------
    # EDIT_SPLIT patterns
    # -------------------------------------------------------------------------
    
    def test_edit_split_separa_x_y_y(self):
        result = parse_follow_up("separa ana y conejos")
        self.assertEqual(result['action'], 'EDIT_SPLIT')
        self.assertEqual(result['data']['entity1'], 'ana')
        self.assertEqual(result['data']['entity2'], 'conejos')
    
    def test_edit_split_x_y_y_separados(self):
        result = parse_follow_up("ana y conejos separados")
        self.assertEqual(result['action'], 'EDIT_SPLIT')
        self.assertEqual(result['data']['entity1'], 'ana')
        self.assertEqual(result['data']['entity2'], 'conejos')
    
    def test_edit_split_separar_form(self):
        result = parse_follow_up("separar jorge y ana")
        self.assertEqual(result['action'], 'EDIT_SPLIT')
        self.assertEqual(result['data']['entity1'], 'jorge')
        self.assertEqual(result['data']['entity2'], 'ana')
    
    def test_edit_split_separa_accent(self):
        """Spanish accent in 'separá' - variant form."""
        # Note: "separá" without final "r" may not match, but "separa" should
        result = parse_follow_up("separa hogar y proyectos")
        self.assertEqual(result['action'], 'EDIT_SPLIT')
    
    def test_edit_split_separadas(self):
        result = parse_follow_up("comida y ropa separadas")
        self.assertEqual(result['action'], 'EDIT_SPLIT')
    
    # -------------------------------------------------------------------------
    # CLARIFY_AMOUNT patterns
    # -------------------------------------------------------------------------
    
    def test_clarify_era_15_dollars(self):
        """'era $15' should be CLARIFY_AMOUNT."""
        result = parse_follow_up("era $15")
        self.assertEqual(result['action'], 'CLARIFY_AMOUNT')
        self.assertIn(15.0, result['data']['amounts'])
    
    def test_clarify_fueron_30_y_15(self):
        """'fueron $30 y $15' should be CLARIFY_AMOUNT with both amounts."""
        result = parse_follow_up("fueron $30 y $15")
        self.assertEqual(result['action'], 'CLARIFY_AMOUNT')
        self.assertIn(30.0, result['data']['amounts'])
        self.assertIn(15.0, result['data']['amounts'])
    
    def test_clarify_bare_dollar_amount(self):
        """'$15' alone should be CLARIFY_AMOUNT."""
        result = parse_follow_up("$15")
        self.assertEqual(result['action'], 'CLARIFY_AMOUNT')
        self.assertIn(15.0, result['data']['amounts'])
    
    def test_clarify_no_el_monto(self):
        """'no, el monto fue $20' should be CLARIFY_AMOUNT."""
        result = parse_follow_up("no, el monto fue $20")
        self.assertEqual(result['action'], 'CLARIFY_AMOUNT')
        self.assertIn(20.0, result['data']['amounts'])
    
    def test_clarify_mcdonalds_was_18(self):
        """'mcdonalds era $18' should be CLARIFY_AMOUNT."""
        result = parse_follow_up("mcdonalds era $18")
        self.assertEqual(result['action'], 'CLARIFY_AMOUNT')
        self.assertIn(18.0, result['data']['amounts'])
    
    # -------------------------------------------------------------------------
    # UNKNOWN patterns (should not match others)
    # -------------------------------------------------------------------------
    
    def test_unknown_random_text(self):
        result = parse_follow_up("cualquier otra cosa")
        self.assertEqual(result['action'], 'UNKNOWN')
        self.assertEqual(result['data']['text'], 'cualquier otra cosa')
    
    def test_unknown_partial_cancel(self):
        """'cancelar algo' is not a simple cancel."""
        result = parse_follow_up("cancelar algo más")
        self.assertEqual(result['action'], 'UNKNOWN')
    
    def test_unknown_partial_confirm(self):
        """'si pero...' is not a simple confirm - but 'si' followed by amounts is clarify."""
        result = parse_follow_up("si pero cambia el monto")
        self.assertEqual(result['action'], 'UNKNOWN')
    
    def test_new_expense_is_clarify(self):
        """A new expense with $ is detected as CLARIFY_AMOUNT when pending.
        
        Note: This is intentional - when there's a pending plan and user sends 
        a message with amounts, it's treated as clarification. The handler 
        will re-process it appropriately.
        """
        result = parse_follow_up("Gasté $50 en comida")
        self.assertEqual(result['action'], 'CLARIFY_AMOUNT')
        self.assertIn(50.0, result['data']['amounts'])


class TestPendingResolverIntegration(unittest.TestCase):
    """
    Integration test scenarios for Pending Resolver.
    These are documented for manual testing.
    """
    
    def test_scenario_t1_documented(self):
        """
        T1: input FIN → aparece card → sin confirmar: "ana y conejos separados"
            → debe seguir en FIN y actualizar el plan o pedir precisión.
        
        Manual test steps:
        1. Send: "$50 comida y $30 conejos"
        2. Wait for plan card to appear with 2 items
        3. Without clicking confirm, send: "ana y conejos separados"
        4. Expected: Responsables should update or clarification message appears
        5. Plan should still be pending (no commit happened)
        """
        # This is an EDIT_SPLIT action
        result = parse_follow_up("ana y conejos separados")
        self.assertEqual(result['action'], 'EDIT_SPLIT')
    
    def test_scenario_t2_documented(self):
        """
        T2: con pending: "cancelar" → cerrar pending, no commit.
        
        Manual test steps:
        1. Send: "$50 comida"
        2. Wait for plan card to appear
        3. Send: "cancelar"
        4. Expected: Plan card removed, "Plan cancelado" message
        5. No commit to Sheets
        """
        result = parse_follow_up("cancelar")
        self.assertEqual(result['action'], 'CANCEL')
    
    def test_scenario_t3_documented(self):
        """
        T3: con pending: "confirmar" → commit de items del plan, luego clear pending.
        
        Manual test steps:
        1. Send: "$50 comida"
        2. Wait for plan card to appear
        3. Send: "confirmar"
        4. Expected: saveAllExpenses() called, items committed to Sheets
        5. pendingPlan cleared
        """
        result = parse_follow_up("confirmar")
        self.assertEqual(result['action'], 'CONFIRM')
    
    def test_scenario_t4_documented(self):
        """
        T4: escape: con pending: "cambiar de tema: …" → clear pending y clasificar normal.
        
        Manual test steps:
        1. Send: "$50 comida"
        2. Wait for plan card to appear
        3. Send: "cambiar de tema: qué hay para almorzar?"
        4. Expected: Plan discarded, proceeds to classify the new message
        """
        result = parse_follow_up("cambiar de tema: qué hay para almorzar?")
        self.assertEqual(result['action'], 'ESCAPE')


if __name__ == '__main__':
    unittest.main()
