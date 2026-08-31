# Class-only MVC architecture

## Target layout

```text
src/
|-- application.py
|-- container.py
|-- registry.py
|-- alexa/
|-- clients/
|-- constants/
|-- controllers/
|-- database/
|-- middleware/
|-- models/
|-- services/
`-- utils/
```

Do not add another architectural layer unless it has a distinct dependency boundary and independent lifecycle.

## Module shape

Every module under `src` contains only:

- `from __future__ import annotations` when required;
- normal imports at the top;
- class definitions.

The class-only rule forbids module functions, module variables, module constants, module logger instances, object singletons, callable aliases, `TYPE_CHECKING` blocks, import fallbacks, and imports inside methods.

Use these class forms:

- `Application` owns skill construction.
- `ApplicationContainer` owns dependency construction and object lifetimes.
- `RouteRegistry` owns ordered controller and middleware class collections as class attributes.
- Controllers subclass the Alexa handler contract and delegate to one injected model.
- Middleware classes delegate non-routing policy to an injected model or focused policy class.
- Feature models own application rules and state transitions.
- Clients own one external protocol.
- Services coordinate clients without Alexa routing or raw persistence access.
- Database classes own DynamoDB and persistence mechanics.
- Constant classes and enums own immutable values.
- Utility classes expose stateless static or class methods.
- Alexa classes own request parsing, response construction, SSML, directives, and runtime dispatch.

## Laravel mapping

| Laravel | Hear |
|---|---|
| Application bootstrap | `Application` |
| Service container | `ApplicationContainer` |
| Routes | `RouteRegistry` |
| Middleware | request interceptors and gate classes |
| Controller | Alexa request or AudioPlayer handler class |
| Model | feature application model class |
| Eloquent model state | `User` listener-state gateway |
| Database driver | class under `database` |
| HTTP integration | class under `clients` |
| Domain support | class under `services` or `utils` according to state and I/O |

## Dependency direction

```text
main -> Application -> ApplicationContainer + RouteRegistry
RouteRegistry -> controllers + middleware
controllers -> models + alexa
middleware -> models/policies + alexa
models -> User + injected services/clients + constants + utilities
services -> clients + constants + utilities
database -> User contracts + constants
clients -> constants + utilities
alexa -> constants + utilities
```

Reverse imports are violations. Models never import the container. Utilities never import Alexa, models, services, clients, database, controllers, middleware, or the container.

## Controller contract

A controller has one reason to change: its Alexa request contract. Its `can_handle` method only matches the request. Its `handle` method delegates to one injected model method and adapts the returned result to an Alexa response. Move searches, state changes, fallback policy, queue manipulation, confirmation decisions, and external calls out of controllers.

## Consolidation contract

Keep related classes in one feature module when they share lifecycle and state. Examples include playback state, playback queue, and playback workflow under `models/playback.py`, or listener identity and listener profile state under `models/listener.py`. Do not create a second model file merely for one helper class.

Do not use consolidation to justify thousand-line classes. Extract cohesive collaborators as classes within the owning feature first. Create a separate feature module only when the collaborator has independent callers, lifecycle, and state ownership.
