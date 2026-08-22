from dataclasses import dataclass

from homelab_mcp.data.loader import DataLoader
from homelab_mcp.data_models import ConfigDirectory, ServiceEntry

GUEST_KINDS = {"vm", "lxc"}


@dataclass
class SshTarget:
    """A resolved command-execution target.

    For proxmox targets, commands run directly over SSH as the configured user.
    For guest targets (vm/lxc), commands are wrapped in `qm guest exec`/`pct exec`
    on the *proxmox node* named by the instance's `proxmox_node` field — the
    guest is never SSH'd into directly.
    """

    host: str
    node_name: str
    kind: str
    vmid: int | None = None


def resolve_config_paths(configs: list[ConfigDirectory]) -> list[dict[str, str]]:
    results = []
    for config_dir in configs:
        for f in config_dir.files:
            full_path = f"{config_dir.directory.rstrip('/')}/{f.path}"
            results.append({"path": full_path, "description": f.description})
    return results


def resolve_service_configs(
    data: DataLoader, node_name: str, service_name: str
) -> list[dict[str, str]] | None:
    services_node = data.get_services(node_name)
    if not services_node:
        return None
    for svc in services_node.host:
        if svc.name == service_name:
            return resolve_config_paths(svc.configs)
    for vm in services_node.vms:
        for svc in vm.services:
            if svc.name == service_name:
                return resolve_config_paths(svc.configs)
    return None


def search_services(data: DataLoader, node_name: str, query: str) -> list[dict]:
    query_lower = query.lower()
    results = []
    services_node = data.get_services(node_name)
    if not services_node:
        return results

    def matches(svc: ServiceEntry) -> bool:
        searchable = f"{svc.name} {svc.type} {svc.note or ''}".lower()
        return query_lower in searchable

    for svc in services_node.host:
        if matches(svc):
            results.append(
                {
                    "name": svc.name,
                    "type": svc.type,
                    "location": "host",
                    "service_name": svc.service_name,
                }
            )

    for vm in services_node.vms:
        for svc in vm.services:
            if matches(svc):
                results.append(
                    {
                        "name": svc.name,
                        "type": svc.type,
                        "location": f"vm:{vm.name}",
                        "service_name": svc.service_name,
                    }
                )

    return results


def resolve_node_ip(data: DataLoader, node_name: str) -> str | None:
    instance = data.get_instance(node_name)
    return instance.wan_ip if instance else None


def resolve_ssh_target(data: DataLoader, node_name: str) -> SshTarget | None:
    """Resolve a node name to an execution target.

    - proxmox node → direct SSH target at its wan_ip
    - vm/lxc guest → target on its `proxmox_node`, carrying the vmid

    Returns None if the node (or, for guests, its proxmox_node) is unknown.
    """
    instance = data.get_instance(node_name)
    if not instance:
        return None

    if instance.kind in GUEST_KINDS:
        if instance.vmid is None:
            raise ValueError(
                f"Instance '{node_name}' has kind '{instance.kind}' but no vmid — cannot route guest commands"
            )
        if instance.proxmox_node == node_name:
            raise ValueError(f"Instance '{node_name}' has invalid proxmox_node pointing at itself")
        host_instance = data.get_instance(instance.proxmox_node)
        if not host_instance:
            raise ValueError(
                f"proxmox_node '{instance.proxmox_node}' (referenced by '{node_name}') not found in instances"
            )
        if host_instance.kind in GUEST_KINDS:
            raise ValueError(
                f"proxmox_node '{instance.proxmox_node}' (referenced by '{node_name}') is itself a guest"
            )
        return SshTarget(
            host=host_instance.wan_ip,
            node_name=node_name,
            kind=instance.kind,
            vmid=instance.vmid,
        )

    return SshTarget(host=instance.wan_ip, node_name=node_name, kind=instance.kind)
