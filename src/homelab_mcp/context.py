import logging
from dataclasses import dataclass

from homelab_mcp.config import AppConfig
from homelab_mcp.data.loader import DataLoader
from homelab_mcp.ssh.client import SSHClient


@dataclass
class AppContext:
    """Application context containing configuration and data loader."""

    config: AppConfig
    data: DataLoader
    ssh: SSHClient
    logger: logging.Logger
