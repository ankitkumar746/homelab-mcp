from mcp.server.fastmcp import Context

from homelab_mcp.context import AppContext
from homelab_mcp.data.resolver import resolve_node_ip
from homelab_mcp.jsonlog import log_tool_call
from homelab_mcp.mcp_instance import mcp
from homelab_mcp.ssh.safety import SafetyLevel


@mcp.tool()
async def run_command(ctx: Context, node_name: str, command: str) -> dict:
    """Run a command on a Proxmox node via SSH. The command goes through a safety pipeline:
    BLOCKED commands are rejected, SAFE commands execute directly, all others require approval.

    Args:
        node_name: Name of the Proxmox node (e.g., 'homelab')
        command: The shell command to execute
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    logger = app_ctx.logger

    with log_tool_call(
        logger, "run_command", node=node_name, command=command
    ) as call_ctx:
        ip = resolve_node_ip(app_ctx.data, node_name)
        if not ip:
            call_ctx.status = "error"
            return {"error": f"Node '{node_name}' not found"}

        from homelab_mcp.ssh.safety import validate_command

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
        stdout, stderr, exit_code = await app_ctx.ssh.execute(ip, command)

        return {
            "status": "executed",
            "safety_level": safety.level.value,
            "command": command,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
        }
