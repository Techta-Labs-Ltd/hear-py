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

    SENTRY_DSN: str = ""
    SENTRY_ENVIRONMENT: str = "development"
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0
    STAGE: str = "development"
    NODE_ENV: str = "development"

    HEAR_DDB_TABLE: str = ""
    HEAR_DDB_PARTITION_KEY: str = "id"
    HEAR_PERSISTENCE_DRIVER: str = "dynamodb"
    HEAR_PERSISTENCE_TTL_DAYS: int = 180
    HEAR_DDB_REGION: str = "eu-west-1"
    AWS_REGION: str = "eu-west-1"

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

    @cached_property
    def feedback_trigger_ms(self) -> int:
        return 90000

    @cached_property
    def speeds(self) -> list[float]:
        return [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]

    @cached_property
    def default_speed(self) -> float:
        return 1.0

    @cached_property
    def seek_step_ms(self) -> int:
        return 30000

    @cached_property
    def max_history(self) -> int:
        return 20

    @cached_property
    def search_page_limit(self) -> int:
        return max(self.HEAR_SEARCH_PAGE_LIMIT, 1)


settings = Settings()
