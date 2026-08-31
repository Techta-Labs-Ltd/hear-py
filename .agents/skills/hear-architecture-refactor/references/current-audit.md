# Current architecture audit

The strict class-only audit passes with zero errors and zero warnings after the MVC migration.

## Enforced configuration boundary

- `config.Settings` owns environment-backed runtime configuration.
- `.env.example` documents every supported application setting.
- Source modules do not call `os.getenv`, `os.environ.get`, or index `os.environ` directly.
- Resolver, HTTP, Alexa, progressive-response, DynamoDB, feedback, playback, queue, browse, search, and history tuning use typed settings.

## Historical baseline

The first class-only audit on 30 August 2026 reported 614 errors and 40 warnings under `src`.

## Historical violation counts

| Count | Rule |
|---:|---|
| 416 | top-level code that is not an import or class |
| 76 | raw request, session, or User state access outside a gateway |
| 57 | code comments |
| 39 | dependency-direction violations |
| 18 | oversized methods |
| 17 | oversized modules |
| 8 | `Container.resolve` service-locator calls |
| 6 | nested or conditional imports |
| 4 | imports from the mixed `src.constants` facade |
| 4 | missing required owner classes |
| 3 | exact duplicate method implementations |
| 2 | production classes with no production caller |

## Historical ownership failures

- `application.py` exposes composition functions instead of `Application`.
- `container.py` and `dependencies.py` split one service-container responsibility and models call `Container.resolve`.
- `registry.py` and `middleware/pipeline.py` split route ordering into loose module tuples and functions.
- Alexa, client, database, controller, middleware, service, and utility modules still contain free functions.
- Constants remain in clients, controllers, middleware, speech, registry, and utilities instead of focused constant classes.
- Middleware and feature code read and write Alexa request attributes directly instead of using `User` and `RequestContext`.
- `DEFAULT_STORE` and `PERSISTED_FIELDS` are separate manually maintained state declarations.
- `utils/filters.py` mixes filter normalization, Alexa request parsing, User locality state, payload construction, and discovery phrase policy.
- Resolver and confirmation middleware contain feature workflows instead of thin interception.
- Launch, intent dispatch, playback events, and report controllers contain application workflows instead of thin delegation.
- Search, playback, confirmation, onboarding, and feedback models coordinate too many independent workflows inside oversized classes.
- `PlaybackStateRepository` duplicates the main persistence path, `BackgroundTaskManager` has no production caller, and observability exposes module-level singleton aliases.

## Completed migration sequence

The migration established application ownership in this order:

1. Create `ApplicationContainer` in `container.py`.
2. Move dependency construction from `Dependencies` into it.
3. Inject exact dependencies into models, middleware, and controllers.
4. Remove every `Container.resolve` call.
5. Create `Application` and `RouteRegistry` classes.
6. Delete `dependencies.py` after all imports migrate.

Then establish `User` and `RequestContext` before moving feature workflows. This prevents another round of direct dictionary access during controller and middleware cleanup.
