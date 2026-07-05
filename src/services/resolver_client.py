from __future__ import annotations

import grpc

from config import settings


class ResolverClient:
    """gRPC client for the NLU resolver service.

    Holds a lazily-constructed gRPC channel. The actual ``resolve``/``health``
    RPCs are not wired up yet: they require stubs generated from
    ``resolver.proto`` and raise ``NotImplementedError`` until those exist.
    Callers should treat this as *not usable for resolution yet* and fall back
    to local NLP; ``is_configured()`` gates that path.
    """

    def __init__(self) -> None:
        self._channel: grpc.Channel | None = None
        self._target: str | None = None

    def is_configured(self) -> bool:
        """Return True if the resolver gRPC backend is configured."""
        return bool(settings.RESOLVER_HOST)

    def _channel_or_build(self) -> grpc.Channel:
        if self._channel is None:
            if not settings.RESOLVER_HOST:
                raise RuntimeError("Resolver not configured — set RESOLVER_HOST")
            self._target = f"{settings.RESOLVER_HOST}:{settings.RESOLVER_PORT}"
            if settings.RESOLVER_TLS:
                credentials = grpc.ssl_channel_credentials()
                self._channel = grpc.secure_channel(self._target, credentials)
            else:
                self._channel = grpc.insecure_channel(self._target)
        return self._channel

    def _metadata(self) -> list[tuple[str, str]]:
        md: list[tuple[str, str]] = []
        if settings.RESOLVER_API_KEY:
            md.append(("x-api-key", settings.RESOLVER_API_KEY))
        return md

    async def resolve(
        self,
        utterance: str,
        *,
        country_code: str | None = None,
        timeout_ms: int | None = None,
    ) -> dict:
        raise Exception(
            "gRPC resolve call not implemented — resolver.proto stubs must be generated first"
        )

    async def health(self, *, timeout_ms: int | None = None) -> dict:
        """Invoke the gRPC health check against the resolver.

        Not implemented yet — requires stubs generated from ``resolver.proto``.
        """
        raise NotImplementedError(
            "gRPC health check not implemented — resolver.proto stubs must be generated first"
        )

    def close(self) -> None:
        """Close the gRPC channel and reset cached state."""
        if self._channel is not None:
            try:
                self._channel.close()
            except Exception:
                pass
            self._channel = None
            self._target = None


resolver_client = ResolverClient()
