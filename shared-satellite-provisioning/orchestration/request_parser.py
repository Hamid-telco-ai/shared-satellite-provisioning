from __future__ import annotations
import yaml
from copy import deepcopy
from models.service import VNF, VirtualLink, ServiceTemplate
from models.slice_request import SliceRequest


def load_services(path: str):
    with open(path, 'r', encoding='utf-8') as f:
        raw = yaml.safe_load(f)['services']

    out = {}
    for name, s in raw.items():
        vnfs = [VNF(**v) for v in s['vnfs']]
        vlinks = [VirtualLink(**vl) for vl in s['virtual_links']]

        out[name] = {
            'name': name,
            'traffic_class': s['traffic_class'],
            'delay_threshold_ms': s['delay_threshold_ms'],
            'min_guaranteed_bw_mbps': s.get('min_guaranteed_bw_mbps', 0.0),
            'latency_target_ms': s.get('latency_target_ms', 0.0),
            'jitter_target_ms': s.get('jitter_target_ms', 0.0),
            'loss_target_pct': s.get('loss_target_pct', 0.0),
            'priority_tier': s.get('priority_tier', 'medium'),
            'degradation_allowed': s.get('degradation_allowed', True),
            'vnfs': vnfs,
            'virtual_links': vlinks,
        }

    return out


def build_slice_request(slice_id: str, tenant_id: str, service_name: str, region: str, lifetime: int,
                        required_bw_mbps: float, tenants: dict, services: dict) -> SliceRequest:
    tenant = tenants[tenant_id]
    service = deepcopy(services[service_name])

    allowed_gateways = set(tenant.get('allowed_gateways', [])) if tenant.get('allowed_gateways') else None

    return SliceRequest(
        slice_id=slice_id,
        tenant_id=tenant_id,
        traffic_class=service['traffic_class'],
        lifetime=lifetime,
        service_name=service_name,
        region=region,
        required_bw_mbps=required_bw_mbps,
        delay_threshold_ms=service['delay_threshold_ms'],
        vnfs=service['vnfs'],
        virtual_links=service['virtual_links'],
        allowed_gateways=allowed_gateways,
        min_guaranteed_bw_mbps=service['min_guaranteed_bw_mbps'],
        latency_target_ms=service['latency_target_ms'],
        jitter_target_ms=service['jitter_target_ms'],
        loss_target_pct=service['loss_target_pct'],
        priority_tier=service['priority_tier'],
        degradation_allowed=service['degradation_allowed'],
    )