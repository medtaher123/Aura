"""Agent Server Configuration"""

from functools import lru_cache

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class AgentServerConfig(BaseSettings):
    """Agent Server configuration with environment variable support"""

    # Server settings
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8080, description="Server port")
    name: str = Field(default="agent-server", description="Server name")
    version: str = Field(default="1.0.0", description="API version")
    description: str = Field(
        default="Agent server for Metaplanet LLM orchestration",
        description="API description",
    )

    # Fargate-specific settings
    workers: int = Field(default=1, description="Number of worker processes")
    dev_mode: bool = Field(default=False, description="Enable development mode")
    log_level: str = Field(default="info", description="Logging level")
    timeout_seconds: int = Field(default=300, description="Request timeout in seconds")

    ws_traffic_log_enabled: bool = Field(default=True, description="Enable WebSocket traffic logging")
    ws_traffic_log_file: str = Field(default="logs/websocket_traffic.jsonl", description="WebSocket traffic log file")

    # MCP Server connection
    mcp_server_url: str = Field(
        default="http://localhost:8000",
        description="MCP Server URL for tool integration (use http://mcp-server:8000 in Docker)",
    )

    # AWS Bedrock settings
    bedrock_region: str = Field(
        default="eu-west-3",
        description="AWS region for Bedrock",
    )
    bedrock_max_tokens: int = Field(
        default=4096,
        description="Maximum tokens for LLM response",
    )
    bedrock_top_p: float = Field(
        default=0.9,
        description="Top-p sampling parameter",
    )
    default_llm_temperature: float = Field(
        default=0.1,
        description="Default LLM temperature",
    )

    # Database settings
    database_url: str = Field(
        #default="postgresql+asyncpg://metaplanet:metaplanet@localhost:5432/metaplanet",
        default="sqlite+aiosqlite:///./agent_server.db",
        description="SQLAlchemy database URL (async driver). Loaded from DATABASE_URL.",
    )
    database_echo: bool = Field(
        default=False,
        description="Echo SQL statements (useful for debugging)",
    )
    database_pool_size: int = Field(
        default=5,
        description="Connection pool size for the database engine",
    )
    database_max_overflow: int = Field(
        default=10,
        description="Maximum overflow connections beyond the pool size",
    )

    # WebSocket settings
    ws_heartbeat_interval: int = Field(
        default=30,
        description="WebSocket heartbeat interval in seconds",
    )
    ws_max_message_size: int = Field(
        default=1024 * 1024,  # 1MB
        description="Maximum WebSocket message size in bytes",
    )

    # Authentication settings
    auth_enabled: bool = Field(
        default=True,
        description="Enable authentication for protected API endpoints",
    )
    auth_providers: str = Field(
        default="cognito",
        description="Comma-separated list of authentication providers to use when auth is enabled",
    )
    cognito_region: Optional[str] = Field(
        default="eu-west-3",
        description="AWS region for the Cognito user pool",
    )
    cognito_user_pool_id: Optional[str] = Field(
        default=None,
        description="Cognito user pool ID used to validate JWT issuers",
    )
    cognito_domain: Optional[str] = Field(
        default=None,
        description="Cognito domain used to fetch user info",
    )
    cognito_app_client_id: Optional[str] = Field(
        default=None,
        description="Cognito app client ID used to validate JWT audience/client_id",
    )
    cognito_token_use: Optional[str] = Field(
        default=None,
        description="Expected Cognito token_use claim, for example 'access' or 'id'",
    )
    cognito_jwt_leeway_seconds: int = Field(
        default=0,
        description="Clock skew leeway in seconds when validating Cognito JWTs",
    )

    # =========================================================================
    # Graph pipeline (ported EO_LLM LangGraph) TODO: remove this once the legacy orchestrator is removed (mtbh)
    # =========================================================================
    use_graph_pipeline: bool = Field(
        default=True,
        description="Route chat requests through the EO_LLM LangGraph pipeline instead of the legacy orchestrator",
    )


    fast_llm_provider: str = Field(
        default="bedrock",
        description="Provider for fast LLM",
    )
    fast_llm_model_id: str = Field(
        default="eu.anthropic.claude-haiku-4-5-20251001-v1:0",
        description="Model ID for fast LLM",
    )
    reasoning_llm_provider: str = Field(
        default="bedrock",
        description="Provider for reasoning LLM",
    )
    reasoning_llm_model_id: str = Field(
        default="eu.anthropic.claude-haiku-4-5-20251001-v1:0",
        description="Model ID for reasoning LLM",
    )
    structured_llm_provider: str = Field(
        default="bedrock",
        description="Provider for structured LLM",
    )
    structured_llm_model_id: str = Field(
        default="eu.anthropic.claude-haiku-4-5-20251001-v1:0",
        description="Model ID for structured LLM",
    )
    document_llm_provider: str = Field(
        default="bedrock",
        description="Provider for document LLM",
    )
    document_llm_model_id: str = Field(
        default="eu.anthropic.claude-haiku-4-5-20251001-v1:0",
        description="Model ID for document LLM",
    )



@lru_cache(maxsize=1)
def get_config() -> AgentServerConfig:
    """Get or create the cached config instance.

    Implemented with ``lru_cache`` so callers can reset it via
    ``get_config.cache_clear()`` (e.g. tests toggling environment variables).
    """
    return AgentServerConfig()
