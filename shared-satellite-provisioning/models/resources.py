from dataclasses import dataclass, field
from typing import List, Optional, Set


@dataclass
class PhysicalNode:
    node_id: str
    node_type: str
    cpu_total: float
    cpu_free: float
    mem_total: float
    mem_free: float
    storage_total: float
    storage_free: float
    allowed_vnfs: Set[str] = field(default_factory=set)
    gateway_id: Optional[str] = None
    hub_id: Optional[str] = None
    hub_delay_ms: Optional[float] = None


@dataclass
class PhysicalLink:
    src: str
    dst: str
    bw_total: float
    bw_free: float
    delay_ms: float
    link_type: str = "transport"


@dataclass
class BeamResource:
    beam_id: str
    region: str
    capacity_total_mbps: float
    capacity_free_mbps: float
    visible_windows: List[int]
    raw_capacity_mbps: float = 0.0
    candidate_gateways: Set[str] = field(default_factory=set)
    mcs_efficiency: float = 1.0
    fade_penalty: float = 1.0
    weather_state: str = "clear"


@dataclass
class FeederResource:
    gateway_id: str
    capacity_total_mbps: float
    capacity_free_mbps: float