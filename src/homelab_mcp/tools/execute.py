from mcp.server.fastmcp import Context

from homelab_mcp.context import AppContext
from homelab_mcp.data.resolver import GUEST_KINDS, resolve_ssh_target
from homelab_mcp.jsonlog import log_tool_call
from homelab_mcp.mcp_instance import mcp
from homelab_mcp.ssh.safety import SafetyLevel, validate_command


@mcp.tool()
async def run_command(ctx: Context, node_name: str, command: str) -> dict:
    """Run a command on a node via SSH. Commands run as the SSH user (with sudo for
    read-only tools). The command goes through a safety pipeline:
    BLOCKED commands are rejected; on vm/lxc guests only read-only (SAFE) commands
    are allowed — anything else is rejected without asking; on the proxmox host,
    non-SAFE commands require explicit approval.

    Args:
        node_name: Name of the node (e.g., 'homelab'), VM (e.g., 'infravm'), or LXC (e.g., 'netbox01')
        command: The shell command to execute
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    logger = app_ctx.logger

    with log_tool_call(logger, "run_command", node=node_name, command=command) as call_ctx:
        try:
            target = resolve_ssh_target(app_ctx.data, node_name)
        except ValueError as e:
            call_ctx.status = "error"
            return {"error": str(e)}
        if target is None:
            call_ctx.status = "error"
            return {"error": f"Node '{node_name}' not found"}

        safety = validate_command(command)

        if safety.level == SafetyLevel.BLOCKED:
            call_ctx.status = "blocked"
            logger.warning(
                safety.reason,
                extra={
                    "event": "safety.blocked",
                    "request_id": call_ctx.request_id,
                    "command": command,
                    "node": node_name,
                    "safety_level": "blocked",
                    "status": "blocked",
                },
            )
            await ctx.warning(f"Blocked command on {node_name}: {command}")
            return {
                "status": "blocked",
                "reason": safety.reason,
                "command": command,
            }

        # Read-only gate for guest targets: commands inside VMs/LXCs run as
        # guest-root with no guest-side permission layer, so only SAFE
        # (allowlisted read-only) commands may run — no approval path exists.
        if target.kind in GUEST_KINDS and safety.level != SafetyLevel.SAFE:
            call_ctx.status = "blocked"
            logger.warning(
                f"guest read-only gate: {safety.reason}",
                extra={
                    "event": "safety.guest_gate",
                    "request_id": call_ctx.request_id,
                    "command": command,
                    "node": node_name,
                    "safety_level": safety.level.value,
                    "status": "blocked",
                },
            )
            await ctx.warning(
                f"Rejected on {node_name}: guest targets are read-only — '{command}' is not an allowlisted read-only command"
            )
            return {
                "status": "blocked",
                "reason": f"Guest targets are read-only: {safety.reason}",
                "command": command,
            }

        if safety.level == SafetyLevel.CONFIRM:
            logger.warning(
                safety.reason,
                extra={
                    "event": "safety.confirm",
                    "request_id": call_ctx.request_id,
                    "command": command,
                    "node": node_name,
                    "safety_level": "confirm",
                    "status": "confirm",
                },
            )
            result = await ctx.elicit(
                message=f"Command requires approval before running on '{node_name}':\n\n```\n{command}\n```\n\nReason: {safety.reason}\n\nAllow this command?",
                schema={
                    "type": "object",
                    "properties": {
                        "approved": {
                            "type": "boolean",
                            "description": "Approve running this command",
                        }
                    },
                    "required": ["approved"],
                },
            )
            if result.action != "accept" or not result.data.get("approved"):
                call_ctx.status = "rejected"
                logger.warning(
                    "user rejected command",
                    extra={
                        "event": "safety.rejected",
                        "request_id": call_ctx.request_id,
                        "command": command,
                        "node": node_name,
                        "safety_level": "confirm",
                        "status": "rejected",
                    },
                )
                return {
                    "status": "rejected",
                    "reason": "User did not approve the command",
                    "command": command,
                }

        await ctx.info(f"Executing on {node_name}: {command}")
        stdout, stderr, exit_code = await app_ctx.ssh.execute(target, command)

        return {
            "status": "executed",
            "safety_level": safety.level.value,
            "command": command,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
        }
