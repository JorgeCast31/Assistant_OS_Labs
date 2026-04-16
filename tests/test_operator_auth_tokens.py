import unittest


class TestOperatorAuthTokens(unittest.TestCase):
    def setUp(self):
        from assistant_os.mso.operator_identity import reset_operator_registry
        from assistant_os.storage.mso_store import clear_mso_store

        reset_operator_registry()
        clear_mso_store()

    def test_valid_token_authenticates_context(self):
        from assistant_os.control_plane.admin_service import mint_operator_token
        from assistant_os.mso.operator_auth import authenticate_operator_token

        token = mint_operator_token(operator_id="ops-admin", ttl_minutes=60)["token"]
        context = authenticate_operator_token(token, request_id="req:test")

        self.assertEqual(context.operator_id, "ops-admin")
        self.assertEqual(context.role, "admin")
        self.assertTrue(context.token_id)
        self.assertEqual(context.request_id, "req:test")

    def test_expired_token_is_rejected(self):
        from assistant_os.control_plane.admin_service import mint_operator_token
        from assistant_os.mso.operator_auth import OperatorAuthenticationError, authenticate_operator_token
        from assistant_os.mso.operator_identity import get_operator_token_by_id
        from assistant_os.storage.mso_store import persist_operator_token

        token_info = mint_operator_token(operator_id="ops-viewer", ttl_minutes=1)
        token = token_info["token"]
        record = get_operator_token_by_id(token_info["token_record"]["token_id"])
        assert record is not None
        record.expires_at = "2000-01-01T00:00:00+00:00"
        persist_operator_token(record)

        with self.assertRaises(OperatorAuthenticationError):
            authenticate_operator_token(token, request_id="req:expired")

    def test_revoked_token_is_rejected(self):
        from assistant_os.control_plane.admin_service import mint_operator_token, revoke_operator_token
        from assistant_os.mso.operator_auth import OperatorAuthenticationError, authenticate_operator_token

        token_info = mint_operator_token(operator_id="ops-reviewer", ttl_minutes=60)
        revoke_operator_token(token_id=token_info["token_record"]["token_id"])

        with self.assertRaises(OperatorAuthenticationError):
            authenticate_operator_token(token_info["token"], request_id="req:revoked")

    def test_list_tokens_returns_metadata_without_secret(self):
        from assistant_os.control_plane.admin_service import list_operator_tokens_view, mint_operator_token

        mint_operator_token(operator_id="ops-admin", ttl_minutes=60)
        payload = list_operator_tokens_view(operator_id="ops-admin")

        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["tokens"][0]["operator_id"], "ops-admin")
        self.assertEqual(payload["tokens"][0]["token_hash"], "")


if __name__ == "__main__":
    unittest.main()
