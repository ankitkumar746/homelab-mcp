import re
from enum import Enum
from dataclasses import dataclass


class SafetyLevel(Enum):
    BLOCKED = "blocked"
    CONFIRM = "confirm"
    SAFE = "safe"


@dataclass
class SafetyResult:
    level: SafetyLevel
    reason: str


BLOCKED_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\brm\s+-[a-zA-Z]*f[a-zA-Z]*\s+(/[^\s]*|~)", re.IGNORECASE),
        "Recursive force delete on root-like paths",
    ),
    (re.compile(r"\bdd\s+.*of=/dev/", re.IGNORECASE), "Direct disk write with dd"),
    (re.compile(r"\bmkfs\b", re.IGNORECASE), "Filesystem format command"),
    (re.compile(r"\bfdisk\b", re.IGNORECASE), "Disk partitioning command"),
    (re.compile(r"\bparted\b", re.IGNORECASE), "Disk partitioning command"),
    (re.compile(r"\bshutdown\b", re.IGNORECASE), "System shutdown"),
    (re.compile(r"\breboot\b", re.IGNORECASE), "System reboot"),
    (re.compile(r"\bpoweroff\b", re.IGNORECASE), "System power off"),
    (re.compile(r"\bhalt\b", re.IGNORECASE), "System halt"),
    (re.compile(r"\biptables\s+-F\b", re.IGNORECASE), "Flush all firewall rules"),
    (re.compile(r":\(\)\{.*:\|:&\s*\}", re.IGNORECASE), "Fork bomb pattern"),
    (re.compile(r"\bchmod\s+(000|777)\s+/", re.IGNORECASE), "Dangerous chmod on system paths"),
    (re.compile(r">\s*/etc/passwd\b", re.IGNORECASE), "Overwrite /etc/passwd"),
    (re.compile(r">\s*/etc/shadow\b", re.IGNORECASE), "Overwrite /etc/shadow"),
    (re.compile(r">\s*/etc/sudoers\b", re.IGNORECASE), "Overwrite /etc/sudoers"),
]

CONFIRM_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\brm\s+", re.IGNORECASE), "File deletion"),
    (
        re.compile(r"\bsystemctl\s+(stop|restart|disable|mask)\s+", re.IGNORECASE),
        "Service management (stop/restart/disable)",
    ),
    (re.compile(r"\bapt(-get)?\s+(install|remove|purge)\b", re.IGNORECASE), "Package management"),
    (re.compile(r"\biptables\s+", re.IGNORECASE), "Firewall modification"),
    (re.compile(r"\bpvesh\b.*(?i:put|post|delete)", re.IGNORECASE), "Proxmox API write operation"),
    (
        re.compile(r"\b(qm|pct)\s+(start|stop|destroy|create|suspend|resume)\b", re.IGNORECASE),
        "VM/Container lifecycle change",
    ),
    (
        re.compile(r"\bip\s+(addr|route)\s+(add|del|flush)\b", re.IGNORECASE),
        "Network configuration change",
    ),
    (re.compile(r"\bsystemctl\s+(start|enable)\s+", re.IGNORECASE), "Starting/enabling a service"),
    (re.compile(r"\bmv\b.*\s+/etc/\b", re.IGNORECASE), "Moving files in /etc"),
    (re.compile(r"\bcp\b.*\s+/etc/\b", re.IGNORECASE), "Copying files into /etc"),
    (re.compile(r"\bsed\s+.*-i\b", re.IGNORECASE), "In-place file editing with sed"),
]

SAFE_COMMANDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^\s*cat\b", re.IGNORECASE), "Read file contents"),
    (re.compile(r"^\s*ls\b", re.IGNORECASE), "List directory"),
    (re.compile(r"^\s*stat\b", re.IGNORECASE), "File status"),
    (re.compile(r"^\s*find\b", re.IGNORECASE), "Find files"),
    (re.compile(r"^\s*head\b", re.IGNORECASE), "Read file head"),
    (re.compile(r"^\s*tail\b", re.IGNORECASE), "Read file tail"),
    (re.compile(r"^\s*less\b", re.IGNORECASE), "Page through file"),
    (re.compile(r"^\s*file\b", re.IGNORECASE), "File type detection"),
    (re.compile(r"^\s*wc\b", re.IGNORECASE), "Word/line count"),
    (re.compile(r"^\s*systemctl\s+status\b", re.IGNORECASE), "Check service status"),
    (re.compile(r"^\s*journalctl\b", re.IGNORECASE), "Read logs"),
    (re.compile(r"^\s*qm\s+(list|status|config)\b", re.IGNORECASE), "VM listing/status"),
    (re.compile(r"^\s*pct\s+(list|status|config)\b", re.IGNORECASE), "Container listing/status"),
    (
        re.compile(r"^\s*ip\s+(addr|route|link|neigh)\s+(show|list)?\b", re.IGNORECASE),
        "Network status",
    ),
    (re.compile(r"^\s*ping\b", re.IGNORECASE), "Ping diagnostic"),
    (re.compile(r"^\s*traceroute\b", re.IGNORECASE), "Traceroute diagnostic"),
    (re.compile(r"^\s*ss\b", re.IGNORECASE), "Socket statistics"),
    (re.compile(r"^\s*hostname\b", re.IGNORECASE), "Hostname display"),
    (re.compile(r"^\s*uname\b", re.IGNORECASE), "System information"),
    (re.compile(r"^\s*df\b", re.IGNORECASE), "Disk usage"),
    (re.compile(r"^\s*free\b", re.IGNORECASE), "Memory usage"),
    (re.compile(r"^\s*ps\b", re.IGNORECASE), "Process list"),
    (re.compile(r"^\s*top\s+-bn1\b", re.IGNORECASE), "Process snapshot"),
    (re.compile(r"^\s*uptime\b", re.IGNORECASE), "System uptime"),
    (re.compile(r"^\s*dmesg\b", re.IGNORECASE), "Kernel messages"),
    (re.compile(r"^\s*pvesh\s+get\b", re.IGNORECASE), "Proxmox API read"),
]


def validate_command(command: str) -> SafetyResult:
    stripped = command.strip()

    if not stripped:
        return SafetyResult(level=SafetyLevel.BLOCKED, reason="Empty command")

    # Normalize: strip leading "sudo" (and optional flags like -n, -S, -u root)
    # so pattern matching evaluates the actual command, not the elevation mechanism
    normalized = re.sub(r"^sudo\b\s*", "", stripped, flags=re.IGNORECASE)

    if any("|" in normalized and p in normalized for p in ["curl", "wget"]) and any(
        s in normalized for s in ["sh", "bash", "dash", "zsh"]
    ):
        return SafetyResult(level=SafetyLevel.BLOCKED, reason="Piping remote content to shell")

    for pattern, reason in BLOCKED_PATTERNS:
        if pattern.search(normalized):
            return SafetyResult(level=SafetyLevel.BLOCKED, reason=reason)

    for pattern, _reason in SAFE_COMMANDS:
        if pattern.search(normalized):
            for conf_pattern, conf_reason in CONFIRM_PATTERNS:
                if conf_pattern.search(normalized):
                    return SafetyResult(level=SafetyLevel.CONFIRM, reason=conf_reason)
            return SafetyResult(level=SafetyLevel.SAFE, reason="Read-only / status command")

    for pattern, reason in CONFIRM_PATTERNS:
        if pattern.search(normalized):
            return SafetyResult(level=SafetyLevel.CONFIRM, reason=reason)

    return SafetyResult(
        level=SafetyLevel.CONFIRM,
        reason="Command not in safe allowlist — requires approval",
    )
