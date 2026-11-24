"""One-command end-to-end demo: `python -m rpx.demo` (or `make demo`)."""
from __future__ import annotations

from collections import Counter

from .announcements import AnnouncementGenerator
from .backhaul import LinkSelector, default_links, run_journey
from .events import EventBus
from .feed import FeedDiffer, Stop, Trip, simulate
from .pids import PIDSService
from .pos import FlakyTransport, GroundLedger, SyncAgent, Terminal


def banner(title: str) -> None:
    print("\n" + "=" * 72 + f"\n{title}\n" + "=" * 72)


def demo_pids() -> None:
    banner("1) Real-time feed -> events -> PIDS + automated announcements")
    trip = Trip("T-501", "Coastal Corridor", [
        Stop("CTR", "Central Terminal", 8 * 3600),
        Stop("HBR", "Harbor Junction", 8 * 3600 + 40 * 60),
        Stop("VAL", "Valley Springs", 9 * 3600 + 25 * 60, "2"),
        Stop("NTH", "North Point", 10 * 3600 + 10 * 60, "1"),
    ])
    bus = EventBus()
    pids = PIDSService(bus)
    ann = AnnouncementGenerator(bus)
    differ = FeedDiffer(bus, trip)
    for feed in simulate(trip, steps=12):
        differ.ingest(feed)
    ann.crew_override("Café car is now open in car 3.", ts=200.0)
    print(f"events published: {dict(Counter(e.topic for e in bus.log))}")
    print("\n".join(pids.render()))
    print(f"\nannouncement queue ({len(ann.queue)}; {ann.suppressed} rate-limited):")
    while (a := ann.next()) is not None:
        print(f"  [p{a.priority}] {a.text['en']}")
        if "es" in a.text:
            print(f"        {a.text['es']}")


def demo_backhaul() -> None:
    banner("2) Multi-link backhaul selection over a 300 km corridor (cell-a outage km 60-110)")
    sel = LinkSelector(default_links())
    tl = run_journey(sel, outage=("cell-a", 60, 110))
    for t, cls, old, new, why in sel.switches:
        km = next(k for tt, k, _ in tl if tt == t)
        print(f"  t={t:6.0f}s km={km:6.1f}  {cls:<9} {str(old):>9} -> {new:<9} ({why})")
    for cls in ("ops", "pos", "passenger"):
        share = Counter(p[cls] for _, _, p in tl)
        total = sum(share.values())
        print(f"  {cls:<9} time on link: " + ", ".join(f"{k} {v / total:.0%}" for k, v in share.most_common()))
    print(f"  ops standby (diverse bearer) at end: {sel.state['ops'].standby}")


def demo_pos() -> None:
    banner("3) Offline-first café POS: sell offline, lost ACKs, idempotent replay, loyalty")
    ledger = GroundLedger(inventory={"coffee": 100, "sandwich": 40})
    term = Terminal("cafe-car-3", local_stock={"coffee": 100, "sandwich": 40})
    transport = FlakyTransport(ledger, down=True)
    agent = SyncAgent(term, transport)
    sales = [term.sell([("coffee", 2, 350), ("sandwich", 1, 1095)], member_id="M-1001"),
             term.sell([("coffee", 1, 350)]),
             term.sell([("sandwich", 2, 1095)], member_id="M-2002")]
    term.refund(sales[1])
    print(f"  offline: {len(term.pending())} txns journaled, sync -> {agent.sync()}")
    transport.down, transport.drop_ack_every = False, 2
    rounds = 0
    while term.pending():
        rounds += 1
        print(f"  link up, sync round {rounds} -> {agent.sync()}")
    print(f"  ground ledger: {len(ledger.txns)} unique txns, revenue ${ledger.revenue_cents / 100:.2f}, "
          f"inventory {ledger.inventory}, loyalty {ledger.points}")


def main() -> None:
    demo_pids()
    demo_backhaul()
    demo_pos()
    print("\nReference prototype by Anthony Blow - not a production system.")


if __name__ == "__main__":
    main()
