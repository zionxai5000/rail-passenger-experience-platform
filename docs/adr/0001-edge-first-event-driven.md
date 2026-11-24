# ADR 0001: Edge-first, event-driven onboard platform

- Status: Accepted (reference architecture)
- Author: Anthony Blow

## Context
A train spends meaningful time with degraded or no WAN connectivity. Passenger-facing functions (journey information, announcements, café sales, portal) cannot depend on a round trip to the cloud. Multiple vendors and fleet generations must integrate without bespoke point-to-point links.

## Decision
Run a small compute + event broker on an onboard edge gateway per trainset. Onboard services publish and consume domain events (`trip.*`, `pos.*`, `link.*`, `device.*`) locally. A store-and-forward bridge synchronizes topics with the ground event backbone whenever any link is available. The ground is authoritative for schedules, content, prices and the commerce ledger, but is never in the synchronous path of a passenger interaction.

## Consequences
- + Passenger functions survive WAN loss; recovery is replay, not manual intervention.
- + New capabilities subscribe to existing events instead of new integrations.
- − Requires event schema governance (registry, versioning) and edge fleet management.
- − Eventual consistency: dashboards must show data freshness.
