# ADR 0002: Policy-based multi-link backhaul

- Status: Accepted (reference architecture)
- Author: Anthony Blow

## Context
Corridor coverage varies: dense urban 5G, rural cellular gaps, satellite with wide coverage but higher cost per GB, and short fiber-fed trackside segments with very high capacity. Traffic classes have different needs: crew/ops and telemetry need reliability, payments need low loss, passenger Wi-Fi needs throughput at a controlled cost.

## Decision
The onboard connectivity manager probes every link and scores healthy links per traffic class with class-specific weights for throughput, latency, loss and cost. It applies:
- **Hysteresis** (challenger must win by a margin) and a **minimum dwell time** to avoid flapping at coverage edges;
- **Fast failover** that bypasses dwell when the primary is down or badly lossy;
- A **standby on a different bearer type** for ops traffic so a single-technology outage does not take it down.
Bonding or per-flow multipath is an optimization layered on top, not a replacement for policy.

## Consequences
- + Predictable, explainable switching (every switch logged with a reason).
- + Cost becomes a tunable policy input rather than an afterthought.
- − Weights need tuning per route with field data; the prototype uses notional values.

Prototype: `rpx/backhaul.py`, tests in `tests/test_backhaul.py`.
