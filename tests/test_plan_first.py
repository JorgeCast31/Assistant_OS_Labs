"""
Tests for Plan-first architecture.

Plan-first flow:
1. Interpreter: text → Plan (no side effects)
2. Confirm: If requires_confirmation, return plan for approval
3. Execute (Kernel): Plan → side effects

Tests:
1. "estado sobre tareas de consultoria" → WORK_QUERY with filters.project="Consultoría"
2. "tareas eiProta?" → WORK_QUERY with filters.project="eiProta" or key="eiprota"
3. Plan has correct fields
4. should_auto_execute() works correctly
5. Override table triggers WORK_QUERY for "tareas" patterns
"""
import unittest

from assistant_os.contracts import (
    Plan, make_plan, should_auto_execute,
    ACTION_WORK_QUERY, ACTION_WORK_CREATE, ACTION_FIN_EXPENSE, ACTION_COMMAND,
    RISK_LOW, RISK_MEDIUM, RISK_HIGH,
)
from assistant_os.classifier import (
    parse_work_query_filters,
    classify_text,
)
from assistant_os.contracts import ClassifyRequest


class TestPlanDataclass(unittest.TestCase):
    """Tests for the Plan dataclass and helpers."""

    def test_make_plan_creates_valid_plan(self):
        """make_plan() creates a Plan with required fields."""
        plan = make_plan(
            domain="WORK",
            action=ACTION_WORK_QUERY,
            target="Consultar tareas",
        )
        
        self.assertEqual(plan["domain"], "WORK")
        self.assertEqual(plan["action"], ACTION_WORK_QUERY)
        self.assertEqual(plan["target"], "Consultar tareas")
        self.assertIn("idempotency_key", plan)
        self.assertIn("trace_id", plan)
        self.assertEqual(plan["risk_level"], RISK_MEDIUM)  # Default
        self.assertEqual(plan["requires_confirmation"], False)  # Default

    def test_make_plan_with_custom_fields(self):
        """make_plan() accepts custom field values."""
        plan = make_plan(
            domain="FIN",
            action=ACTION_FIN_EXPENSE,
            target="Registrar gasto",
            requires_confirmation=True,
            risk_level=RISK_HIGH,
            filters={"amount": 100},
            preview="Registrar $100 en gasolina",
        )
        
        self.assertEqual(plan["domain"], "FIN")
        self.assertEqual(plan["action"], ACTION_FIN_EXPENSE)
        self.assertEqual(plan["requires_confirmation"], True)
        self.assertEqual(plan["risk_level"], RISK_HIGH)
        self.assertEqual(plan["filters"]["amount"], 100)
        self.assertEqual(plan["preview"], "Registrar $100 en gasolina")


class TestShouldAutoExecute(unittest.TestCase):
    """Tests for should_auto_execute() logic."""

    def test_work_query_low_risk_auto_executes(self):
        """WORK_QUERY with risk_level=low should auto-execute."""
        plan = make_plan(
            domain="WORK",
            action=ACTION_WORK_QUERY,
            target="Consultar tareas",
            risk_level=RISK_LOW,
            requires_confirmation=False,
        )
        
        self.assertTrue(should_auto_execute(plan))

    def test_work_query_with_confirmation_does_not_auto_execute(self):
        """WORK_QUERY with requires_confirmation=True should not auto-execute."""
        plan = make_plan(
            domain="WORK",
            action=ACTION_WORK_QUERY,
            target="Consultar tareas",
            risk_level=RISK_LOW,
            requires_confirmation=True,
        )
        
        self.assertFalse(should_auto_execute(plan))

    def test_fin_expense_medium_risk_auto_executes(self):
        """
        M0.6: FIN_EXPENSE with risk_level=medium DOES auto-execute.

        _create_plan_from_intent sets requires_confirmation=False for FIN_EXPENSE
        ("Single expense auto-executes"). The whitelist was updated in M0.6 to
        reflect this design intent. This test validates the corrected behavior.
        """
        plan = make_plan(
            domain="FIN",
            action=ACTION_FIN_EXPENSE,
            target="Registrar gasto",
            risk_level=RISK_MEDIUM,
            requires_confirmation=False,
        )

        self.assertTrue(should_auto_execute(plan))

    def test_unlisted_low_risk_action_does_not_auto_execute(self):
        """
        Low risk does NOT auto-execute unless (action, risk_level) is in the
        explicit whitelist.  ACTION_COMMAND / RISK_LOW is not whitelisted,
        so it must require confirmation.
        """
        plan = make_plan(
            domain="WORK",
            action=ACTION_COMMAND,
            target="Algo",
            risk_level=RISK_LOW,
            requires_confirmation=False,
        )

        self.assertFalse(should_auto_execute(plan))


