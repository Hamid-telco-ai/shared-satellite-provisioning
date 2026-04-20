from dataclasses import dataclass
from typing import List, Optional


@dataclass
class VNF:
    name: str
    vnf_type: str
    cpu: float
    mem: float
    storage: float
    proc_delay_ms: float
    attached_pnf: Optional[str] = None
    max_fronthaul_delay_ms: Optional[float] = None
    max_hub_delay_ms: Optional[float] = None


@dataclass
class VirtualLink:
    src: str
    dst: str
    bw: float


@dataclass
class ServiceTemplate:
    service_name: str
    traffic_class: str
    delay_threshold_ms: float
    vnfs: List[VNF]
    virtual_links: List[VirtualLink]
