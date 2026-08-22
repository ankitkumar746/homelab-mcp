from pathlib import Path

import pytest

from homelab_mcp.data.loader import DataLoader
from homelab_mcp.data.resolver import resolve_ssh_target
from homelab_mcp.ssh.client import build_guest_command, parse_guest_exec_output
from homelab_mcp.ssh.safety import SafetyLevel, validate_command

INSTANCES_YAML = """
cluster:
  - name: homelab
    fqdn: homelab.ankit.lab
    platform_user: platform
    wan_ip: 192.168.29.167
    proxmox_node: homelab

  - name: infravm
    fqdn: infra-node-1.ankit.lab
    platform_user: platform
    wan_ip: 192.168.200.50
    proxmox_node: homelab
    kind: vm
    vmid: 50001

  - name: netbox01
    fqdn: netbox01.ankit.lab
    platform_user: platform
    wan_ip: 192.168.200.10
    proxmox_node: homelab
    kind: lxc
    vmid: 10001

  - name: novmid
    fqdn: novmid.lab
    platform_user: p
    wan_ip: 10.0.0.5
    proxmox_node: homelab
    kind: vm

  - name: badhost
    fqdn: badhost.lab
    platform_user: p
    wan_ip: 10.0.0.6
    proxmox_node: missing-node
    kind: lxc
    vmid: 10002

  - name: guesthost
    fqdn: guesthost.lab
    platform_user: p
    wan_ip: 10.0.0.7
    proxmox_node: infravm
    kind: lxc
    vmid: 10003
"""


@pytest.fixture()
def loader(tmp_path: Path) -> DataLoader:
    (tmp_path / "instances.yml").write_text(INSTANCES_YAML)
    return DataLoader(tmp_path)


class TestResolveSshTarget:
    def test_proxmox_node_direct(self, loader):
        target = resolve_ssh_target(loader, "homelab")
        assert target is not None
        assert target.host == "192.168.29.167"
        assert target.kind == "proxmox"
        assert target.vmid is None

    def test_vm_routes_to_proxmox_node(self, loader):
        target = resolve_ssh_target(loader, "infravm")
        assert target is not None
        assert target.host == "192.168.29.167"  # proxmox node, not the VM IP
        assert target.kind == "vm"
        assert target.vmid == 50001
        assert target.node_name == "infravm"

    def test_lxc_routes_to_proxmox_node(self, loader):
        target = resolve_ssh_target(loader, "netbox01")
        assert target is not None
        assert target.host == "192.168.29.167"
        assert target.kind == "lxc"
        assert target.vmid == 10001

    def test_unknown_node_returns_none(self, loader):
        assert resolve_ssh_target(loader, "nope") is None

    def test_guest_without_vmid_raises(self, loader):
        with pytest.raises(ValueError, match="vmid"):
            resolve_ssh_target(loader, "novmid")

    def test_guest_with_unknown_proxmox_node_raises(self, loader):
        with pytest.raises(ValueError, match="missing-node"):
            resolve_ssh_target(loader, "badhost")

    def test_guest_with_guest_proxmox_node_raises(self, loader):
        with pytest.raises(ValueError, match="itself a guest"):
            resolve_ssh_target(loader, "guesthost")

    def test_real_repo_instances_resolve(self):
        dl = DataLoader(Path("data"))
        for name in dl.get_node_names():
            target = resolve_ssh_target(dl, name)
            assert target is not None, f"{name} failed to resolve"


class TestBuildGuestCommand:
    def test_lxc(self):
        from homelab_mcp.data.resolver import SshTarget

        target = SshTarget(host="192.168.29.167", node_name="netbox01", kind="lxc", vmid=10001)
        cmd = build_guest_command(target, "systemctl status netbox --no-pager")
        assert cmd == "sudo pct exec 10001 -- bash -c 'systemctl status netbox --no-pager'"

    def test_vm(self):
        from homelab_mcp.data.resolver import SshTarget

        target = SshTarget(host="192.168.29.167", node_name="infravm", kind="vm", vmid=50001)
        cmd = build_guest_command(target, "cat /etc/dnsmasq.d/dhcp.conf")
        assert cmd == "sudo qm guest exec 50001 -- bash -c 'cat /etc/dnsmasq.d/dhcp.conf'"

    def test_inner_shell_metachars_are_quoted(self):
        from homelab_mcp.data.resolver import SshTarget

        target = SshTarget(host="h", node_name="n", kind="lxc", vmid=10001)
        cmd = build_guest_command(target, "ps aux | grep nginx; hostname")
        # the whole inner command must arrive as ONE bash -c argument
        assert cmd.endswith("'ps aux | grep nginx; hostname'")

    def test_inner_quote_is_escaped(self):
        from homelab_mcp.data.resolver import SshTarget

        target = SshTarget(host="h", node_name="n", kind="lxc", vmid=10001)
        cmd = build_guest_command(target, "grep 'server_name' /etc/nginx/nginx.conf")
        assert "bash -c " in cmd
        # shlex.quote handles the inner single quotes safely
        assert shlex_split_roundtrip(cmd) == [
            "sudo",
            "pct",
            "exec",
            "10001",
            "--",
            "bash",
            "-c",
            "grep 'server_name' /etc/nginx/nginx.conf",
        ]


