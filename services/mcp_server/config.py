"""MCP Server Configuration"""

from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class MCPServerConfig(BaseSettings):
    """MCP Server configuration with environment variable support"""

    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, description="Server port")
    name: str = Field(default="metaplanet-llm-mcp-server", description="Server name")
    version: str = Field(default="1.0.0", description="API version")
    description: str = Field(
        default="MCP server for Metaplanet LLM tools and services",
        description="API description",
    )

    # Fargate-specific settings (matches Terraform env vars)
    workers: int = Field(default=1, description="Number of worker processes")
    log_level: str = Field(default="info", description="Logging level")
    timeout_seconds: int = Field(default=300, description="Request timeout in seconds")

    # API keys
    opentopo_api_key: str = Field(
        ...,
        description="OpenTopography API key - REQUIRED from environment",
    )
    map_key: str = Field(
        ...,
        description="NASA FIRMS Map key - REQUIRED from environment",
    )

    # GeoServer settings
    geoserver_base_url: str = Field(
        ...,
        description="GeoServer base URL - REQUIRED from environment",
    )
    geoserver_risk_layer: str = Field(
        default="georisk:predictions",
        description="GeoServer risk layer name",
    )
    fire_archive_dir: str = Field(
        default="./fire_archive",
        description="Directory for fire detection archives",
    )

    # GDFC drought/flood data (S3 public bucket)
    gdfc_drought_s3: str = Field(
        default="",
        description="S3 URI or prefix for GDFC drought NetCDF",
    )
    gdfc_flood_s3: str = Field(
        default="",
        description="S3 URI or prefix for GDFC flood NetCDF",
    )
    gdfc_drought_var: str = Field(
        default="",
        description="Optional GDFC drought variable name override",
    )
    gdfc_flood_var: str = Field(
        default="",
        description="Optional GDFC flood variable name override",
    )

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


# Singleton instance
_config_instance: Optional[MCPServerConfig] = None


def get_config() -> MCPServerConfig:
    """Get or create singleton config instance."""
    global _config_instance
    if _config_instance is None:
        _config_instance = MCPServerConfig()
    return _config_instance
