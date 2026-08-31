---
name: hear-architecture-refactor
description: Audit and refactor the Hear Python Alexa backend into strict class-only Laravel-style MVC. Use for whole-project restructuring, duplicated logic, loose functions or constants, service-locator cleanup, User and listener state centralization, DynamoDB ownership, reusable filters and utilities, middleware routing, dead code removal, or behavior-preserving architecture migrations.
---

# Hear Architecture Refactor

Restructure `src` into a class-only MVC application while preserving Alexa behavior, middleware order, persistence, external API contracts, and deployment behavior.

## Hard rules

- Every Python module under `src` contains top-level imports and class definitions only.
- Do not leave module functions, async functions, assignments, instantiated objects, loggers, aliases, executable expressions, `TYPE_CHECKING` blocks, or nested imports.
- Put every import at the top of its module. Resolve circular dependencies through ownership and constructor injection.
- Put immutable values in focused classes or enums under `src/constants`.
- Put reusable transformations in focused utility classes with static or class methods under `src/utils`.
- Do not add code comments. Use class names, method names, types, and tests to communicate intent.
- Keep controllers thin: request match, one model call, Alexa response adaptation.
- Keep application logic in feature model classes. Do not put Alexa routing, SDK handlers, HTTP calls, or DynamoDB calls in models.
- Use one constructor-injected application container. Never resolve the container from a model, controller, service, or utility.
- Use `User` as the only persistent listener-state gateway and `RequestContext` as the only transient request-state gateway.
- Make `Listener` depend on `User`; do not create parallel identity, profile-state, or listener-store models.
- Keep DynamoDB implementation in class-based database adapters that use the key and serialization contracts owned by `User`.
- Centralize each filter, query normalization, field name, intent group, and state schema once. Delete duplicate implementations after callers migrate.
- Do not create `actions`, `adapters`, `handlers`, `presenters`, `repositories`, or `runtime` packages.
- Do not retain compatibility aliases, dead wrappers, duplicate containers, or test-only production classes after migration.

`main.py` may expose the module-level Lambda `handler` required by AWS. Do not use that transport exception inside `src`.

## Workflow

1. Run `python .agents/skills/hear-architecture-refactor/scripts/audit_architecture.py .`.
2. Read [references/current-audit.md](references/current-audit.md) for the current prioritized violations.
3. Read [references/class-only-mvc.md](references/class-only-mvc.md) before changing structure.
4. Read [references/state-and-persistence.md](references/state-and-persistence.md) for User, listener, request state, or DynamoDB work.
5. Read [references/routing-and-middleware.md](references/routing-and-middleware.md) for controllers, routing, gates, interceptors, or Alexa dispatch.
6. Read [references/migration-playbook.md](references/migration-playbook.md) for a whole-project migration.
7. Use [references/feature-template.md](references/feature-template.md) when moving a feature vertical slice.
8. Establish baseline tests before structural edits. Add characterization tests for uncovered behavior.
9. Migrate one ownership boundary at a time, update every caller, remove the obsolete source, and run focused tests.
10. Run the architecture audit, Ruff, compile checks, and the full test suite before declaring completion.

## Decision rules

- Consolidate files when they share callers, lifecycle, state, and reason to change.
- Split files only when responsibilities have independent callers or lifecycles. Do not split merely because a file is long.
- A large class is still a violation when it coordinates unrelated workflows. Extract cohesive class collaborators into the same feature module first; create another module only for an independently owned feature.
- Pure deterministic logic belongs to a utility class. Stateful business rules belong to a model class. External I/O belongs to a client or database class. Cross-client orchestration belongs to a service class.
- Controllers and middleware receive the exact model or policy class they use, not the whole container.
- Preserve request-handler order, interceptor order, AudioPlayer no-speech rules, SSML safety, persistence timing, resolver contracts, and response envelopes.

## Verification

```powershell
python .agents/skills/hear-architecture-refactor/scripts/audit_architecture.py . --strict
python -m ruff check src tests
python -m compileall -q main.py src config
python -m pytest -q
```

Do not claim the migration is complete while the strict audit reports violations or behavior tests fail.
