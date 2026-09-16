from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class FeedbackCommand:
    value: Literal["enjoyed", "somewhat", "not_enjoyed", "skipped"]

    def __post_init__(self) -> None:
        if self.value not in {"enjoyed", "somewhat", "not_enjoyed", "skipped"}:
            raise ValueError("feedback command requires a supported answer")


@dataclass(frozen=True, slots=True)
class FeedbackReceipt:
    command: FeedbackCommand
    feedback_key: str | None
