from __future__ import annotations

from typing import Dict, Any


def _reset_node_resources(graph) -> None:
    for _, data in graph.nodes(data=True):
        node = data["obj"]
        node.cpu_free = node.cpu_total
        node.mem_free = node.mem_total
        node.storage_free = node.storage_total


def _reset_link_resources(graph) -> None:
    for a, b in graph.edges():
        link = graph[a][b]["obj"]
        link.bw_free = link.bw_total


def _reset_beam_feeder_resources(beams, feeders) -> None:
    for beam in beams.values():
        beam.capacity_free_mbps = beam.capacity_total_mbps

    for feeder in feeders.values():
        feeder.capacity_free_mbps = feeder.capacity_total_mbps


def _apply_node_allocations(active, graph) -> None:
    req = active.request
    for vnf in req.vnfs:
        node_id = active.placement.get(vnf.name)
        if not node_id:
            continue
        node = graph.nodes[node_id]["obj"]
        node.cpu_free -= float(vnf.cpu)
        node.mem_free -= float(vnf.mem)
        node.storage_free -= float(vnf.storage)


def _apply_link_allocations(active, graph) -> None:
    req = active.request
    target_bw = max(float(active.target_bw_mbps), 1.0)

    for vlink in req.virtual_links:
        key = (vlink.src, vlink.dst)
        path = active.paths.get(key, [])

        if not path or len(path) < 2:
            continue

        coeff = float(vlink.bw) / target_bw
        reserved_bw = coeff * float(active.granted_bw_mbps)

        for a, b in zip(path[:-1], path[1:]):
            if graph.has_edge(a, b):
                graph[a][b]["obj"].bw_free -= reserved_bw
            elif graph.has_edge(b, a):
                graph[b][a]["obj"].bw_free -= reserved_bw


def _apply_beam_feeder_allocations(active, beams, feeders) -> None:
    beam_id = active.beam_id
    gateway_id = active.gateway_id
    granted = float(active.granted_bw_mbps)

    if beam_id in beams:
        beams[beam_id].capacity_free_mbps -= granted
    if gateway_id in feeders:
        feeders[gateway_id].capacity_free_mbps -= granted


def apply_phase_a_result(result: Dict[str, Any], active_slices, beams, feeders, graph=None):
    if graph is None:
        raise ValueError("graph is required for D+E MILP apply")

    _reset_node_resources(graph)
    _reset_link_resources(graph)
    _reset_beam_feeder_resources(beams, feeders)

    to_remove = []

    for slice_id, info in result["slices"].items():
        active = active_slices.get(slice_id)
        if active is None:
            continue

        if info["dropped"] == 1 or not info["beam_gateway"]:
            to_remove.append(slice_id)
            continue

        beam_id, gateway_id = info["beam_gateway"]
        granted = float(info["granted_bw_mbps"])

        active.beam_id = beam_id
        active.gateway_id = gateway_id
        active.granted_bw_mbps = granted
        active.request.required_bw_mbps = granted

        placement = info.get("placement")
        if placement:
            active.placement = dict(placement)

        routes = info.get("routes", {})
        new_paths = {}
        for vlink in active.request.virtual_links:
            key = (vlink.src, vlink.dst)
            route_key = f"{vlink.src}->{vlink.dst}"
            path = routes.get(route_key, [])

            if path:
                new_paths[key] = list(path)
            else:
                src_node = active.placement.get(vlink.src)
                dst_node = active.placement.get(vlink.dst)
                if src_node and dst_node and src_node == dst_node:
                    new_paths[key] = [src_node]
                else:
                    new_paths[key] = []

        active.paths = new_paths

        if granted < float(active.target_bw_mbps):
            active.sla_state = "degraded"
            active.recovery_action = "milp_degraded"
        else:
            active.sla_state = "normal"
            active.recovery_action = "milp_assigned"

    for slice_id in to_remove:
        active_slices.pop(slice_id, None)

    for active in active_slices.values():
        _apply_node_allocations(active, graph)
        _apply_link_allocations(active, graph)
        _apply_beam_feeder_allocations(active, beams, feeders)

    return to_remove