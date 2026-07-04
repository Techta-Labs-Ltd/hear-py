def resolve_persistence_user_id(request_envelope: dict) -> str:
    if not request_envelope or not isinstance(request_envelope, dict):
        return "__invalid_envelope__"
    ctx_user = (
        (request_envelope.get("context") or {})
        .get("System", {})
        .get("user", {})
        .get("userId")
    )
    if ctx_user:
        return ctx_user
    sess_user = (request_envelope.get("session") or {}).get("user", {}).get("userId")
    if sess_user:
        return sess_user
    session_id = (request_envelope.get("session") or {}).get("sessionId")
    if session_id:
        return f"session:{session_id}"
    return "__no_identity__"
