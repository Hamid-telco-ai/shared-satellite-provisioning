from __future__ import annotations
import argparse
import json
from optimization.milp_solver import solve_phase_de_milp
from inventory.topology_loader import load_infrastructure
from inventory.graph_builder import build_graph
from policy.tenant_policy import load_tenants
from policy.qos_policy import load_runtime
from policy.policy_engine import PolicyEngine
from orchestration.request_parser import load_services, build_slice_request
from orchestration.admission import AdmissionController
from orchestration.reservation import (
    scale_active_slice_bandwidth,
    reoptimize_active_slice_beam,
    reoptimize_active_slice_gateway,
)
from runtime.lifecycle import LifecycleManager
from runtime.monitor import snapshot
from runtime.qos_model import evaluate_slice_qos
from runtime.milp_apply import apply_phase_a_result


def build_parser():
    p = argparse.ArgumentParser(description='Shared satellite service provisioning platform starter')
    p.add_argument('--mode', choices=['static', 'runtime'], default='static')
    p.add_argument('--topology', default='config/topology.yaml')
    p.add_argument('--services', default='config/services.yaml')
    p.add_argument('--tenants', default='config/tenants.yaml')
    p.add_argument('--runtime', default='config/runtime.yaml')
    p.add_argument('--use_milp', action='store_true')
    p.add_argument('--ticks', type=int, default=5)
    return p


def try_admit_with_policy(req, tick, controller, lifecycle, policy_engine):
    ok, reason = policy_engine.can_admit(req, lifecycle.active_slices)
    if not ok:
        return False, f'POLICY_REJECTED - {reason}'

    result = controller.admit(req, tick=tick)
    if result.accepted:
        lifecycle.add(result.active_slice)
        evaluate_slice_qos(result.active_slice)
        return True, 'Accepted'

    if not policy_engine.can_preempt(req):
        return False, result.reason

    victims = policy_engine.find_preemption_candidates(req, lifecycle.active_slices)
    preempted = []

    for victim_id in victims:
        removed = lifecycle.remove_slice(victim_id)
        if removed:
            preempted.append(victim_id)

        ok, reason = policy_engine.can_admit(req, lifecycle.active_slices)
        if not ok:
            continue

        retry = controller.admit(req, tick=tick)
        if retry.accepted:
            lifecycle.add(retry.active_slice)
            evaluate_slice_qos(retry.active_slice)
            return True, f'Accepted after preempting {preempted}'

    return False, result.reason


def degrade_active_slice(active, beams, feeders):
    if not active.degradation_allowed:
        return False, "degradation not allowed"

    if active.granted_bw_mbps <= active.min_guaranteed_bw_mbps:
        return False, "already at minimum guaranteed bandwidth"

    reduction = active.granted_bw_mbps * 0.2
    new_bw = max(active.min_guaranteed_bw_mbps, active.granted_bw_mbps - reduction)
    released_bw = active.granted_bw_mbps - new_bw

    beams[active.beam_id].capacity_free_mbps += released_bw
    feeders[active.gateway_id].capacity_free_mbps += released_bw

    active.granted_bw_mbps = new_bw
    active.request.required_bw_mbps = new_bw

    if new_bw == active.min_guaranteed_bw_mbps:
        active.sla_state = "critical"
    else:
        active.sla_state = "degraded"

    active.recovery_action = "degraded"

    return True, f"degraded to {round(new_bw, 2)} Mbps"


def run_static(args):
    nodes, links, beams, feeders, pnfs = load_infrastructure(args.topology)
    graph = build_graph(nodes, links)
    tenants = load_tenants(args.tenants)
    services = load_services(args.services)
    controller = AdmissionController(graph, beams, feeders, pnfs)
    lifecycle = LifecycleManager(graph, beams, feeders)
    policy_engine = PolicyEngine(tenants)

    request = build_slice_request(
        slice_id='slice_A', tenant_id='tenant_A', service_name='mission_critical_voice',
        region='north_zone', lifetime=3, required_bw_mbps=30, tenants=tenants, services=services
    )
    accepted, reason = try_admit_with_policy(request, 0, controller, lifecycle, policy_engine)
    if not accepted:
        print('REJECTED:', reason)
        return

    active = lifecycle.active_slices[request.slice_id]
    print('ACCEPTED')
    print('reason:', reason)
    print('beam:', active.beam_id)
    print('gateway:', active.gateway_id)
    print('placement:', json.dumps(active.placement, indent=2))
    print('paths:', json.dumps({f'{k[0]}->{k[1]}': v for k, v in active.paths.items()}, indent=2))
    print('total_delay_ms:', round(active.total_delay_ms, 2))
    print(json.dumps(snapshot(graph, beams, feeders, lifecycle), indent=2))


