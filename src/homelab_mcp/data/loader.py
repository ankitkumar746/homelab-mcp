from pathlib import Path

import yaml
from pydantic import ValidationError

from homelab_mcp.data_models import (
    HardwareCluster,
    HardwareNode,
    InstanceCluster,
    InstanceNode,
    NetworkCluster,
    NetworkNode,
    ServicesCluster,
    ServicesNode,
)


# Custom exception for data loading errors
class DataLoadError(Exception):
    def __init__(self, filename: str, detail: str) -> None:
        self.filename = filename
        self.detail = detail
        super().__init__(f"Error loading {filename}: {detail}")


class DataLoader:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self._hardware: HardwareCluster | None = None
        self._instances: InstanceCluster | None = None
        self._network: NetworkCluster | None = None
        self._services: ServicesCluster | None = None

    def _load_yaml(self, filename: str) -> dict:
        filepath = self.data_dir / filename
        if not filepath.exists():
            raise DataLoadError(filename, f"File not found: {filepath}")
        with open(filepath, "r") as file:
            data = yaml.safe_load(file)
        if data is None:
            raise DataLoadError(filename, "File is empty")
        return data

    def _load_and_validate(self, filename: str, model_class: type):
        raw = self._load_yaml(filename)
        try:
            return model_class.model_validate(raw)
        except ValidationError as e:
            raise DataLoadError(filename, str(e)) from e

    @property
    def instances(self) -> InstanceCluster:
        if self._instances is None:
            self._instances = self._load_and_validate("instances.yml", InstanceCluster)
        return self._instances

    @property
    def hardware(self) -> HardwareCluster:
        if self._hardware is None:
            self._hardware = self._load_and_validate("hardware.yml", HardwareCluster)
        return self._hardware

    @property
    def network(self) -> NetworkCluster:
        if self._network is None:
            self._network = self._load_and_validate("network.yml", NetworkCluster)
        return self._network

    @property
    def services(self) -> ServicesCluster:
        if self._services is None:
            self._services = self._load_and_validate("services.yml", ServicesCluster)
        return self._services

    def load_all(self) -> None:
        for property_name in ("hardware", "instances", "network", "services"):
            getattr(self, property_name)  # Accessing the property to trigger loading

    def get_node_names(self) -> list[str]:
        return [node.name for node in self.instances.cluster]

    def get_instance(self, node_name: str) -> InstanceNode | None:
        for node in self.instances.cluster:
            if node.name == node_name:
                return node
        return None

    def get_hardware(self, node_name: str) -> HardwareNode | None:
        for node in self.hardware.cluster:
            if node.name == node_name:
                return node
        return None

    def get_network(self, node_name: str) -> NetworkNode | None:
        for node in self.network.cluster:
            if node.name == node_name:
                return node
        return None

    def get_services(self, node_name: str) -> ServicesNode | None:
        for node in self.services.cluster:
            if node.name == node_name:
                return node
        return None
