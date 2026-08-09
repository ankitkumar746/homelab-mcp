# homelab-mcp

MCP server for managing a Proxmox homelab. Gives LLMs (Claude, GPT, etc.)
the ability to understand your infrastructure and run commands safely.

## What It Does

- Reads your homelab's YAML data files (hardware, network, services, instances)
- Exposes this data as MCP resources and tools that LLMs can query
- Lets the LLM SSH into Proxmox nodes to read configs, check services, run commands
- Safety pipeline blocks destructive commands (`rm -rf /`, `iptables -F`) and
  asks for your confirmation on risky ones (`systemctl restart`, `apt install`)

## Prerequisites

- macOS or Linux
- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- SSH access to your Proxmox node (key-based, not password)
- Git

## Setup from Scratch

### 1. Install uv

```bash
# macOS
brew install uv

# Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Clone the repo

```bash
git clone <repo-url> homelab-mcp
cd homelab-mcp
```

### 3. Install dependencies

```bash
uv sync
```

This reads `pyproject.toml`, resolves all dependencies, creates a `.venv/` folder,
and installs everything. No `pip3 install` needed — `uv` handles it all.

### 4. Create the MCP user on Proxmox

SSH into your Proxmox node as root:

```bash
ssh root@192.168.29.167
```

Create a dedicated user for the MCP server:

```bash
sudo useradd -r -m -s /bin/bash mcp
sudo mkdir -p /home/mcp/.ssh
sudo chmod 700 /home/mcp/.ssh
```

### 5. Set up SSH key authentication

On your **MacBook** (not Proxmox), generate a key pair for the MCP server:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/homelab_mcp -C "homelab-mcp"
```

Copy the public key to the Proxmox node. Since the `mcp` user has no password
and Proxmox only allows key-based auth, you need to SSH in as root first and
add the key manually:

```bash
# Copy your public key content on your Mac
cat ~/.ssh/homelab_mcp.pub

# SSH into Proxmox as root
ssh root@192.168.29.167

# On Proxmox — add the key manually
mkdir -p /home/mcp/.ssh
chmod 700 /home/mcp/.ssh
echo "PASTE_YOUR_PUBLIC_KEY_HERE" >> /home/mcp/.ssh/authorized_keys
chmod 600 /home/mcp/.ssh/authorized_keys
chown -R mcp:mcp /home/mcp/.ssh
```

Verify it works (should connect without asking for a password):

```bash
ssh -i ~/.ssh/homelab_mcp mcp@192.168.29.167 "hostname"
# Should print: homelab
```

### 6. (Optional) Set up sudo access on Proxmox

The MCP server runs commands via `sudo` (e.g., `sudo systemctl status`,
`sudo journalctl`, `sudo qm list`, `sudo cat /etc/...`). You have two options:

**Option A — Full sudo (simpler, less secure):**

```bash
visudo -f /etc/sudoers.d/mcp
```

```
mcp ALL=(ALL) NOPASSWD: ALL
```

**Option B — Restricted sudo (more secure):**

```
mcp ALL=(ALL) NOPASSWD: /usr/sbin/qm list, /usr/sbin/qm status *, \
    /usr/sbin/qm config *, \
    /usr/sbin/pct list, /usr/sbin/pct status *, \
    /usr/sbin/pct config *, \
    /usr/bin/pvesh get *, \
    /usr/sbin/pve-firewall status, \
    /usr/bin/systemctl status *, \
    /usr/bin/journalctl *, \
    /usr/bin/cat /etc/*, \
    /usr/bin/cat /srv/*, \
    /usr/bin/cat /var/*, \
    /usr/sbin/ip addr show, /usr/sbin/ip route show, \
    /usr/bin/ss -tlnp
```

Option B covers the read-only commands the inspect tools use. Anything beyond
that (like `systemctl restart`, `apt install`, `qm stop`) will prompt for
sudo password and fail — the safety pipeline will ask for your approval first,
but the command itself won't run without broader sudo access.

> **Note:** If you're just starting out, use Option A. You can tighten it later.

### 7. Create your `.env` file

```bash
cp .env.example .env
```

