from pathlib import Path

import pytest

from homelab_mcp.data.loader import DataLoader, DataLoadError

DATA_DIR = Path(__file__).parent.parent / "data"


@pytest.fixture
def loader() -> DataLoader:
    return DataLoader(DATA_DIR)


class TestLoader:
    def test_load_all(self, loader: DataLoader) -> None:
        loader.load_all()

    def test_get_node_names(self, loader: DataLoader) -> None:
        names = loader.get_node_names()
        assert "homelab" in names

    def test_get_instance(self, loader: DataLoader) -> None:
        node = loader.get_instance("homelab")
        assert node is not None
        assert node.name == "homelab"
        assert node.wan_ip == "192.168.29.167"

    def test_get_instance_not_found(self, loader: DataLoader) -> None:
        assert loader.get_instance("nonexistent") is None

    def test_get_hardware(self, loader: DataLoader) -> None:
        hw = loader.get_hardware("homelab")
        assert hw is not None
        assert hw.cpu.model == "AMD Ryzen 9 7900"
        assert hw.memory.capacity_gb == 64

    def test_get_network(self, loader: DataLoader) -> None:
        net = loader.get_network("homelab")
        assert net is not None
        assert len(net.nics) == 2
        assert net.wan is not None
        assert net.wan.ip == "192.168.29.167"

    def test_get_services(self, loader: DataLoader) -> None:
        svc = loader.get_services("homelab")
        assert svc is not None
        assert len(svc.host) == 2
        assert len(svc.vms) == 1
        assert svc.vms[0].name == "infravm"

    def test_invalid_data_dir(self) -> None:
        bad_loader = DataLoader(Path("/nonexistent"))
        with pytest.raises(DataLoadError):
            bad_loader.load_all()
