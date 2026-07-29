from __future__ import annotations
from config import settings

def is_listener_api_enabled() -> bool:
    explicit = settings.HEAR_LISTENER_API
    if explicit is not None and str(explicit).strip() != "":
        return str(explicit).strip() == "1"
    return bool(str(settings.api_base_url or "").strip())
