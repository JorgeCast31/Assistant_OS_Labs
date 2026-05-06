"""
assistant_os.output.inspector
------------------------------
OutputInspector — content-based inspection of execution output streams.

Design goals
------------
- Simple regex patterns with low false-negative rate on real secrets.
- Conservative false-positive rate: flag only clear signals.
- Non-blocking: inspect() never raises; errors produce a safe fallback result.
- No external dependencies beyond the standard library.

Detection categories
--------------------
potential_secret   — high-confidence patterns: API key prefixes, known token
                     formats, credential assignment lines.
absolute_path      — Unix or Windows absolute paths that could leak infra layout.
env_var_pattern    — env-file style KEY=VALUE lines (credential exposure vector).
long_encoded_string— contiguous non-whitespace token >200 chars (encoded key/data).
binary_content     — non-printable characters outside \\n \\r \\t (bad encoding).

Classification
--------------
Derived from the worst flag found:
    binary_content               → invalid
    potential_secret             → sensitive
    env_var_pattern              → sensitive   (credential assignment patterns)
    absolute_path | long_encoded → warning
    (no flags)                   → safe

Usage
-----
    inspector = OutputInspector()
    result = inspector.inspect(stdout, stderr)
    if result.is_sensitive():
        ...
"""

from __future__ import annotations

import re
import time
from typing import List, Tuple

from .models import (
    FLAG_ABSOLUTE_PATH,
    FLAG_BINARY_CONTENT,
    FLAG_ENV_VAR_PATTERN,
    FLAG_LONG_ENCODED_STRING,
    FLAG_POTENTIAL_SECRET,
    OUTPUT_INSPECTION_INVALID,
    OUTPUT_INSPECTION_SAFE,
    OUTPUT_INSPECTION_SENSITIVE,
    OUTPUT_INSPECTION_WARNING,
    InspectionResult,
    OutputFlag,
)

# ---------------------------------------------------------------------------
# Tuneable limits
# ---------------------------------------------------------------------------

# Maximum characters inspected per stream (prevents O(n) blow-up on huge output)
_MAX_INSPECT_CHARS: int = 64_000  # 64 KB

# Minimum contiguous non-whitespace token length to flag as long_encoded_string
_LONG_TOKEN_MIN_LEN: int = 200

# Minimum non-printable characters to flag as binary_content
_BINARY_THRESHOLD: int = 5

# ---------------------------------------------------------------------------
# Compiled patterns — ordered from most specific to most general
# ---------------------------------------------------------------------------

# (compiled_pattern, flag_type, detail_template)
_PatternEntry = Tuple[re.Pattern, str, str]


def _p(pattern: str, flags: int = 0) -> re.Pattern:
    return re.compile(pattern, flags)


# Potential secrets — high-confidence known-format patterns
_SECRET_PATTERNS: List[_PatternEntry] = [
    # OpenAI-style keys: sk-... or sk-proj-...
    (_p(r'\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}\b'),
     FLAG_POTENTIAL_SECRET, "Possible OpenAI-style API key (sk- prefix)"),

    # GitHub personal access tokens (classic and fine-grained)
    (_p(r'\bghp_[A-Za-z0-9]{36}\b'),
     FLAG_POTENTIAL_SECRET, "Possible GitHub PAT (ghp_ prefix)"),
    (_p(r'\bgithub_pat_[A-Za-z0-9_]{40,}\b'),
     FLAG_POTENTIAL_SECRET, "Possible GitHub fine-grained PAT"),

    # Slack tokens
    (_p(r'\bxox[bpoas]-[A-Za-z0-9\-]+\b'),
     FLAG_POTENTIAL_SECRET, "Possible Slack token"),

    # Anthropic API keys
    (_p(r'\bsk-ant-[A-Za-z0-9\-_]{20,}\b'),
     FLAG_POTENTIAL_SECRET, "Possible Anthropic API key"),

    # Generic Bearer token in HTTP headers / logs
    (_p(r'(?i)\bBearer\s+[A-Za-z0-9._\-+/]{20,}'),
     FLAG_POTENTIAL_SECRET, "Possible Bearer token value"),

    # Credential assignment lines: API_KEY=..., SECRET=..., PASSWORD=...
    (_p(
        r'(?i)(?:api[-_]?key|api[-_]?secret|access[-_]?token|auth[-_]?token'
        r'|private[-_]?key|client[-_]?secret|consumer[-_]?secret'
        r'|refresh[-_]?token)\s*[=:]\s*["\']?[A-Za-z0-9._\-+/]{10,}',
    ), FLAG_POTENTIAL_SECRET, "Possible credential in key=value assignment"),

    # Password assignments
    (_p(r'(?i)(?:password|passwd|passphrase)\s*[=:]\s*["\']?\S{6,}'),
     FLAG_POTENTIAL_SECRET, "Possible password value"),

    # AWS-style access key IDs
    (_p(r'\b(?:AKIA|ASIA|AROA)[A-Z0-9]{16}\b'),
     FLAG_POTENTIAL_SECRET, "Possible AWS access key ID"),
]