class TestConsultoriaRoutingRegression(unittest.TestCase):
    """Regression tests for consultoria/consultoría routing."""

    def test_estado_sobre_tareas_de_consultoria_routes_to_work_query(self):
        """
        REGRESSION: 'estado sobre tareas de consultoria' should:
        1. Route to WORK_QUERY (not ENERGY or other domain)
        2. Have filters.project = "Consultoría"
        """
        text = "estado sobre tareas de consultoria"
        
        filters = parse_work_query_filters(text)
        
        # Should have project filter with correct value
        self.assertIn("project", filters)
        self.assertEqual(filters["project"], "Consultoría")

    def test_tareas_consultoria_simple(self):
        """'tareas consultoria' should parse filters correctly."""
        text = "tareas consultoria"
        
        filters = parse_work_query_filters(text)
        
        self.assertIn("project", filters)
        self.assertEqual(filters["project"], "Consultoría")


class TestEiProtaRouting(unittest.TestCase):
    """Tests for eiProta project routing."""

    def test_tareas_eiprota_routes_correctly(self):
        """
        'tareas eiProta?' should route to WORK_QUERY with eiProta filter.
        
        Since 'eiprota' maps to key type, filters should have project_key.
        """
        text = "tareas eiProta?"
        
        filters = parse_work_query_filters(text)
        
        # Should have either project_key or project filter
        has_eiprota_filter = (
            filters.get("project_key") == "eiprota" or
            filters.get("project") == "eiProta"
        )
        self.assertTrue(has_eiprota_filter, 
                        f"Expected eiProta filter, got: {filters}")

    def test_tareas_eiprota_with_space(self):
        """'tareas ei prota' (with space) should also work."""
        text = "tareas ei prota"
        
        filters = parse_work_query_filters(text)
        
        # "ei prota" maps to ("project", "eiProta") in ALIAS_MAP
        has_eiprota_filter = (
            filters.get("project") == "eiProta" or
            filters.get("project_key") == "eiprota"
        )
        self.assertTrue(has_eiprota_filter,
                        f"Expected eiProta filter, got: {filters}")


class TestOverrideTable(unittest.TestCase):
    """Tests for deterministic routing override table."""

    def test_tareas_pattern_detected(self):
        """'tareas' keyword should trigger WORK_QUERY intent."""
        from assistant_os.classifier import is_work_query
        
        texts = [
            "tareas",
            "tareas pendientes",
            "estado sobre tareas",
            "qué tareas tengo",
            "cuáles son mis tareas",
        ]
        
        for text in texts:
            with self.subTest(text=text):
                self.assertTrue(is_work_query(text), 
                                f"'{text}' should be detected as work query")

    def test_pendientes_pattern_detected(self):
        """'pendientes' keyword should trigger WORK_QUERY."""
        from assistant_os.classifier import is_work_query
        
        self.assertTrue(is_work_query("pendientes"))
        self.assertTrue(is_work_query("qué hay pendiente"))


