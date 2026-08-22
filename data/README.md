# Homelab Data Files — Structure Guide

## Overview

All YAML files follow a consistent structure so they are readable by humans,
parseable by the MCP server, and understandable by LLMs.

## Files

| File | Purpose | Mutability |
|---|---|---|
| `instances.yaml` | Registry of all Proxmox nodes in the cluster | Static |
| `hardware.yaml` | Physical hardware specs per node | Static |
| `network.yaml` | Network topology, interfaces, NAT, DHCP, PXE per node | Semi-static |
| `services.yaml` | Software services running on host, VMs, and LXC per node | Semi-static |
| `homelab.db` | SQLite database for dynamic data (VMs, containers, facts) | Dynamic |

## Structural Rules

### Rule 1: Every file uses `cluster:` as a list of nodes

```yaml
cluster:
  - name: homelab
    ...
  - name: backup-node
    ...
```

The MCP server finds a node by filtering the list where `name` matches.
Node names must be identical across all files.

### Rule 2: Every collection is a list, keyed by `name`

```yaml
nics:
  - name: nic0
    ...
  - name: wlp12s0
    ...
```

Exception: `configs` uses `directory` + `files` (see Rule 5).

### Rule 3: Every node has `host`, `vms`, `lxc` sections

Applies to `network.yaml` and `services.yaml`:

```yaml
cluster:
  - name: homelab
    host:
      ...
    vms:
      - name: infravm
        ...
    lxc: []
```

All three sections must be present. Use `[]` when empty.
`hardware.yaml` and `instances.yaml` do not use these sections.

### Rule 4: VM/container names must match across files and SQLite

The `name` field for a VM must be identical in `network.yaml`,
`services.yaml`, and the SQLite `vms` table.

```
network.yaml   →  vms: [{ name: infravm, ... }]
services.yaml  →  vms: [{ name: infravm, services: [...] }]
SQLite         →  INSERT INTO vms (name, ...) VALUES ('infravm', ...);
```

### Rule 5: Config files use `configs:` grouped by directory

```yaml
configs:
  - directory: /etc/dnsmasq.d
    files:
      - path: dhcp.conf
        description: DHCP range and gateway config
      - path: tftp-ipxe.conf
        description: PXE boot and TFTP server
  - directory: /etc/nginx/sites-available
    files:
      - path: pxe
        description: PXE HTTP server
```

The MCP server reconstructs full paths: `directory + "/" + path`.

For files in subdirectories, use the relative path from directory:

```yaml
- directory: /etc/network
  files:
    - path: if-up.d/masquerade
      description: iptables MASQUERADE rule
```

### Rule 6: YAML = intent (static), SQLite = state (dynamic)

| Data type | Where | Why |
|---|---|---|
| Hardware specs | YAML | Changes only on upgrade |
| Network topology | YAML | Architecture decision |
| Service definitions | YAML | Architecture decision |
| Config file paths | YAML | Part of architecture definition |
| VM inventory (VMID, status) | SQLite | VMs get created and destroyed |
| Container inventory | SQLite | Same |
| Runtime facts | SQLite | Dynamic metadata |

## How to Add a New Node

Add a list entry with the same `name` to every YAML file:

```yaml
cluster:
  - name: homelab
    ...
  - name: new-node
    ...
```

Update all four YAML files: `instances.yaml`, `hardware.yaml`,
`network.yaml`, `services.yaml`.

## How to Add a New VM

1. Add VM to `network.yaml` under the node's `vms:` list
2. Add VM to `services.yaml` under the node's `vms:` list
3. Add VM to SQLite: `INSERT INTO vms (name, vmid, node, ...) VALUES (...)`
4. Use the same `name` in all three places

## How to Add a New LXC Container

Same as VM but under `lxc:` instead of `vms:` in both YAML files.
Insert into SQLite `containers` table instead of `vms`.

## How to Add a New Service

Determine where the service runs:

```yaml
host:                           # Base OS of the Proxmox node
  - name: my-service
    type: monitoring
    service_name: my-service
    configs:
      - directory: /etc/my-service
        files:
          - path: config.conf
            description: Main configuration
```

For a service inside a VM:

```yaml
vms:
  - name: infravm
    services:
      - name: my-service
        type: monitoring
        service_name: my-service
        configs:
          - directory: /etc/my-service
            files:
              - path: config.conf
                description: Main configuration
```

## How to Add a New Config File

Find the relevant `configs:` section and add an entry.
If the directory already exists, add to its `files:` list.
If not, create a new directory group:

```yaml
configs:
  - directory: /etc/new-service
    files:
      - path: main.conf
        description: Main service config
      - path: logging.conf
        description: Logging configuration
```

## How to Add a New Network Interface

Add to the `nics:` list in `network.yaml`:

```yaml
nics:
  - name: nic1
    status: down
    mac: AA:BB:CC:DD:EE:FF
    note: Secondary NIC, not yet in use
```

If it bridges to VMs, also add to `bridges:` and reference
it in `bridge_ports`.
