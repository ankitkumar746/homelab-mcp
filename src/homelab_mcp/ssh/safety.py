"""Three-tier command safety pipeline.

The command is first split into shell "units" — segments separated by ``;``,
``&&``, ``||``, ``|``, ``&`` and newlines — plus the bodies of command
substitutions (``$(...)``, ``...``). Splitting is quote-aware: separators and
substitutions inside single/double quotes are literal text, not shell syntax.

Every unit is classified independently and the most severe result wins
(BLOCKED > CONFIRM > SAFE). A command is SAFE only if *every* unit is SAFE.
Anything that cannot be parsed with certainty (unbalanced quotes, unclosed
substitutions) fails closed to CONFIRM.

Known limitation: heredoc bodies are scanned as if they were commands, which
can only make the verdict more conservative, never less.
"""

import re
from dataclasses import dataclass
from enum import Enum


class SafetyLevel(Enum):
    BLOCKED = "blocked"
    CONFIRM = "confirm"
    SAFE = "safe"


@dataclass
class SafetyResult:
    level: SafetyLevel
    reason: str


# --------------------------------------------------------------------------
# Command-name sets (matched against the first token of each unit)
# --------------------------------------------------------------------------

POWER_COMMANDS = {"shutdown", "reboot", "poweroff", "halt"}
PARTITION_COMMANDS = {"fdisk", "sfdisk", "cfdisk", "parted", "gdisk", "sgdisk"}
BLOCKED_NAME_PREFIXES = ("mkfs",)

SYSTEMCTL_READ = {
    "status",
    "is-active",
    "is-enabled",
    "is-failed",
    "show",
    "cat",
    "help",
    "list-units",
    "list-jobs",
    "list-timers",
    "list-unit-files",
    "list-dependencies",
    "list-sockets",
    "list-machines",
}
SYSTEMCTL_POWER = {
    "reboot",
    "poweroff",
    "halt",
    "shutdown",
    "suspend",
    "hibernate",
    "kexec",
    "emergency",
    "rescue",
}

FETCHERS = {"curl", "wget"}
DOCKER_READ = {
    "ps",
    "images",
    "inspect",
    "logs",
    "top",
    "version",
    "info",
    "port",
    "stats",
}
INTERPRETERS = {
    "sh",
    "bash",
    "dash",
    "zsh",
    "ksh",
    "python",
    "python2",
    "python3",
    "perl",
    "ruby",
    "node",
    "php",
    "lua",
}

SAFE_COMMAND_NAMES = {
    "cat",
    "ls",
    "stat",
    "head",
    "tail",
    "less",
    "file",
    "wc",
    "hostname",
    "uname",
    "df",
    "free",
    "ps",
    "uptime",
    "dmesg",
    "ping",
    "traceroute",
    "ss",
    "grep",
    "egrep",
    "fgrep",
    "cut",
    "tr",
    "uniq",
    "column",
    "jq",
    "journalctl",
}

# ip OBJECTS that have read-only show semantics; any other subcommand
# (set/add/del/change/replace/flush/exec...) is treated as a config change.
IP_OBJECTS = {
    "addr",
    "address",
    "a",
    "link",
    "l",
    "route",
    "r",
    "rule",
    "neigh",
    "neighbor",
    "n",
    "netns",
}
IP_READ_ACTIONS = {"show", "list", "get", "dump"}
IP_OPTS_WITH_ARG = {"-f", "--family", "-netns", "--netns", "-N"}

FIND_DESTRUCTIVE_PREFIXES = (
    "-delete",
    "-exec",
    "-execdir",
    "-ok",
    "-okdir",
    "-fprint",
    "-fprintf",
    "-fls",
)

SHELL_KEYWORDS = {
    "if",
    "then",
    "else",
    "elif",
    "fi",
    "do",
    "done",
    "for",
    "while",
    "until",
    "case",
    "esac",
    "in",
    "time",
    "exec",
    "nohup",
    "nice",
    "command",
    "builtin",
    "env",
    "!",
    "{",
    "}",
}

SUDO_WITH_ARG = {
    "-u",
    "--user",
    "-g",
    "--group",
    "-p",
    "--prompt",
    "-C",
    "--close-from",
    "-D",
    "--chdir",
    "-r",
    "--role",
    "-t",
    "--type",
    "-U",
    "--other-user",
}

# --------------------------------------------------------------------------
# Regex rules (applied per unit, after sudo/keyword normalization)
# --------------------------------------------------------------------------

