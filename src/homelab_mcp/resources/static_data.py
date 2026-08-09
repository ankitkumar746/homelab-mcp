import json

from mcp.server.fastmcp import Context

from homelab_mcp.context import AppContext
from homelab_mcp.mcp_instance import mcp


@mcp.resource("homelab://instances")
def get_instances(ctx: Context) -> str:
    app_ctx: AppContext = ctx.request_context.lifespan_context
    return json.dumps(app_ctx.data.instances.model_dump(), default=str, ensure_ascii=False)


@mcp.resource("homelab://hardware/{node_name}")
def get_hardware_resource(node_name: str, ctx: Context) -> str:
    app_ctx: AppContext = ctx.request_context.lifespan_context
    node = app_ctx.data.get_hardware(node_name)
    if not node:
        return f"Node '{node_name}' not found in hardware data"
    return json.dumps(node.model_dump(), default=str, ensure_ascii=False)


@mcp.resource("homelab://network/{node_name}")
def get_network_resource(node_name: str, ctx: Context) -> str:
    app_ctx: AppContext = ctx.request_context.lifespan_context
    node = app_ctx.data.get_network(node_name)
    if not node:
        return f"Node '{node_name}' not found in network data"
    return json.dumps(node.model_dump(), default=str, ensure_ascii=False)


@mcp.resource("homelab://services/{node_name}")
def get_services_resource(node_name: str, ctx: Context) -> str:
    app_ctx: AppContext = ctx.request_context.lifespan_context
    node = app_ctx.data.get_services(node_name)
    if not node:
        return f"Node '{node_name}' not found in services data"
    return json.dumps(node.model_dump(), default=str, ensure_ascii=False)
