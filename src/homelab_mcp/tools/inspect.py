import re
import shlex

from mcp.server.fastmcp import Context

from homelab_mcp.context import AppContext
from homelab_mcp.data.resolver import GUEST_KINDS, resolve_ssh_target
from homelab_mcp.jsonlog import log_tool_call
from homelab_mcp.mcp_instance import mcp
from homelab_mcp.ssh.client import SSHError

_SERVICE_NAME_RE = re.compile(r"^[a-zA-Z0-9@_.\-]+$")


def _validate_service_name(name: str) -> str:
    """Validate service name contains only safe characters."""
    if not _SERVICE_NAME_RE.match(name):
        raise ValueError(
            f"Invalid service name: {name!r}. Only alphanumeric, @, _, ., - are allowed."
        )
    return name


def _resolve_target(app_ctx: AppContext, node_name: str):
    """Resolve node to SshTarget; returns (target, error_dict). Exactly one is set."""
    try:
        target = resolve_ssh_target(app_ctx.data, node_name)
    except ValueError as e:
        return None, {"error": str(e)}
    if target is None:
        return None, {"error": f"Node '{node_name}' not found"}
    return target, None


def _sudo_prefix(target) -> str:
    # Guest commands already run as root inside the vm/lxc; only the proxmox
    # host needs the sudo prefix for privileged reads.
    return "" if target.kind in GUEST_KINDS else "sudo "


@mcp.tool()
async def read_config(ctx: Context, node_name: str, file_path: str) -> dict:
    """Read the current contents of a config file from a node via SSH.

    Args:
        node_name: Name of the node (e.g., 'homelab'), VM (e.g., 'infravm'), or LXC (e.g., 'netbox01')
        file_path: Absolute path to the config file on the node
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    with log_tool_call(app_ctx.logger, "read_config", node=node_name, file_path=file_path):
        target, err = _resolve_target(app_ctx, node_name)
        if err:
            return err

        await ctx.info(f"Reading {file_path} from {node_name}")
        try:
            content = await app_ctx.ssh.read_file(target, file_path)
        except SSHError as e:
            return {"error": str(e)}

        return {"file": file_path, "content": content}


@mcp.tool()
async def check_service(ctx: Context, node_name: str, service_name: str) -> dict:
    """Check systemd status of a service on a node via SSH.

    Args:
        node_name: Name of the node (e.g., 'homelab'), VM (e.g., 'infravm'), or LXC (e.g., 'netbox01')
        service_name: systemd service name (e.g., 'dnsmasq')
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    with log_tool_call(app_ctx.logger, "check_service", node=node_name, service_name=service_name):
        try:
            safe_name = _validate_service_name(service_name)
        except ValueError as e:
            return {"error": str(e)}

        target, err = _resolve_target(app_ctx, node_name)
        if err:
            return err

        await ctx.info(f"Checking service {service_name} on {node_name}")
        try:
            stdout, stderr, exit_code = await app_ctx.ssh.execute(
                target,
                f"{_sudo_prefix(target)}systemctl status {shlex.quote(safe_name)} --no-pager -l",
            )
        except SSHError as e:
            return {"error": str(e)}

        return {
            "service": service_name,
            "node": node_name,
            "exit_code": exit_code,
            "output": stdout or stderr,
        }


@mcp.tool()
async def read_logs(ctx: Context, node_name: str, service_name: str, lines: int = 50) -> dict:
    """Read journalctl logs for a service on a node via SSH.

    Args:
        node_name: Name of the node (e.g., 'homelab'), VM (e.g., 'infravm'), or LXC (e.g., 'netbox01')
        service_name: systemd service name (e.g., 'dnsmasq')
        lines: Number of log lines to return (default 50, max 1000)
    """
    lines = max(1, min(lines, 1000))
    app_ctx: AppContext = ctx.request_context.lifespan_context
    with log_tool_call(
        app_ctx.logger,
        "read_logs",
        node=node_name,
        service_name=service_name,
        lines=lines,
    ):
        try:
            safe_name = _validate_service_name(service_name)
        except ValueError as e:
            return {"error": str(e)}

        target, err = _resolve_target(app_ctx, node_name)
        if err:
            return err

        await ctx.info(f"Reading logs for {safe_name} on {node_name} (last {lines} lines)")
        try:
            stdout, stderr, _exit_code = await app_ctx.ssh.execute(
                target,
                f"{_sudo_prefix(target)}journalctl -u {shlex.quote(safe_name)} --no-pager -n {lines}",
            )
        except SSHError as e:
            return {"error": str(e)}

        return {
            "service": safe_name,
            "node": node_name,
            "lines": lines,
            "output": stdout or stderr,
        }


@mcp.tool()
async def network_status(ctx: Context, node_name: str) -> dict:
    """Get current network status on a node — interfaces, routes, and listening ports via SSH.

    Args:
        node_name: Name of the node (e.g., 'homelab'), VM (e.g., 'infravm'), or LXC (e.g., 'netbox01')
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    with log_tool_call(app_ctx.logger, "network_status", node=node_name):
        target, err = _resolve_target(app_ctx, node_name)
        if err:
            return err

        await ctx.info(f"Checking network status on {node_name}")
        prefix = _sudo_prefix(target)
        try:
            addr_out, _, _ = await app_ctx.ssh.execute(target, f"{prefix}ip addr show")
            route_out, _, _ = await app_ctx.ssh.execute(target, f"{prefix}ip route show")
            ports_out, _, _ = await app_ctx.ssh.execute(target, f"{prefix}ss -tlnp")
        except SSHError as e:
            return {"error": str(e)}

        return {
            "node": node_name,
            "interfaces": addr_out,
            "routes": route_out,
            "listening_ports": ports_out,
        }
