from dataclasses import dataclass
import logging

from homelab_mcp.config import AppConfig
from homelab_mcp.data.loader import DataLoader

@dataclass
class AppContext:
    """Application context containing configuration and data loader."""

    config: AppConfig
    data_loader: DataLoader
    logger: logging.Logger