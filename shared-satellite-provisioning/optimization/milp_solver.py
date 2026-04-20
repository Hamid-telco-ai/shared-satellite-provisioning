from typing import Dict, Any, List, Tuple
import pulp

from orchestration.reservation import effective_beam_total_capacity


def priority_weights(priority_tier: str) -> tuple[float, float, float, float, float]:
    mapping = {
        "critical": (100000.0, 500.0, 2000.0, 800.0, 50.0),
        "high": (20000.0, 200.0, 1000.0, 400.0, 20.0),
        "medium": (5000.0, 50.0, 500.0, 120.0, 8.0),
        "low": (500.0, 10.0, 100.0, 20.0, 2.0),
    }
    return mapping.get(priority_tier, mapping["medium"])


def _candidate_nodes_for_vnf(graph, vnf) -> List[str]:
    candidates = []
    for node_id, data in graph.nodes(data=True):
        obj = data["obj"]
        allowed = getattr(obj, "allowed_vnfs", set()) or set()
        if getattr(vnf, "vnf_type", None) in allowed:
            candidates.append(node_id)
    return candidates


def _directed_arcs_from_graph(graph) -> List[Tuple[str, str]]:
    arcs: List[Tuple[str, str]] = []
    for a, b in graph.edges():
        arcs.append((a, b))
        arcs.append((b, a))
    return arcs


def _route_cost(graph, i: str, j: str) -> float:
    return float(graph[i][j]["obj"].delay_ms)


def _reconstruct_path(used_arcs: List[Tuple[str, str]], start: str, end: str) -> List[str]:
    if start == end:
        return [start]

    next_hop = {}
    for i, j in used_arcs:
        next_hop[i] = j

    path = [start]
    visited = {start}
    cur = start

    while cur != end:
        if cur not in next_hop:
            break
        cur = next_hop[cur]
        if cur in visited:
            break
        path.append(cur)
        visited.add(cur)

    return path


def _beam_quality_score(beam) -> float:
    mcs = float(getattr(beam, "mcs_efficiency", 1.0) or 1.0)
    fade = float(getattr(beam, "fade_penalty", 1.0) or 1.0)
    return 3.0 * mcs * fade


