from mcp.server.fastmcp import Context

from homelab_mcp.context import AppContext
from homelab_mcp.data.resolver import resolve_config_paths, search_services
from homelab_mcp.jsonlog import log_tool_call
from homelab_mcp.mcp_instance import mcp


@mcp.tool()
def list_nodes(ctx: Context) -> dict:
    """List all Proxmox nodes registered in the homelab."""
    app_ctx: AppContext = ctx.request_context.lifespan_context
    with log_tool_call(app_ctx.logger, "list_nodes"):
        nodes = []
        for instance in app_ctx.data.instances.cluster:
            nodes.append(
                {
                    "name": instance.name,
                    "fqdn": instance.fqdn,
                    "wan_ip": instance.wan_ip,
                    "platform_user": instance.platform_user,
                    "proxmox_node": instance.proxmox_node,
                    "kind": instance.kind,
                    "vmid": instance.vmid,
                }
            )
        return {"nodes": nodes}


@mcp.tool()
def get_hardware(ctx: Context, node_name: str) -> dict:
    """Get hardware specifications for a node.

    Args:
        node_name: Name of the Proxmox node (e.g., 'homelab')
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    with log_tool_call(app_ctx.logger, "get_hardware", node=node_name):
        node = app_ctx.data.get_hardware(node_name)
        if not node:
            return {"error": f"Node '{node_name}' not found in hardware data"}
        return node.model_dump()


@mcp.tool()
def get_network(ctx: Context, node_name: str) -> dict:
    """Get network topology for a node — NICs, WAN, bridges, NAT, DHCP, PXE.

    Args:
        node_name: Name of the Proxmox node (e.g., 'homelab')
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    with log_tool_call(app_ctx.logger, "get_network", node=node_name):
        node = app_ctx.data.get_network(node_name)
        if not node:
            return {"error": f"Node '{node_name}' not found in network data"}
        return node.model_dump()


@mcp.tool()
def list_services(ctx: Context, node_name: str) -> dict:
    """List all services running on a node — host services, VM services, and LXC services.

    Args:
        node_name: Name of the Proxmox node (e.g., 'homelab')
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    with log_tool_call(app_ctx.logger, "list_services", node=node_name):
        node = app_ctx.data.get_services(node_name)
        if not node:
            return {"error": f"Node '{node_name}' not found in services data"}

        result: dict = {"host": [], "vms": [], "lxc": []}

        for svc in node.host:
            result["host"].append(
                {
                    "name": svc.name,
                    "type": svc.type,
                    "service_name": svc.service_name,
                    "critical": svc.critical,
                    "note": svc.note,
                }
            )

        for vm in node.vms:
            vm_services = []
            for svc in vm.services:
                vm_services.append(
                    {
                        "name": svc.name,
                        "type": svc.type,
                        "service_name": svc.service_name,
                        "note": svc.note,
                    }
                )
            result["vms"].append({"vm_name": vm.name, "services": vm_services})

        return result


@mcp.tool()
def get_service(ctx: Context, node_name: str, service_name: str) -> dict:
    """Get details for a specific service by name.

    Args:
        node_name: Name of the Proxmox node (e.g., 'homelab')
        service_name: Name of the service (e.g., 'dnsmasq')
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    with log_tool_call(app_ctx.logger, "get_service", node=node_name, service_name=service_name):
        node = app_ctx.data.get_services(node_name)
        if not node:
            return {"error": f"Node '{node_name}' not found in services data"}

        for svc in node.host:
            if svc.name == service_name:
                return {
                    "location": "host",
                    **svc.model_dump(exclude_none=True),
                    "config_files": resolve_config_paths(svc.configs),
                }

        for vm in node.vms:
            for svc in vm.services:
                if svc.name == service_name:
                    return {
                        "location": f"vm:{vm.name}",
                        **svc.model_dump(exclude_none=True),
                        "config_files": resolve_config_paths(svc.configs),
                    }

        return {"error": f"Service '{service_name}' not found on node '{node_name}'"}


@mcp.tool()
def search_services_tool(ctx: Context, node_name: str, query: str) -> dict:
    """Search services by keyword matching name, type, or notes.

    Args:
        node_name: Name of the Proxmox node (e.g., 'homelab')
        query: Keyword to search for (matches name, type, or note)
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    with log_tool_call(app_ctx.logger, "search_services_tool", node=node_name, query=query):
        results = search_services(app_ctx.data, node_name, query)
        if not results:
            return {
                "results": [],
                "message": f"No services matching '{query}' on '{node_name}'",
            }
        return {"results": results}


@mcp.tool()
def list_configs(ctx: Context, node_name: str, service_name: str) -> dict:
    """List all config files for a service, with full reconstructed paths.

    Args:
        node_name: Name of the Proxmox node (e.g., 'homelab')
        service_name: Name of the service (e.g., 'dnsmasq')
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    with log_tool_call(app_ctx.logger, "list_configs", node=node_name, service_name=service_name):
        from homelab_mcp.data.resolver import resolve_service_configs

        configs = resolve_service_configs(app_ctx.data, node_name, service_name)
        if configs is None:
            return {"error": f"Node '{node_name}' not found"}
        if not configs:
            return {
                "configs": [],
                "message": f"No config files found for service '{service_name}'",
            }
        return {"configs": configs}
