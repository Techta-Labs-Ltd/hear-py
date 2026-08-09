from __future__ import annotations

import time

from src.services.store import get_store, update_store


def record_report(
    handler_input,
    *,
    subject_type: str,
    subject_id: str,
    subject_name: str | None = None,
    content_id: str | None = None,
    publication_id: str | None = None,
) -> dict:
    """Persist a bounded moderation report instead of acknowledging a no-op."""
    report = {
        "subjectType": subject_type,
        "subjectId": str(subject_id),
        "subjectName": subject_name,
        "contentId": content_id,
        "publicationId": publication_id,
        "recordedAt": int(time.time() * 1000),
        "status": "pending",
    }
    history = list(get_store(handler_input).get("reportHistory") or [])
    history.append(report)
    update_store(handler_input, {"reportHistory": history[-100:]})
    return report
