from __future__ import annotations
from typing import Dict, List
import networkx as nx
from models.resources import PhysicalNode
from models.service import VNF


def vnf_candidates(
    vnf: VNF,
    graph: nx.Graph,
    pnfs: Dict,
    allowed_gateways=None,
    strict_gateway_binding=True
) -> List[str]:
    candidates = []

    for node_id, attrs in graph.nodes(data=True):
        node: PhysicalNode = attrs["obj"]

        if vnf.vnf_type not in node.allowed_vnfs:
            continue

        if node.cpu_free < vnf.cpu or node.mem_free < vnf.mem or node.storage_free < vnf.storage:
            continue

        if strict_gateway_binding and allowed_gateways and node.gateway_id and node.gateway_id not in allowed_gateways:
            if vnf.vnf_type != "SBG":
                continue

        if vnf.max_hub_delay_ms is not None:
            if node.hub_delay_ms is None or node.hub_delay_ms > vnf.max_hub_delay_ms:
                continue

        if vnf.attached_pnf and vnf.max_fronthaul_delay_ms is not None:
            # Default: use the explicitly attached PNF
            candidate_pnfs = [vnf.attached_pnf]

            # Special handling for SBG: allow any SBG PNF anchor
            if vnf.vnf_type == "SBG":
                candidate_pnfs = list(pnfs.keys())
            else:
                candidate_pnfs = [vnf.attached_pnf] if vnf.attached_pnf else []

            fronthaul_ok = False

            for pnf_name in candidate_pnfs:
                pnf_node = pnfs.get(pnf_name, {}).get("attached_node")
                if not pnf_node:
                    continue

                try:
                    d = nx.shortest_path_length(graph, node_id, pnf_node, weight="delay_ms")
                except nx.NetworkXNoPath:
                    continue

                if d <= vnf.max_fronthaul_delay_ms:
                    fronthaul_ok = True
                    break

            if not fronthaul_ok:
                continue

        candidates.append(node_id)

    return candidates