class TestWorkCreateRouting(unittest.TestCase):
    """
    Tests for WORK_CREATE action routing and parsing.
    
    Requirements:
    - "Crea una tarea…" => plan.action == WORK_CREATE, requires_confirmation == True
    - Preview includes title + project
    - "tareas de consultoria?" => still WORK_QUERY
    - "estado sobre tareas de consultoria" => WORK_QUERY with project=Consultoría
    """

    def test_crea_tarea_routes_to_work_create(self):
        """'Crea una tarea...' should route to WORK_CREATE action."""
        from assistant_os.webhook_server import _has_create_intent, _create_plan_from_intent
        from assistant_os.contracts import ACTION_WORK_CREATE
        
        text = "Crea una tarea para llamar al banco"
        
        # Test has_create_intent
        self.assertTrue(_has_create_intent(text))
        
        # Create plan via classification
        req: ClassifyRequest = {"text": text}
        intent = classify_text(req)
        plan = _create_plan_from_intent(text, intent)
        
        self.assertEqual(plan["action"], ACTION_WORK_CREATE)
        self.assertTrue(plan["requires_confirmation"])

    def test_anade_tarea_routes_to_work_create(self):
        """'Añade tarea...' should route to WORK_CREATE action."""
        from assistant_os.webhook_server import _has_create_intent
        from assistant_os.contracts import ACTION_WORK_CREATE
        
        texts = [
            "Añade tarea de revisar informe",
            "Agrega una tarea nueva",
            "Registrar tarea: reunión cliente",
            "Nueva tarea para mañana",
        ]
        
        for text in texts:
            with self.subTest(text=text):
                self.assertTrue(_has_create_intent(text), 
                               f"'{text}' should be detected as create intent")

    def test_tareas_de_consultoria_still_routes_to_work_query(self):
        """'tareas de consultoria?' should still route to WORK_QUERY."""
        from assistant_os.webhook_server import _has_create_intent, _create_plan_from_intent
        
        text = "tareas de consultoria?"
        
        # Should NOT have create intent
        self.assertFalse(_has_create_intent(text))
        
        # Should route to WORK_QUERY
        req: ClassifyRequest = {"text": text}
        intent = classify_text(req)
        plan = _create_plan_from_intent(text, intent)
        
        self.assertEqual(plan["action"], ACTION_WORK_QUERY)
        self.assertFalse(plan["requires_confirmation"])

    def test_estado_sobre_tareas_routes_to_work_query_with_filter(self):
        """'estado sobre tareas de consultoria' should route to WORK_QUERY with project filter."""
        from assistant_os.webhook_server import _has_create_intent, _create_plan_from_intent
        
        text = "estado sobre tareas de consultoria"
        
        # Should NOT have create intent
        self.assertFalse(_has_create_intent(text))
        
        # Should route to WORK_QUERY with project filter
        req: ClassifyRequest = {"text": text}
        intent = classify_text(req)
        plan = _create_plan_from_intent(text, intent)
        
        self.assertEqual(plan["action"], ACTION_WORK_QUERY)
        self.assertIn("project", plan.get("filters", {}))
        # Check for "consul" prefix to handle accent variations
        project = plan["filters"].get("project", "").lower()
        self.assertTrue(project.startswith("consul"), 
                       f"Expected project to start with 'consul', got '{project}'")

    def test_work_create_plan_has_title_in_filters(self):
        """WORK_CREATE plan should have title in filters from parsed text."""
        from assistant_os.webhook_server import _create_plan_from_intent
        from assistant_os.contracts import ACTION_WORK_CREATE
        
        text = "Crea una tarea de revisar el informe trimestral"
        
        req: ClassifyRequest = {"text": text}
        intent = classify_text(req)
        plan = _create_plan_from_intent(text, intent)
        
        self.assertEqual(plan["action"], ACTION_WORK_CREATE)
        self.assertIn("title", plan.get("filters", {}))
        self.assertIn("informe", plan["filters"]["title"].lower())

    def test_work_create_preview_includes_title(self):
        """WORK_CREATE plan preview should include task title."""
        from assistant_os.webhook_server import _create_plan_from_intent
        from assistant_os.contracts import ACTION_WORK_CREATE
        
        text = "Crea una tarea de llamar al banco\nProyecto: Consultoría"
        
        req: ClassifyRequest = {"text": text}
        intent = classify_text(req)
        plan = _create_plan_from_intent(text, intent)
        
        self.assertEqual(plan["action"], ACTION_WORK_CREATE)
        # Preview should contain "Crear tarea:"
        self.assertIn("Crear tarea:", plan.get("preview", ""))


