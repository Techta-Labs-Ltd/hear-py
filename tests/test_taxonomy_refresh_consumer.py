from __future__ import annotations

import logging
from unittest.mock import MagicMock

from src.webhooks import taxonomy_refresh_consumer


def test_legacy_active_revision_is_treated_as_uninitialized(monkeypatch, caplog):
    table = MagicMock()
    table.get_item.return_value = {"Item": {"revision": "v1"}}
    resource = MagicMock()
    resource.Table.return_value = table
    monkeypatch.setattr(
        taxonomy_refresh_consumer.boto3,
        "resource",
        lambda *args, **kwargs: resource,
    )

    with caplog.at_level(logging.WARNING):
        revision = taxonomy_refresh_consumer._active_revision()

    assert revision == 0
    assert "legacy non-numeric active taxonomy revision" in caplog.text
    table.get_item.assert_called_once_with(
        Key={"pk": "taxonomy#current"},
        ConsistentRead=True,
    )


def test_refresh_failure_is_logged_and_persisted(monkeypatch, caplog):
    statuses = MagicMock()
    monkeypatch.setattr(taxonomy_refresh_consumer, "_active_revision", lambda: 0)
    monkeypatch.setattr(taxonomy_refresh_consumer, "_set_status", statuses)
    monkeypatch.setattr(
        taxonomy_refresh_consumer,
        "_build_artifact",
        MagicMock(side_effect=RuntimeError("artifact validation failed")),
    )

    with caplog.at_level(logging.ERROR):
        result = taxonomy_refresh_consumer.handler({"Records": [{
            "messageId": "message-9",
            "body": (
                '{"revision":9,"manifestUrl":"https://cdn.hear.media/'
                'runtime/taxonomy/manifest.json","manifestSha256":"'
                + "a" * 64
                + '"}'
            ),
        }]})

    assert result == {"batchItemFailures": [{"itemIdentifier": "message-9"}]}
    assert "revision=9 stage=downloading errorType=RuntimeError" in caplog.text
    statuses.assert_any_call(
        "9",
        "failed",
        failedStage="downloading",
        errorType="RuntimeError",
        errorMessage="artifact validation failed",
    )
