from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResolverSlot:
    resolved: str | None = None
    spoken: str | None = None


class ResolverSlots:
    __slots__ = ()

    @staticmethod
    def resolved(slots: dict[str, ResolverSlot], name: str) -> str | None:
        slot = slots.get(name)
        return slot.resolved if slot else None

    @staticmethod
    def spoken(slots: dict[str, ResolverSlot], name: str) -> str | None:
        slot = slots.get(name)
        return slot.spoken if slot else None

    @staticmethod
    def values(slots: dict[str, ResolverSlot]) -> tuple[str | None, ...]:
        return tuple(
            value
            for slot in slots.values()
            for value in (slot.resolved, slot.spoken)
        )