def solve_phase_de_milp(
    active_slices: Dict[str, Any],
    beams: Dict[str, Any],
    feeders: Dict[str, Any],
    graph,
    tick: int
) -> Dict[str, Any]:
    slice_ids = list(active_slices.keys())
    beam_ids = list(beams.keys())
    gateway_ids = list(feeders.keys())
    node_ids = list(graph.nodes())
    arcs = _directed_arcs_from_graph(graph)
    undirected_edges = list(graph.edges())

    current_bg = {}
    current_bw = {}
    current_placement = {}
    for s in slice_ids:
        active = active_slices[s]
        current_bg[s] = (active.beam_id, active.gateway_id)
        current_bw[s] = float(active.granted_bw_mbps)
        current_placement[s] = dict(active.placement)

    vnf_names: Dict[str, List[str]] = {}
    vnf_objs: Dict[Tuple[str, str], Any] = {}
    vlink_keys: Dict[str, List[Tuple[str, str]]] = {}
    vlink_objs: Dict[Tuple[str, Tuple[str, str]], Any] = {}
    candidates: Dict[Tuple[str, str], List[str]] = {}

    for s in slice_ids:
        req = active_slices[s].request

        vnf_names[s] = []
        for vnf in req.vnfs:
            vnf_names[s].append(vnf.name)
            vnf_objs[(s, vnf.name)] = vnf
            candidates[(s, vnf.name)] = _candidate_nodes_for_vnf(graph, vnf)

        vlink_keys[s] = []
        for e in req.virtual_links:
            key = (e.src, e.dst)
            vlink_keys[s].append(key)
            vlink_objs[(s, key)] = e

    prob = pulp.LpProblem("SharedSatellitePhaseFG", pulp.LpMinimize)

    # Core variables
    a = {s: pulp.LpVariable(f"a_{s}", cat="Binary") for s in slice_ids}
    q = {s: pulp.LpVariable(f"q_{s}", cat="Binary") for s in slice_ids}
    y = {s: pulp.LpVariable(f"y_{s}", lowBound=0, cat="Continuous") for s in slice_ids}

    d_bw = {s: pulp.LpVariable(f"d_bw_{s}", lowBound=0, cat="Continuous") for s in slice_ids}
    d_min = {s: pulp.LpVariable(f"d_min_{s}", lowBound=0, cat="Continuous") for s in slice_ids}
    latency = {s: pulp.LpVariable(f"latency_{s}", lowBound=0, cat="Continuous") for s in slice_ids}

    m_bg = {s: pulp.LpVariable(f"m_bg_{s}", cat="Binary") for s in slice_ids}
    m_bw = {s: pulp.LpVariable(f"m_bw_{s}", lowBound=0, cat="Continuous") for s in slice_ids}

    z = {
        (s, b, g): pulp.LpVariable(f"z_{s}_{b}_{g}", cat="Binary")
        for s in slice_ids for b in beam_ids for g in gateway_ids
    }

    v = {
        (s, b, g): pulp.LpVariable(f"v_{s}_{b}_{g}", lowBound=0, cat="Continuous")
        for s in slice_ids for b in beam_ids for g in gateway_ids
    }

    # Placement variables
    x = {}
    for s in slice_ids:
        for vnf_name in vnf_names[s]:
            for p in candidates[(s, vnf_name)]:
                x[(s, vnf_name, p)] = pulp.LpVariable(f"x_{s}_{vnf_name}_{p}", cat="Binary")

    m_place = {
        (s, vnf_name): pulp.LpVariable(f"m_place_{s}_{vnf_name}", cat="Binary")
        for s in slice_ids for vnf_name in vnf_names[s]
    }

    # Routing variables
    f = {}
    u = {}
    for s in slice_ids:
        for e_key in vlink_keys[s]:
            for i, j in arcs:
                f[(s, e_key, i, j)] = pulp.LpVariable(
                    f"f_{s}_{e_key[0]}_{e_key[1]}_{i}_{j}", cat="Binary"
                )
                u[(s, e_key, i, j)] = pulp.LpVariable(
                    f"u_{s}_{e_key[0]}_{e_key[1]}_{i}_{j}", lowBound=0, cat="Continuous"
                )

    # Phase F helper variables
    node_cpu_used = {
        p: pulp.LpVariable(f"node_cpu_used_{p}", lowBound=0, cat="Continuous")
        for p in node_ids
    }
    gateway_used = {
        g: pulp.LpVariable(f"gateway_used_{g}", lowBound=0, cat="Continuous")
        for g in gateway_ids
    }
    link_used = {
        (a_node, b_node): pulp.LpVariable(f"link_used_{a_node}_{b_node}", lowBound=0, cat="Continuous")
        for (a_node, b_node) in undirected_edges
    }
    node_active_flag = {
        (s, p): pulp.LpVariable(f"node_active_{s}_{p}", cat="Binary")
        for s in slice_ids for p in node_ids
    }

    # Objective
    obj_terms = []

    for s in slice_ids:
        active = active_slices[s]
        drop_penalty, shortfall_penalty, min_violation_penalty, migration_penalty, bw_change_penalty = priority_weights(
            active.priority_tier
        )

        obj_terms.append(drop_penalty * q[s])
        obj_terms.append(shortfall_penalty * d_bw[s])
        obj_terms.append(min_violation_penalty * d_min[s])
        obj_terms.append(migration_penalty * m_bg[s])
        obj_terms.append(bw_change_penalty * m_bw[s])

        # Phase G latency penalty
        obj_terms.append(5.0 * latency[s])

        for vnf_name in vnf_names[s]:
            obj_terms.append(20.0 * m_place[(s, vnf_name)])

        for e_key in vlink_keys[s]:
            for i, j in arcs:
                obj_terms.append(2.0 * _route_cost(graph, i, j) * f[(s, e_key, i, j)])

    # Phase F objective terms
    for p in node_ids:
        obj_terms.append(25.0 * node_cpu_used[p])

    for g in gateway_ids:
        obj_terms.append(4.0 * gateway_used[g])

    for edge_key in undirected_edges:
        obj_terms.append(2.0 * link_used[edge_key])

    for s in slice_ids:
        for b in beam_ids:
            quality = _beam_quality_score(beams[b])
            for g in gateway_ids:
                obj_terms.append(-120.0 * quality * z[(s, b, g)])

    for s in slice_ids:
        for p in node_ids:
            obj_terms.append(-50.0 * node_active_flag[(s, p)])

    prob += pulp.lpSum(obj_terms)

    # Constraints per slice
    for s in slice_ids:
        active = active_slices[s]
        target_bw = float(active.target_bw_mbps)
        min_bw = float(active.min_guaranteed_bw_mbps)
        degradation_allowed = bool(active.degradation_allowed)
        old_beam, old_gateway = current_bg[s]
        old_bw = current_bw[s]
        latency_target = float(getattr(active, "latency_target_ms", 0.0) or 0.0)

        prob += a[s] + q[s] == 1, f"active_or_drop_{s}"
        prob += pulp.lpSum(z[(s, b, g)] for b in beam_ids for g in gateway_ids) == a[s], f"one_bg_{s}"
        prob += y[s] <= target_bw * a[s], f"max_bw_{s}"

        if not degradation_allowed:
            prob += y[s] == target_bw * a[s], f"fixed_bw_{s}"

        prob += d_bw[s] >= target_bw * a[s] - y[s], f"bw_shortfall_{s}"

        if min_bw > 0:
            prob += d_min[s] >= min_bw * a[s] - y[s], f"min_violation_{s}"
            prob += d_min[s] >= 0, f"min_violation_nonneg_{s}"

        for b in beam_ids:
            beam = beams[b]
            visible = (not beam.visible_windows) or (tick in beam.visible_windows)

            for g in gateway_ids:
                compatible = (not beam.candidate_gateways) or (g in beam.candidate_gateways)
                if not visible or not compatible:
                    prob += z[(s, b, g)] == 0, f"infeasible_bg_{s}_{b}_{g}"

        M_bw = max(target_bw, 1.0)
        for b in beam_ids:
            for g in gateway_ids:
                prob += v[(s, b, g)] <= y[s], f"v1_{s}_{b}_{g}"
                prob += v[(s, b, g)] <= M_bw * z[(s, b, g)], f"v2_{s}_{b}_{g}"
                prob += v[(s, b, g)] >= y[s] - M_bw * (1 - z[(s, b, g)]), f"v3_{s}_{b}_{g}"
                prob += v[(s, b, g)] >= 0, f"v4_{s}_{b}_{g}"

        prob += m_bg[s] >= a[s] - z[(s, old_beam, old_gateway)], f"migrate_bg_{s}"
        prob += m_bw[s] >= y[s] - old_bw, f"bw_change_pos_{s}"
        prob += m_bw[s] >= old_bw - y[s], f"bw_change_neg_{s}"

        for vnf_name in vnf_names[s]:
            cand = candidates[(s, vnf_name)]
            if not cand:
                prob += a[s] == 0, f"no_candidate_{s}_{vnf_name}"
            else:
                prob += pulp.lpSum(x[(s, vnf_name, p)] for p in cand) == a[s], f"place_once_{s}_{vnf_name}"

            old_p = current_placement[s].get(vnf_name)
            if old_p in cand:
                prob += m_place[(s, vnf_name)] >= a[s] - x[(s, vnf_name, old_p)], f"place_migrate_{s}_{vnf_name}"
            else:
                prob += m_place[(s, vnf_name)] >= a[s], f"place_migrate_forced_{s}_{vnf_name}"

        for p in node_ids:
            relevant_pairs = [
                (vnf_name, x[(s, vnf_name, p)])
                for vnf_name in vnf_names[s]
                if (s, vnf_name, p) in x
            ]
            if relevant_pairs:
                for vnf_name, xv in relevant_pairs:
                    prob += node_active_flag[(s, p)] >= xv, f"node_active_lb_{s}_{p}_{vnf_name}"
                prob += node_active_flag[(s, p)] <= pulp.lpSum(xv for _, xv in relevant_pairs), f"node_active_ub_{s}_{p}"
            else:
                prob += node_active_flag[(s, p)] == 0, f"node_active_zero_{s}_{p}"

        for e_key in vlink_keys[s]:
            src_vnf, dst_vnf = e_key

            for n in node_ids:
                outgoing = [f[(s, e_key, n, j)] for (i, j) in arcs if i == n]
                incoming = [f[(s, e_key, i, n)] for (i, j) in arcs if j == n]

                src_term = x[(s, src_vnf, n)] if (s, src_vnf, n) in x else 0
                dst_term = x[(s, dst_vnf, n)] if (s, dst_vnf, n) in x else 0

                prob += (
                    pulp.lpSum(outgoing) - pulp.lpSum(incoming) == src_term - dst_term
                ), f"flow_{s}_{src_vnf}_{dst_vnf}_{n}"

            for i, j in arcs:
                prob += u[(s, e_key, i, j)] <= y[s], f"u1_{s}_{e_key}_{i}_{j}"
                prob += u[(s, e_key, i, j)] <= M_bw * f[(s, e_key, i, j)], f"u2_{s}_{e_key}_{i}_{j}"
                prob += u[(s, e_key, i, j)] >= y[s] - M_bw * (1 - f[(s, e_key, i, j)]), f"u3_{s}_{e_key}_{i}_{j}"
                prob += u[(s, e_key, i, j)] >= 0, f"u4_{s}_{e_key}_{i}_{j}"

        # Phase G latency model
        latency_terms = []

        # processing delay
        for vnf_name in vnf_names[s]:
            vnf = vnf_objs[(s, vnf_name)]
            proc_delay = float(getattr(vnf, "proc_delay_ms", 0.0) or 0.0)
            for p in candidates[(s, vnf_name)]:
                if (s, vnf_name, p) in x:
                    latency_terms.append(proc_delay * x[(s, vnf_name, p)])

        # routing delay
        for e_key in vlink_keys[s]:
            for i, j in arcs:
                link_delay = float(graph[i][j]["obj"].delay_ms)
                latency_terms.append(link_delay * f[(s, e_key, i, j)])

        prob += latency[s] == pulp.lpSum(latency_terms), f"latency_def_{s}"

        if latency_target > 0:
            prob += latency[s] <= latency_target + 1000.0 * q[s], f"latency_sla_{s}"

    # Node capacities
    for p in node_ids:
        node = graph.nodes[p]["obj"]

        cpu_terms = []
        mem_terms = []
        sto_terms = []

        for s in slice_ids:
            for vnf_name in vnf_names[s]:
                if (s, vnf_name, p) in x:
                    vnf = vnf_objs[(s, vnf_name)]
                    cpu_terms.append(float(vnf.cpu) * x[(s, vnf_name, p)])
                    mem_terms.append(float(vnf.mem) * x[(s, vnf_name, p)])
                    sto_terms.append(float(vnf.storage) * x[(s, vnf_name, p)])

        prob += node_cpu_used[p] == pulp.lpSum(cpu_terms), f"node_cpu_used_{p}"
        prob += pulp.lpSum(cpu_terms) <= float(node.cpu_total), f"cpu_cap_{p}"
        prob += pulp.lpSum(mem_terms) <= float(node.mem_total), f"mem_cap_{p}"
        prob += pulp.lpSum(sto_terms) <= float(node.storage_total), f"sto_cap_{p}"

    # Link capacities
    for a_node, b_node in undirected_edges:
        link = graph[a_node][b_node]["obj"]
        cap = float(link.bw_total)

        terms = []
        for s in slice_ids:
            for e_key in vlink_keys[s]:
                e = vlink_objs[(s, e_key)]
                target_bw = max(float(active_slices[s].target_bw_mbps), 1.0)
                coeff = float(e.bw) / target_bw

                terms.append(coeff * u[(s, e_key, a_node, b_node)])
                terms.append(coeff * u[(s, e_key, b_node, a_node)])

        prob += link_used[(a_node, b_node)] == pulp.lpSum(terms), f"link_used_{a_node}_{b_node}"
        prob += pulp.lpSum(terms) <= cap, f"link_cap_{a_node}_{b_node}"

    # Beam capacities
    for b in beam_ids:
        eff_cap = float(effective_beam_total_capacity(beams[b]))
        prob += pulp.lpSum(v[(s, b, g)] for s in slice_ids for g in gateway_ids) <= eff_cap, f"beam_cap_{b}"

    # Feeder capacities
    for g in gateway_ids:
        feeder_cap = float(feeders[g].capacity_total_mbps)
        feeder_terms = [v[(s, b, g)] for s in slice_ids for b in beam_ids]
        prob += gateway_used[g] == pulp.lpSum(feeder_terms), f"gateway_used_{g}"
        prob += pulp.lpSum(feeder_terms) <= feeder_cap, f"feeder_cap_{g}"

    solver = pulp.PULP_CBC_CMD(msg=False)
    status = prob.solve(solver)

    result = {
        "status": pulp.LpStatus[status],
        "objective": pulp.value(prob.objective),
        "slices": {},
    }

    for s in slice_ids:
        chosen_bg = None
        for b in beam_ids:
            for g in gateway_ids:
                val = pulp.value(z[(s, b, g)])
                if val is not None and val > 0.5:
                    chosen_bg = (b, g)
                    break
            if chosen_bg:
                break

        placement = {}
        for vnf_name in vnf_names[s]:
            chosen_p = None
            for p in candidates[(s, vnf_name)]:
                val = pulp.value(x[(s, vnf_name, p)])
                if val is not None and val > 0.5:
                    chosen_p = p
                    break
            placement[vnf_name] = chosen_p

        routes = {}
        for e_key in vlink_keys[s]:
            src_vnf, dst_vnf = e_key
            src_node = placement.get(src_vnf)
            dst_node = placement.get(dst_vnf)

            used_arcs = []
            for i, j in arcs:
                val = pulp.value(f[(s, e_key, i, j)])
                if val is not None and val > 0.5:
                    used_arcs.append((i, j))

            if src_node is not None and dst_node is not None:
                routes[f"{src_vnf}->{dst_vnf}"] = _reconstruct_path(used_arcs, src_node, dst_node)
            else:
                routes[f"{src_vnf}->{dst_vnf}"] = []

        result["slices"][s] = {
            "active": int(round(pulp.value(a[s]) or 0)),
            "dropped": int(round(pulp.value(q[s]) or 0)),
            "granted_bw_mbps": float(pulp.value(y[s]) or 0.0),
            "bw_shortfall": float(pulp.value(d_bw[s]) or 0.0),
            "min_violation": float(pulp.value(d_min[s]) or 0.0),
            "migration_flag": int(round(pulp.value(m_bg[s]) or 0)),
            "bw_change": float(pulp.value(m_bw[s]) or 0.0),
            "latency_ms": float(pulp.value(latency[s]) or 0.0),
            "beam_gateway": chosen_bg,
            "placement": placement,
            "routes": routes,
        }

    return result