from homelab_mcp.config import AppConfig
from homelab_mcp.mcp_instance import mcp


def main() -> None:
    config = AppConfig()
    mcp.run(transport=config.transport)


if __name__ == "__main__":
    main()
