from __future__ import annotations

from config import settings
from src.clients.alexa import AlexaClient
from src.clients.alexa_locality import AlexaLocalityClient
from src.clients.hear import HearApiClient
from src.clients.resolver import ResolverClient


class Dependencies:
    __slots__ = ("locality", "alexa", "heara", "resolver")

    def __init__(
        self,
        *,
        locality: AlexaLocalityClient | None = None,
        alexa: AlexaClient | None = None,
        heara: HearApiClient | None = None,
        resolver: ResolverClient | None = None,
    ) -> None:
        self.locality = locality or AlexaLocalityClient()
        self.alexa = alexa or AlexaClient()
        self.heara = heara or HearApiClient()
        self.resolver = resolver or ResolverClient(
            host=getattr(settings, "RESOLVER_HOST", None) or "https://resolver.hear.media",
            api_key=settings.HEAR_API_KEY,
            default_country=getattr(settings, "RESOLVER_DEFAULT_COUNTRY", None) or "gb",
            timeout_ms=getattr(settings, "RESOLVER_TIMEOUT_MS", None) or 2000,
        )