def shlex_split_roundtrip(cmd: str) -> list[str]:
    import shlex

    return shlex.split(cmd)


class TestParseGuestExecOutput:
    def test_json_with_out_and_err(self):
        raw = '{"exitcode": 0, "out-data": "hello\\r\\nworld", "err-data": ""}'
        stdout, stderr, exit_code = parse_guest_exec_output(raw)
        assert stdout == "hello\r\nworld"
        assert stderr == ""
        assert exit_code == 0

    def test_json_nonzero_exit(self):
        raw = '{"exitcode": 4, "out-data": "", "err-data": "unit not found"}'
        stdout, stderr, exit_code = parse_guest_exec_output(raw)
        assert stdout == ""
        assert stderr == "unit not found"
        assert exit_code == 4

    def test_truncated_flag(self):
        raw = '{"exitcode": 0, "out-data": "x", "out-truncated": true}'
        _stdout, stderr, _ = parse_guest_exec_output(raw)
        assert "[output truncated by guest agent]" in stderr

    def test_non_json_falls_back_to_raw(self):
        raw = "some plain failure output"
        stdout, stderr, exit_code = parse_guest_exec_output(raw)
        assert stdout == raw
        assert stderr == ""
        assert exit_code == 0

    def test_json_array_falls_back_to_raw(self):
        raw = "[1, 2, 3]"
        stdout, _, _ = parse_guest_exec_output(raw)
        assert stdout == raw


class TestGuestRouteLockdown:
    """Raw pct exec / qm guest exec on the host must be BLOCKED so the
    read-only-gated vm/lxc targets are the only route into guests."""

    def test_raw_pct_exec_blocked(self):
        result = validate_command("pct exec 10001 -- bash -c 'cat /etc/hostname'")
        assert result.level == SafetyLevel.BLOCKED

    def test_raw_qm_guest_exec_blocked(self):
        result = validate_command("qm guest exec 50001 -- cat /etc/hostname")
        assert result.level == SafetyLevel.BLOCKED

    def test_sudo_prefixed_guest_exec_blocked(self):
        result = validate_command("sudo qm guest exec 50001 -- cat /etc/hostname")
        assert result.level == SafetyLevel.BLOCKED

    def test_pct_read_subcommands_stay_safe(self):
        for cmd in ["pct list", "pct status 10001", "pct config 10001"]:
            assert validate_command(cmd).level == SafetyLevel.SAFE

    def test_qm_read_subcommands_stay_safe(self):
        for cmd in ["qm list", "qm status 50001", "qm config 50001"]:
            assert validate_command(cmd).level == SafetyLevel.SAFE

    def test_agent_ping_stays_safe(self):
        result = validate_command("pvesh get /nodes/homelab/qemu/50001/agent/ping")
        assert result.level == SafetyLevel.SAFE


class TestGuestReadOnlyGateSemantics:
    """The gate itself lives in run_command (needs ctx); these pin the safety
    classification the gate depends on for common guest read-only vs mutating
    commands."""

    def test_common_readonly_guest_commands_are_safe(self):
        for cmd in [
            "cat /etc/netbox/configuration.py",
            "systemctl status netbox",
            "systemctl status netbox-rq",
            "journalctl -u netbox -n 100 --no-pager",
            "ip addr show",
            "ss -tlnp",
            "ps aux",
        ]:
            assert validate_command(cmd).level == SafetyLevel.SAFE, cmd

    def test_mutating_guest_commands_not_safe(self):
        for cmd in [
            "systemctl restart netbox",
            "apt install htop",
            "rm /tmp/x",
            "echo data > /etc/netbox/configuration.py",
            "systemctl stop nginx",
        ]:
            assert validate_command(cmd).level != SafetyLevel.SAFE, cmd
