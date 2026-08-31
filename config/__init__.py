from functools import cached_property

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    HEAR_API_URL: str = ""
    HEAR_API_KEY: str = ""
    HEAR_API_TIMEOUT_MS: int | None = None
    HEAR_API_RETRY: int | None = None
    HEAR_API_PATH_PREFIX: str = ""
    HEAR_CLIENT_VERSION: str = "alexa-skill"
    HEAR_HTTP_DEFAULT_TIMEOUT_MS: int = 30000
    HEAR_HTTP_MAX_CONNECTIONS: int = 20
    HEAR_HTTP_MAX_KEEPALIVE_CONNECTIONS: int = 10
    HEAR_HTTP_CIRCUIT_FAILURE_THRESHOLD: int = 5
    HEAR_HTTP_CIRCUIT_RECOVERY_MS: int = 30000
    HEAR_ALEXA_API_TIMEOUT_MS: int = 10000
    HEAR_EVENT_WEBHOOK_TIMEOUT_MS: int = 10000
    HEAR_PROGRESSIVE_TIMEOUT_MS: int = 700
    HEAR_PROGRESSIVE_RESPONSES: bool | None = None
    HEAR_RESOLVER_URL: str = "https://resolver.hear.media"
    HEAR_RESOLVER_TIMEOUT_MS: int = 5000
    HEAR_RESOLVER_DEFAULT_COUNTRY: str = "gb"
    HEAR_RESOLVER_TIMEZONE: str = "Europe/London"
    HEAR_RESOLVER_CACHE_TTL_MS: int = 60000
    HEAR_RESOLVER_CACHE_MAX_ITEMS: int = 128
    HEAR_API_RETRY_BACKOFF_MS: int = 200

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
        if self.is_lambda:
            return 8000
        return None

    @cached_property
    def api_retry_count(self) -> int:
        if self.HEAR_API_RETRY is not None and self.HEAR_API_RETRY >= 0:
            return self.HEAR_API_RETRY
        return 0 if self.is_lambda else 2

    SENTRY_DSN: str = ""
    SENTRY_ENVIRONMENT: str = "development"
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0
    STAGE: str = "development"
    NODE_ENV: str = "development"
    DEBUG_HEAR: bool = False
    POWERTOOLS_SERVICE_NAME: str = "hear-alexa-skill"
    POWERTOOLS_LOG_LEVEL: str = "INFO"
    HEAR_METRICS_NAMESPACE: str = "HearAlexa"
    AWS_EXECUTION_ENV: str = ""

    HEAR_DDB_TABLE: str = ""
    HEAR_DDB_PARTITION_KEY: str = "id"
    HEAR_PERSISTENCE_DRIVER: str = "dynamodb"
    HEAR_PERSISTENCE_CONDITIONAL: bool = True
    HEAR_PERSISTENCE_CONFLICT_RETRIES: int = 3
    HEAR_PERSISTENCE_CONFLICT_BACKOFF_MS: int = 20
    HEAR_PERSISTENCE_TTL_DAYS: int = 180
    HEAR_DDB_REGION: str = "eu-west-1"
    AWS_REGION: str = "eu-west-1"
    SQS_OUT_QUEUE_URL: str = ""
    WEBHOOK_OUTBOUND_URL: str = ""
    WEBHOOK_OUTBOUND_SECRET: str = ""
    HEAR_LISTENER_SYNC_ON_LAUNCH: bool = False
    HEAR_DDB_ITEM_SIZE_WARN_BYTES: int = 65536
    HEAR_DDB_ITEM_SIZE_MAX_BYTES: int = 350000
    HEAR_PERSISTED_COLLECTION_LIMIT: int = 100
    HEAR_PERSISTED_TEXT_LIMIT: int = 4096

    @cached_property
    def dynamo_table(self) -> str:
        return self.HEAR_DDB_TABLE or "hear-service"

    @cached_property
    def ddb_region(self) -> str:
        return self.HEAR_DDB_REGION or self.AWS_REGION or "eu-west-1"

    HEAR_FEEDBACK_RATIO: float = 0.7
    HEAR_FEEDBACK_SHORT_RATIO: float = 0.6
    HEAR_FEEDBACK_SHORT_THRESHOLD_SECS: int = 30
    HEAR_RECENT_EXCLUDE_LIMIT: int = 20
    HEAR_AUDIO_SPEED_PARAM: str = "speed"
    HEAR_QUEUE_PREFETCH_LIMIT: int = 10
    HEAR_MAX_TRACK_LISTEN_LOG: int = 20
    HEAR_SEARCH_PAGE_LIMIT: int = 3
    HEAR_BROWSE_MAX_CATALOG: int = 50
    HEAR_FEEDBACK_TRIGGER_MS: int = 90000
    HEAR_PLAYBACK_SPEEDS: str = "0.5,0.75,1.0,1.25,1.5,2.0"
    HEAR_DEFAULT_PLAYBACK_SPEED: float = 1.0
    HEAR_SEEK_STEP_MS: int = 30000
    HEAR_MAX_HISTORY: int = 20

    @cached_property
    def is_lambda(self) -> bool:
        return self.AWS_EXECUTION_ENV.startswith("AWS_Lambda_")

    @cached_property
    def progressive_responses_enabled(self) -> bool:
        if self.HEAR_PROGRESSIVE_RESPONSES is not None:
            return self.HEAR_PROGRESSIVE_RESPONSES
        return self.is_lambda

    @cached_property
    def feedback_trigger_ms(self) -> int:
        return max(self.HEAR_FEEDBACK_TRIGGER_MS, 0)

    @cached_property
    def speeds(self) -> list[float]:
        values = []
        for value in self.HEAR_PLAYBACK_SPEEDS.split(","):
            try:
                speed = float(value.strip())
            except ValueError:
                continue
            if speed > 0 and speed not in values:
                values.append(speed)
        return values or [1.0]

    @cached_property
    def default_speed(self) -> float:
        return self.HEAR_DEFAULT_PLAYBACK_SPEED if self.HEAR_DEFAULT_PLAYBACK_SPEED > 0 else 1.0

    @cached_property
    def seek_step_ms(self) -> int:
        return max(self.HEAR_SEEK_STEP_MS, 1000)

    @cached_property
    def max_history(self) -> int:
        return max(self.HEAR_MAX_HISTORY, 1)

    @cached_property
    def search_page_limit(self) -> int:
        return max(self.HEAR_SEARCH_PAGE_LIMIT, 1)


settings = Settings()
