# File ledger

Every tracked baseline file and new deliverable is classified below. Preserved means unchanged in this release; it does not mark pending comprehensive architecture requirements as fixed. Live service/AWS acceptance blockers are listed in IMPLEMENTATION_STATUS.md.

| File | Classification | Reason |
| --- | --- | --- |
| `.agents/skills/hear-architecture-refactor/SKILL.md` | Preserved | Repository skill and audit policy retained without modification. |
| `.agents/skills/hear-architecture-refactor/agents/openai.yaml` | Preserved | Repository skill and audit policy retained without modification. |
| `.agents/skills/hear-architecture-refactor/references/class-only-mvc.md` | Preserved | Repository skill and audit policy retained without modification. |
| `.agents/skills/hear-architecture-refactor/references/current-audit.md` | Preserved | Repository skill and audit policy retained without modification. |
| `.agents/skills/hear-architecture-refactor/references/feature-template.md` | Preserved | Repository skill and audit policy retained without modification. |
| `.agents/skills/hear-architecture-refactor/references/migration-playbook.md` | Preserved | Repository skill and audit policy retained without modification. |
| `.agents/skills/hear-architecture-refactor/references/routing-and-middleware.md` | Preserved | Repository skill and audit policy retained without modification. |
| `.agents/skills/hear-architecture-refactor/references/state-and-persistence.md` | Preserved | Repository skill and audit policy retained without modification. |
| `.agents/skills/hear-architecture-refactor/scripts/audit_architecture.py` | Preserved | Repository skill and audit policy retained without modification. |
| `.agents/skills/hear-architecture-refactor/scripts/migrate_class_modules.py` | Preserved | Repository skill and audit policy retained without modification. |
| `.agents/skills/hear-architecture-refactor/scripts/migrate_request_context.py` | Preserved | Repository skill and audit policy retained without modification. |
| `.dockerignore` | Preserved | No change required for this reliability stage; wider configuration/cleanup work remains tracked. |
| `.env.example` | Preserved | No change required for this reliability stage; wider configuration/cleanup work remains tracked. |
| `.github/workflows/deploy-develop.yml` | Preserved | Entrypoints, deployment paths and infrastructure retained; no deployment performed. |
| `.github/workflows/deploy-main.yml` | Preserved | Entrypoints, deployment paths and infrastructure retained; no deployment performed. |
| `.gitignore` | Preserved | No change required for this reliability stage; wider configuration/cleanup work remains tracked. |
| `Dockerfile` | Preserved | Entrypoints, deployment paths and infrastructure retained; no deployment performed. |
| `README.md` | Modified | Link the evidence-backed staged implementation status. |
| `alexa-slot-imports/HEAR_LOCATION.csv` | Preserved | No change required for this reliability stage; wider configuration/cleanup work remains tracked. |
| `alexa-slot-imports/HEAR_ORGANIZATION.csv` | Preserved | No change required for this reliability stage; wider configuration/cleanup work remains tracked. |
| `alexa-slot-imports/HEAR_TOPIC.csv` | Preserved | No change required for this reliability stage; wider configuration/cleanup work remains tracked. |
| `config/__init__.py` | Preserved | No change required for this reliability stage; wider configuration/cleanup work remains tracked. |
| `config/permission_scopes.py` | Preserved | No change required for this reliability stage; wider configuration/cleanup work remains tracked. |
| `deploy/ecr-lambda-policy.json` | Preserved | Entrypoints, deployment paths and infrastructure retained; no deployment performed. |
| `deploy/oidc-permissions-policy.json` | Preserved | Entrypoints, deployment paths and infrastructure retained; no deployment performed. |
| `deploy/oidc-trust-policy.json` | Preserved | Entrypoints, deployment paths and infrastructure retained; no deployment performed. |
| `docs/alexa-event-contracts.md` | Preserved | Existing documentation retained; current migration status is in the new evidence ledger. |
| `docs/alexa-permissions.md` | Preserved | Existing documentation retained; current migration status is in the new evidence ledger. |
| `docs/alexa-search-feedback-playback-audit.md` | Preserved | Existing documentation retained; current migration status is in the new evidence ledger. |
| `docs/alexa-search-slot.md` | Preserved | Existing documentation retained; current migration status is in the new evidence ledger. |
| `docs/architecture/API_CONSUMER_MAP.md` | Modified (new) | Evidence, supplied specification, consumer inventory or per-file status for the staged release. |
| `docs/architecture/COMPREHENSIVE_REFACTOR_SPEC.md` | Modified (new) | Evidence, supplied specification, consumer inventory or per-file status for the staged release. |
| `docs/architecture/FILE_LEDGER.md` | Modified (new) | Evidence, supplied specification, consumer inventory or per-file status for the staged release. |
| `docs/architecture/IMPLEMENTATION_STATUS.md` | Modified (new) | Evidence, supplied specification, consumer inventory or per-file status for the staged release. |
| `docs/availability-routing-payload-contract.md` | Preserved | Existing documentation retained; current migration status is in the new evidence ledger. |
| `docs/backend-events-and-feedback.md` | Preserved | Existing documentation retained; current migration status is in the new evidence ledger. |
| `docs/notification-delivery-plan.md` | Preserved | Existing documentation retained; current migration status is in the new evidence ledger. |
| `docs/universal-user-recognition-plan.md` | Preserved | Existing documentation retained; current migration status is in the new evidence ledger. |
| `en-GB.json` | Preserved | Wire/storage/interaction contract unchanged; JSON parsing checked. |
| `main.py` | Modified | Request-type-aware outer fallback; worker identifier validation and preserved deadlines. |
| `requirements.txt` | Preserved | No change required for this reliability stage; wider configuration/cleanup work remains tracked. |
| `ruff.toml` | Preserved | No change required for this reliability stage; wider configuration/cleanup work remains tracked. |
| `samconfig.toml` | Preserved | Entrypoints, deployment paths and infrastructure retained; no deployment performed. |
| `schemas/alexa-search-slot.schema.json` | Preserved | Wire/storage/interaction contract unchanged; JSON parsing checked. |
| `schemas/availability-request.schema.json` | Preserved | Wire/storage/interaction contract unchanged; JSON parsing checked. |
| `schemas/backend-event.schema.json` | Preserved | Wire/storage/interaction contract unchanged; JSON parsing checked. |
| `schemas/listener-identity-resolve.schema.json` | Preserved | Wire/storage/interaction contract unchanged; JSON parsing checked. |
| `schemas/listener-sync.schema.json` | Preserved | Wire/storage/interaction contract unchanged; JSON parsing checked. |
| `schemas/notification-delivery-message.schema.json` | Preserved | Wire/storage/interaction contract unchanged; JSON parsing checked. |
| `schemas/notification-item.schema.json` | Preserved | Wire/storage/interaction contract unchanged; JSON parsing checked. |
| `schemas/resolver-request.schema.json` | Preserved | Wire/storage/interaction contract unchanged; JSON parsing checked. |
| `schemas/resolver-response.schema.json` | Preserved | Wire/storage/interaction contract unchanged; JSON parsing checked. |
| `schemas/search-request.schema.json` | Preserved | Wire/storage/interaction contract unchanged; JSON parsing checked. |
| `schemas/search-response.schema.json` | Preserved | Wire/storage/interaction contract unchanged; JSON parsing checked. |
| `schemas/store.schema.json` | Preserved | Wire/storage/interaction contract unchanged; JSON parsing checked. |
| `scratch/debug_turn2b.py` | Preserved | No change required for this reliability stage; wider configuration/cleanup work remains tracked. |
| `scratch/diagnose_ambiguity.py` | Preserved | No change required for this reliability stage; wider configuration/cleanup work remains tracked. |
| `scratch/inspect_creators.py` | Preserved | No change required for this reliability stage; wider configuration/cleanup work remains tracked. |
| `scratch/inspect_openapi.py` | Preserved | No change required for this reliability stage; wider configuration/cleanup work remains tracked. |
| `scratch/test_all_56_intents.py` | Preserved | No change required for this reliability stage; wider configuration/cleanup work remains tracked. |
| `scratch/test_real_lambda_ambiguity.py` | Preserved | No change required for this reliability stage; wider configuration/cleanup work remains tracked. |
| `scratch/test_real_lambda_comprehensive.py` | Preserved | No change required for this reliability stage; wider configuration/cleanup work remains tracked. |
| `scratch/test_real_lambda_dialog_flows.py` | Preserved | No change required for this reliability stage; wider configuration/cleanup work remains tracked. |
| `scratch/test_turn2_simulation.py` | Preserved | No change required for this reliability stage; wider configuration/cleanup work remains tracked. |
| `scratch/update_tests.py` | Preserved | No change required for this reliability stage; wider configuration/cleanup work remains tracked. |
| `scripts/__init__.py` | Preserved | No change required for this reliability stage; wider configuration/cleanup work remains tracked. |
| `scripts/apply_alexa_slot_lexicon.py` | Preserved | No change required for this reliability stage; wider configuration/cleanup work remains tracked. |
| `scripts/build_alexa_interaction_model.py` | Preserved | No change required for this reliability stage; wider configuration/cleanup work remains tracked. |
| `scripts/deploy-live.ps1` | Preserved | No change required for this reliability stage; wider configuration/cleanup work remains tracked. |
| `scripts/deploy.sh` | Preserved | No change required for this reliability stage; wider configuration/cleanup work remains tracked. |
| `scripts/setup-github-oidc.sh` | Preserved | No change required for this reliability stage; wider configuration/cleanup work remains tracked. |
| `scripts/unresolved_imports.py` | Preserved | No change required for this reliability stage; wider configuration/cleanup work remains tracked. |
| `src/__init__.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/alexa/__init__.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/alexa/availability_speech.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/alexa/context.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/alexa/discovery_speech.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/alexa/entities.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/alexa/feedback.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/alexa/help.py` | Modified | Correct the pre-existing Ruff import-format error; formatting only. |
| `src/alexa/playback.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/alexa/playback_context.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/alexa/playback_speech.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/alexa/request.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/alexa/response.py` | Modified | Central callback response allowlists shared by normal and outer fallback paths. |
| `src/alexa/resume_speech.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/alexa/runtime.py` | Modified | Validated response before commit; fresh error builder; no commit after exception; bounded redispatch; direct interceptor binding. |
| `src/alexa/search_speech.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/alexa/speech.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/alexa/ssml.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/application.py` | Modified | Reject unknown drivers and non-durable deployed configurations. |
| `src/clients/__init__.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/clients/alexa.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/clients/alexa_settings.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/clients/availability.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/clients/events.py` | Modified | Validate v3 event envelope/data contracts before worker transmission. |
| `src/clients/hear.py` | Modified | Construct and validate configured Hear pool; preserve wire paths and bodies. |
| `src/clients/notifications.py` | Modified | Construct and validate configured notification pool; preserve wire contract. |
| `src/clients/pool.py` | Modified | Immutable upstream configuration, mismatch rejection and closed-client/loop isolation. |
| `src/clients/proactive.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/clients/progressive.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/clients/resolver.py` | Modified | Isolated anonymous cache, personalized bypass, bound pool, safe diagnostic fields. |
| `src/constants/__init__.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/constants/availability.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/constants/creator.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/constants/dialog.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/constants/discovery.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/constants/events.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/constants/listener.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/constants/notifications.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/constants/onboarding.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/constants/organization.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/constants/playback.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/constants/resolver.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/constants/search.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/constants/state.py` | Modified | Fresh default factory; persisted field/scope registry unchanged. |
| `src/container.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/controllers/__init__.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/controllers/availability.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/controllers/browse.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/controllers/can_fulfill.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/controllers/confirmation.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/controllers/error.py` | Modified | Remove error-path playback side effects; reuse request-aware fallback. |
| `src/controllers/fallback.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/controllers/feedback.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/controllers/intent_dispatch.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/controllers/launch.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/controllers/notifications.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/controllers/permission.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/controllers/play.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/controllers/playback_controls.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/controllers/playback_events.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/controllers/report.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/controllers/social.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/controllers/system.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/database/__init__.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/database/dynamo_merge.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/database/dynamo_user.py` | Modified | Return actual committed versions/documents after successful independent scope operations. |
| `src/database/dynamodb.py` | Modified | Lazy SDK construction and SDK timeouts; all SDK work remains offloaded. |
| `src/database/persistence.py` | Modified | Memory copies, change-set conflict merging and commit receipts. |
| `src/middleware/__init__.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/middleware/confirmation.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/middleware/deadline.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/middleware/dialog_validation.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/middleware/feedback_gate.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/middleware/identity.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/middleware/onboarding_gate.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/middleware/persistence.py` | Modified | Bound load/commit waits and propagate required-save failures. |
| `src/middleware/resolver.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/__init__.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/affirmative.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/availability.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/availability_data.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/availability_dialog.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/availability_request.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/browse.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/confirmation.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/decline.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/dialog.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/feedback.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/feedback_response.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/intent_dispatch.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/launch_workflow.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/listener.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/notifications.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/onboarding.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/onboarding_state.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/permission.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/play.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/playback.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/playback_controls.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/playback_events.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/playback_history.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/playback_state.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/report.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/resolver.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/resolver_runner.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/resolver_workflow.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/search.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/social.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/suggestion.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/models/user.py` | Modified | Own typed commit contracts, protected snapshots and confirmed-save bookkeeping. |
| `src/registry.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/services/__init__.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/services/alexa_locality.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/services/alexa_profile.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/services/events.py` | Modified | Validate each record, preserve batch deadline and report partial failures. |
| `src/services/listener_identity.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/services/listener_sync.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/services/logging_control.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/services/notification_delivery.py` | Modified | Validate message identifiers/targets; retain unacknowledged outcomes for retries/redrive. |
| `src/services/observability.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/utils/__init__.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/utils/alexa_date.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/utils/browse.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/utils/content.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/utils/content_normalizer.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/utils/deadline.py` | Modified | One captured deadline object and no fictitious time beyond the remaining budget. |
| `src/utils/events.py` | Modified | Shared SQS identifier validation and non-finite JSON rejection. |
| `src/utils/filters.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/utils/listener_payload.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/utils/notifications.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/utils/playback.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/utils/playback_history.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/utils/search_payload.py` | Preserved | Existing behaviour retained; remaining target ownership work is tracked in the status matrix. |
| `src/utils/user_state.py` | Modified | Final owner of moved pure normalization; existing collection policy preserved. |
| `template.yaml` | Preserved | Entrypoints, deployment paths and infrastructure retained; no deployment performed. |
| `tests/__init__.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/conftest.py` | Modified | Offline transport defaults plus collection/execution socket guards. |
| `tests/run_end_to_end.py` | Preserved | Existing optional end-to-end runner retained; not executed against live systems. |
| `tests/test_alexa_date.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_alexa_device_address.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_alexa_interaction_model_build.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_alexa_request.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_alexa_slot_lexicon.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_api_client.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_audio_player_runtime.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_availability_flow.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_cards_and_progressive.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_config.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_dialog_validation.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_discovery_prompt_capture.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_discovery_session_cleanup.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_dynamic_entities.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_dynamodb_persistence.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_feedback_queue_listener.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_help_command.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_http_pool_isolation.py` | Modified (new) | Behavioural regression coverage or fixture update for this reliability stage. |
| `tests/test_identity.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_interaction_model.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_launch_simulation.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_listener_repository.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_local_search_payload.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_logging_control.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_main.py` | Modified | Behavioural regression coverage or fixture update for this reliability stage. |
| `tests/test_middleware_pipeline.py` | Modified | Behavioural regression coverage or fixture update for this reliability stage. |
| `tests/test_normalize_content_item.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_notifications.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_onboarding_completion.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_onboarding_repository.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_onboarding_search_conversation.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_outbound_events.py` | Modified | Behavioural regression coverage or fixture update for this reliability stage. |
| `tests/test_permission_flow.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_persistence.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_playback_speech.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_playback_speed_validation.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_publication_feedback.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_publication_following_validation.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_reliability_foundation.py` | Modified (new) | Behavioural regression coverage or fixture update for this reliability stage. |
| `tests/test_reserved_discovery_phrases.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_resolver_client.py` | Modified | Behavioural regression coverage or fixture update for this reliability stage. |
| `tests/test_resolver_dispatch_routing.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_resolver_speech.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_runtime_failure_safety.py` | Modified (new) | Behavioural regression coverage or fixture update for this reliability stage. |
| `tests/test_search_confirmation.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_search_queue.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_structure.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_trending_playback.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
| `tests/test_utterance.py` | Preserved | Existing regression retained; pytest cases remain in the offline suite. |
