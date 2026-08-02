from unittest.mock import MagicMock

from src.webhooks import taxonomy_seed


def test_seed_creates_runtime_v1_when_revision_is_absent(monkeypatch):
    table = MagicMock()
    resource = MagicMock()
    resource.Table.return_value = table
    monkeypatch.setattr(taxonomy_seed.boto3, "resource", lambda *args, **kwargs: resource)

    taxonomy_seed._seed_revision(
        "v1",
        "https://cdn.hear.media/runtime/taxonomy/v3/manifest.json",
    )

    table.put_item.assert_called_once_with(
        Item={
            "pk": "taxonomy#current",
            "revision": "v1",
            "manifestUrl": "https://cdn.hear.media/runtime/taxonomy/v3/manifest.json",
            "status": "active",
        },
        ConditionExpression="attribute_not_exists(pk)",
    )


def test_seed_keeps_a_newer_existing_revision(monkeypatch):
    error = Exception("already exists")
    error.response = {"Error": {"Code": "ConditionalCheckFailedException"}}
    table = MagicMock()
    table.put_item.side_effect = error
    resource = MagicMock()
    resource.Table.return_value = table
    monkeypatch.setattr(taxonomy_seed.boto3, "resource", lambda *args, **kwargs: resource)

    taxonomy_seed._seed_revision(
        "v1",
        "https://cdn.hear.media/runtime/taxonomy/v3/manifest.json",
    )

    table.put_item.assert_called_once()
