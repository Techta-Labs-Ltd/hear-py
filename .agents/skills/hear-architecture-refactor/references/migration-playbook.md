# Migration playbook

## Completion standard

A migration is complete only when callers use the new owner, obsolete files and aliases are removed, strict architecture checks pass, and behavior tests pass. A compatibility wrapper is unfinished work.

## Sequence

1. Run the architecture audit, Ruff design checks, compile checks, and the full test suite.
2. Record handler order, middleware order, persistence timing, response envelopes, and external request payloads in characterization tests.
3. Replace `dependencies.py` and the service-locator wrapper with one `ApplicationContainer` class in `container.py`.
4. Create class-owned constant groups and migrate loose module constants and intent collections.
5. Convert request parsing, response building, speech, directives, filters, content normalization, playback helpers, and deadlines into focused classes.
6. Introduce `RequestContext` and migrate every raw request-attribute access.
7. Complete the `User` state schema and route all listener-state changes through `User`.
8. Make `Listener` compose `User`; remove duplicate identity or listener-state owners.
9. Consolidate DynamoDB and memory persistence behind one User persistence contract.
10. Move middleware policy into model or policy classes and leave interceptors thin.
11. Move controller workflows into feature model classes and leave handlers thin.
12. Replace giant conditional dispatch with class-owned route mapping.
13. Consolidate exact duplicate helpers and repeated filter/query logic into one utility class.
14. Remove dead classes, aliases, wrappers, unused imports, empty services, obsolete files, and cache-only legacy folders.
15. Run focused tests after each vertical slice and the complete verification suite at the end.

## Safe migration loop

For each ownership move:

1. Identify every importer and behavioral test.
2. Add missing characterization tests.
3. Create or extend the final owner class.
4. Move behavior without changing inputs, outputs, or side effects.
5. Update all callers in the same change.
6. Delete the previous implementation and compatibility path.
7. Run the architecture audit and focused tests.

## Refactor priorities for the current repository

1. Remove the `Container.resolve` service-locator pattern from models.
2. Merge `Dependencies` and `Container` into `ApplicationContainer`.
3. Replace raw `request_attributes` access with `User` and `RequestContext`.
4. Replace all module functions and module assignments under `src` with class methods and class attributes.
5. Centralize duplicated intent groups, search filters, state fields, and normalization logic.
6. Thin resolver and confirmation middleware.
7. Thin launch, playback-event, intent-dispatch, and report controllers.
8. Decompose oversized search, playback, confirmation, onboarding, and feedback workflows into cohesive classes without creating unnecessary feature folders.
9. Remove test-only production classes and module-level observability aliases.
10. Remove code comments from migrated source and rely on names and tests.

## Verification commands

```powershell
python .agents/skills/hear-architecture-refactor/scripts/audit_architecture.py . --strict
python -m ruff check src tests --select E4,E7,E9,F,I,C90,PLR0912,PLR0913,PLR0915
python -m compileall -q main.py src config
python -m pytest -q
```
