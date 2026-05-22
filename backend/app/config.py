from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    agent_model: str = "gpt-4o-mini"

    redis_url: str = "redis://localhost:6379/0"
    database_url: str = "sqlite+aiosqlite:///./data/clinic.db"

    session_ttl_seconds: int = 3600
    patient_memory_ttl_seconds: int = 60 * 60 * 24 * 90

    deepgram_api_key: str = ""
    elevenlabs_api_key: str = ""

    latency_target_ms: int = 450


settings = Settings()
