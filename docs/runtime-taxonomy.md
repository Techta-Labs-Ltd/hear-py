# Runtime taxonomy refresh

The Hear backend publishes runtime taxonomy changes without rebuilding the
repository or container image.

## Backend request

Send the update to the deployed `TaxonomyWebhookEndpoint`:

```http
POST /webhook/taxonomy
Content-Type: application/json
X-Api-Key: <HEAR_API_KEY>
x-webhook-signature: t=<unix-seconds>,v1=<hmac-sha256>
x-webhook-timestamp: <unix-seconds>
```

```json
{
  "event": "taxonomy.updated",
  "schemaVersion": 3,
  "revision": "v2",
  "manifestUrl": "https://cdn.hear.media/runtime/taxonomy/v3/manifest.json"
}
```

The endpoint records an idempotent pending revision, sends a job to the
taxonomy refresh queue, and returns HTTP `202`. It never downloads taxonomy
files in the HTTP request.

## Default state

CloudFormation conditionally creates this DynamoDB item:

```json
{
  "pk": "taxonomy#current",
  "revision": "v1",
  "status": "active",
  "manifestUrl": "https://cdn.hear.media/runtime/taxonomy/v3/manifest.json"
}
```

The conditional write preserves any newer active revision during subsequent
stack deployments.

Every update also owns a revision record such as
`taxonomy#revision#v2`. Its status moves through `pending`, `downloading`,
`warming`, and `active`. Failed SQS deliveries are retried and then moved to the
taxonomy dead-letter queue. `taxonomy#current` changes only after activation.

## Background activation

The taxonomy refresh Lambda:

1. downloads the manifest and all referenced files;
2. verifies the manifest revision and every supplied SHA-256 digest;
3. parses a complete immutable taxonomy snapshot;
4. packages the validated files and uploads them to the encrypted, versioned
   taxonomy S3 bucket;
5. updates the resolver `$LATEST` environment with the revision and S3 object;
6. publishes a new Lambda version using the existing container image;
7. points the `candidate` alias at that version and invokes its health check;
8. verifies the candidate reports the expected revision;
9. atomically moves the `live` alias to the candidate version; and
10. marks the revision active in DynamoDB.

The resolver downloads the private S3 artifact during candidate cold
initialisation and loads it before the health check succeeds. User requests
continue through the previous `live` version throughout downloading,
validation and warm-up. In-flight requests remain on the old version when the
alias changes.

If any stage fails, the worker does not move `live` or update
`taxonomy#current`; the last complete resolver version keeps serving users.

## Manifest rules

- Revision identifiers are immutable and never reused.
- Each manifest describes a complete snapshot, not a patch.
- All file URLs use HTTPS.
- Every production file includes a SHA-256 digest.
- Upload data files first and publish the manifest last.
- Retain the previous snapshot for rollback.

Example descriptor:

```json
{
  "revision": "v2",
  "files": [
    {
      "entityType": "creator",
      "url": "https://cdn.hear.media/runtime/taxonomy/v3/creators.json",
      "sha256": "<hex-sha256>"
    },
    {
      "name": "aliases.json",
      "url": "https://cdn.hear.media/runtime/taxonomy/v3/aliases.json",
      "sha256": "<hex-sha256>"
    }
  ]
}
```

## Operations

Monitor:

- taxonomy webhook HTTP `202`, `400`, `401`, and `503` rates;
- `TaxonomyRefreshQueue` age and visible-message count;
- the taxonomy refresh DLQ;
- revision status records in DynamoDB;
- candidate health responses and `taxonomyRevision`;
- resolver `live` and `candidate` alias versions; and
- S3 snapshot size and object versions.

No GitHub workflow, Docker build, or listener request performs a taxonomy
refresh.
