# ADR 0004: Offline-first POS with idempotent sync

- Status: Accepted (reference architecture)
- Author: Anthony Blow

## Context
Café sales must continue through coverage gaps. Retries after lost acknowledgements must never double-charge, double-decrement inventory or double-award loyalty points.

## Decision
- Terminals write every sale/refund to a durable, append-only local journal with a client-generated UUID idempotency key and a per-terminal sequence number.
- A sync agent replays unacknowledged entries in order whenever any link is up.
- The ground ledger dedupes on the key; a duplicate returns `duplicate` with no side effects.
- Refunds reference the original key and reverse inventory, revenue and points.
- Payment data: P2PE at the reader, tokens only on the terminal, offline floor limits by policy.

## Consequences
- + Exactly-once business effects with at-least-once transport.
- + Loyalty works offline; balances reconcile on sync.
- − Offline authorization risk must be bounded by floor limits and fraud rules.

Prototype: `rpx/pos.py`, tests in `tests/test_pos.py`.
