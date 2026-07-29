---
name: hear-alexa-python
description: Build, refactor, review, debug, and verify the Hear Python Alexa skill backend in this repository. Use for Alexa handlers, AudioPlayer events, middleware, interaction-model intents or slots, persistence, Hear API integrations, webhooks, async runtime behavior, tests, configuration, or Lambda/SAM deployment; also use to flag wrong classes, calls, names, duplicate functions, misplaced code, unsafe SSML, broken handler order, and architecture violations.
---

# Hear Alexa Python

## Establish the source of truth

1. Read `README.md`, the files being changed, their registries or exports, and the closest tests.
2. Read [references/architecture.md](references/architecture.md) before choosing a folder, class, function, or registration point.
3. Read [references/alexa-python-practices.md](references/alexa-python-practices.md) for handler, response, AudioPlayer, state, permission, or interaction-model work.
4. Treat executable code, tests, and `README.md` as the architectural source of truth.
5. Search before writing:

```powershell
rg "class ProposedName|def proposed_name|ProposedIntent" src tests en-GB.json
rg "existing_concept|existing_api_call" src tests
```

Reuse or extend the existing owner. Never add a second implementation of the same responsibility.

## Implement in the established shape

- Keep `main.py` a transport adapter and `src/application.py` the composition root.
- Put Alexa handlers under `src/handlers/<feature>/`; derive them from `AbstractRequestHandler`.
- Make `can_handle(handler_input) -> bool` narrow and side-effect free. Use `async def handle` whenever it awaits or participates in the async runtime.
- Register handlers only in `src/handlers/registry.py`. Put specific handlers before fallbacks.
- Register middleware only through `src/middleware/pipeline.py`; preserve behaviorally significant order.
- Put orchestration and external effects in `src/services/`; put pure parsing, formatting, normalization, and calculations in `src/utils/`.
- Put storage implementations behind `src/adapters/` or repositories in `src/services/storage/`.
- Keep reusable speech in `src/utils/speech.py`; escape dynamic user/API text.
- Keep settings in `config/`; never embed credentials, endpoints, table names, or permission scopes in feature code.
- Update `en-GB.json`, NLP routing, exports, registry entries, and tests together when adding or renaming an intent.
- Use existing runtime types and response-builder methods. Do not invent SDK methods or mix a synchronous builder lifecycle into `AsyncSkill`.
- Keep one canonical class or function per responsibility. Extract shared logic instead of copying it.

## Execute changes

1. Trace the request from `main.py` through application construction, middleware, dispatch, services, persistence, and response.
2. Identify the files and contracts that must change.
3. Make the smallest cohesive edit and preserve unrelated changes.
4. Test dispatch selection, directives/cards/SSML, state transitions, ordering, and failure paths as applicable.
5. Run:

```powershell
python .agents/skills/hear-alexa-python/scripts/audit_project.py .
python -m compileall -q main.py src config
python -m pytest -q
```

If Python is blocked by the sandbox, retry with required execution approval. Never claim verification unless the commands ran.

## Flag incorrect implementations

For review-only requests, report findings without editing. Give file and line, violated contract, runtime impact, and preferred owner/pattern.

Block completion for:

- duplicate module-level functions/classes or duplicate handler registration;
- handlers after catch-all fallbacks;
- wrong handler base class or missing `can_handle`/`handle`;
- direct registration in `main.py`;
- interaction-model, NLP, export, and registry mismatches;
- unsafe dynamic SSML, malformed AudioPlayer directives, or unstable tokens;
- persistence mutation bypassing its service/repository owner;
- blocking network work in the async request path;
- swallowed exceptions without useful logging or deliberate fallback;
- committed secrets or production identifiers;
- tests that mock away the behavior they claim to prove.

Separate pre-existing findings from regressions. Do not silently clean unrelated code.

## Completion gate

Confirm names are unique, placement and ownership are correct, actual base types/signatures/APIs are used, order remains intentional, Alexa response and state behavior is covered, model and Python routing agree, and audit/compilation/tests pass or exact failures are reported.
