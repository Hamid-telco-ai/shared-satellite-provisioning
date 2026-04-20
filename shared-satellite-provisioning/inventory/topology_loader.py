from __future__ import annotations
import yaml
from typing import Dict, Tuple
from models.resources import PhysicalNode, PhysicalLink, BeamResource, FeederResource


def load_yaml(path: str):
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_infrastructure(path: str):
    data = load_yaml(path)

    nodes: Dict[str, PhysicalNode] = {}
    for node_id, n in data['nodes'].items():
        nodes[node_id] = PhysicalNode(
            node_id=node_id,
            node_type=n['node_type'],
            cpu_total=n['cpu_total'], cpu_free=n['cpu_total'],
            mem_total=n['mem_total'], mem_free=n['mem_total'],
            storage_total=n['storage_total'], storage_free=n['storage_total'],
            allowed_vnfs=set(n.get('allowed_vnfs', [])),
            gateway_id=n.get('gateway_id'),
            hub_id=n.get('hub_id'),
            hub_delay_ms=n.get('hub_delay_ms'),
        )

    links: Dict[Tuple[str, str], PhysicalLink] = {}
    for l in data['links']:
        key = tuple(sorted((l['src'], l['dst'])))
        links[key] = PhysicalLink(
            src=l['src'],
            dst=l['dst'],
            bw_total=l['bw_total'],
            bw_free=l['bw_total'],
            delay_ms=l['delay_ms'],
            link_type=l.get('link_type', 'transport')
        )

    beams: Dict[str, BeamResource] = {}
    for beam_id, b in data.get('beams', {}).items():
        raw_capacity = b.get('raw_capacity_mbps', b['capacity_total_mbps'])
        mcs_efficiency = b.get('mcs_efficiency', 1.0)
        fade_penalty = b.get('fade_penalty', 1.0)
        weather_state = b.get('weather_state', 'clear')

        beams[beam_id] = BeamResource(
            beam_id=beam_id,
            region=b['region'],
            capacity_total_mbps=b['capacity_total_mbps'],
            capacity_free_mbps=b['capacity_total_mbps'],
            visible_windows=list(b.get('visible_windows', [])),
            raw_capacity_mbps=raw_capacity,
            candidate_gateways=set(b.get('candidate_gateways', [])),
            mcs_efficiency=mcs_efficiency,
            fade_penalty=fade_penalty,
            weather_state=weather_state,
        )

    feeders: Dict[str, FeederResource] = {}
    for gw_id, f in data.get('feeders', {}).items():
        feeders[gw_id] = FeederResource(
            gateway_id=gw_id,
            capacity_total_mbps=f['capacity_total_mbps'],
            capacity_free_mbps=f['capacity_total_mbps'],
        )

    pnfs = data.get('pnfs', {})
    return nodes, links, beams, feeders, pnfs