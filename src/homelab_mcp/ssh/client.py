import asyncio
import shlex
from pathlib import Path

import asyncssh

from homelab_mcp.config import AppConfig


class SSHError(Exception):
    pass


class SSHClient:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._connections: dict[str, asyncssh.SSHClientConnection] = {}

    def _resolve_key_path(self) -> Path:
        p = Path(self._config.ssh_key_path).expanduser()
        if not p.exists():
            raise SSHError(f"SSH key not found: {p}")
        return p

    async def _get_connection(self, host: str) -> asyncssh.SSHClientConnection:
        if host in self._connections:
            conn = self._connections[host]
            if not conn.is_closed():
                return conn

        key_path = self._resolve_key_path()
        known_hosts = str(Path("~/.ssh/known_hosts").expanduser())
        try:
            conn = await asyncio.wait_for(
                asyncssh.connect(
                    host=host,
                    port=self._config.ssh_port,
                    username=self._config.ssh_user,
                    client_keys=[str(key_path)],
                    known_hosts=known_hosts,
                ),
                timeout=10,
            )
        except TimeoutError:
            raise SSHError(f"SSH connection timed out to {host} (10s)")
        except asyncssh.Error as e:
            raise SSHError(f"SSH connection failed to {host}: {e}") from e

        self._connections[host] = conn
        return conn

    async def execute(self, host: str, command: str, timeout: int = 30) -> tuple[str, str, int]:
        conn = await self._get_connection(host)
        try:
            result = await asyncio.wait_for(
                conn.run(command, check=False),
                timeout=timeout,
            )
        except TimeoutError:
            raise SSHError(f"Command timed out after {timeout}s: {command}")

        return result.stdout, result.stderr, result.exit_status

    async def read_file(self, host: str, path: str) -> str:
        safe_path = shlex.quote(path)
        stdout, stderr, exit_code = await self.execute(host, f"sudo cat {safe_path}")
        if exit_code != 0:
            raise SSHError(f"Failed to read {path}: {stderr.strip()}")
        return stdout

    async def close(self) -> None:
        for conn in self._connections.values():
            if not conn.is_closed():
                conn.close()
        self._connections.clear()
