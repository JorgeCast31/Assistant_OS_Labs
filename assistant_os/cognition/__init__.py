"""
Cognition layer — exposes local cognitive provider health and preferences
to the API and UI without violating kernel sovereignty.

Rules enforced here:
- The local model has NO execution authority.
- All state derives from real backend probes — nothing is invented.
- Feature-flagged: disabled when ASSISTANT_LOCAL_LLM_ENABLED is false.
"""
