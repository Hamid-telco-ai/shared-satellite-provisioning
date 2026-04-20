from __future__ import annotations


def evaluate_slice_qos(active):
    # Assume offered traffic is some fraction of the target bandwidth.
    # This avoids treating target == granted as immediate overload.
    arrival = max(0.8 * active.target_bw_mbps, 0.001)
    service = max(active.granted_bw_mbps, 0.001)

    if service <= arrival:
        rho = 1.0
        active.queue_delay_ms = 200.0
        active.jitter_ms = 50.0
        active.loss_pct = 10.0
    else:
        rho = arrival / service
        active.queue_delay_ms = 5.0 + 20.0 * rho / max(1e-6, (1.0 - rho))
        active.jitter_ms = 2.0 + 10.0 * rho
        active.loss_pct = max(0.0, (rho - 0.85) * 20.0)

    bw_ok = active.granted_bw_mbps >= active.min_guaranteed_bw_mbps
    delay_ok = active.latency_target_ms <= 0 or active.total_delay_ms <= active.latency_target_ms
    jitter_ok = active.jitter_target_ms <= 0 or active.jitter_ms <= active.jitter_target_ms
    loss_ok = active.loss_target_pct <= 0 or active.loss_pct <= active.loss_target_pct

    if bw_ok and delay_ok and jitter_ok and loss_ok and active.granted_bw_mbps >= active.target_bw_mbps:
        active.sla_state = "normal"
    elif bw_ok:
        active.sla_state = "degraded"
    else:
        active.sla_state = "failed"