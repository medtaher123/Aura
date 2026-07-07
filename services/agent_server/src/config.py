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
    bedrock_model_id: str = Field(
        default="anthropic.claude-3-5-sonnet-20241022-v2:0",
        description="AWS Bedrock model ID",
    )
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
    # Graph pipeline (ported EO_LLM LangGraph)
    # =========================================================================
    use_graph_pipeline: bool = Field(
        default=True,
        description="Route chat requests through the EO_LLM LangGraph pipeline instead of the legacy orchestrator",
    )

    # Bedrock LLM settings for the EO_LLM graph pipeline
    bedrock_llm_enabled: bool = Field(
        default=True,
        description="Enable Bedrock LLM calls for the EO_LLM graph pipeline",
        validation_alias=AliasChoices("bedrock_llm_enabled", "agentcore_enabled"),
    )
    bedrock_endpoint: str = Field(
        default="",
        description="Optional Bedrock runtime endpoint URL",
        validation_alias=AliasChoices("bedrock_endpoint", "agentcore_endpoint"),
    )
    bedrock_router_model_id: str = Field(
        default="",
        description="Bedrock model ID for domain routing decisions",
        validation_alias=AliasChoices("bedrock_router_model_id", "agentcore_router_model_id"),
    )
    bedrock_tool_planner_model_id: str = Field(
        default="",
        description="Bedrock model ID for per-domain tool planning",
        validation_alias=AliasChoices(
            "bedrock_tool_planner_model_id", "agentcore_tool_planner_model_id"
        ),
    )

    # AgentCore Browser (Strands) — web fallback via managed browser
    agentcore_browser_enabled: bool = Field(
        default=False,
        description="Enable AgentCore Browser (Strands) for the web_search node",
    )
    agentcore_browser_region: str = Field(
        default="",
        description="AWS region for Browser API (defaults to bedrock_region)",
    )
    agentcore_browser_timeout_seconds: int = Field(
        default=180,
        ge=30,
        le=3600,
        description="Max wall-clock seconds for one browser agent run",
    )
    agentcore_browser_max_tool_rounds: int = Field(
        default=4,
        ge=1,
        le=25,
        description="Max successful browser tool completions per web run",
    )
    agentcore_browser_message_window: int = Field(
        default=14,
        ge=6,
        le=60,
        description="SlidingWindowConversationManager max messages kept",
    )

    # AgentCore Memory config (optional; not used when history lives in Postgres)
    agentcore_memory_id: str = Field(
        default="",
        description="AgentCore Memory resource ID for short/long-term chat memory",
    )
    agentcore_memory_short_term_turns: int = Field(
        default=8,
        ge=1,
        le=30,
        description="How many recent short-term conversation turns to load",
    )
    agentcore_memory_long_term_top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="How many long-term memory records to retrieve per namespace",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @model_validator(mode="after")
    def _backfill_bedrock_llm_settings(self) -> "AgentServerConfig":
        """Default graph Bedrock LLM model IDs from the main Bedrock config.

        Explicit ``BEDROCK_ROUTER_MODEL_ID`` / legacy ``AGENTCORE_*`` values still
        take precedence via field aliases.
        """
        if not (self.bedrock_router_model_id or "").strip():
            self.bedrock_router_model_id = self.bedrock_model_id
        if not (self.bedrock_tool_planner_model_id or "").strip():
            self.bedrock_tool_planner_model_id = self.bedrock_router_model_id
        if not (self.agentcore_browser_region or "").strip():
            self.agentcore_browser_region = self.bedrock_region
        return self


@lru_cache(maxsize=1)
def get_config() -> AgentServerConfig:
    """Get or create the cached config instance.

    Implemented with ``lru_cache`` so callers can reset it via
    ``get_config.cache_clear()`` (e.g. tests toggling environment variables).
    """
    return AgentServerConfig()
