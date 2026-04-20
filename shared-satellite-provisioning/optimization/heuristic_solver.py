from __future__ import annotations
from typing import Dict, List, Optional
import networkx as nx
from models.resources import PhysicalNode
from models.slice_request import SliceRequest


def _score(node: PhysicalNode, constrained: bool) -> float:
    base = node.cpu_free + 0.2 * node.mem_free + 0.1 * node.storage_free
    if constrained:
        base += 100.0 - (node.hub_delay_ms or 50.0)
    return base


def place_vnfs_heuristic(request: SliceRequest, graph: nx.Graph, candidates: Dict[str, List[str]]) -> Optional[Dict[str, str]]:
    ordered_vnfs = sorted(request.vnfs, key=lambda v: (len(candidates[v.name]), 0 if v.vnf_type in {'SBG', 'RRM', 'QOS'} else 1))
    placement: Dict[str, str] = {}
    temp_usage: Dict[str, Dict[str, float]] = {}

    for vnf in ordered_vnfs:
        constrained = vnf.vnf_type in {'SBG', 'RRM', 'QOS'} or vnf.attached_pnf is not None
        best = None
        best_score = -1e9
        for node_id in candidates[vnf.name]:
            node: PhysicalNode = graph.nodes[node_id]['obj']
            used = temp_usage.get(node_id, {'cpu': 0.0, 'mem': 0.0, 'storage': 0.0})
            if node.cpu_free - used['cpu'] < vnf.cpu or node.mem_free - used['mem'] < vnf.mem or node.storage_free - used['storage'] < vnf.storage:
                continue
            s = _score(node, constrained)
            if s > best_score:
                best = node_id
                best_score = s
        if best is None:
            return None
        placement[vnf.name] = best
        temp_usage.setdefault(best, {'cpu': 0.0, 'mem': 0.0, 'storage': 0.0})
        temp_usage[best]['cpu'] += vnf.cpu
        temp_usage[best]['mem'] += vnf.mem
        temp_usage[best]['storage'] += vnf.storage
    return placement
