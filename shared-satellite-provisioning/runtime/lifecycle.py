from __future__ import annotations
from typing import Dict, List
from models.active_slice import ActiveSlice
from orchestration.reservation import release_slice


class LifecycleManager:
    def __init__(self, graph, beams, feeders):
        self.graph = graph
        self.beams = beams
        self.feeders = feeders
        self.active_slices: Dict[str, ActiveSlice] = {}

    def add(self, active: ActiveSlice):
        active.remaining_lifetime -= 1
        self.active_slices[active.request.slice_id] = active

    def remove_slice(self, slice_id: str) -> bool:
        active = self.active_slices.pop(slice_id, None)
        if active is None:
            return False
        release_slice(self.graph, active, self.beams, self.feeders)
        return True

    def tick(self):
        expired: List[str] = []
        for slice_id, active in self.active_slices.items():
            active.remaining_lifetime -= 1
            if active.remaining_lifetime <= 0:
                expired.append(slice_id)
        for slice_id in expired:
            active = self.active_slices.pop(slice_id)
            release_slice(self.graph, active, self.beams, self.feeders)
        return expired