Edit `.env` with your settings. See the [Configuration](#configuration) section below
for all available variables.

### 8. Verify everything works

Run the tests:

```bash
uv run pytest tests/ -v
```

Test that the server starts:

```bash
uv run homelab-mcp
```

You should see no errors. Press `Ctrl+C` to stop it.

### 9. Add to Claude Code

```bash
claude mcp add homelab-mcp -- uv --directory /path/to/homelab-mcp run homelab-mcp
```

### 10. Add to opencode

Add to your `opencode.json` (or `.opencode/config.json` in the project root):

```json
{
  "mcp": {
    "servers": {
      "homelab-mcp": {
        "command": "uv",
        "args": ["--directory", "/path/to/homelab-mcp", "run", "homelab-mcp"]
      }
    }
  }
}
```

### 11. Add to Cursor / VS Code

Add to your MCP settings (`~/.cursor/mcp.json` or VS Code `settings.json`):

```json
{
  "mcpServers": {
    "homelab-mcp": {
      "command": "uv",
      "args": ["--directory", "/path/to/homelab-mcp", "run", "homelab-mcp"]
    }
  }
}
```

## Configuration

All config is done through environment variables. Create a `.env` file in the
project root (a `.env.example` template is provided).

| Variable | Default | Description |
|---|---|---|
| `HOMELAB_SSH_HOST` | `192.168.29.167` | Proxmox node IP or hostname |
| `HOMELAB_SSH_PORT` | `22` | SSH port |
| `HOMELAB_SSH_USER` | `mcp` | SSH username on Proxmox |
| `HOMELAB_SSH_KEY_PATH` | `~/.ssh/homelab_mcp` | Path to SSH private key on your machine |
| `HOMELAB_DATA_DIR` | `data` | Path to YAML data directory |
| `HOMELAB_LOG_DIR` | `logs` | Directory for JSONL log files (one per execution) |
| `HOMELAB_TRANSPORT` | `stdio` | MCP transport: `stdio` or `streamable-http` |
| `HOMELAB_HTTP_PORT` | `8000` | Port for `streamable-http` transport |
| `HOMELAB_LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

All variables have sensible defaults, so a minimal `.env` only needs to override
what differs in your setup.

## Available Tools

| Tool | What it does |
|---|---|
| `list_nodes` | List all Proxmox nodes |
| `get_hardware` | Hardware specs for a node (CPU, RAM, storage, etc.) |
| `get_network` | Network topology — NICs, WAN, bridges, NAT, DHCP, PXE |
| `list_services` | All services on a node (host + VMs + LXC) |
| `get_service` | Details for a specific service by name |
| `search_services` | Search services by keyword (matches name, type, notes) |
| `list_configs` | Config files for a service, with full reconstructed paths |
| `read_config` | SSH to node and read a config file's current contents |
| `check_service` | SSH to node and check systemd status of a service |
| `read_logs` | SSH to node and read journalctl logs for a service |
| `network_status` | SSH to node and check interfaces, routes, listening ports |
| `run_command` | SSH to node and run a command (goes through safety pipeline) |

## Available Resources

The LLM can read these to understand your infrastructure without running any commands:

| Resource URI | What it returns |
|---|---|
| `homelab://instances` | All node instances from `instances.yml` |
| `homelab://hardware/{node}` | Hardware specs for a specific node |
| `homelab://network/{node}` | Network config for a specific node |
| `homelab://services/{node}` | Services for a specific node |

## Available Prompts

| Prompt | What it does |
|---|---|
| `homelab_overview` | "Give me a complete picture of my homelab" |
| `troubleshoot_service` | "Service X is misbehaving, help me diagnose" |
| `review_firewall` | "Review my firewall rules for security gaps" |

## Command Safety Pipeline

Every command the LLM tries to run goes through a 3-tier safety check before
reaching your Proxmox server:

```
BLOCKED  →  Rejected immediately, never reaches the server
            Examples: rm -rf /, dd of=/dev/, shutdown, iptables -F

CONFIRM  →  You get asked for approval before it runs
            Examples: systemctl restart, apt install, rm (any), iptables rules,
            VM lifecycle (start/stop/destroy), editing files in /etc

SAFE     →  Executes directly, no approval needed
            Examples: cat, ls, systemctl status, journalctl, ping, ip addr,
            qm list, qm status, df, ps
```

Anything not explicitly in the SAFE list defaults to CONFIRM — the LLM must ask
you first. This means even if the LLM invents a command we've never seen before,
it can't run it silently.

## Running Tests

```bash
uv run pytest tests/ -v
```

This runs all tests in the `tests/` directory. The safety module has 57 tests
covering blocked, safe, confirm, and sudo-normalization patterns.

## Logging

The server writes structured JSONL logs — one file per execution, stored in
`logs/` (configurable via `HOMELAB_LOG_DIR` in `.env`).

Each log line is a JSON object with ClickHouse-compatible timestamps. Tool calls,
SSH commands, and safety events are all logged with timing and context.

### Log Analytics CLI

```bash
# Latest log file summary
uv run homelab-logview

# All log files aggregated
uv run homelab-logview --all

# Filter by date
uv run homelab-logview --date 2026-08-01

# Live tail (like tail -f)
uv run homelab-logview --tail

# Filter by tool name
uv run homelab-logview --tool check_service

# Show only errors
uv run homelab-logview --errors

# Show only safety events (blocked, confirm, rejected)
uv run homelab-logview --safety

# Export to CSV or JSON
uv run homelab-logview --all --export csv > report.csv
uv run homelab-logview --all --export json > report.json
```

The viewer shows overview stats (total calls, success rate, avg/p95 response
time), safety events table, top 10 most called tools, top 10 slowest requests,
and recent errors — all with rich formatting.

## Modifying YAML Data

The YAML files in `data/` define your homelab. If you change the **structure**
(add a new field, rename a key, change a value type), you must also update the
corresponding Pydantic model in `src/homelab_mcp/data_models.py`.

For example, if you add a `serial_number` field to a NIC in `network.yml`:

```yaml
nics:
  - name: nic0
    serial_number: SN-12345    # new field
    status: down
```

You must add it to the `Nic` model in `data_models.py`:

```python
class Nic(BaseModel):
    name: str
    serial_number: str | None = None  # add this
    status: str
    mac: str
```

If the YAML structure doesn't match the model, the server will fail to start
with a validation error telling you exactly what's wrong.

Adding new entries that follow the existing structure (new VMs, new services,
new config files) does **not** require model changes — only structural changes do.

## Project Structure

```
homelab-mcp/
├── pyproject.toml          # Project config, dependencies, entrypoints
├── uv.lock                 # Pinned exact versions of all dependencies
├── .env.example            # Template for environment variables
├── .opencode/config.json   # opencode MCP client config
├── data/                   # Static YAML data (your homelab definition)
│   ├── instances.yml
│   ├── hardware.yml
│   ├── network.yml
│   ├── services.yml
│   └── README.md           # Structure guide for the YAML files
├── logs/                   # JSONL log files (one per server execution)
├── src/homelab_mcp/        # The Python package
│   ├── server.py           # Entry point
│   ├── mcp_instance.py     # FastMCP instance + lifespan (startup/shutdown)
│   ├── context.py          # AppContext (shared state: config, data, ssh, logger)
│   ├── config.py           # Reads .env and environment variables
│   ├── jsonlog.py          # JSON logger setup, ClickHouse timestamps, redaction
│   ├── logview.py          # Log analytics CLI (homelab-logview command)
│   ├── data_models.py      # Pydantic models matching YAML structure
│   ├── data/               # YAML loading and cross-referencing
│   │   ├── loader.py       # Load, validate, cache YAML files
│   │   └── resolver.py     # Resolve service→config paths, search, etc.
│   ├── ssh/                # SSH connection and safety
│   │   ├── client.py       # AsyncSSH connection pool with logging
│   │   └── safety.py       # 3-tier command safety pipeline (sudo-aware)
│   ├── tools/              # MCP tools (actions the LLM can take)
│   │   ├── inventory.py    # list_nodes, get_hardware, list_services, etc.
│   │   ├── inspect.py      # read_config, check_service, read_logs, etc.
│   │   └── execute.py      # run_command (with safety checks + audit logging)
│   ├── resources/          # MCP resources (data the LLM can read)
│   │   └── static_data.py  # YAML data exposed as resources
│   └── prompts/            # MCP prompts (reusable templates)
│       └── homelab.py      # homelab_overview, troubleshoot, etc.
└── tests/                  # Automated tests
    ├── test_safety.py      # 57 tests: blocked, safe, confirm, sudo normalization
    └── test_loader.py      # 8 tests for YAML data loading
```
