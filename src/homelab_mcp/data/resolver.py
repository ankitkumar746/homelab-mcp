from homelab_mcp.data.loader import DataLoader
from homelab_mcp.data_models import ConfigDirectory, ServiceEntry


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


def search_services(
    data: DataLoader, node_name: str, query: str
) -> list[dict]:
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
            results.append({"name": svc.name, "type": svc.type, "location": "host", "service_name": svc.service_name})

    for vm in services_node.vms:
        for svc in vm.services:
            if matches(svc):
                results.append({"name": svc.name, "type": svc.type, "location": f"vm:{vm.name}", "service_name": svc.service_name})

    return results


def resolve_node_ip(data: DataLoader, node_name: str) -> str | None:
    instance = data.get_instance(node_name)
    return instance.wan_ip if instance else None
