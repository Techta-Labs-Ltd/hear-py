# Alexa and Python practices

## Requests and responses

- Match request type/intent explicitly and tolerate missing request, intent, or slots.
- Keep `can_handle` side-effect free.
- Return the response shape expected by `AsyncSkill`.
- Set `shouldEndSession` deliberately and reprompt when keeping conversation open.
- Put fallbacks last and test registration order.

## Speech and audio

- Use shared SSML and escaping helpers; escape external titles, names, and towns.
- Keep speech concise and never expose internal errors.
- Use Alexa-compatible HTTPS audio URLs.
- Keep playback tokens stable and opaque; preserve previous-token/play-behavior semantics.
- Treat playback events as duplicated, delayed, or out of order. Make transitions idempotent.
- Do not assume AudioPlayer events contain session attributes.

## State, API, and permissions

- Resolve identity through existing helpers.
- Mutate persistence through the storage owner to preserve dirty/save semantics.
- Put network access behind clients with configured timeouts. Retry only safe operations.
- Request only declared permissions and handle denial/missing consent.
- Never store or log access tokens.

## Interaction model

- Keep intent and slot names identical across `en-GB.json`, NLP classifier/dispatch, handlers, and tests.
- Add representative samples without broad collisions.
- Prefer built-in AMAZON intents for standard controls.
- Preserve EN-GB wording and custom slot synonyms.

## Python

- Follow neighboring use of `from __future__ import annotations`.
- Keep imports at module scope unless a real circular-import constraint exists.
- Type public boundaries and non-obvious data shapes.
- Catch narrow exceptions, log context without secrets, and return deliberate user-safe fallbacks.
- Avoid mutable defaults, hidden singleton state, duplicate helpers, and functions mixing parsing, I/O, mutation, and response construction.
- Test observable behavior.
