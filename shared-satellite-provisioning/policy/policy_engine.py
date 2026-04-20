from __future__ import annotations
from typing import Dict, List, Tuple


class PolicyEngine:
    def __init__(self, tenants_cfg: Dict):
        self.tenants = tenants_cfg.get('tenants', tenants_cfg)
        self.traffic_class_priority = {
            'qos1': 300,
            'qos2': 200,
            'qos3': 100,
        }

    def _tenant_cfg(self, tenant_id: str) -> Dict:
        return self.tenants.get(tenant_id, {})

    def request_priority(self, request) -> int:
        tenant_cfg = self._tenant_cfg(request.tenant_id)
        base = self.traffic_class_priority.get(getattr(request, 'traffic_class', ''), 0)
        boost = tenant_cfg.get('priority_boost', 0)
        return base + boost

    def active_count_for_tenant(self, tenant_id: str, active_slices: Dict[str, object]) -> int:
        return sum(1 for active in active_slices.values() if active.request.tenant_id == tenant_id)

    def active_bw_for_tenant(self, tenant_id: str, active_slices: Dict[str, object]) -> float:
        return sum(active.request.required_bw_mbps for active in active_slices.values()
                   if active.request.tenant_id == tenant_id)

    def can_admit(self, request, active_slices: Dict[str, object]) -> Tuple[bool, str]:
        tenant_cfg = self._tenant_cfg(request.tenant_id)

        service_name = getattr(request, 'service_name', None)
        region = getattr(request, 'region', None)

        allowed_services = tenant_cfg.get('allowed_services', [])
        if allowed_services and service_name is not None and service_name not in allowed_services:
            return False, f'service {service_name} not allowed for tenant {request.tenant_id}'

        allowed_regions = tenant_cfg.get('allowed_regions', [])
        if allowed_regions and region is not None and region not in allowed_regions:
            return False, f'region {region} not allowed for tenant {request.tenant_id}'

        max_active_slices = tenant_cfg.get('max_active_slices')
        if max_active_slices is not None:
            current_active = self.active_count_for_tenant(request.tenant_id, active_slices)
            if current_active >= max_active_slices:
                return False, f'tenant {request.tenant_id} reached max_active_slices={max_active_slices}'

        max_total_bw_mbps = tenant_cfg.get('max_total_bw_mbps')
        if max_total_bw_mbps is not None:
            current_bw = self.active_bw_for_tenant(request.tenant_id, active_slices)
            if current_bw + request.required_bw_mbps > max_total_bw_mbps:
                return False, f'tenant {request.tenant_id} would exceed max_total_bw_mbps={max_total_bw_mbps}'

        return True, 'Policy check passed'

    def can_preempt(self, request) -> bool:
        tenant_cfg = self._tenant_cfg(request.tenant_id)
        return bool(tenant_cfg.get('can_preempt', False))

    def find_preemption_candidates(self, request, active_slices: Dict[str, object]) -> List[str]:
        req_priority = self.request_priority(request)
        candidates = []

        for slice_id, active in active_slices.items():
            active_priority = self.request_priority(active.request)
            if active_priority < req_priority:
                candidates.append((
                    active_priority,
                    active.request.required_bw_mbps,
                    slice_id
                ))

        candidates.sort(key=lambda x: (x[0], -x[1]))
        return [slice_id for _, _, slice_id in candidates]