def run_runtime(args):
    nodes, links, beams, feeders, pnfs = load_infrastructure(args.topology)
    graph = build_graph(nodes, links)
    tenants = load_tenants(args.tenants)
    services = load_services(args.services)
    runtime_cfg = load_runtime(args.runtime)
    controller = AdmissionController(graph, beams, feeders, pnfs)
    lifecycle = LifecycleManager(graph, beams, feeders)
    policy_engine = PolicyEngine(tenants)

    requests = runtime_cfg.get('requests', [])
    requests_by_tick = {}
    for r in requests:
        requests_by_tick.setdefault(r['tick'], []).append(r)

    events = runtime_cfg.get('events', [])
    events_by_tick = {}
    for e in events:
        events_by_tick.setdefault(e['tick'], []).append(e)

    for tick in range(args.ticks):
        print(f'--- TICK {tick} ---')

        for e in events_by_tick.get(tick, []):
            event_type = e.get('type')

            if event_type == 'backhaul_failure':
                target_slice = e.get('target_slice')
                extra_bw_mbps = e.get('extra_bw_mbps', 0)

                active = lifecycle.active_slices.get(target_slice)
                if active is None:
                    print(f"event backhaul_failure target={target_slice} FAILED - slice not active")
                else:
                    print(
                        f"event debug target={target_slice} "
                        f"current_beam={active.beam_id} current_bw={active.request.required_bw_mbps}"
                    )

                    ok = scale_active_slice_bandwidth(active, extra_bw_mbps, beams, feeders)
                    if ok:
                        evaluate_slice_qos(active)
                        print(
                            f"event backhaul_failure target={target_slice} RECOVERED - "
                            f"scaled on current beam/gateway extra_bw_mbps={extra_bw_mbps}"
                        )
                    else:
                        moved, new_beam = reoptimize_active_slice_beam(active, extra_bw_mbps, beams, feeders)
                        if moved:
                            evaluate_slice_qos(active)
                            print(
                                f"event backhaul_failure target={target_slice} RECOVERED - "
                                f"reoptimized to beam={new_beam} extra_bw_mbps={extra_bw_mbps}"
                            )
                        else:
                            moved_gw, new_alloc = reoptimize_active_slice_gateway(active, extra_bw_mbps, beams, feeders)
                            if moved_gw:
                                evaluate_slice_qos(active)
                                new_beam, new_gateway = new_alloc
                                print(
                                    f"event backhaul_failure target={target_slice} RECOVERED - "
                                    f"reoptimized to beam={new_beam} gateway={new_gateway} "
                                    f"extra_bw_mbps={extra_bw_mbps}"
                                )
                            else:
                                degraded, msg = degrade_active_slice(active, beams, feeders)
                                if degraded:
                                    evaluate_slice_qos(active)
                                    print(
                                        f"event backhaul_failure target={target_slice} DEGRADED - {msg}"
                                    )
                                else:
                                    print(
                                        f"event backhaul_failure target={target_slice} FAILED - {msg}"
                                    )
            else:
                print(f"event {event_type} IGNORED - unsupported event type")

        # STEP 4: run Phase A MILP after event handling and before expiry
        if args.use_milp and lifecycle.active_slices:
            milp_result = solve_phase_de_milp(lifecycle.active_slices, beams, feeders, graph, tick)
            print("MILP:", json.dumps(milp_result, indent=2))
            removed = apply_phase_a_result(milp_result, lifecycle.active_slices, beams, feeders, graph)
            if removed:
                print("milp_removed:", removed)

            # re-evaluate SLA/QoS after MILP assignments
            for active in lifecycle.active_slices.values():
                evaluate_slice_qos(active)

        expired = lifecycle.tick()
        if expired:
            print('expired:', expired)

        for r in requests_by_tick.get(tick, []):
            req = build_slice_request(
                slice_id=r['slice_id'], tenant_id=r['tenant_id'], service_name=r['service_name'],
                region=r['region'], lifetime=r['lifetime'], required_bw_mbps=r['required_bw_mbps'],
                tenants=tenants, services=services
            )
            accepted, reason = try_admit_with_policy(req, tick, controller, lifecycle, policy_engine)
            print(req.slice_id, 'ACCEPTED' if accepted else 'REJECTED', '-', reason)

        print(json.dumps(snapshot(graph, beams, feeders, lifecycle), indent=2))


if __name__ == '__main__':
    args = build_parser().parse_args()
    if args.mode == 'static':
        run_static(args)
    else:
        run_runtime(args)