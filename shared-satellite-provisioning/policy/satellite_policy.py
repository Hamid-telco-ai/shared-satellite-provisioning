from __future__ import annotations
from typing import Dict, List, Optional, Tuple
from models.resources import BeamResource, FeederResource


def effective_beam_total_capacity(beam: BeamResource) -> float:
    raw = beam.raw_capacity_mbps if beam.raw_capacity_mbps > 0 else beam.capacity_total_mbps
    return raw * beam.mcs_efficiency * beam.fade_penalty


def effective_beam_free_capacity(beam: BeamResource) -> float:
    # For now, treat capacity_free_mbps as the current usable free pool.
    # Later we can make this stricter by explicitly tracking used-vs-effective capacity.
    return min(beam.capacity_free_mbps, effective_beam_total_capacity(beam))


def find_candidate_beams(region: str, beams: Dict[str, BeamResource], tick: Optional[int] = None) -> List[str]:
    out = []
    for beam_id, beam in beams.items():
        if beam.region != region:
            continue
        if tick is not None and beam.visible_windows and tick not in beam.visible_windows:
            continue
        out.append(beam_id)
    return sorted(out)


def choose_beam_and_gateway(region: str, bandwidth: float, beams: Dict[str, BeamResource], feeders: Dict[str, FeederResource],
                            allowed_gateways=None, tick: Optional[int] = None) -> Optional[Tuple[str, str]]:
    candidates = find_candidate_beams(region, beams, tick)

    for beam_id in candidates:
        beam = beams[beam_id]
        beam_free = effective_beam_free_capacity(beam)
        if beam_free < bandwidth:
            continue

        gateways = beam.candidate_gateways or set(feeders.keys())
        for gw in gateways:
            if allowed_gateways and gw not in allowed_gateways:
                continue

            feeder = feeders.get(gw)
            if not feeder or feeder.capacity_free_mbps < bandwidth:
                continue

            return (beam_id, gw)

    return None