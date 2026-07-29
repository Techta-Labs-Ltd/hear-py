from __future__ import annotations

from src.handlers.can_fulfill import CanFulfillIntentHandler
from src.handlers.intents import ErrorHandler, TownCaptureHandler
from src.middleware.deadline import LambdaDeadlineInterceptor
from src.middleware.feedback_gate import FeedbackGateHandler
from src.middleware.notification import NotificationMiddleware
from src.middleware.onboarding_gate import OnboardingGateHandler
from src.nlp import NlpInterceptor
from src.nlp.dispatch_handler import IntentDispatchHandler
from src.services.storage.persistence import (
    LoadPersistenceInterceptor,
    SavePersistenceInterceptor,
)

GATE_HANDLERS = (
    CanFulfillIntentHandler,
    FeedbackGateHandler,
    OnboardingGateHandler,
    TownCaptureHandler,
    IntentDispatchHandler,
)

REQUEST_INTERCEPTORS = (
    LambdaDeadlineInterceptor,
    LoadPersistenceInterceptor,
    NotificationMiddleware,
    NlpInterceptor,
)

RESPONSE_INTERCEPTORS = (SavePersistenceInterceptor,)


def register_middleware(builder) -> None:
    for handler_type in GATE_HANDLERS:
        builder.add_request_handler(handler_type())
    builder.add_exception_handler(ErrorHandler())
    for interceptor_type in REQUEST_INTERCEPTORS:
        builder.add_global_request_interceptor(interceptor_type())
    for interceptor_type in RESPONSE_INTERCEPTORS:
        builder.add_global_response_interceptor(interceptor_type())
