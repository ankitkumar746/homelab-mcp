from homelab_mcp.mcp_instance import mcp


@mcp.prompt(title="Homelab Overview")
def homelab_overview() -> str:
    """Generate a comprehensive overview of the homelab infrastructure."""
    return (
        "Please provide a complete overview of my homelab. "
        "Use the homelab://instances, homelab://hardware/homelab, "
        "homelab://network/homelab, and homelab://services/homelab resources "
        "to gather information, then summarize:\n"
        "1. Hardware capabilities\n"
        "2. Network topology (WAN, bridges, NAT)\n"
        "3. All running services and their purposes\n"
        "4. VM infrastructure\n"
        "5. Any potential concerns or recommendations"
    )


@mcp.prompt(title="Troubleshoot Service")
def troubleshoot_service(service_name: str, node_name: str = "homelab") -> str:
    """Template for diagnosing a misbehaving service.

    Args:
        service_name: Name of the service to troubleshoot (e.g., 'dnsmasq')
        node_name: Node where the service runs (default: 'homelab')
    """
    return (
        f"The service '{service_name}' on node '{node_name}' is misbehaving. "
        "Please help me troubleshoot:\n\n"
        f"1. First, use get_service to understand what '{service_name}' does and where its config files are.\n"
        f"2. Use check_service to see the current systemd status.\n"
        f"3. Use read_logs to check recent journalctl output for '{service_name}'.\n"
        f"4. Read relevant config files using read_config.\n"
        "5. Identify the root cause and suggest fixes.\n\n"
        "Important: Do NOT restart or modify anything without asking for my approval first."
    )


@mcp.prompt(title="Review Firewall")
def review_firewall(node_name: str = "homelab") -> str:
    """Template for reviewing firewall configuration and rules.

    Args:
        node_name: Node to review (default: 'homelab')
    """
    return (
        f"Please review the firewall configuration on node '{node_name}':\n\n"
        "1. Use get_service to find firewall-related services and config files.\n"
        "2. Read the firewall config files (host.fw, cluster.fw) using read_config.\n"
        "3. Use run_command to check current iptables rules (iptables-save or iptables -L -n -v).\n"
        "4. Review for security gaps, overly permissive rules, or misconfigurations.\n"
        "5. Suggest improvements if any.\n\n"
        "Important: Do NOT modify any firewall rules without asking for my approval first."
    )
