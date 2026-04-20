from __future__ import annotations
import networkx as nx
from typing import Dict, Tuple
from models.resources import PhysicalNode, PhysicalLink


def build_graph(nodes: Dict[str, PhysicalNode], links: Dict[Tuple[str, str], PhysicalLink]) -> nx.Graph:
    g = nx.Graph()
    for node_id, node in nodes.items():
        g.add_node(node_id, obj=node)
    for (a, b), link in links.items():
        g.add_edge(a, b, obj=link, delay_ms=link.delay_ms)
    return g