class TestParseWorkCreateFields(unittest.TestCase):
    """Tests for parse_work_create_fields function."""

    def test_parse_simple_title(self):
        """Parse simple task creation text."""
        from assistant_os.webhook_server import parse_work_create_fields
        
        text = "Crea una tarea de llamar al banco"
        fields = parse_work_create_fields(text)
        
        self.assertEqual(fields["title"], "llamar al banco")
        self.assertEqual(fields["status"], "INBOX")  # Default

    def test_parse_with_project(self):
        """Parse task with project field."""
        from assistant_os.webhook_server import parse_work_create_fields
        
        text = "Crea una tarea de revisar informe\nProyecto: Consultoría"
        fields = parse_work_create_fields(text)
        
        self.assertEqual(fields["title"], "revisar informe")
        self.assertEqual(fields["project"], "Consultoría")

    def test_parse_with_load_priority(self):
        """Parse task with load/priority field (maps to Carga)."""
        from assistant_os.webhook_server import parse_work_create_fields
        
        text = "Nueva tarea: completar documentación\nCarga: Alta"
        fields = parse_work_create_fields(text)
        
        self.assertEqual(fields["load"], "Alta")

    def test_parse_with_due_date(self):
        """Parse task with due date."""
        from assistant_os.webhook_server import parse_work_create_fields
        
        text = "Crea una tarea para mañana\nDue: 2026-03-04"
        fields = parse_work_create_fields(text)
        
        self.assertEqual(fields["due"], "2026-03-04")

    def test_parse_null_due(self):
        """Parse task with null due date."""
        from assistant_os.webhook_server import parse_work_create_fields
        
        text = "Crea una tarea\nDue: null"
        fields = parse_work_create_fields(text)
        
        self.assertIsNone(fields["due"])

    def test_parse_single_line_period_separated(self):
        """Parse single-line format with period-separated fields."""
        from assistant_os.webhook_server import parse_work_create_fields
        
        text = "Crea una tarea en WORK: Título: Implementación de recordatorios y atención familiar. Proyecto: Vínculos personales. Status: INBOX. Prioridad: P3. Carga cognitiva: Media. Due: null."
        fields = parse_work_create_fields(text)
        
        self.assertEqual(fields["title"], "Implementación de recordatorios y atención familiar")
        self.assertEqual(fields["project"], "Vínculos personales")
        self.assertEqual(fields["status"], "INBOX")
        self.assertEqual(fields["priority"], "P3")
        self.assertEqual(fields["load"], "Media")
        self.assertIsNone(fields["due"])

    def test_work_create_full_plan_generation(self):
        """Full plan generation for WORK_CREATE with all fields."""
        from assistant_os.webhook_server import _create_plan_from_intent
        
        text = "Crea una tarea en WORK: Título: Implementación de recordatorios y atención familiar. Proyecto: Vínculos personales. Status: INBOX. Prioridad: P3. Carga cognitiva: Media. Due: null."
        
        req: ClassifyRequest = {"text": text}
        intent = classify_text(req)
        plan = _create_plan_from_intent(text, intent)
        
        # Verify action and confirmation
        self.assertEqual(plan["action"], ACTION_WORK_CREATE)
        self.assertTrue(plan["requires_confirmation"])
        self.assertNotEqual(plan["risk_level"], "low")
        
        # Verify preview includes title
        self.assertIn("Implementación de recordatorios", plan.get("preview", ""))
        self.assertIn("Vínculos personales", plan.get("preview", ""))
        
        # Verify filters contain parsed fields
        filters = plan.get("filters", {})
        self.assertEqual(filters.get("title"), "Implementación de recordatorios y atención familiar")
        self.assertEqual(filters.get("project"), "Vínculos personales")


