from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Formwise Agent API"
    environment: str = "development"
    database_url: str = "sqlite:///./formwise.db"
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_pool_timeout_seconds: int = 30
    database_pool_recycle_seconds: int = 1800
    storage_root: str = "./private_storage"
    storage_provider: str = "local"
    storage_s3_endpoint_url: str = ""
    storage_s3_bucket: str = ""
    storage_s3_access_key_id: str = ""
    storage_s3_secret_access_key: str = ""
    storage_s3_region: str = "ap-south-1"
    storage_s3_server_side_encryption: str = "AES256"
    storage_s3_kms_key_id: str = ""
    storage_signed_url_ttl_seconds: int = 300
    max_upload_size_bytes: int = 10 * 1024 * 1024
    browser_headless: bool = True
    browser_timeout_ms: int = 15000
    browser_navigation_timeout_ms: int = 20000
    browser_max_sessions_per_user: int = 2
    browser_max_pages_per_session: int = 3
    browser_screenshot_enabled: bool = True
    browser_block_private_networks: bool = True
    browser_allow_local_demo_target: bool = True
    browser_demo_target_port: int = 5000
    browser_use_enabled: bool = False
    browser_use_model: str = "gpt-5.6-luna"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    allow_legacy_user_header: bool = True
    secure_cookies: bool = False
    csrf_enabled: bool = True
    serper_api_key: str = ""
    serper_url: str = "https://google.serper.dev/search"
    research_timeout_seconds: float = 20.0
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    frontend_base_url: str = "http://localhost:5173"
    email_provider: str = "brevo"
    email_delivery_enabled: bool = False
    redis_url: str = "redis://localhost:6379/0"
    redis_username: str = ""
    redis_password: str = ""
    redis_tls: bool = False
    redis_ca_file: str = ""
    redis_socket_timeout_seconds: float = 5.0
    redis_pool_max_connections: int = 50
    task_queue_name: str = "formwise:tasks"
    task_dead_letter_queue_name: str = "formwise:tasks:dead"
    task_worker_lease_seconds: int = 60
    task_worker_heartbeat_seconds: int = 15
    task_worker_concurrency: int = 2
    task_worker_shutdown_seconds: int = 30
    task_max_retries: int = 3
    task_retry_base_seconds: float = 2.0
    task_retry_max_seconds: float = 300.0
    api_request_size_limit_bytes: int = 12 * 1024 * 1024
    rate_limit_per_minute: int = 120
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
