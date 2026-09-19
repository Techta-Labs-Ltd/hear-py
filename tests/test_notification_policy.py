from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.models.notification_policy import NotificationPolicy
from src.models.notifications import (
    Notification,
    NotificationAcceptCommand,
    NotificationOfferCommand,
)
from src.utils.notifications import NotificationItem


class TestNotificationPolicy:
    def test_offer_classifies_request_and_availability(self) -> None:
        assert (
            NotificationPolicy.offer(
                explicit=False,
                request_type="IntentRequest",
                listener_id="listener-1",
                api_enabled=True,
            ).kind
            == "none"
        )
        assert (
            NotificationPolicy.offer(
                explicit=True,
                request_type="IntentRequest",
                listener_id="",
                api_enabled=True,
            ).kind
            == "unavailable"
        )
        assert (
            NotificationPolicy.offer(
                explicit=False,
                request_type="LaunchRequest",
                listener_id="listener-1",
                api_enabled=True,
                has_items=True,
            ).kind
            == "offer"
        )
        assert (
            NotificationPolicy.offer(
                explicit=False,
                request_type="LaunchRequest",
                listener_id="listener-1",
                api_enabled=True,
            ).kind
            == "fetch"
        )

    def test_dialog_item_keeps_only_persisted_dialogue_fields(self) -> None:
        item = NotificationPolicy.dialog_item(
            {
                "notificationId": "notice-1",
                "sourceName": "The Gazette",
                "publication": {
                    "id": "publication-1",
                    "title": "Morning Brief",
                    "trackCount": 1,
                },
                "listenerId": "listener-1",
                "secret": "do-not-copy",
            }
        )
        assert item == {
            "notificationId": "notice-1",
            "sourceName": "The Gazette",
            "publication": {
                "id": "publication-1",
                "title": "Morning Brief",
                "trackCount": 1,
            },
        }

    def test_normalize_preserves_structured_publication(self) -> None:
        normalized = NotificationItem.normalize(
            {
                "listenerId": "listener-1",
                "notificationId": "notice-1",
                "notificationType": "creator_update",
                "sourceType": "creator",
                "sourceId": "creator-1",
                "sourceName": "Creator",
                "lastDate": "2026-09-11T10:00:00Z",
                "publication": {
                    "id": "publication-1",
                    "title": "Morning Brief",
                    "trackCount": 1,
                    "ignored": "value",
                },
            }
        )

        assert normalized is not None
        assert normalized["publication"] == {
            "id": "publication-1",
            "title": "Morning Brief",
            "trackCount": 1,
        }

    def test_dialog_item_keeps_only_safe_publication_fields(self) -> None:
        item = NotificationPolicy.dialog_item(
            {
                "notificationId": "notice-1",
                "publication": {
                    "id": "publication-1",
                    "title": " Morning Brief ",
                    "trackCount": 1,
                    "secret": "value",
                },
            }
        )

        assert item == {
            "notificationId": "notice-1",
            "publication": {
                "id": "publication-1",
                "title": "Morning Brief",
                "trackCount": 1,
            },
        }

    def test_policy_has_no_platform_dependency(self) -> None:
        source = (Path(__file__).parents[1] / "src/models/notification_policy.py").read_text(
            encoding="utf-8"
        )
        assert "src.alexa" not in source
        assert "handler_input" not in source

    def test_notification_workflow_has_no_platform_dependency(self) -> None:
        source = (Path(__file__).parents[1] / "src/models/notifications.py").read_text(
            encoding="utf-8"
        )
        assert "src.alexa" not in source
        assert "handler_input" not in source
        assert "response_builder" not in source

    @pytest.mark.asyncio
    async def test_workflow_offers_a_bounded_item_without_an_alexa_request(self) -> None:
        notification_api = SimpleNamespace(
            pending=AsyncMock(
                return_value={
                    "items": [
                        {
                            "notificationId": "notice-1",
                            "listenerId": "listener-1",
                            "sourceType": "creator",
                            "sourceId": "creator-1",
                            "sourceName": "Creator",
                            "publication": {"id": "publication-1"},
                            "secret": "not-in-dialogue-state",
                        }
                    ]
                }
            ),
            update=AsyncMock(return_value={"updated": True}),
        )
        workflow = Notification(notification_api, SimpleNamespace(search=AsyncMock()))

        result = await workflow.offer(
            NotificationOfferCommand(
                explicit=True,
                request_type="IntentRequest",
                listener_id="listener-1",
                api_enabled=True,
            )
        )

        assert result.kind == "offer"
        assert result.item == {
            "notificationId": "notice-1",
            "sourceType": "creator",
            "sourceId": "creator-1",
            "sourceName": "Creator",
            "publication": {"id": "publication-1"},
        }
        assert notification_api.update.await_args.args[0]["status"] == "offered"

    @pytest.mark.asyncio
    async def test_workflow_accepts_explicit_input_and_returns_search_outcome(self) -> None:
        notification_api = SimpleNamespace(update=AsyncMock(return_value={"updated": True}))
        heara = SimpleNamespace(
            search=AsyncMock(return_value={"results": [{"contentId": "content-1"}]})
        )
        workflow = Notification(notification_api, heara)

        result = await workflow.accept(
            NotificationAcceptCommand(
                listener_id="listener-1",
                alexa_user_id="alexa-user-1",
                store={"listenerId": "listener-1"},
                item={
                    "notificationId": "notice-1",
                    "sourceType": "creator",
                    "sourceId": "creator-1",
                },
                timeout_ms=1000,
            )
        )

        assert result.kind == "play"
        assert result.results == ({"contentId": "content-1"},)
        assert heara.search.await_args.kwargs["timeout_ms"] == 1000
        assert heara.search.await_args.args[0]["filter"] == {"creatorIds": ["creator-1"]}
        assert notification_api.update.await_args_list[0].args[0]["status"] == "resolving"
