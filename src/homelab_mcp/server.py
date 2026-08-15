import homelab_mcp.prompts  # side-effect: registers @mcp.prompt() handlers
import homelab_mcp.resources  # side-effect: registers @mcp.resource() handlers
import homelab_mcp.tools  # noqa: F401  # side-effect: registers @mcp.tool() handlers
from homelab_mcp.config import AppConfig
from homelab_mcp.mcp_instance import mcp


def main() -> None:
    config = AppConfig()
    mcp.run(transport=config.transport)


if __name__ == "__main__":
    main()
