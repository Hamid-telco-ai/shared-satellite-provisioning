from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple
from models.slice_request import SliceRequest


@dataclass
class ActiveSlice:
    request: SliceRequest
    placement: Dict[str, str]
    paths: Dict[Tuple[str, str], List[str]]
    beam_id: str
    gateway_id: str
    remaining_lifetime: int
    total_delay_ms: float

    target_bw_mbps: float = 0.0
    granted_bw_mbps: float = 0.0
    min_guaranteed_bw_mbps: float = 0.0

    latency_target_ms: float = 0.0
    jitter_target_ms: float = 0.0
    loss_target_pct: float = 0.0

    priority_tier: str = "medium"
    sla_state: str = "normal"
    degradation_allowed: bool = True
    recovery_action: str = "initial_admission"

    queue_delay_ms: float = 0.0
    jitter_ms: float = 0.0
    loss_pct: float = 0.0