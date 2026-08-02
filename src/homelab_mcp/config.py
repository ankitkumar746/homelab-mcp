from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class AppConfig(BaseSettings):
    """Application configuration settings."""

    ssh_host: str = Field(default="192.168.29.50", description="Proxmox SSH hostname/IP")
    ssh_port: int = Field(default=22, description="SSH Port")
    ssh_user: str = Field(default="mcp", description="SSH username")
    ssh_key_path: str = Field(default="~/.ssh/id_ed25519", description="Path to SSH private key")

    data_dir: Path = Field(default=Path("data"), description="Path to YAML data directory")
    log_path: Path = Field(default=Path("logs"), description="Directory to store log files")
    log_level: str = Field(
        default="INFO", description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )

    transport: Literal["stdio", "streamable-http"] = Field(
        default="studio", description="MCP transport mode"
    )
    http_port: int = Field(default=8000, description="HTTP port for streamable-http transport mode")

    model_config = {"env_prefix": "HOMELAB_", "env_file": ".env", "extra": "ignore"}
