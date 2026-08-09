from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from homelab_mcp.config import AppConfig
from homelab_mcp.context import AppContext
from homelab_mcp.data.loader import DataLoader
from homelab_mcp.jsonlog import setup_logger
from homelab_mcp.ssh.client import SSHClient


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    config = AppConfig()
    data = DataLoader(config.data_dir)
    data.load_all()
    logger = setup_logger(config.log_dir, config.log_level)
    logger.info("server starting", extra={"event": "server.start"})
    ssh = SSHClient(config, logger)
    try:
        yield AppContext(config=config, data_loader=data, ssh=ssh, logger=logger)
    finally:
        logger.info("server stopping", extra={"event": "server.stop"})
        await ssh.close()


mcp = FastMCP("homelab-mcp", lifespan=app_lifespan)