# Absolute path patterns — may leak host infrastructure layout
_PATH_PATTERNS: List[_PatternEntry] = [
    # Unix sensitive paths: /home/*, /root/*, /etc/*, /var/secret*, /run/secrets*
    (_p(r'(?<!\w)/(?:home|root|etc|proc|var/(?:secret|run)|run/secrets)/\S+'),
     FLAG_ABSOLUTE_PATH, "Absolute Unix path detected (possible infra layout leak)"),

    # Windows user/system paths
    (_p(r'[A-Za-z]:\\(?:Users\\[^\\]+|Windows|Program Files|ProgramData)\\\S+'),
     FLAG_ABSOLUTE_PATH, "Absolute Windows path detected (possible infra layout leak)"),
]

# Env-file / variable assignment patterns
_ENV_PATTERNS: List[_PatternEntry] = [
    # Lines that look like .env file entries: CAPS_VARNAME=value
    (_p(r'^[A-Z_][A-Z0-9_]{2,}=[^=\n\r]{1,}', re.MULTILINE),
     FLAG_ENV_VAR_PATTERN, "Possible env-file variable assignment"),
]

# All patterns combined for single-pass inspection (binary/long handled separately)
_ALL_PATTERNS: List[_PatternEntry] = (
    _SECRET_PATTERNS + _PATH_PATTERNS + _ENV_PATTERNS
)


# ---------------------------------------------------------------------------
# OutputInspector
# ---------------------------------------------------------------------------

class OutputInspector:
    """
    Stateless content inspector for execution output streams.

    All state is derived from the input on each call to inspect().
    Thread-safe: a single shared instance is safe for concurrent use.
    """

    def inspect(self, stdout: str, stderr: str) -> InspectionResult:
        """
        Inspect stdout and stderr for sensitive or suspicious content.

        Parameters
        ----------
        stdout : Governed stdout string (post-policy, post-truncation).
        stderr : Governed stderr string (post-policy, post-truncation).

        Returns
        -------
        InspectionResult — never raises; returns a safe 'safe' result on error.
        """
        try:
            return self._do_inspect(stdout, stderr)
        except Exception:
            # Inspection must never block execution results.
            return InspectionResult(
                classification=OUTPUT_INSPECTION_SAFE,
                flags=[],
                inspected_at=time.time(),
                stdout_redacted=stdout,
                stderr_redacted=stderr,
            )

    def _do_inspect(self, stdout: str, stderr: str) -> InspectionResult:
        flags: List[OutputFlag] = []
        stdout_redacted = stdout
        stderr_redacted = stderr

        streams = [("stdout", stdout), ("stderr", stderr)]

        for stream_name, content in streams:
            bounded = content[:_MAX_INSPECT_CHARS]

            # --- Pattern matching ---
            for pattern, flag_type, detail in _ALL_PATTERNS:
                for match in pattern.finditer(bounded):
                    flags.append(OutputFlag(
                        flag_type=flag_type,
                        detail=detail,
                        stream=stream_name,
                    ))
                    # Redact matched value
                    matched_text = match.group(0)
                    if stream_name == "stdout":
                        stdout_redacted = stdout_redacted.replace(
                            matched_text, "[REDACTED]", 1
                        )
                    else:
                        stderr_redacted = stderr_redacted.replace(
                            matched_text, "[REDACTED]", 1
                        )

            # --- Long encoded string detection ---
            for token in re.split(r'\s+', bounded):
                if len(token) > _LONG_TOKEN_MIN_LEN:
                    flags.append(OutputFlag(
                        flag_type=FLAG_LONG_ENCODED_STRING,
                        detail=(
                            f"Token of {len(token)} characters without whitespace "
                            f"in {stream_name} (possible encoded/obfuscated data)"
                        ),
                        stream=stream_name,
                    ))
                    # Redact the long token
                    if stream_name == "stdout":
                        stdout_redacted = stdout_redacted.replace(token, "[REDACTED]", 1)
                    else:
                        stderr_redacted = stderr_redacted.replace(token, "[REDACTED]", 1)

            # --- Binary content detection ---
            non_printable = sum(
                1 for c in bounded
                if ord(c) < 32 and c not in "\n\r\t"
            )
            if non_printable >= _BINARY_THRESHOLD:
                flags.append(OutputFlag(
                    flag_type=FLAG_BINARY_CONTENT,
                    detail=(
                        f"{non_printable} non-printable character(s) in {stream_name} "
                        "(possible binary data or encoding issue)"
                    ),
                    stream=stream_name,
                ))

        classification = _classify(flags)

        return InspectionResult(
            classification=classification,
            flags=flags,
            inspected_at=time.time(),
            stdout_redacted=stdout_redacted,
            stderr_redacted=stderr_redacted,
        )


# ---------------------------------------------------------------------------
# Classification helper
# ---------------------------------------------------------------------------

def _classify(flags: List[OutputFlag]) -> str:
    """
    Derive the overall risk classification from the flag list.

    Severity order: invalid > sensitive > warning > safe
    """
    if not flags:
        return OUTPUT_INSPECTION_SAFE

    types = {f.flag_type for f in flags}

    if FLAG_BINARY_CONTENT in types:
        return OUTPUT_INSPECTION_INVALID

    if FLAG_POTENTIAL_SECRET in types or FLAG_ENV_VAR_PATTERN in types:
        return OUTPUT_INSPECTION_SENSITIVE

    # absolute_path and long_encoded_string are warning-level
    return OUTPUT_INSPECTION_WARNING
