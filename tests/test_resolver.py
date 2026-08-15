from pathlib import Path

import pytest

from homelab_mcp.config import AppConfig
from homelab_mcp.data.loader import DataLoader, DataLoadError
from homelab_mcp.data.resolver import resolve_ssh_target

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
    ssh:
      jump_via: homelab
      user: mcp
      use_sudo: true

  - name: nestedvm
    fqdn: nested.ankit.lab
    platform_user: platform
    wan_ip: 10.0.0.10
    proxmox_node: homelab
    kind: vm
    ssh:
      jump_via: infravm
      port: 2222
      key_path: ~/.ssh/nested_key
      use_sudo: false

  - name: loopa
    fqdn: loopa.ankit.lab
    platform_user: platform
    wan_ip: 10.0.0.1
    proxmox_node: homelab
    ssh:
      jump_via: loopb

  - name: loopb
    fqdn: loopb.ankit.lab
    platform_user: platform
    wan_ip: 10.0.0.2
    proxmox_node: homelab
    ssh:
      jump_via: loopa

  - name: badjump
    fqdn: badjump.ankit.lab
    platform_user: platform
    wan_ip: 10.0.0.3
    proxmox_node: homelab
    ssh:
      jump_via: nonexistent
"""


@pytest.fixture()
def loader(tmp_path: Path) -> DataLoader:
    (tmp_path / "instances.yml").write_text(INSTANCES_YAML)
    return DataLoader(tmp_path)


@pytest.fixture()
def config() -> AppConfig:
    return AppConfig(
        ssh_host="192.168.29.167",
        ssh_port=22,
        ssh_user="mcp",
        ssh_key_path="~/.ssh/homelab_mcp",
        ssh_use_sudo=True,
    )


class TestResolveSshTarget:
    def test_unknown_node_returns_none(self, loader, config):
        assert resolve_ssh_target(loader, config, "nope") is None

    def test_global_fallback(self, loader, config):
        target = resolve_ssh_target(loader, config, "homelab")
        assert target is not None
        assert target.host == "192.168.29.167"
        assert target.user == "mcp"
        assert target.port == 22
        assert target.key_path == "~/.ssh/homelab_mcp"
        assert target.use_sudo is True
        assert target.jump is None
        assert target.kind == "proxmox"

    def test_vm_overrides_and_jump(self, loader, config):
        target = resolve_ssh_target(loader, config, "infravm")
        assert target is not None
        assert target.host == "192.168.200.50"
        assert target.user == "mcp"
        assert target.port == 22  # inherited from global
        assert target.key_path == "~/.ssh/homelab_mcp"  # inherited
        assert target.use_sudo is True
        assert target.kind == "vm"
        # jump chain points at the proxmox node with global settings
        assert target.jump is not None
        assert target.jump.host == "192.168.29.167"
        assert target.jump.user == "mcp"
        assert target.jump.jump is None

    def test_multihop_chain(self, loader, config):
        target = resolve_ssh_target(loader, config, "nestedvm")
        assert target is not None
        assert target.port == 2222
        assert target.key_path == "~/.ssh/nested_key"
        assert target.use_sudo is False
        assert target.jump is not None
        assert target.jump.node_name == "infravm"
        assert target.jump.jump is not None
        assert target.jump.jump.node_name == "homelab"

    def test_jump_cycle_raises(self, loader, config):
        with pytest.raises(ValueError, match="cycle"):
            resolve_ssh_target(loader, config, "loopa")

    def test_unknown_jump_host_raises(self, loader, config):
        with pytest.raises(ValueError, match="nonexistent"):
            resolve_ssh_target(loader, config, "badjump")

    def test_self_jump_raises(self, tmp_path, config):
        yaml = """
cluster:
  - name: selfish
    fqdn: selfish.lab
    platform_user: p
    wan_ip: 10.0.0.9
    proxmox_node: homelab
    ssh:
      jump_via: selfish
"""
        (tmp_path / "instances.yml").write_text(yaml)
        dl = DataLoader(tmp_path)
        with pytest.raises(ValueError, match="cycle"):
            resolve_ssh_target(dl, config, "selfish")

    def test_real_repo_instances_resolves(self, config):
        """The repo's own data/instances.yml must resolve every node."""
        dl = DataLoader(Path("data"))
        for name in dl.get_node_names():
            target = resolve_ssh_target(dl, config, name)
            assert target is not None, f"{name} failed to resolve"

    def test_missing_instances_file_raises(self, tmp_path, config):
        dl = DataLoader(tmp_path)
        with pytest.raises(DataLoadError):
            resolve_ssh_target(dl, config, "homelab")
