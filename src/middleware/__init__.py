"""Central middleware registry for the Hear skill.

All cross-cutting request/response processing is wired here — the ordered gate
handlers (which must run before any content handler) and the global
request/response interceptors. ``main.py`` calls :func:`register_middleware`, so
the run order is defined in exactly one place.

The order is load-bearing. Do not reorder without understanding the flow:

Gate handlers (first match wins; registered before all content handlers):
  1. CanFulfillIntentHandler  - answers CanFulfillIntentRequest (name-free)
  2. FeedbackGateHandler      - intercepts while awaiting post-listen feedback
  3. OnboardingGateHandler    - routes new users through onboarding
  4. TownCaptureHandler       - captures the town during onboarding
  5. IntentDispatchHandler    - dispatches NLP-classified intents

Global request interceptors (run top-to-bottom on every request):
  1. LambdaDeadlineInterceptor  - stamps the invocation deadline
  2. LoadPersistenceInterceptor - loads the user store (must precede readers)
  3. NotificationMiddleware
  4. NlpInterceptor             - NLP classification (reads the store)
  5. LocalityGateMiddleware
  6. ConfirmationMiddleware

Global response interceptor:
  - SavePersistenceInterceptor  - persists the store (must run last)

Self-contained middleware lives in this package. Three components are left in
their home modules because they are too coupled to relocate cleanly, and are
merely referenced here for ordering: the persistence interceptors
(``src.services.persistence``) and ``NlpInterceptor`` (``src.nlp``).
"""
from __future__ import annotations

# --- Gate handlers -----------------------------------------------------------
from src.handlers.can_fulfill import CanFulfillIntentHandler
from src.middleware.feedback_gate import FeedbackGateHandler
from src.middleware.onboarding_gate import OnboardingGateHandler
from src.handlers.intents import TownCaptureHandler, ErrorHandler
from src.nlp.dispatch_handler import IntentDispatchHandler

# --- Interceptors ------------------------------------------------------------
from src.middleware.deadline import LambdaDeadlineInterceptor
from src.services.persistence import LoadPersistenceInterceptor, SavePersistenceInterceptor
from src.middleware.notification import NotificationMiddleware
from src.nlp import NlpInterceptor
from src.middleware.locality_gate import LocalityGateMiddleware
from src.middleware.confirmation import ConfirmationMiddleware

# Ordered gate handlers — registered before any content handler so they win.
GATE_HANDLERS = [
    CanFulfillIntentHandler,
    FeedbackGateHandler,
    OnboardingGateHandler,
    TownCaptureHandler,
    IntentDispatchHandler,
]

# Ordered global request interceptors.
REQUEST_INTERCEPTORS = [
    LambdaDeadlineInterceptor,
    LoadPersistenceInterceptor,
    NotificationMiddleware,
    NlpInterceptor,
    LocalityGateMiddleware,
    ConfirmationMiddleware,
]

# Ordered global response interceptors.
RESPONSE_INTERCEPTORS = [
    SavePersistenceInterceptor,
]

__all__ = [
    "register_middleware",
    "GATE_HANDLERS",
    "REQUEST_INTERCEPTORS",
    "RESPONSE_INTERCEPTORS",
]


def register_middleware(builder) -> None:
    """Register every gate handler, interceptor, and the exception handler on
    the skill ``builder`` in the one correct order.

    Call this *before* registering content handlers so the gate handlers take
    precedence over them.
    """
    for handler_cls in GATE_HANDLERS:
        builder.add_request_handler(handler_cls)

    builder.add_exception_handler(ErrorHandler)

    for interceptor_cls in REQUEST_INTERCEPTORS:
        builder.add_global_request_interceptor(interceptor_cls())

    for interceptor_cls in RESPONSE_INTERCEPTORS:
        builder.add_global_response_interceptor(interceptor_cls())
