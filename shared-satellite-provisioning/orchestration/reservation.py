from __future__ import annotations
from typing import Dict, List, Tuple, Optional
import networkx as nx
from models.active_slice import ActiveSlice
from models.resources import BeamResource, FeederResource, PhysicalNode
from models.slice_request import SliceRequest


def effective_beam_total_capacity(beam: BeamResource) -> float:
    raw = beam.raw_capacity_mbps if beam.raw_capacity_mbps > 0 else beam.capacity_total_mbps
    return raw * beam.mcs_efficiency * beam.fade_penalty


def effective_beam_free_capacity(beam: BeamResource) -> float:
    return min(beam.capacity_free_mbps, effective_beam_total_capacity(beam))


def reserve_slice(graph: nx.Graph, request: SliceRequest, placement: Dict[str, str], paths: Dict[Tuple[str, str], List[str]],
                  beam_id: str, gateway_id: str, beams: Dict[str, BeamResource], feeders: Dict[str, FeederResource], total_delay_ms: float) -> ActiveSlice:
    for vnf in request.vnfs:
        node: PhysicalNode = graph.nodes[placement[vnf.name]]['obj']
        node.cpu_free -= vnf.cpu
        node.mem_free -= vnf.mem
        node.storage_free -= vnf.storage

    for vlink in request.virtual_links:
        path = paths[(vlink.src, vlink.dst)]
        for a, b in zip(path[:-1], path[1:]):
            link = graph[a][b]['obj']
            link.bw_free -= vlink.bw

    beams[beam_id].capacity_free_mbps -= request.required_bw_mbps
    feeders[gateway_id].capacity_free_mbps -= request.required_bw_mbps

    return ActiveSlice(
        request=request,
        placement=placement,
        paths=paths,
        beam_id=beam_id,
        gateway_id=gateway_id,
        remaining_lifetime=request.lifetime,
        total_delay_ms=total_delay_ms,
        target_bw_mbps=request.required_bw_mbps,
        granted_bw_mbps=request.required_bw_mbps,
        min_guaranteed_bw_mbps=request.min_guaranteed_bw_mbps,
        latency_target_ms=request.latency_target_ms,
        jitter_target_ms=request.jitter_target_ms,
        loss_target_pct=request.loss_target_pct,
        priority_tier=request.priority_tier,
        sla_state="normal",
        degradation_allowed=request.degradation_allowed,
        recovery_action="initial_admission",
        queue_delay_ms=0.0,
        jitter_ms=0.0,
        loss_pct=0.0,
    )


def release_slice(graph: nx.Graph, active: ActiveSlice, beams: Dict[str, BeamResource], feeders: Dict[str, FeederResource]) -> None:
    req = active.request

    for vnf in req.vnfs:
        node = graph.nodes[active.placement[vnf.name]]['obj']
        node.cpu_free += vnf.cpu
        node.mem_free += vnf.mem
        node.storage_free += vnf.storage

    for vlink in req.virtual_links:
        path = active.paths[(vlink.src, vlink.dst)]
        for a, b in zip(path[:-1], path[1:]):
            graph[a][b]['obj'].bw_free += vlink.bw

    beams[active.beam_id].capacity_free_mbps += active.granted_bw_mbps
    feeders[active.gateway_id].capacity_free_mbps += active.granted_bw_mbps


def can_scale_active_slice(active: ActiveSlice, extra_bw_mbps: float,
                           beams: Dict[str, BeamResource], feeders: Dict[str, FeederResource]) -> bool:
    if extra_bw_mbps <= 0:
        return True

    beam_free = effective_beam_free_capacity(beams[active.beam_id])
    beam_ok = beam_free >= extra_bw_mbps
    feeder_ok = feeders[active.gateway_id].capacity_free_mbps >= extra_bw_mbps
    return beam_ok and feeder_ok


def scale_active_slice_bandwidth(active: ActiveSlice, extra_bw_mbps: float,
                                 beams: Dict[str, BeamResource], feeders: Dict[str, FeederResource]) -> bool:
    if extra_bw_mbps <= 0:
        return True
    if not can_scale_active_slice(active, extra_bw_mbps, beams, feeders):
        return False

    beams[active.beam_id].capacity_free_mbps -= extra_bw_mbps
    feeders[active.gateway_id].capacity_free_mbps -= extra_bw_mbps

    active.request.required_bw_mbps += extra_bw_mbps
    active.granted_bw_mbps += extra_bw_mbps
    active.target_bw_mbps += extra_bw_mbps
    active.recovery_action = "scale_current"

    return True

def reoptimize_active_slice_gateway(active: ActiveSlice, extra_bw_mbps: float,
                                    beams: Dict[str, BeamResource],
                                    feeders: Dict[str, FeederResource]) -> Tuple[bool, Optional[Tuple[str, str]]]:

    target_total_bw = active.granted_bw_mbps + extra_bw_mbps
    region = getattr(active.request, 'region', None)

    for beam_id, beam in beams.items():
        if region is not None and getattr(beam, 'region', None) != region:
            continue

        beam_free = effective_beam_free_capacity(beam)
        if beam_free < target_total_bw:
            continue

        gateways = beam.candidate_gateways or set(feeders.keys())

        for gw in gateways:
            if gw == active.gateway_id and beam_id == active.beam_id:
                continue  # skip current allocation

            feeder = feeders.get(gw)
            if not feeder or feeder.capacity_free_mbps < target_total_bw:
                continue

            # 🔹 RELEASE old resources
            beams[active.beam_id].capacity_free_mbps += active.granted_bw_mbps
            feeders[active.gateway_id].capacity_free_mbps += active.granted_bw_mbps

            # 🔹 RESERVE new resources
            beam.capacity_free_mbps -= target_total_bw
            feeder.capacity_free_mbps -= target_total_bw

            # 🔹 UPDATE slice
            active.beam_id = beam_id
            active.gateway_id = gw
            active.granted_bw_mbps = target_total_bw
            active.target_bw_mbps = target_total_bw
            active.request.required_bw_mbps = target_total_bw
            active.recovery_action = "gateway_migration"

            return True, (beam_id, gw)

    return False, None

def reoptimize_active_slice_beam(active, extra_bw_mbps, beams, feeders):
    """
    Try to move slice to another beam (same gateway) with enough capacity.
    """
    target_total_bw = active.request.required_bw_mbps + extra_bw_mbps
    region = getattr(active.request, 'region', None)

    feeder = feeders.get(active.gateway_id)
    if feeder is None:
        return False, None

    # Check feeder can support extra load
    if feeder.capacity_free_mbps < extra_bw_mbps:
        return False, None

    for beam_id, beam in beams.items():
        if beam_id == active.beam_id:
            continue

        if region is not None and getattr(beam, 'region', None) != region:
            continue

        if beam.capacity_free_mbps >= target_total_bw:
            # release old beam capacity
            beams[active.beam_id].capacity_free_mbps += active.request.required_bw_mbps

            # allocate new beam capacity
            beam.capacity_free_mbps -= target_total_bw

            # feeder only needs extra
            feeder.capacity_free_mbps -= extra_bw_mbps

            active.beam_id = beam_id
            active.request.required_bw_mbps = target_total_bw
            active.granted_bw_mbps = target_total_bw

            return True, beam_id

    return False, None