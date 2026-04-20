from dataclasses import dataclass
from typing import List, Optional, Set
from .service import VNF, VirtualLink


@dataclass
class SliceRequest:
    slice_id: str
    tenant_id: str
    traffic_class: str
    lifetime: int
    service_name: str
    region: str
    required_bw_mbps: float
    delay_threshold_ms: float
    vnfs: List[VNF]
    virtual_links: List[VirtualLink]
    allowed_gateways: Optional[Set[str]] = None
    min_guaranteed_bw_mbps: float = 0.0
    latency_target_ms: float = 0.0
    jitter_target_ms: float = 0.0
    loss_target_pct: float = 0.0
    priority_tier: str = "medium"
    degradation_allowed: bool = True