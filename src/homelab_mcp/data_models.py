from pydantic import BaseModel, Field


class ConfigFile(BaseModel):
    path: str
    description: str


class ConfigDirectory(BaseModel):
    directory: str
    files: list[ConfigFile]


class Nic(BaseModel):
    name: str
    status: str
    mac: str
    altname: str | None = None
    note: str | None = None


class WanConfig(BaseModel):
    interface: str
    ip: str
    subnet: str
    ssid: str | None = None
    wpa_config: str | None = None
    wpa_service: str | None = None


class Bridge(BaseModel):
    name: str
    ip: str
    subnet: str
    gateway: str | None = None
    bridge_ports: str
    autostart: bool
    status: str
    note: str | None = None


class IpForwarding(BaseModel):
    enabled: bool
    param: str
    config: str


class NatConfig(BaseModel):
    enabled: bool
    type: str
    backend: str
    source_subnet: str
    outbound_interface: str
    config: str
    note: str | None = None


class DhcpScope(BaseModel):
    service: str
    interface: str
    range_start: str
    range_end: str
    lease_time: str
    gateway: str
    dns_servers: list[str]


class PxeConfig(BaseModel):
    service: str
    bootloader: str
    boot_file: str
    tftp_root: str
    http_root: str


class VmInterface(BaseModel):
    name: str
    bridge: str
    ip: str


class VmNetworkEntry(BaseModel):
    name: str
    interfaces: list[VmInterface] = []
    dhcp_scope: DhcpScope | None = None
    pxe: PxeConfig | None = None
    configs: list[ConfigDirectory] = []


class HostNetworkEntry(BaseModel):
    configs: list[ConfigDirectory] = []


class LxcNetworkEntry(BaseModel):
    name: str
    interfaces: list[VmInterface] = []
    configs: list[ConfigDirectory] = []


class NetworkNode(BaseModel):
    name: str
    nics: list[Nic] = []
    wan: WanConfig | None = None
    bridges: list[Bridge] = []
    ip_forwarding: IpForwarding | None = None
    nat: NatConfig | None = None
    host: HostNetworkEntry = Field(default_factory=HostNetworkEntry)
    vms: list[VmNetworkEntry] = []
    lxc: list[LxcNetworkEntry] = []


class NetworkCluster(BaseModel):
    cluster: list[NetworkNode]


class ServiceEntry(BaseModel):
    name: str
    type: str
    service_name: str | None = None
    critical: bool = False
    configs: list[ConfigDirectory] = []
    log_file: str | None = None
    document_root: str | None = None
    live_command: str | None = None
    note: str | None = None


class VmServiceEntry(BaseModel):
    name: str
    services: list[ServiceEntry] = []


class LxcServiceEntry(BaseModel):
    name: str
    services: list[ServiceEntry] = []


class ServicesNode(BaseModel):
    name: str
    host: list[ServiceEntry] = []
    vms: list[VmServiceEntry] = []
    lxc: list[LxcServiceEntry] = []


class ServicesCluster(BaseModel):
    cluster: list[ServicesNode]


class SshSettings(BaseModel):
    """Per-node SSH connection settings; unset fields fall back to global config."""

    jump_via: str | None = None
    user: str | None = None
    port: int | None = None
    key_path: str | None = None
    use_sudo: bool | None = None


class InstanceNode(BaseModel):
    name: str
    fqdn: str
    platform_user: str
    wan_ip: str
    proxmox_node: str
    kind: str = "proxmox"
    ssh: SshSettings | None = None
    role: str | None = None
    single_node: bool | None = None
    notes: str | None = None


class InstanceCluster(BaseModel):
    cluster: list[InstanceNode]


class CpuSpec(BaseModel):
    model: str
    cores: int
    threads: int
    threads_per_core: int
    sockets: int
    architecture: str
    vendor: str
    base_clock_ghz: float
    max_boost_clock_ghz: float
    tdp_watts: int
    virtualization: str
    cache: dict[str, str]


class MotherboardSpec(BaseModel):
    model: str
    vrm: str
    pcie_slots: list[str]
    m2_slots: str
    sata_ports: str
    ddr5_slots: int
    max_memory_gb: int
    max_memory_speed_mhz: int
    lan: str
    wifi: str
    bluetooth: str | float
    usb_c: str
    pcb: str


class MemorySpec(BaseModel):
    model: str
    capacity_gb: int
    configuration: str
    type: str
    speed_mts: int
    cas_latency: str
    rank: str
    total_installed_gb: int


class StorageSpec(BaseModel):
    model: str
    capacity_gb: int
    form_factor: str
    interface: str
    type: str
    sequential_read_mbps: int
    sequential_write_mbps: int


class PsuSpec(BaseModel):
    model: str
    wattage: str
    efficiency: str
    modularity: str
    pcie5_ready: bool


class CoolingSpec(BaseModel):
    model: str
    type: str
    design: str
    heat_pipes: str
    fans: str
    height_mm: int
    included_thermal_paste: bool


class CaseSpec(BaseModel):
    model: str
    color: str
    side_panel: str
    form_factor_support: str
    preinstalled_fans: str
    max_fans: int
    top_dust_cover: str


class KernelSpec(BaseModel):
    virtualization: str
    numa_nodes: int


class HardwareNode(BaseModel):
    name: str
    cpu: CpuSpec
    motherboard: MotherboardSpec
    memory: MemorySpec
    storage: list[StorageSpec]
    psu: PsuSpec
    cooling: CoolingSpec
    case: CaseSpec
    kernel: KernelSpec


class HardwareCluster(BaseModel):
    cluster: list[HardwareNode]
