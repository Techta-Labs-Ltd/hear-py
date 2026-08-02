# Alexa listener identity and backend authentication

## Request identity

Every Alexa request contains an opaque skill-scoped user ID. The skill reads
it from `context.System.user.userId`, with `session.user.userId` as a fallback,
and stores the non-empty value as `alexaUserId`. Playback, feedback,
notification, follow, and listener-sync operations must not be dispatched when
that value is absent.

The backend must treat blank or whitespace-only `alexaUserId` values as a
`400 Bad Request`. It must never insert an empty identifier. Listener sync must
be an atomic upsert on the normalized non-empty `alexaUserId`; a
lookup-followed-by-insert implementation can race and violate the unique
constraint.

The Alexa user ID identifies one skill installation. It is useful for skill
persistence, playback correlation, notification routing, and migration, but it
is not a backend authentication credential.

## Recommended account identity

Use Alexa standard account linking with OAuth 2.0 authorization code grant and
PKCE. The Hear backend should provide:

- an HTTPS authorization endpoint with a mobile-friendly login and consent UI;
- an HTTPS token endpoint that exchanges a single-use authorization code and
  PKCE verifier for access and refresh tokens;
- short-lived access tokens whose subject is the immutable Hear account ID;
- refresh-token rotation and revocation;
- a protected identity endpoint that validates the access token and returns
  the Hear account ID.

After linking, Alexa supplies the Hear access token on each skill request. The
skill should validate it through the backend and use its subject as the
canonical `listenerId`. Store the relationship:

```text
Hear account ID -> Alexa skill user ID(s) -> optional Alexa person ID(s)
```

This lets one Hear account survive device changes and relate a newly issued
Alexa skill user ID after the listener links again. Do not use `personId` as
the account key: it identifies a recognised speaker when available and is not
present on every request. Do not persist or log Alexa access tokens in the
skill database.

## Listener sync contract

`POST /api/v1/alexa/listeners/sync` must require a non-empty `alexaUserId` and
perform an atomic upsert. When account linking is present, authenticate the
request's bearer token and attach the Alexa ID to the token subject's Hear
account. The API key and webhook HMAC authenticate service-to-service traffic;
they do not identify the listener.

For an existing anonymous Alexa listener that later links an account, merge
playback history, follows, notification state, location, and preferences into
the Hear account in one transaction. Preserve the Alexa ID mapping so delayed
AudioPlayer events still resolve correctly.

## Voice-first accessibility

Hear serves blind and visually impaired listeners, so account linking must be
optional for ordinary listening and must never make a visual card the only
way forward. Explain the benefit in one short spoken prompt, support “link my
account”, “not now”, “repeat”, and “help”, and keep the session usable when the
listener declines. If the Alexa app is required to complete OAuth, say that
instructions were sent there and immediately offer “continue without linking”.

Do not require account linking for public catalogue playback. Require it only
for a feature that genuinely needs the listener's Hear account, and preserve
anonymous history so it can be merged after linking.
