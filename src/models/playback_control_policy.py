from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.constants.playback import PlaybackConstants
from src.utils.playback import PlaybackUtils


@dataclass(frozen=True, slots=True)
class PlaybackSpeedDecision:
    kind: Literal["unavailable", "idle", "restart", "unsupported", "limit"]
    speed: float | None = None
    available_speeds: tuple[float, ...] = ()
    offset_ms: int | None = None


@dataclass(frozen=True, slots=True)
class PlaybackSeekDecision:
    kind: Literal["cannot_seek", "restart"]
    offset_ms: int | None = None
    moved_ms: int = 0
    duration_ms: int | float | None = None


class PlaybackControlPolicy:
    @staticmethod
    def _variants(state: dict | None, store: dict) -> list[dict]:
        return list((state or {}).get("playbackSpeeds") or store.get("currentPlaybackSpeeds") or [])

    @staticmethod
    def _available_speeds(variants: list[dict]) -> tuple[float, ...]:
        values = []
        for value in variants:
            raw_speed = value.get("speed")
            if raw_speed is None:
                continue
            try:
                values.append(float(raw_speed))
            except (TypeError, ValueError):
                continue
        return tuple(values)

    @classmethod
    def apply_speed(
        cls,
        state: dict | None,
        store: dict,
        speed: float,
        *,
        default_speed: float,
    ) -> PlaybackSpeedDecision:
        variants = cls._variants(state, store)
        available = cls._available_speeds(variants)
        if speed != default_speed and variants and not PlaybackUtils.find_speed_url(variants, speed):
            return PlaybackSpeedDecision("unavailable", speed=speed, available_speeds=available)
        if not state or state.get("status") not in PlaybackConstants.ACTIVE_PLAYBACK_STATUSES:
            return PlaybackSpeedDecision("idle", speed=speed)
        return PlaybackSpeedDecision(
            "restart", speed=speed, offset_ms=int(state.get("offsetMs") or 0)
        )

    @classmethod
    def step_speed(
        cls,
        state: dict | None,
        store: dict,
        direction: str,
        *,
        default_speed: float,
    ) -> PlaybackSpeedDecision:
        variants = cls._variants(state, store)
        if not variants:
            return PlaybackSpeedDecision("unsupported")
        value = PlaybackUtils.get_next_speed(
            variants, store.get("playbackSpeed", default_speed), direction
        )
        if not value:
            return PlaybackSpeedDecision("limit")
        return cls.apply_speed(
            state, store, float(value["speed"]), default_speed=default_speed
        )

    @staticmethod
    def seek(
        state: dict | None, direction: int, amount_ms: int
    ) -> PlaybackSeekDecision:
        if not state:
            return PlaybackSeekDecision("cannot_seek")
        current = max(0, int(state.get("offsetMs", 0)))
        target = max(0, current + direction * max(1, int(amount_ms)))
        duration = state.get("durationMs")
        if isinstance(duration, (int, float)):
            target = min(target, max(0, int(duration) - 1000))
        return PlaybackSeekDecision(
            "restart",
            offset_ms=target,
            moved_ms=abs(target - current),
            duration_ms=duration,
        )