BLOCKED_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\brm\s+-[a-zA-Z]*f[a-zA-Z]*\s+(/[^\s]*|~)", re.IGNORECASE),
        "Recursive force delete on root-like paths",
    ),
    (re.compile(r"\bdd\b.*\bof=/dev/", re.IGNORECASE), "Direct disk write with dd"),
    (
        re.compile(r"\biptables\s+(?:-\S+\s+)*(?:-F|--flush)\b", re.IGNORECASE),
        "Flush all firewall rules",
    ),
    (re.compile(r":\(\)\s*\{.*:\|:&\s*\}", re.IGNORECASE | re.DOTALL), "Fork bomb pattern"),
    (
        re.compile(r"\bchmod\s+(?:-[A-Za-z]+\s+)*(?:000|777)\s+/", re.IGNORECASE),
        "Dangerous chmod on system paths",
    ),
    (
        re.compile(r">\s*/etc/(?:passwd|shadow|sudoers)\b", re.IGNORECASE),
        "Overwrite critical /etc file via redirection",
    ),
    (
        re.compile(r"\btee\s+(?:-\S+\s+)*/etc/(?:passwd|shadow|sudoers)\b", re.IGNORECASE),
        "Overwrite critical /etc file via tee",
    ),
    (
        re.compile(r"\bpct\s+exec\b", re.IGNORECASE),
        "Guest access must go through vm/lxc node targets (read-only enforced) — raw 'pct exec' is blocked",
    ),
    (
        re.compile(r"\bqm\s+guest\s+exec\b", re.IGNORECASE),
        "Guest access must go through vm/lxc node targets (read-only enforced) — raw 'qm guest exec' is blocked",
    ),
]

CONFIRM_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\brm\s+", re.IGNORECASE), "File deletion"),
    (
        re.compile(
            r"\bsystemctl\s+(?:-\S+\s+)*(?:stop|restart|disable|mask|start|enable|kill|reload|isolate|edit|daemon-reload)\b",
            re.IGNORECASE,
        ),
        "Service management",
    ),
    (
        re.compile(
            r"\bapt(?:-get)?\s+(?:install|remove|purge|update|upgrade|full-upgrade)\b",
            re.IGNORECASE,
        ),
        "Package management",
    ),
    (re.compile(r"\biptables\b", re.IGNORECASE), "Firewall modification"),
    (
        re.compile(
            r"\b(?:qm|pct)\s+(?:start|stop|destroy|create|suspend|resume|shutdown|reboot|migrate|resize|rollback|template|clone)\b",
            re.IGNORECASE,
        ),
        "VM/Container lifecycle change",
    ),
    (re.compile(r"\bmv\b.*\s+/etc/\b", re.IGNORECASE), "Moving files in /etc"),
    (re.compile(r"\bcp\b.*\s+/etc/\b", re.IGNORECASE), "Copying files into /etc"),
    (re.compile(r"\bsed\s+[^;|]*\s-i\b", re.IGNORECASE), "In-place file editing with sed"),
]

_SEVERITY_ORDER = [SafetyLevel.BLOCKED, SafetyLevel.CONFIRM, SafetyLevel.SAFE]

_FD_DUP_RE = re.compile(r"\d*>&\d")
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


# --------------------------------------------------------------------------
# Quote-aware splitting
# --------------------------------------------------------------------------


def _flush(buf: list[str], units: list[str]) -> None:
    text = "".join(buf).strip()
    if text and text.strip(" \t;|&(){}\n\r"):
        units.append(text)


def _read_backtick(s: str, start: int) -> tuple[str, bool, int]:
    """Read backtick-substitution body starting after the opening backtick."""
    i = start
    in_single = in_double = False
    while i < len(s):
        c = s[i]
        if in_single:
            if c == "'":
                in_single = False
        elif in_double:
            if c == "\\":
                i += 1
            elif c == '"':
                in_double = False
        else:
            if c == "'":
                in_single = True
            elif c == '"':
                in_double = True
            elif c == "\\":
                i += 1
            elif c == "`":
                return s[start:i], True, i + 1
            elif c == "$" and i + 1 < len(s) and s[i + 1] == "(":
                _inner, ok, j = _read_paren(s, i + 2)
                if not ok:
                    return "", False, i
                i = j
                continue
        i += 1
    return "", False, i


