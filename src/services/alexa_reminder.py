from __future__ import annotations

from src.clients.alexa import AlexaClient
from src.models.user import User


class AlexaReminderModule:
    _REMINDER_TOKEN = "feedbackReminderAlertToken"


class AlexaReminderService:
    __slots__ = ("_alexa", "_user")

    def __init__(self, alexa: AlexaClient, store: User) -> None:
        self._alexa = alexa
        self._user = store

    async def cancel(self, handler_input) -> None:
        token = self._user.snapshot(handler_input).get(AlexaReminderModule._REMINDER_TOKEN)
        if not token:
            return
        await self._alexa.cancel_feedback_reminder(handler_input, token)
        self._user.update(handler_input, {AlexaReminderModule._REMINDER_TOKEN: None})
