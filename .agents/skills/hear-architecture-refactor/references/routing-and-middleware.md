# Routing and middleware

## Registry ownership

`RouteRegistry` is the single source of truth for ordered request controllers, gate handlers, request interceptors, response interceptors, and exception handlers. Store these collections as class attributes. Do not maintain separate loose tuples across `registry.py` and `middleware/pipeline.py`.

`Application` asks `RouteRegistry` to register constructed classes from `ApplicationContainer`.

## Preserved lifecycle

Preserve the current behavior until characterization tests prove a deliberate change:

```text
request interceptors
1. Lambda deadline
2. persistence load
3. dialog validation
4. identity
5. resolver
6. confirmation

gate handlers
1. can-fulfill
2. dialog validation
3. feedback
4. onboarding
5. town capture
6. search confirmation
7. resolved intent dispatch

request controllers
ordered from most specific to fallback

response interceptors
1. persistence save

exception handler
1. Alexa error handler
```

Order is a behavioral contract. Add a pipeline-order test before moving these classes.

## Middleware contract

Middleware intercepts or enriches a request. It does not become a second controller or contain a feature workflow. A middleware class may:

- inspect request metadata through Alexa request classes;
- read or write transient values through `RequestContext`;
- call one injected policy/model class;
- short-circuit with an Alexa response when that is the declared gate behavior.

Move resolver parsing, confirmation speech selection, ambiguity matching, and onboarding business decisions into cohesive model or policy classes. Keep only orchestration in the interceptor.

## Dispatch contract

Do not use one giant conditional intent dispatcher. Map canonical intent names to injected model commands through class-owned registry data. Each command is a class. Controller and middleware code never instantiate the application container or construct feature dependencies.

## Alexa behavior parity

Preserve:

- first-match handler semantics;
- CanFulfill response envelopes;
- AudioPlayer events returning no speech;
- safe SSML and card behavior;
- progressive-response timing;
- resolver-unavailable fallback behavior;
- confirmation and onboarding follow-up ownership;
- persistence on success, short-circuit, and exception paths;
- session-ending behavior and reprompts.

Test success, non-match, short-circuit, exception, and persistence behavior for every pipeline migration.
