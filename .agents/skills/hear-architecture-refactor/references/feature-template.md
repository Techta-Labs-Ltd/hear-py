# Feature template

## Feature model

One feature module contains a public facade class and only the tightly related classes that share its lifecycle and state. Every dependency arrives through the constructor. Public methods express use cases. Private methods contain cohesive internal policy.

## Controller

The controller constructor receives exactly one feature model. `can_handle` matches one request contract. `handle` calls one feature method and passes its result to an Alexa response class.

## Utility

A utility module contains one focused utility class. Stateless operations use static or class methods. Utilities accept ordinary values and return ordinary values. They do not accept `HandlerInput`, resolve dependencies, access User state, log, perform I/O, or construct Alexa responses.

## Constants

A constants module contains one or more focused enum or constant classes. Callers import the owning class from its specific module and qualify values through the class. Do not re-export a mixed constants catalog from `constants/__init__.py`.

## State

Feature models read and update durable listener state through their injected `User`. They use `RequestContext` for request-only state. They never access Alexa attributes directly.

## Tests

Cover controller match and delegation, model success and failure behavior, User state changes, request-context changes, Alexa response adaptation, external client calls, and a nearby non-match. Keep architecture tests that reject free functions, module assignments, nested imports, raw state access, and container resolution.
