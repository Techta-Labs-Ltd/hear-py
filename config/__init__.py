import os
from functools import cached_property
from pydantic_settings import BaseSettings


def _is_lambda() -> bool:
    return (os.environ.get("AWS_EXECUTION_ENV") or "").startswith("AWS_Lambda_")


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    HEAR_API_URL: str = ""
    HEAR_API_KEY: str = ""
    HEAR_API_TIMEOUT_MS: int | None = None
    HEAR_API_RETRY: int | None = None
    HEAR_API_PATH_PREFIX: str = ""
    HEAR_API_REQUEST_LOG: bool = False
    HEAR_LISTENER_API: str = ""
    HEAR_ALEXA_API_URL: str = ""
    HEAR_AI_SERVICE_SECRET: str = ""

    @cached_property
    def api_base_url(self) -> str:
        return self.HEAR_API_URL

    @cached_property
    def api_key(self) -> str:
        return self.HEAR_API_KEY

    @cached_property
    def api_timeout_ms(self) -> int | None:
        if self.HEAR_API_TIMEOUT_MS is not None and self.HEAR_API_TIMEOUT_MS > 0:
            return self.HEAR_API_TIMEOUT_MS
        if _is_lambda():
            return 8000
        return None

    @cached_property
    def api_retry_count(self) -> int:
        if self.HEAR_API_RETRY is not None and self.HEAR_API_RETRY >= 0:
            return self.HEAR_API_RETRY
        return 0 if _is_lambda() else 2

    @cached_property
    def api_path_prefix(self) -> str:
        return self.HEAR_API_PATH_PREFIX.strip("/")

    @cached_property
    def api_request_log(self) -> bool:
        return self.HEAR_API_REQUEST_LOG

    HEAR_TAXONOMY_MANIFEST_URL: str = (
        "https://cdn.hear.media/runtime/taxonomy/v3/manifest.json"
    )
    HEAR_TAXONOMY_REVISION_TABLE: str = ""
    HEAR_TAXONOMY_REFRESH_SECONDS: int = 300
    HEAR_TAXONOMY_AUTO_REFRESH: bool = _is_lambda()
    HEAR_TAXONOMY_BUNDLE_DIR: str = ""
    HEAR_SEMANTIC_ROUTER_ENABLED: bool = _is_lambda()
    HEAR_SEMANTIC_ROUTER_MODEL: str = "BAAI/bge-small-en-v1.5"
    HEAR_SEMANTIC_ROUTER_CACHE_DIR: str = "/opt/hear-semantic-models"
    HEAR_SEMANTIC_ROUTER_INDEX_PATH: str = "/opt/hear-semantic-index.npz"
    HEAR_SEMANTIC_ROUTER_THRESHOLD: float = 0.72
    HEAR_SEMANTIC_ROUTER_THREADS: int = 2

    SENTRY_DSN: str = ""
    SENTRY_ENVIRONMENT: str = "development"
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0
    STAGE: str = "development"
    NODE_ENV: str = "development"

    HEAR_DDB_TABLE: str = ""
    HEAR_NLP_TABLE: str = ""
    HEAR_PERSISTENCE_DRIVER: str = "dynamodb"
    HEAR_PERSISTENCE_TTL_DAYS: int = 180
    HEAR_DDB_REGION: str = "eu-west-1"
    HEAR_PERSISTENCE_CONDITIONAL: bool = False
    DYNAMO_PLAYBACK_STATE_TABLE: str = ""
    AWS_REGION: str = "eu-west-1"

    @cached_property
    def dynamo_table(self) -> str:
        return self.HEAR_DDB_TABLE or self.HEAR_NLP_TABLE or "hear-service"

    @cached_property
    def ddb_region(self) -> str:
        return self.HEAR_DDB_REGION or self.AWS_REGION or "eu-west-1"

    HEAR_FEEDBACK_RATIO: float = 0.7
    HEAR_FEEDBACK_SHORT_RATIO: float = 0.6
    HEAR_FEEDBACK_SHORT_THRESHOLD_SECS: int = 30
    HEAR_FEEDBACK_REMINDER: bool = True
    HEAR_FEEDBACK_NEARLY_BUFFER_MS: int = 30000
    HEAR_FEEDBACK_TAIL_MS: int = 45000
    HEAR_FEEDBACK_REMINDER_OFFSET_SEC: int = 45
    HEAR_RECENT_EXCLUDE_LIMIT: int = 20
    HEAR_AUDIO_SPEED_PARAM: str = "speed"
    HEAR_QUEUE_REFILL_THRESHOLD: int = 2
    HEAR_QUEUE_PREFETCH_LIMIT: int = 10
    HEAR_STILL_LISTENING_INTERVAL: int = 5
    HEAR_MIN_TRACK_RECORD_MS: int = 3000
    HEAR_MAX_TRACK_LISTEN_LOG: int = 20
    HEAR_SEARCH_PAGE_LIMIT: int = 3
    HEAR_BROWSE_SPEAK_WINDOW: int = 3
    HEAR_BROWSE_MAX_CATALOG: int = 50
    HEAR_REFRESH_BROWSE_ON_LAUNCH: bool = True
    HEAR_REFRESH_BROWSE_ON_BARE_PLAY: bool = True

    @cached_property
    def feedback_trigger_ms(self) -> int:
        return 90000

    @cached_property
    def speeds(self) -> list[float]:
        return [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0]

    @cached_property
    def default_speed(self) -> float:
        return 1.0

    @cached_property
    def seek_step_ms(self) -> int:
        return 30000

    @cached_property
    def max_seek_ms(self) -> int:
        return 300000

    @cached_property
    def max_history(self) -> int:
        return 20

    @cached_property
    def search_page_limit(self) -> int:
        return max(self.HEAR_SEARCH_PAGE_LIMIT, 1)

    @cached_property
    def locality_ttl_ms(self) -> int:
        return 7 * 24 * 60 * 60 * 1000

    HEAR_ENABLE_CITY_CAPTURE: bool = False

    HEAR_GEO_RADIUS_KM: int = 30

    HEAR_LAMBDA_TIMEOUT_SEC: int = 8
    HEAR_LAMBDA_MEMORY_MB: int = 512

    WEBHOOK_SECRET: str = ""
    SETTINGS_TABLE: str = "hear_settings"
    NOTIFICATIONS_TABLE: str = "hear_notifications"
    WEBHOOK_OUTBOUND_URL: str = ""
    WEBHOOK_OUTBOUND_SECRET: str = ""
    SQS_OUT_QUEUE_URL: str = ""
    WEBHOOK_API_GATEWAY_URL: str = ""
    WEBHOOK_SIGNATURE_TOLERANCE_SECONDS: int = 300

    ALEXA_SKILL_ID: str = ""

    @cached_property
    def debug_hear(self) -> bool:
        return os.environ.get("DEBUG_HEAR", "0") == "1"


settings = Settings()