def _read_paren(s: str, start: int) -> tuple[str, bool, int]:
    """Read $(...) body starting after the opening parenthesis."""
    depth = 1
    i = start
    in_single = in_double = False
    while i < len(s):
        c = s[i]
        if in_single:
            if c == "'":
                in_single = False
        elif in_double:
            if c == "\\":
                i += 1
            elif c == '"':
                in_double = False
        else:
            if c == "'":
                in_single = True
            elif c == '"':
                in_double = True
            elif c == "\\":
                i += 1
            elif c == "`":
                _inner, ok, j = _read_backtick(s, i + 1)
                if not ok:
                    return "", False, i
                i = j
                continue
            elif c == "$" and i + 1 < len(s) and s[i + 1] == "(":
                _inner, ok, j = _read_paren(s, i + 2)
                if not ok:
                    return "", False, i
                i = j
                continue
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    return s[start:i], True, i + 1
        i += 1
    return "", False, i


def _split_into_units(text: str) -> tuple[list[str], bool]:
    """Split a command string into units (command segments + substitution bodies).

    Returns (units, parse_ok). parse_ok is False on unbalanced quotes or
    unclosed substitutions — callers must fail closed in that case.
    """
    units: list[str] = []

    def scan(s: str) -> bool:
        buf: list[str] = []
        i = 0
        n = len(s)
        in_single = in_double = False
        while i < n:
            c = s[i]
            if in_single:
                if c == "'":
                    in_single = False
                buf.append(c)
                i += 1
                continue
            if in_double:
                if c == "\\" and i + 1 < n and s[i + 1] in '"\\$`':
                    buf.append(c)
                    buf.append(s[i + 1])
                    i += 2
                    continue
                if c == '"':
                    in_double = False
                    buf.append(c)
                    i += 1
                    continue
                # $(...) and backticks execute even inside double quotes
                if c == "`":
                    inner, ok, j = _read_backtick(s, i + 1)
                    if not ok:
                        return False
                    if not scan(inner):
                        return False
                    buf.append(" ")
                    i = j
                    continue
                if c == "$" and i + 1 < n and s[i + 1] == "(":
                    inner, ok, j = _read_paren(s, i + 2)
                    if not ok:
                        return False
                    if not scan(inner):
                        return False
                    buf.append(" ")
                    i = j
                    continue
                buf.append(c)
                i += 1
                continue
            if c == "\\" and i + 1 < n:
                buf.append(c)
                buf.append(s[i + 1])
                i += 2
                continue
            if c == "'":
                in_single = True
                buf.append(c)
                i += 1
                continue
            if c == '"':
                in_double = True
                buf.append(c)
                i += 1
                continue
            if c == "`":
                inner, ok, j = _read_backtick(s, i + 1)
                if not ok:
                    return False
                if not scan(inner):
                    return False
                buf.append(" ")
                i = j
                continue
            if c == "$" and i + 1 < n and s[i + 1] == "(":
                # bash arithmetic $((...)) is not a command substitution
                if s[i + 1 : i + 3] == "((" and "))" in s[i + 2 :]:
                    j = s.index("))", i + 2)
                    buf.append(s[i : j + 2])
                    i = j + 2
                    continue
                inner, ok, j = _read_paren(s, i + 2)
                if not ok:
                    return False
                if not scan(inner):
                    return False
                buf.append(" ")
                i = j
                continue
            if c == "&" and ((buf and buf[-1] == ">") or (i + 1 < n and s[i + 1] == ">")):
                # part of a redirection (2>&1, >&2, &>) — not a separator
                buf.append(c)
                i += 1
                continue
            if c in ";|&\n\r":
                _flush(buf, units)
                buf = []
                i += 1
                continue
            if c in "()":
                _flush(buf, units)
                buf = []
                i += 1
                continue
            buf.append(c)
            i += 1
        if in_single or in_double:
            return False
        _flush(buf, units)
        return True

    ok = scan(text)
    return units, ok


# --------------------------------------------------------------------------
# Normalization helpers
# --------------------------------------------------------------------------


def _strip_prefix_tokens(tokens: list[str]) -> list[str]:
    """Strip leading sudo/doas (with options), env assignments and shell keywords."""
    i = 0
    while i < len(tokens):
        t = tokens[i].lower()
        if t in ("sudo", "doas"):
            i += 1
            while i < len(tokens) and tokens[i].startswith("-") and tokens[i] not in ("-", "--"):
                if tokens[i].lower() in SUDO_WITH_ARG:
                    i += 2
                else:
                    i += 1
            continue
        if t in SHELL_KEYWORDS or _ENV_ASSIGN_RE.match(tokens[i]):
            i += 1
            continue
        break
    return tokens[i:]


