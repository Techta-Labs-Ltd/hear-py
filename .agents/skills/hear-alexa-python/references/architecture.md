# Hear repository architecture

## Placement map

| Concern | Owner |
|---|---|
| Lambda routing | `main.py` |
| Composition | `src/application.py` |
| Ordered handlers | `src/handlers/registry.py` |
| Handler implementations | `src/handlers/` feature packages |
| Gates/interceptors | `src/middleware/pipeline.py` |
| Async Alexa runtime | `src/runtime/__init__.py` |
| Workflows/integrations | `src/services/` |
| Hear HTTP API | `src/services/api/` |
| Alexa APIs/locality | `src/services/alexa/` |
| Persistent state | `src/services/storage/`, `src/adapters/` |
| Pure helpers | `src/utils/` |
| NLP | `src/nlp/` |
| HTTP/SQS webhooks | `src/webhooks/` |
| Settings/permissions | `config/` |
| Interaction model | `en-GB.json` |

Prefer the dependency direction:

`main -> application -> registries -> handlers/middleware -> services -> adapters/API`

Handlers may call services and pure utilities. Services may call repositories, adapters, API clients, and utilities. Avoid handler-to-handler calls; move shared workflows into a service. Pure utilities must not become hidden service containers.

## Project contracts

- `AsyncSkill` accepts ask-sdk-style handlers/interceptors and awaits awaitables.
- Handler dispatch is first-match wins; middleware order is behavioral.
- Persistent state uses the storage owner and middleware save lifecycle.
- EN-GB is the interaction locale.
- Memory persistence is a development fallback.
- Verify `PROJECT_MAP.txt` against current paths because it may lag refactors.

## Add a handler

1. Find the feature package and nearest analogous handler.
2. Add one `AbstractRequestHandler` subclass with narrow matching.
3. Export it if registry imports use package exports.
4. Add it once to `REQUEST_HANDLERS` in specificity order.
5. Update `en-GB.json` and NLP maps for a new custom intent.
6. Test its positive match and a nearby request it must not capture.

## Add a service

Use a class for state, injected collaborators, or a coherent owned interface. Use a function for a focused stateless operation. Search for the existing owner first. Avoid mutable module globals and implicit cross-request state.
