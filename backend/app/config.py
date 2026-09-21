from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Formwise Agent API"
    environment: str = "development"
    database_url: str = "sqlite:///./formwise.db"
    storage_root: str = "./private_storage"
    max_upload_size_bytes: int = 10 * 1024 * 1024
    browser_headless: bool = True
    browser_timeout_ms: int = 15000
    browser_navigation_timeout_ms: int = 20000
    browser_max_sessions_per_user: int = 2
    browser_max_pages_per_session: int = 3
    browser_screenshot_enabled: bool = True
    browser_block_private_networks: bool = True
    # Development-only exception is still restricted to localhost:5000 by
    # browser_agent._is_local_demo_url; production deployments must override
    # this to false and validate_production_security enforces that boundary.
    browser_allow_local_demo_target: bool = True
    browser_demo_target_port: int = 5000
    browser_use_enabled: bool = False
    browser_use_model: str = "gpt-5.6-luna"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    allow_legacy_user_header: bool = True
    serper_api_key: str = ""
    serper_url: str = "https://google.serper.dev/search"
    research_timeout_seconds: float = 20.0
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    frontend_base_url: str = "http://localhost:5173"
    email_provider: str = "brevo"
    email_delivery_enabled: bool = False

    live_browser_enabled: bool = True
    live_input_enabled: bool = True
    live_frame_interval_ms: int = 250
    live_policy_check_interval_ms: int = 750
    live_jpeg_quality: int = 60
    live_token_ttl_seconds: int = 300
    live_max_connections_per_session: int = 1
    live_max_message_bytes: int = 65536
    live_require_secure_transport: bool = False

    ai_failover_budget_seconds: float = 1.8
    ai_provider_timeout_seconds: float = 0.75
    ai_route_vision_form_reading: str = "gemini,groq,anthropic,openrouter"
    ai_route_document_processing: str = "base64_ai,azure_document_intelligence,aws_bedrock,gemini"
    ai_route_semantic_analysis: str = "anthropic,openai,gemini,mistral,cohere"
    ai_route_general: str = "openai,anthropic,gemini,groq,openrouter"

    model_config = SettingsConfigDict(env_file=".env", env_prefix="FORMWISE_", extra="ignore")


settings = Settings()