def _remove_quote_chars(s: str) -> str:
    """Remove quote characters but keep quoted contents (unescaping doubles)."""
    out: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "'":
            j = s.find("'", i + 1)
            if j == -1:
                out.append(s[i + 1 :])
                break
            out.append(s[i + 1 : j])
            i = j + 1
        elif c == '"':
            i += 1
            while i < n and s[i] != '"':
                if s[i] == "\\" and i + 1 < n:
                    out.append(s[i + 1])
                    i += 2
                else:
                    out.append(s[i])
                    i += 1
            i += 1
        elif c == "\\" and i + 1 < n:
            out.append(s[i + 1])
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _strip_quoted_contents(s: str) -> str:
    """Remove quoted spans entirely (used to detect *real* operators only)."""
    out: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "'":
            j = s.find("'", i + 1)
            if j == -1:
                break
            i = j + 1
        elif c == '"':
            i += 1
            while i < n and s[i] != '"':
                if s[i] == "\\" and i + 1 < n:
                    i += 2
                else:
                    i += 1
            i += 1
        elif c == "\\" and i + 1 < n:
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _has_output_redirect(unquoted: str) -> bool:
    """True if the text contains an output redirection (2>&1-style dups excluded)."""
    return ">" in _FD_DUP_RE.sub("", unquoted)


def _first_non_option(tokens: list[str]) -> str | None:
    for t in tokens:
        if not t.startswith("-"):
            return t
    return None


# --------------------------------------------------------------------------
# Per-unit classifiers
# --------------------------------------------------------------------------


def _classify_ip(tokens: list[str]) -> SafetyResult:
    """tokens[0] == 'ip'. Show/list semantics are SAFE; anything else CONFIRM."""
    rest = tokens[1:]
    i = 0
    while i < len(rest):
        if rest[i] in IP_OPTS_WITH_ARG:
            i += 2
        elif rest[i].startswith("-"):
            i += 1
        else:
            break
    if i >= len(rest):
        return SafetyResult(level=SafetyLevel.SAFE, reason="Network status")
    if rest[i].lower() not in IP_OBJECTS:
        return SafetyResult(
            level=SafetyLevel.CONFIRM, reason="Network command (unknown ip subcommand)"
        )
    i += 1
    while i < len(rest) and rest[i].startswith("-"):
        if rest[i] in IP_OPTS_WITH_ARG:
            i += 2
        else:
            i += 1
    if i >= len(rest):
        return SafetyResult(level=SafetyLevel.SAFE, reason="Network status")
    if rest[i].lower() in IP_READ_ACTIONS:
        return SafetyResult(level=SafetyLevel.SAFE, reason="Network status")
    return SafetyResult(level=SafetyLevel.CONFIRM, reason="Network configuration change")


def _is_safe_command(cmd: str, tokens: list[str]) -> bool:
    if cmd == "hostname":
        # bare hostname / hostname -f is read-only; hostname <name> sets it
        return _first_non_option(tokens[1:]) is None
    if cmd == "top":
        return any(t.startswith("-bn") for t in tokens[1:])
    if cmd in ("qm", "pct"):
        return _first_non_option(tokens[1:]) in {"list", "status", "config"}
    if cmd == "pvesh":
        return _first_non_option(tokens[1:]) == "get"
    return cmd in SAFE_COMMAND_NAMES


