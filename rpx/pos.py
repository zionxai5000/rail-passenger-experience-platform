"""Offline-first food & beverage POS with idempotent sync and loyalty accrual.

Onboard, the café terminal must keep selling when backhaul drops. Each sale is
written to a local append-only journal with a client-generated idempotency key
(UUID). A sync agent replays unacknowledged entries to the ground ledger
whenever any link is up. The ground ledger dedupes on the key, so retries after
a lost ACK never double-charge, double-decrement inventory, or double-award
loyalty points. Card data is never stored here: the terminal holds only a
P2PE/tokenized reference (see docs/adr/0004-pos-offline-sync.md).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass(frozen=True)
class Txn:
    key: str
    terminal_id: str
    seq: int
    kind: str                 # sale | refund
    items: tuple              # ((sku, qty, unit_cents), ...)
    member_id: Optional[str] = None
    payment_token: str = "tok_offline_auth"
    refund_of: Optional[str] = None

    @property
    def total_cents(self) -> int:
        sign = -1 if self.kind == "refund" else 1
        return sign * sum(q * c for _, q, c in self.items)


class LinkDown(Exception):
    pass


@dataclass
class GroundLedger:
    """Authoritative store in the ground cloud. Idempotent by txn key."""

    inventory: Dict[str, int] = field(default_factory=dict)
    points: Dict[str, int] = field(default_factory=dict)
    txns: Dict[str, Txn] = field(default_factory=dict)
    points_per_dollar: int = 2
    revenue_cents: int = 0

    def apply(self, txn: Txn) -> str:
        if txn.key in self.txns:
            return "duplicate"  # replay after lost ACK: no side effects
        if txn.kind == "refund":
            orig = self.txns.get(txn.refund_of or "")
            if orig is None:
                return "rejected:unknown_original"
        self.txns[txn.key] = txn
        self.revenue_cents += txn.total_cents
        sign = 1 if txn.kind == "refund" else -1
        for sku, qty, _ in txn.items:
            self.inventory[sku] = self.inventory.get(sku, 0) + sign * qty
        if txn.member_id:
            delta = (txn.total_cents // 100) * self.points_per_dollar
            self.points[txn.member_id] = max(0, self.points.get(txn.member_id, 0) + delta)
        return "applied"


@dataclass
class Terminal:
    terminal_id: str
    journal: List[Txn] = field(default_factory=list)
    acked: set = field(default_factory=set)
    local_stock: Dict[str, int] = field(default_factory=dict)
    _seq: int = 0

    def sell(self, items, member_id=None) -> Txn:
        for sku, qty, _ in items:
            if self.local_stock.get(sku, 0) < qty:
                raise ValueError(f"out of stock: {sku}")
        for sku, qty, _ in items:
            self.local_stock[sku] -= qty
        return self._record("sale", items, member_id)

    def refund(self, original: Txn) -> Txn:
        for sku, qty, _ in original.items:
            self.local_stock[sku] = self.local_stock.get(sku, 0) + qty
        return self._record("refund", original.items, original.member_id, refund_of=original.key)

    def _record(self, kind, items, member_id, refund_of=None) -> Txn:
        self._seq += 1
        t = Txn(str(uuid.uuid4()), self.terminal_id, self._seq, kind, tuple(items), member_id,
                refund_of=refund_of)
        self.journal.append(t)  # durable append (fsync'd file / SQLite WAL in production)
        return t

    def pending(self) -> List[Txn]:
        return [t for t in self.journal if t.key not in self.acked]


@dataclass
class SyncAgent:
    terminal: Terminal
    send: Callable[[Txn], str]      # transport to ground; may raise LinkDown
    batch: int = 50

    def sync(self) -> Dict[str, int]:
        stats = {"sent": 0, "applied": 0, "duplicate": 0, "rejected": 0, "deferred": 0}
        for txn in self.terminal.pending()[: self.batch]:  # in journal order
            try:
                result = self.send(txn)
            except LinkDown:
                stats["deferred"] = len(self.terminal.pending())
                break
            stats["sent"] += 1
            stats[result.split(":")[0]] += 1
            self.terminal.acked.add(txn.key)
        return stats


class FlakyTransport:
    """Simulates link loss and lost ACKs (server applied, client never heard)."""

    def __init__(self, ledger: GroundLedger, down: bool = False, drop_ack_every: int = 0):
        self.ledger, self.down, self.drop_ack_every, self.calls = ledger, down, drop_ack_every, 0

    def __call__(self, txn: Txn) -> str:
        if self.down:
            raise LinkDown()
        self.calls += 1
        result = self.ledger.apply(txn)
        if self.drop_ack_every and self.calls % self.drop_ack_every == 0:
            raise LinkDown()  # applied server-side, ACK lost in transit
        return result
