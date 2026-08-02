from __future__ import annotations

import json
import tempfile
import tarfile
from pathlib import Path

import boto3

from config import settings
from src.resolver.taxonomy import TaxonomyManager


def _set_status(revision: str, status: str, **values) -> None:
    table = boto3.resource("dynamodb", region_name=settings.ddb_region).Table(
        settings.HEAR_TAXONOMY_REVISION_TABLE
    )
    item = {"pk": f"taxonomy#revision#{revision}", "revision": revision, "status": status, **values}
    table.put_item(Item=item)


def _build_artifact(revision: str, manifest_url: str) -> str:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        snapshot_dir = root / "snapshot"
        manager = TaxonomyManager(cache_dir=snapshot_dir)
        if not manager.refresh(manifest_url) or manager.snapshot.revision != revision:
            raise ValueError("Manifest revision does not match requested revision")
        archive = root / "snapshot.tar.gz"
        with tarfile.open(archive, "w:gz") as output:
            for path in snapshot_dir.iterdir():
                output.add(path, arcname=path.name)
        key = f"taxonomy/{settings.STAGE}/{revision}/snapshot.tar.gz"
        boto3.client("s3").upload_file(
            str(archive), settings.HEAR_TAXONOMY_SNAPSHOT_BUCKET, key,
        )
        return key


def _publish_resolver(revision: str, key: str) -> str:
    client = boto3.client("lambda", region_name=settings.ddb_region)
    name = settings.HEAR_RESOLVER_FUNCTION_NAME
    configuration = client.get_function_configuration(FunctionName=name)
    environment = dict((configuration.get("Environment") or {}).get("Variables") or {})
    environment.update({
        "HEAR_TAXONOMY_ACTIVE_REVISION": revision,
        "HEAR_TAXONOMY_SNAPSHOT_BUCKET": settings.HEAR_TAXONOMY_SNAPSHOT_BUCKET,
        "HEAR_TAXONOMY_SNAPSHOT_KEY": key,
    })
    client.update_function_configuration(
        FunctionName=name,
        Environment={"Variables": environment},
    )
    client.get_waiter("function_updated").wait(FunctionName=name)
    version = client.publish_version(
        FunctionName=name,
        Description=f"Runtime taxonomy {revision}",
    )["Version"]
    candidate = settings.HEAR_RESOLVER_CANDIDATE_ALIAS
    try:
        client.update_alias(FunctionName=name, Name=candidate, FunctionVersion=version)
    except client.exceptions.ResourceNotFoundException:
        client.create_alias(FunctionName=name, Name=candidate, FunctionVersion=version)
    response = client.invoke(
        FunctionName=name,
        Qualifier=candidate,
        InvocationType="RequestResponse",
        Payload=json.dumps({"version": 1, "operation": "health"}).encode(),
    )
    health = json.loads(response["Payload"].read() or "{}")
    if health.get("status") != "ready" or health.get("taxonomyRevision") != revision:
        raise RuntimeError("Candidate resolver did not load the requested taxonomy")
    client.update_alias(
        FunctionName=name,
        Name=settings.HEAR_RESOLVER_LIVE_ALIAS,
        FunctionVersion=version,
    )
    return version


def _activate(revision: str, manifest_url: str, key: str, version: str) -> None:
    table = boto3.resource("dynamodb", region_name=settings.ddb_region).Table(
        settings.HEAR_TAXONOMY_REVISION_TABLE
    )
    table.put_item(Item={
        "pk": "taxonomy#current",
        "revision": revision,
        "manifestUrl": manifest_url,
        "snapshotKey": key,
        "resolverVersion": version,
        "status": "active",
    })
    _set_status(revision, "active", manifestUrl=manifest_url, snapshotKey=key, resolverVersion=version)


def handler(event: dict, context=None) -> dict:
    failures = []
    for record in event.get("Records") or []:
        try:
            payload = json.loads(record.get("body") or "{}")
            revision = str(payload.get("revision") or "").strip()
            manifest_url = str(payload.get("manifestUrl") or "").strip()
            if not revision or not manifest_url:
                raise ValueError("revision and manifestUrl are required")
            _set_status(revision, "downloading", manifestUrl=manifest_url)
            key = _build_artifact(revision, manifest_url)
            _set_status(revision, "warming", manifestUrl=manifest_url, snapshotKey=key)
            version = _publish_resolver(revision, key)
            _activate(revision, manifest_url, key, version)
        except Exception:
            failures.append({"itemIdentifier": record.get("messageId")})
    return {"batchItemFailures": failures}

