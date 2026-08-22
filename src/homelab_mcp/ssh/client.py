import asyncio
import json
import logging
import shlex
import time
from pathlib import Path

import asyncssh

from homelab_mcp.config import AppConfig
from homelab_mcp.data.resolver import GUEST_KINDS, SshTarget


class SSHError(Exception):
    pass


def build_guest_command(target: SshTarget, command: str) -> str:
    """Build the host-side command that runs `command` inside a vm/lxc guest.

    The inner command is quoted and passed to `bash -c` so pipes/redirects
    behave as the caller expects *inside* the guest, and the host shell never
    interprets the inner text. Commands run as root in the guest — the
    read-only safety gate at the tool layer is the guard, not guest permissions.
    """
    if target.kind == "lxc":
        opener = f"pct exec {target.vmid} --"
    else:
        opener = f"qm guest exec {target.vmid} --"
    return f"sudo {opener} bash -c {shlex.quote(command)}"


def parse_guest_exec_output(raw: str) -> tuple[str, str, int]:
    """Parse `qm guest exec` JSON output into (stdout, stderr, exit_code).

    Falls back to raw text if the output isn't the expected JSON document.
    """
    try:
        doc = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw, "", 0

    if not isinstance(doc, dict):
        return raw, "", 0

    stdout = doc.get("out-data", "")
    stderr = doc.get("err-data", "")
    if doc.get("out-truncated") or doc.get("err-truncated"):
        stderr = (stderr + "\n[output truncated by guest agent]").strip("\n")
    exit_code = doc.get("exitcode", 0)
    if not isinstance(exit_code, int):
        exit_code = 0
    return stdout, stderr, exit_code


class SSHClient:
    def __init__(self, config: AppConfig, logger: logging.Logger) -> None:
        self._config = config
        self._logger = logger
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
            raise SSHError(f"SSH connection timed out to {host} (10s)") from None
        except asyncssh.Error as e:
            raise SSHError(f"SSH connection failed to {host}: {e}") from e

        self._connections[host] = conn
        return conn

    async def execute(
        self, target: SshTarget, command: str, timeout: int = 30
    ) -> tuple[str, str, int]:
        start = time.monotonic()
        host_cmd = build_guest_command(target, command) if target.kind in GUEST_KINDS else command
        self._logger.debug(
            f"executing on {target.node_name}: {command[:100]}",
            extra={
                "event": "ssh.command",
                "command": command,
                "host_command": host_cmd,
                "node": target.node_name,
            },
        )
        conn = await self._get_connection(target.host)
        try:
            result = await asyncio.wait_for(
                conn.run(host_cmd, check=False),
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
            raise SSHError(f"Command timed out after {timeout}s: {command}") from None

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

        if target.kind == "vm" and "qm guest exec" in host_cmd:
            stdout, stderr, exit_code = parse_guest_exec_output(result.stdout)
            return stdout.replace("\r\n", "\n"), stderr.replace("\r\n", "\n"), exit_code

        return result.stdout, result.stderr, result.exit_status

    async def read_file(self, target: SshTarget, path: str) -> str:
        safe_path = shlex.quote(path)
        prefix = "" if target.kind in GUEST_KINDS else "sudo "
        stdout, stderr, exit_code = await self.execute(target, f"{prefix}cat {safe_path}")
        if exit_code != 0:
            raise SSHError(f"Failed to read {path}: {stderr.strip()}")
        return stdout

    async def close(self) -> None:
        for conn in self._connections.values():
            if not conn.is_closed():
                conn.close()
        self._connections.clear()
