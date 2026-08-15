import asyncio
import logging
import shlex
import time
from pathlib import Path

import asyncssh

from homelab_mcp.config import AppConfig
from homelab_mcp.data.resolver import SshTarget


class SSHError(Exception):
    pass


class SSHClient:
    def __init__(self, config: AppConfig, logger: logging.Logger) -> None:
        self._config = config
        self._logger = logger
        self._connections: dict[tuple[str, str, int], asyncssh.SSHClientConnection] = {}

    def _resolve_key_path(self, key_path: str) -> Path:
        p = Path(key_path).expanduser()
        if not p.exists():
            raise SSHError(f"SSH key not found: {p}")
        return p

    async def _get_connection(self, target: SshTarget) -> asyncssh.SSHClientConnection:
        key = (target.host, target.user, target.port)
        conn = self._connections.get(key)
        if conn is not None and not conn.is_closed():
            return conn

        tunnel_conn: asyncssh.SSHClientConnection | None = None
        if target.jump is not None:
            tunnel_conn = await self._get_connection(target.jump)

        key_path = self._resolve_key_path(target.key_path)
        known_hosts = str(Path("~/.ssh/known_hosts").expanduser())
        try:
            conn = await asyncio.wait_for(
                asyncssh.connect(
                    host=target.host,
                    port=target.port,
                    username=target.user,
                    client_keys=[str(key_path)],
                    known_hosts=known_hosts,
                    tunnel=tunnel_conn,
                ),
                timeout=10,
            )
        except TimeoutError:
            raise SSHError(f"SSH connection timed out to {target.user}@{target.host} (10s)")
        except asyncssh.Error as e:
            raise SSHError(f"SSH connection failed to {target.user}@{target.host}: {e}") from e

        self._connections[key] = conn
        return conn

    async def execute(
        self, target: SshTarget, command: str, timeout: int = 30
    ) -> tuple[str, str, int]:
        start = time.monotonic()
        dest = f"{target.user}@{target.host}"
        self._logger.debug(
            f"executing on {dest}: {command[:100]}",
            extra={
                "event": "ssh.command",
                "command": command,
                "node": target.node_name,
                "ssh_destination": dest,
            },
        )
        conn = await self._get_connection(target)
        try:
            result = await asyncio.wait_for(
                conn.run(command, check=False),
                timeout=timeout,
            )
        except TimeoutError:
            duration = round((time.monotonic() - start) * 1000, 1)
            self._logger.error(
                f"command timed out after {timeout}s: {command[:80]}",
                extra={
                    "event": "ssh.error",
                    "command": command,
                    "node": target.node_name,
                    "duration_ms": duration,
                    "status": "error",
                },
            )
            raise SSHError(f"Command timed out after {timeout}s: {command}")

        duration = round((time.monotonic() - start) * 1000, 1)
        self._logger.debug(
            f"command completed in {duration}ms (exit {result.exit_status})",
            extra={
                "event": "ssh.command",
                "command": command,
                "node": target.node_name,
                "duration_ms": duration,
                "status": "success" if result.exit_status == 0 else "error",
            },
        )
        return result.stdout, result.stderr, result.exit_status

    async def read_file(self, target: SshTarget, path: str) -> str:
        safe_path = shlex.quote(path)
        prefix = "sudo " if target.use_sudo else ""
        stdout, stderr, exit_code = await self.execute(target, f"{prefix}cat {safe_path}")
        if exit_code != 0:
            raise SSHError(f"Failed to read {path}: {stderr.strip()}")
        return stdout

    async def close(self) -> None:
        for conn in self._connections.values():
            if not conn.is_closed():
                conn.close()
        self._connections.clear()
