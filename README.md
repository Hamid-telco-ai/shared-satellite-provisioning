# Shared Satellite Service Provisioning Framework  
### SLA-Aware Multi-Domain Orchestration for NTN + Terrestrial Networks

---

## Overview

Shared Satellite Provisioning is an advanced orchestration framework for **Non-Terrestrial Networks (NTN)** that jointly optimizes:

- Satellite beam selection  
- Gateway assignment  
- VNF placement (edge + core)  
- End-to-end routing  

All decisions are made simultaneously using a **Mixed-Integer Linear Programming (MILP)** model under strict **Service Level Agreement (SLA)** constraints.

Unlike traditional approaches that optimize domains independently, this system enables:

- SLA-aware optimization *(bandwidth + latency embedded in solver)*  
- Physical constraints *(PNF anchoring)*  
- Closed-loop re-optimization under dynamic conditions  

---

## System Architecture:

Satellite Layer → Beam Selection
        ↓
Gateway Layer → Feeder Constraints
        ↓
Compute Layer → VNF Placement
        ↓
Transport Layer → Routing
        ↓
MILP Orchestrator

## Framework Overview:

### Phase 1 — Baseline Orchestration
  - Static network topology
  - VNF placement
  - Routing and delay verification
  - Admission control and resource reservation

### Phase 2 — Satellite-Aware Placement
  - Gateway selection constraints
  - Fronthaul delay limitations
  - PNF anchoring enforcement

### Phase 3 — Beam & Feeder Allocation
  - Satellite beam selection
  - Feeder capacity constraints
  - Beam–gateway coupling

### Phase 4 — Runtime Lifecycle
  - Slice admission over time
  - Slice expiration handling
  - Resource release and reuse

### Phase 5 — Dynamic Re-Optimization
  - Failure detection and handling
  - Degradation-aware recovery
  - MILP-ready orchestration architecture

## Mathematical Model

### 🔹 Beam Capacity

C_b = C_b_raw × η_b × φ_b

        - **C_b_raw**: raw beam capacity  
        - **η_b**: modulation efficiency  
        - **φ_b**: channel degradation  

---

### 🔹 Latency Model

  ```text
  λ_s = Σ (processing delay) + Σ (link delay)

  Constraint:

  λ_s ≤ L_s_max + M × q_s

    λ_s: Actual end-to-end latency of slice s
    L_s_max: Maximum allowed latency (SLA requirement)
    M: Big-M constant (very large number)
    q_s: Binary variable (0 or 1)


  ### Objective Function:

  Minimizes:

    - SLA violations
    - Bandwidth shortfall
    - Reconfiguration cost
    - Congestion
    - Latency

  ### Core Constraints:

    - Slice activation
    - Beam capacity
    - Gateway capacity
    - Node compute limits
    - Flow conservation

  ### PNF Constraint:
  
  ```text
  d(node, PNF) ≤ D_max

    d(node,PNF): Network delay (latency) between a candidate compute node and a PNF (Physical Network Function)
    D_max: Maximum allowed delay between VNF and its associated PNF
    
    This constraint directly impacts:
      VNF placement variables x_s,v,n
      Candidate filtering:
        if d(node, PNF) > D_max → x = 0 (forbidden)

## 1. Requirements

- Python 3.10+
- Packages:
  - `networkx`
  - `pyyaml`
  - `pulp`

Install:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install networkx pyyaml pulp
```

Windows PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install networkx pyyaml pulp
```

## 2. Run the static demo

```bash
python3 main.py --mode static
```

This will:
- load topology, beams, feeders, PNF attachment, tenants, and services
- create one request (`slice_A`)
- select a valid beam and gateway
- generate candidate PoPs per VNF
- place VNFs heuristically
- build physical paths for virtual links
- check end-to-end delay
- reserve compute, link, beam, and feeder resources
- print a snapshot of remaining resources

## 3. Run the runtime simulation

```bash
python3 main.py --mode runtime --ticks 5
```

This will:
- inject requests from `config/runtime.yaml`
- admit or reject requests per tick
- decrement lifetimes
- free expired slices
- print snapshots after each tick

## 4. Configuration Files

### Topology
`config/topology.yaml`:
- nodes / PoPs
- transport and fronthaul links
- beams
- feeders
- PNF attachment points

### Services
`config/services.yaml`:
- VNF chains
- per-VNF resource demand
- delay thresholds
- fronthaul or hub-delay sensitivity

### Tenants
`config/tenants.yaml`:
- allowed services
- allowed gateways
- allowed regions

### Runtime requests
`config/runtime.yaml`:
- arrival time
- service type
- region
- lifetime
- requested bandwidth

## 5. Project Structure
shared-satellite-provisioning/
├── orchestrator/
├── models/
├── solver/
├── scenarios/
├── results/
├── docs/
└── README.md

## 6. Example Output (Static mode: core orchestration result)

```bash
python3 main.py --mode static
```

Result
  ACCEPTED
  beam: beam_101
  gateway: gw_1
  total_delay_ms: 17.0

VNF Placement
  {
  "fw": "edge_pop_1",
  "qos": "gw_pop_1",
  "sbg": "gw_pop_2"
}

Routing Paths
  {
  "fw->qos": ["edge_pop_1", "gw_pop_1"],
  "qos->sbg": ["gw_pop_1", "pnf_attach_1", "gw_pop_2"]
}

## 7. Example Output (Runtime mode: lifecycle and dynamic operation result)

```bash
python main.py --mode runtime --ticks 5
```

TICK 0:
slice_A ACCEPTED

TICK 1:
slice_B ACCEPTED

TICK 2:
backhaul_failure → slice_B DEGRADED (40 → 32 Mbps)
slice_A expired

TICK 3:
slice_B expired

TICK 4:
no active slices

## Interpretation

This simulation highlights the system's ability to:
- adapt to network degradation
- manage competing slice demands
- enforce SLA-aware orchestration under constraints