def _classify_unit(unit: str) -> tuple[SafetyResult, str | None]:
    tokens = _strip_prefix_tokens(unit.split())
    if not tokens:
        return (
            SafetyResult(level=SafetyLevel.CONFIRM, reason="Unrecognized command"),
            None,
        )
    cmd = tokens[0].lstrip("\\").rsplit("/", 1)[-1].lower()
    plain = _remove_quote_chars(" ".join(tokens))
    unquoted = _strip_quoted_contents(" ".join(tokens))

    # 1. Blocked by command name
    if cmd in POWER_COMMANDS or cmd in PARTITION_COMMANDS or cmd.startswith(BLOCKED_NAME_PREFIXES):
        return (
            SafetyResult(
                level=SafetyLevel.BLOCKED, reason=f"System power/partition command: {cmd}"
            ),
            cmd,
        )

    # 2. Blocked regex rules
    for pattern, reason in BLOCKED_PATTERNS:
        if pattern.search(plain):
            return SafetyResult(level=SafetyLevel.BLOCKED, reason=reason), cmd

    # 3. find: SAFE unless it has write/execute action flags
    if cmd == "find":
        if any(t.startswith(p) for t in tokens[1:] for p in FIND_DESTRUCTIVE_PREFIXES):
            return (
                SafetyResult(level=SafetyLevel.CONFIRM, reason="find with write/execute action"),
                cmd,
            )
        return SafetyResult(level=SafetyLevel.SAFE, reason="Read-only / status command"), cmd

    # 4. Output redirection is a file write — never SAFE silently
    if _has_output_redirect(unquoted):
        return (
            SafetyResult(level=SafetyLevel.CONFIRM, reason="Output redirection — may write a file"),
            cmd,
        )

    # 5. ip subcommand analysis
    if cmd == "ip":
        return _classify_ip(tokens), cmd

    # 6. systemctl subcommand analysis
    if cmd == "systemctl":
        sub = _first_non_option(tokens[1:])
        sub = sub.lower() if sub else None
        if sub is None:
            return (
                SafetyResult(
                    level=SafetyLevel.CONFIRM,
                    reason="Command not in safe allowlist — requires approval",
                ),
                cmd,
            )
        if sub in SYSTEMCTL_POWER:
            return (
                SafetyResult(
                    level=SafetyLevel.BLOCKED, reason=f"systemctl {sub} — system power state change"
                ),
                cmd,
            )
        if sub not in SYSTEMCTL_READ:
            return SafetyResult(level=SafetyLevel.CONFIRM, reason="Service management"), cmd
        return SafetyResult(level=SafetyLevel.SAFE, reason="Read-only / status command"), cmd

    # 6b. docker subcommand analysis
    if cmd == "docker":
        sub = _first_non_option(tokens[1:])
        sub = sub.lower() if sub else None
        if sub is not None and sub in DOCKER_READ:
            return SafetyResult(level=SafetyLevel.SAFE, reason="Read-only / status command"), cmd
        return SafetyResult(level=SafetyLevel.CONFIRM, reason="Docker management"), cmd

    # 7. SAFE allowlist
    if _is_safe_command(cmd, tokens):
        return SafetyResult(level=SafetyLevel.SAFE, reason="Read-only / status command"), cmd

    # 8. CONFIRM regex rules, then default
    for pattern, reason in CONFIRM_PATTERNS:
        if pattern.search(plain):
            return SafetyResult(level=SafetyLevel.CONFIRM, reason=reason), cmd

    return (
        SafetyResult(
            level=SafetyLevel.CONFIRM, reason="Command not in safe allowlist — requires approval"
        ),
        cmd,
    )


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def validate_command(command: str) -> SafetyResult:
    stripped = command.strip()

    if not stripped:
        return SafetyResult(level=SafetyLevel.BLOCKED, reason="Empty command")

    units, parse_ok = _split_into_units(stripped)
    if not parse_ok:
        return SafetyResult(
            level=SafetyLevel.CONFIRM,
            reason="Could not parse command structure — requires approval",
        )

    # Full-string catch-alls that need the original contiguous text (fork bomb)
    for pattern, reason in BLOCKED_PATTERNS:
        if pattern.search(stripped):
            return SafetyResult(level=SafetyLevel.BLOCKED, reason=reason)

    results: list[SafetyResult] = []
    command_names: set[str] = set()
    for unit in units:
        result, cmd = _classify_unit(unit)
        if cmd:
            command_names.add(cmd)
        results.append(result)

    if not results:
        return SafetyResult(
            level=SafetyLevel.CONFIRM,
            reason="No recognizable command — requires approval",
        )

    if any(r.level == SafetyLevel.BLOCKED for r in results):
        return next(r for r in results if r.level == SafetyLevel.BLOCKED)

    if command_names & FETCHERS and command_names & INTERPRETERS:
        return SafetyResult(
            level=SafetyLevel.BLOCKED,
            reason="Remote content downloaded and executed",
        )

    if any(r.level == SafetyLevel.CONFIRM for r in results):
        return next(r for r in results if r.level == SafetyLevel.CONFIRM)

    return SafetyResult(level=SafetyLevel.SAFE, reason="Read-only / status command")
