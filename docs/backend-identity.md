# Alexa listener identity and backend authentication

## Request identity

Every Alexa request contains an opaque skill-scoped user ID. The skill reads
it from `context.System.user.userId`, with `session.user.userId` as a fallback,
and stores the non-empty value as `alexaUserId`. Playback, feedback,
notification, follow, and listener-sync operations must not be dispatched when
that value is absent.

The backend must treat blank or whitespace-only `alexaUserId` values as a
`400 Bad Request`. It must never insert an empty identifier. Listener sync must
be an atomic upsert rather than lookup followed by insert.

The API key and webhook HMAC authenticate the Alexa skill and its event worker
to the Hear backend. The listener does not sign in or link an account.

## Automatic listener recognition

Use the current `alexaUserId` as the primary installation identifier and the
backend `listenerId` as the canonical Hear listener record. Maintain a mapping
that allows multiple historical Alexa IDs to point to one listener:

```text
Hear listener ID -> Alexa user ID aliases
```

On listener sync, use this order:

1. Reject an empty `alexaUserId`.
2. If the Alexa ID already exists, update that listener.
3. Otherwise, normalize the permission-sourced Alexa profile email by trimming
   whitespace and lowercasing it.
4. If that non-empty email uniquely matches one existing listener, attach the
   new Alexa ID as an alias and update the same listener.
5. If the email is missing or does not have one unique match, create a new
   listener for the Alexa ID. Never guess or merge ambiguous accounts.

Perform the lookup, alias attachment, and merge in one transaction. Preserve
old Alexa ID aliases so delayed AudioPlayer events still resolve. Merge
playback history, follows, notification state, location, and speed preferences
idempotently.

The email is obtained through Alexa profile permission and is used only for
safe record reconciliation. It is not a password or listener authentication
token. Encrypt it at rest, restrict access, and do not log it.

## Voice-first accessibility

Hear serves blind and visually impaired listeners. Identity reconciliation is
automatic and must never introduce a Link Account card, OAuth screen, spoken
login flow, or visual dependency. If email permission is unavailable, continue
listening under the current Alexa ID without blocking or repeatedly prompting.

## Listener sync contract

`POST /api/v1/alexa/listeners/sync` requires:

- a non-empty `alexaUserId`;
- service authentication with `X-Api-Key`;
- an atomic upsert keyed by Alexa ID;
- optional reconciliation by one uniquely matching permission-sourced email;
- a stable `listenerId` in the response.

Remove any existing database row whose `alexa_user_id` is blank before enabling
the strict validation. Add a database check constraint requiring
`length(trim(alexa_user_id)) > 0` so no caller can recreate the invalid row.
