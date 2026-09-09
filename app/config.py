from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    public_base_url: str = ""
    vobiz_webhook_secret: str = ""
    business_name: str = "Your Business"
    agent_name: str = "Asha"
    agent_voice: str = "marin"
    default_language: str = "English and Hindi"
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_recipient: str = ""
    whatsapp_graph_version: str = "v25.0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
