from __future__ import annotations


def snapshot(graph, beams, feeders, lifecycle_manager):
    nodes = {
        n: {
            'cpu_free': data['obj'].cpu_free,
            'mem_free': data['obj'].mem_free,
            'storage_free': data['obj'].storage_free,
        }
        for n, data in graph.nodes(data=True)
    }

    links = {
        f'{a}<->{b}': graph[a][b]['obj'].bw_free
        for a, b in graph.edges()
    }

    beam_view = {bid: b.capacity_free_mbps for bid, b in beams.items()}
    feeder_view = {gid: f.capacity_free_mbps for gid, f in feeders.items()}

    active_slice_details = {
        sid: {
            'beam_id': active.beam_id,
            'gateway_id': active.gateway_id,
            'target_bw_mbps': active.target_bw_mbps,
            'granted_bw_mbps': active.granted_bw_mbps,
            'min_guaranteed_bw_mbps': active.min_guaranteed_bw_mbps,
            'sla_state': active.sla_state,
            'recovery_action': active.recovery_action,
            'remaining_lifetime': active.remaining_lifetime,
        }
        for sid, active in lifecycle_manager.active_slices.items()
    }

    return {
        'nodes': nodes,
        'links': links,
        'beams': beam_view,
        'feeders': feeder_view,
        'active_slices': list(lifecycle_manager.active_slices.keys()),
        'active_slice_details': active_slice_details,
    }