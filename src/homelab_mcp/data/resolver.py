from dataclasses import dataclass

from homelab_mcp.config import AppConfig
from homelab_mcp.data.loader import DataLoader
from homelab_mcp.data_models import ConfigDirectory, ServiceEntry


@dataclass
class SshTarget:
    """A fully-resolved SSH destination (per-node settings merged with global config)."""

    host: str
    user: str
    port: int
    key_path: str
    use_sudo: bool
    node_name: str
    kind: str
    jump: "SshTarget | None" = None


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


def resolve_ssh_target(
    data: DataLoader, config: AppConfig, node_name: str, _visited: set[str] | None = None
) -> SshTarget | None:
    """Resolve a node name to a fully-merged SshTarget, including its jump chain.

    Returns None if the node is unknown; raises ValueError on jump-host cycles
    or a jump_via that names an unknown node.
    """
    instance = data.get_instance(node_name)
    if not instance:
        return None

    visited = _visited if _visited is not None else set()
    if node_name in visited:
        raise ValueError(f"SSH jump-host cycle detected at '{node_name}'")
    visited.add(node_name)

    settings = instance.ssh
    jump: SshTarget | None = None
    if settings and settings.jump_via:
        jump = resolve_ssh_target(data, config, settings.jump_via, visited)
        if jump is None:
            raise ValueError(
                f"Jump host '{settings.jump_via}' (referenced by '{node_name}') not found"
            )

    return SshTarget(
        host=instance.wan_ip,
        user=(settings.user if settings and settings.user else config.ssh_user),
        port=(settings.port if settings and settings.port else config.ssh_port),
        key_path=(settings.key_path if settings and settings.key_path else config.ssh_key_path),
        use_sudo=(
            config.ssh_use_sudo
            if settings is None or settings.use_sudo is None
            else settings.use_sudo
        ),
        node_name=node_name,
        kind=instance.kind,
        jump=jump,
    )
