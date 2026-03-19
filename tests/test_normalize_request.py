"""
Tests for normalize_request() — CanonicalRequest v1 entry-point normalization.

Validates all invariants guaranteed by normalize_request():
- Always returns a dict with all four keys
- text: stripped, never None
- context_id: generated UUID4 when absent
- filters: always dict, {} when absent or invalid
- metadata: always dict, {} when absent or invalid
"""
import re
from assistant_os.contracts import normalize_request, CanonicalRequest

UUID4_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


class TestNormalizeRequestStructure:
    """Always returns a complete dict with all required keys."""

    def test_returns_dict_with_all_keys(self):
        result = normalize_request(text="hello")
        assert set(result.keys()) >= {"text", "context_id", "filters", "metadata"}

    def test_no_args_returns_all_keys(self):
        result = normalize_request()
        assert "text" in result
        assert "context_id" in result
        assert "filters" in result
        assert "metadata" in result

    def test_all_kwargs_returns_all_keys(self):
        result = normalize_request(
            text="buy milk",
            context_id="ctx-123",
            filters={"status": "pending"},
            metadata={"source": "cli"},
        )
        assert set(result.keys()) >= {"text", "context_id", "filters", "metadata"}


class TestTextNormalization:
    """text field: stripped, never None, preserves non-whitespace content."""

    def test_text_unchanged_when_no_whitespace(self):
        result = normalize_request(text="buy milk")
        assert result["text"] == "buy milk"

    def test_text_stripped_leading_whitespace(self):
        result = normalize_request(text="   buy milk")
        assert result["text"] == "buy milk"

    def test_text_stripped_trailing_whitespace(self):
        result = normalize_request(text="buy milk   ")
        assert result["text"] == "buy milk"

    def test_text_stripped_both_ends(self):
        result = normalize_request(text="  buy milk  ")
        assert result["text"] == "buy milk"

    def test_text_stripped_newlines(self):
        result = normalize_request(text="\nbuy milk\n")
        assert result["text"] == "buy milk"

    def test_text_none_becomes_empty_string(self):
        result = normalize_request(text=None)
        assert result["text"] == ""

    def test_text_not_provided_becomes_empty_string(self):
        result = normalize_request()
        assert result["text"] == ""

    def test_text_whitespace_only_becomes_empty_string(self):
        result = normalize_request(text="   \t  \n  ")
        assert result["text"] == ""

    def test_text_preserves_internal_spaces(self):
        result = normalize_request(text="  buy   two   milks  ")
        assert result["text"] == "buy   two   milks"

    def test_text_is_always_str(self):
        result = normalize_request(text=None)
        assert isinstance(result["text"], str)


class TestContextIdNormalization:
    """context_id: preserved when valid, generated UUID4 when absent."""

    def test_context_id_preserved_when_provided(self):
        result = normalize_request(text="x", context_id="my-ctx-id")
        assert result["context_id"] == "my-ctx-id"

    def test_context_id_generated_when_absent(self):
        result = normalize_request(text="x")
        assert isinstance(result["context_id"], str)
        assert len(result["context_id"]) > 0

    def test_context_id_generated_is_uuid4(self):
        result = normalize_request(text="x")
        assert UUID4_RE.match(result["context_id"]), f"not a UUID4: {result['context_id']!r}"

    def test_context_id_generated_when_none(self):
        result = normalize_request(text="x", context_id=None)
        assert UUID4_RE.match(result["context_id"])

    def test_context_id_generated_when_empty_string(self):
        result = normalize_request(text="x", context_id="")
        assert UUID4_RE.match(result["context_id"])

    def test_context_id_unique_per_call(self):
        r1 = normalize_request(text="x")
        r2 = normalize_request(text="x")
        assert r1["context_id"] != r2["context_id"]


class TestFiltersNormalization:
    """filters: always dict, {} when absent or non-dict."""

    def test_filters_preserved_when_provided(self):
        result = normalize_request(text="x", filters={"status": "pending"})
        assert result["filters"] == {"status": "pending"}

    def test_filters_default_to_empty_dict(self):
        result = normalize_request(text="x")
        assert result["filters"] == {}

    def test_filters_none_becomes_empty_dict(self):
        result = normalize_request(text="x", filters=None)
        assert result["filters"] == {}

    def test_filters_list_becomes_empty_dict(self):
        result = normalize_request(text="x", filters=["status"])  # type: ignore[arg-type]
        assert result["filters"] == {}

    def test_filters_string_becomes_empty_dict(self):
        result = normalize_request(text="x", filters="status=pending")  # type: ignore[arg-type]
        assert result["filters"] == {}

    def test_filters_is_always_dict(self):
        result = normalize_request(text="x")
        assert isinstance(result["filters"], dict)


class TestMetadataNormalization:
    """metadata: always dict, {} when absent or non-dict."""

    def test_metadata_preserved_when_provided(self):
        result = normalize_request(text="x", metadata={"source": "cli"})
        assert result["metadata"] == {"source": "cli"}

    def test_metadata_default_to_empty_dict(self):
        result = normalize_request(text="x")
        assert result["metadata"] == {}

    def test_metadata_none_becomes_empty_dict(self):
        result = normalize_request(text="x", metadata=None)
        assert result["metadata"] == {}

    def test_metadata_list_becomes_empty_dict(self):
        result = normalize_request(text="x", metadata=["source"])  # type: ignore[arg-type]
        assert result["metadata"] == {}

    def test_metadata_is_always_dict(self):
        result = normalize_request(text="x")
        assert isinstance(result["metadata"], dict)


class TestNormalizeRequestCombinations:
    """Integration-style: representative call patterns from webhook_server."""

    def test_typical_webhook_call(self):
        """Mirrors normalize_request(text=text) in _route_text_by_classification."""
        result = normalize_request(text="  crear tarea revisar propuesta  ")
        assert result["text"] == "crear tarea revisar propuesta"
        assert isinstance(result["context_id"], str)
        assert result["filters"] == {}
        assert result["metadata"] == {}

    def test_all_fields_provided(self):
        result = normalize_request(
            text=" query open tasks ",
            context_id="abc-123",
            filters={"assignee": "me"},
            metadata={"channel": "slack"},
        )
        assert result["text"] == "query open tasks"
        assert result["context_id"] == "abc-123"
        assert result["filters"] == {"assignee": "me"}
        assert result["metadata"] == {"channel": "slack"}

    def test_text_with_unicode(self):
        result = normalize_request(text="  crear tarea: 📋 revisión  ")
        assert result["text"] == "crear tarea: 📋 revisión"
