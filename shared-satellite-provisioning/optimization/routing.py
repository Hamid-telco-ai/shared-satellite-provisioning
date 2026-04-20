from __future__ import annotations
from typing import Dict, List, Tuple
import networkx as nx
from models.slice_request import SliceRequest


def build_paths_and_delay(graph: nx.Graph, request: SliceRequest, placement: Dict[str, str], pnfs: dict):
    paths: Dict[Tuple[str, str], List[str]] = {}
    total_transport = 0.0
    for vlink in request.virtual_links:
        src = placement[vlink.src]
        dst = placement[vlink.dst]
        try:
            path = nx.shortest_path(graph, src, dst, weight='delay_ms')
        except nx.NetworkXNoPath:
            return False, f'No physical path for virtual link {vlink.src}->{vlink.dst}', 0.0
        for a, b in zip(path[:-1], path[1:]):
            if graph[a][b]['obj'].bw_free < vlink.bw:
                return False, f'Insufficient link bandwidth on {a}<->{b}', 0.0
            total_transport += graph[a][b]['obj'].delay_ms
        paths[(vlink.src, vlink.dst)] = path

    total_processing = sum(v.proc_delay_ms for v in request.vnfs)
    total_fronthaul = 0.0
    for v in request.vnfs:
        if v.attached_pnf and v.max_fronthaul_delay_ms is not None:
            pnf_node = pnfs.get(v.attached_pnf, {}).get('attached_node')
            if pnf_node:
                total_fronthaul += nx.shortest_path_length(graph, placement[v.name], pnf_node, weight='delay_ms')
    total_delay = total_processing + total_transport + total_fronthaul
    return True, paths, total_delay
