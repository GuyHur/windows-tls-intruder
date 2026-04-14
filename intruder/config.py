from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8443
    auto_forward_timeout_ms: int = 30_000
    max_pending: int = 5_000
    debug: bool = False

    model_config = {"env_prefix": "TLS_INTRUDER_"}


settings = Settings()
