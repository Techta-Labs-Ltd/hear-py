# State and persistence

## State owners

Use three explicit owners:

- `User` owns durable listener state, defaults, allowed fields, serialization, updates, dirty tracking, reliable-save requirements, and persistence identity.
- `Listener` owns listener identity and profile behavior by composing an injected `User` instance.
- `RequestContext` owns resolver output, pending confirmations, deadlines, diagnostics, and other request-only values.

No other class reads or writes raw `handler_input.attributes_manager.request_attributes`. Session access also belongs behind a focused Alexa context class.

## User contract

`User` provides class-owned methods for:

- loading a snapshot;
- reading one field;
- applying validated changes;
- removing fields;
- incrementing counters;
- appending capped history;
- marking reliable persistence;
- deriving the Alexa persistence key;
- serializing persisted fields;
- hydrating defaults from stored data.

Feature models call these methods instead of merging dictionaries or setting `_store` and `_dirty` directly.

## State schema

Define each state field once in a focused constant or schema class. The same declaration provides its default, persistence policy, and optional normalization. Do not manually maintain separate default and persisted-field lists that can drift.

Keep transient request flags out of the User store. Values such as resolver payloads, pending middleware output, diagnostics, and deadline budgets belong to `RequestContext`.

## Listener ownership

Do not create separate identity and listener models for the same Alexa user. `Listener` receives `User` through its constructor and exposes listener-specific behavior. Profile and synchronization services receive `Listener` or `User`; they never mutate raw dictionaries.

## DynamoDB ownership

Use one persistence path:

- `DynamoUserStore` or an equivalently clear database class owns DynamoDB calls.
- `User.persistence_key` owns key derivation.
- `User.serialize` owns the persisted document.
- `User.hydrate` owns defaults and migrations.
- Persistence middleware coordinates load before state-dependent middleware and save after the response.

Delete secondary playback repositories, memory stores, DynamoDB wrappers, or test-only persistence classes when they duplicate the User persistence path. Keep a class-based memory implementation only as the local implementation of the same interface.

## Update behavior

All feature updates flow through `User`. For atomic DynamoDB operations, expose a class method on the database store that accepts a typed update object owned by `User`; do not build update expressions in controllers, middleware, models, or utilities.

Tests cover default hydration, unknown fields, persistence keys, dirty state, reliable saves, serialization, conditional versions, TTL, concurrent updates, and listener-to-User delegation.
