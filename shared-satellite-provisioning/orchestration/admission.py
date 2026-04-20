from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import networkx as nx
from models.active_slice import ActiveSlice
from models.resources import BeamResource, FeederResource
from models.slice_request import SliceRequest
from policy.placement_policy import vnf_candidates
from policy.satellite_policy import choose_beam_and_gateway
from optimization.heuristic_solver import place_vnfs_heuristic
from optimization.routing import build_paths_and_delay
from orchestration.reservation import reserve_slice


@dataclass
class AdmissionResult:
    accepted: bool
    reason: str
    active_slice: Optional[ActiveSlice] = None


class AdmissionController:
    def __init__(self, graph: nx.Graph, beams: Dict[str, BeamResource], feeders: Dict[str, FeederResource], pnfs: dict):
        self.graph = graph
        self.beams = beams
        self.feeders = feeders
        self.pnfs = pnfs

    def admit(self, request: SliceRequest, tick: Optional[int] = None) -> AdmissionResult:
        choice = choose_beam_and_gateway(request.region, request.required_bw_mbps, self.beams, self.feeders,
                                         allowed_gateways=request.allowed_gateways, tick=tick)
        if not choice:
            return AdmissionResult(False, 'No valid beam/gateway with enough capacity or visibility')
        beam_id, gateway_id = choice

        candidates: Dict[str, List[str]] = {}
        for vnf in request.vnfs:
            allowed_gateways = {gateway_id} if vnf.vnf_type in {'SBG', 'RRM', 'QOS'} else request.allowed_gateways
            cand = vnf_candidates(vnf, self.graph, self.pnfs, allowed_gateways=allowed_gateways)
            if not cand:
                return AdmissionResult(False, f'No valid PoP candidates for VNF {vnf.name}')
            candidates[vnf.name] = cand

        placement = place_vnfs_heuristic(request, self.graph, candidates)
        if placement is None:
            return AdmissionResult(False, 'Heuristic placement failed')

        routing = build_paths_and_delay(self.graph, request, placement, self.pnfs)
        if not routing[0]:
            return AdmissionResult(False, routing[1])
        _, paths, total_delay = routing
        if total_delay > request.delay_threshold_ms:
            return AdmissionResult(False, f'Delay threshold exceeded: {total_delay:.2f} ms > {request.delay_threshold_ms:.2f} ms')

        active = reserve_slice(self.graph, request, placement, paths, beam_id, gateway_id, self.beams, self.feeders, total_delay)
        return AdmissionResult(True, 'Accepted', active)
