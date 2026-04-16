import unittest


class TestOperatorAuth(unittest.TestCase):
    def setUp(self):
        from assistant_os.mso.operator_identity import reset_operator_registry

        reset_operator_registry()

    def test_viewer_can_read(self):
        from assistant_os.mso.operator_auth import authorize_operator_read

        operator = authorize_operator_read("ops-viewer")
        self.assertEqual(operator.role, "viewer")
        self.assertTrue(operator.last_used_at)

    def test_reviewer_can_acknowledge(self):
        from assistant_os.mso.operator_auth import authorize_operator_action

        operator = authorize_operator_action("ops-reviewer", "acknowledge_restriction")
        self.assertEqual(operator.role, "reviewer")

    def test_viewer_cannot_clear(self):
        from assistant_os.mso.operator_auth import OperatorAuthorizationError, authorize_operator_action

        with self.assertRaises(OperatorAuthorizationError):
            authorize_operator_action("ops-viewer", "clear_restriction")

    def test_inactive_operator_is_denied(self):
        from assistant_os.mso.operator_auth import OperatorAuthorizationError, authorize_operator_read
        from assistant_os.mso.operator_identity import set_operator_active

        set_operator_active("ops-admin", is_active=False)
        with self.assertRaises(OperatorAuthorizationError):
            authorize_operator_read("ops-admin")

    def test_unknown_operator_is_denied(self):
        from assistant_os.mso.operator_auth import OperatorAuthorizationError, authorize_operator_read

        with self.assertRaises(OperatorAuthorizationError):
            authorize_operator_read("missing-operator")


if __name__ == "__main__":
    unittest.main()
