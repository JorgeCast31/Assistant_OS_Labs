import io
import json
import unittest
from contextlib import redirect_stdout


class TestTokenLifecycle(unittest.TestCase):
    def setUp(self):
        from assistant_os.mso.operator_identity import reset_operator_registry
        from assistant_os.storage.mso_store import clear_mso_store

        reset_operator_registry()
        clear_mso_store()

    def test_issue_token_returns_raw_once_and_store_keeps_hash(self):
        from assistant_os.control_plane.token_service import issue_operator_token
        from assistant_os.mso.operator_identity import get_operator_token_by_id

        payload = issue_operator_token(
            operator_id="ops-admin",
            ttl_minutes=60,
            issued_reason="test-issue",
        )

        self.assertTrue(payload["token"])
        record = get_operator_token_by_id(payload["token_record"]["token_id"])
        assert record is not None
        self.assertTrue(record.token_hash)
        self.assertNotEqual(record.token_hash, payload["token"])

    def test_token_audit_splits_active_and_revoked(self):
        from assistant_os.control_plane.token_service import issue_operator_token, list_operator_tokens, revoke_operator_token

        issued = issue_operator_token(operator_id="ops-admin", ttl_minutes=60, issued_reason="audit")
        revoke_operator_token(token_id=issued["token_record"]["token_id"], reason="cleanup")
        audit = list_operator_tokens(operator_id="ops-admin")

        self.assertEqual(audit["count"], 1)
        self.assertEqual(len(audit["active_tokens"]), 0)
        self.assertEqual(len(audit["revoked_tokens"]), 1)
        self.assertEqual(audit["revoked_tokens"][0]["token_hash"], "")

    def test_admin_server_cli_can_issue_token_without_starting_webhook(self):
        from assistant_os.control_plane import admin_server

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = admin_server.main(["--issue-token", "--operator-id", "ops-admin", "--ttl-minutes", "30"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["token"])
        self.assertEqual(payload["token_record"]["operator_id"], "ops-admin")


if __name__ == "__main__":
    unittest.main()