class TestRoutingOverrideRegression(unittest.TestCase):
    """
    Regression tests for routing override bug.
    
    Bug: _apply_routing_overrides was applying WORK_QUERY override even when
    the text contains creation verbs (crea, añade, agrega, etc.).
    
    Root cause: Override table pattern "tareas?" matched without considering
    creation verbs first.
    
    Fix: Rule 0 (HIGHEST PRIORITY) checks for creation intent BEFORE
    checking WORK_QUERY patterns.
    """

    def test_tareas_de_consultoria_routes_to_work_query(self):
        """'tareas de consultoria' => WORK_QUERY."""
        from assistant_os.webhook_server import _create_plan_from_intent
        
        text = "tareas de consultoria"
        plan = _create_plan_from_intent(text, {})
        
        self.assertEqual(plan["action"], ACTION_WORK_QUERY)
        self.assertFalse(plan["requires_confirmation"])

    def test_estado_sobre_tareas_with_project_filter(self):
        """'estado sobre tareas de consultoría' => WORK_QUERY + project=Consultoría."""
        from assistant_os.webhook_server import _create_plan_from_intent
        
        text = "estado sobre tareas de consultoría"
        plan = _create_plan_from_intent(text, {})
        
        self.assertEqual(plan["action"], ACTION_WORK_QUERY)
        filters = plan.get("filters", {})
        project = filters.get("project", "").lower()
        self.assertTrue(project.startswith("consul"),
                       f"Expected project filter to start with 'consul', got '{project}'")

    def test_crea_tarea_full_format_routes_to_work_create(self):
        """
        Full format 'Crea una tarea en WORK: Título: ... Proyecto: ... Status: ...'
        => WORK_CREATE + requires_confirmation=True + correct fields.
        
        This is the exact regression case from the bug report.
        """
        from assistant_os.webhook_server import _create_plan_from_intent
        
        text = "Crea una tarea en WORK: Título: Test. Proyecto: X. Status: INBOX. Prioridad: P3. Carga cognitiva: Media. Due: null."
        plan = _create_plan_from_intent(text, {})
        
        # Must be WORK_CREATE (NOT WORK_QUERY)
        self.assertEqual(plan["action"], ACTION_WORK_CREATE,
                        "Bug: routing override should NOT apply WORK_QUERY when creation verb is present")
        self.assertTrue(plan["requires_confirmation"],
                       "WORK_CREATE must require confirmation")
        
        # Verify fields are correctly parsed
        filters = plan.get("filters", {})
        self.assertEqual(filters.get("title"), "Test")
        self.assertEqual(filters.get("project"), "X")
        self.assertEqual(filters.get("status"), "INBOX")
        self.assertEqual(filters.get("priority"), "P3")
        self.assertEqual(filters.get("load"), "Media")
        self.assertIsNone(filters.get("due"))

    def test_anade_tarea_routes_to_work_create(self):
        """'Añade una tarea: ...' => WORK_CREATE."""
        from assistant_os.webhook_server import _has_create_intent, _create_plan_from_intent
        
        text = "Añade una tarea: Revisar código del proyecto"
        
        # Verify intent detection
        self.assertTrue(_has_create_intent(text),
                       "'Añade' verb must be detected as creation intent")
        
        # Verify plan action
        plan = _create_plan_from_intent(text, {})
        self.assertEqual(plan["action"], ACTION_WORK_CREATE)
        self.assertTrue(plan["requires_confirmation"])

    def test_agrega_tarea_routes_to_work_create(self):
        """'Agrega tarea: ...' => WORK_CREATE."""
        from assistant_os.webhook_server import _has_create_intent, _create_plan_from_intent
        
        text = "Agrega tarea: Enviar informe semanal"
        
        self.assertTrue(_has_create_intent(text))
        plan = _create_plan_from_intent(text, {})
        self.assertEqual(plan["action"], ACTION_WORK_CREATE)

    def test_nueva_tarea_routes_to_work_create(self):
        """'Nueva tarea: ...' => WORK_CREATE."""
        from assistant_os.webhook_server import _has_create_intent, _create_plan_from_intent
        
        text = "Nueva tarea: Llamar al cliente"
        
        self.assertTrue(_has_create_intent(text))
        plan = _create_plan_from_intent(text, {})
        self.assertEqual(plan["action"], ACTION_WORK_CREATE)

    def test_override_priority_create_over_query(self):
        """
        Verify that creation intent (Rule 0) has HIGHER priority than
        generic 'tareas' pattern (Rule 1).
        
        Both patterns match, but WORK_CREATE must win.
        """
        from assistant_os.webhook_server import _apply_routing_overrides, _has_create_intent
        from assistant_os.contracts import ACTION_WORK_CREATE
        
        # This text matches both:
        # - "tareas" pattern (WORK_QUERY)
        # - "Crea" + "tarea" pattern (WORK_CREATE)
        text = "Crea tareas para el proyecto"
        
        # Should detect create intent
        self.assertTrue(_has_create_intent(text))
        
        # Override should return WORK_CREATE (not WORK_QUERY)
        action_override, reason = _apply_routing_overrides(text, {})
        self.assertEqual(action_override, ACTION_WORK_CREATE,
                        "Creation intent must have higher priority than WORK_QUERY override")


if __name__ == "__main__":
    unittest.main()
