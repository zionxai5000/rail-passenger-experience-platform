import unittest

from rpx.pos import FlakyTransport, GroundLedger, SyncAgent, Terminal


def setup(down=False, drop=0):
    ledger = GroundLedger(inventory={"coffee": 10, "snack": 10})
    term = Terminal("t1", local_stock={"coffee": 10, "snack": 10})
    tr = FlakyTransport(ledger, down=down, drop_ack_every=drop)
    return ledger, term, tr, SyncAgent(term, tr)


def drain(agent, limit=50):
    for _ in range(limit):
        if not agent.terminal.pending():
            return
        agent.sync()
    raise AssertionError("did not drain")


class POSTests(unittest.TestCase):
    def test_sells_offline_and_defers(self):
        ledger, term, tr, agent = setup(down=True)
        term.sell([("coffee", 1, 300)])
        self.assertEqual(agent.sync()["deferred"], 1)
        self.assertEqual(ledger.txns, {})
        self.assertEqual(term.local_stock["coffee"], 9)

    def test_lost_acks_do_not_double_apply(self):
        ledger, term, tr, agent = setup(drop=2)
        for _ in range(5):
            term.sell([("coffee", 1, 300)], member_id="M1")
        drain(agent)
        self.assertEqual(len(ledger.txns), 5)
        self.assertEqual(ledger.inventory["coffee"], 5)
        self.assertEqual(ledger.revenue_cents, 1500)
        self.assertEqual(ledger.points["M1"], 5 * 3 * 2)
        self.assertGreater(tr.calls, 5)  # retries happened

    def test_replaying_whole_journal_is_idempotent(self):
        ledger, term, _, agent = setup()
        term.sell([("snack", 2, 250)], member_id="M2")
        drain(agent)
        before = (dict(ledger.inventory), dict(ledger.points), ledger.revenue_cents)
        for t in term.journal:
            self.assertEqual(ledger.apply(t), "duplicate")
        self.assertEqual(before, (dict(ledger.inventory), dict(ledger.points), ledger.revenue_cents))

    def test_refund_reverses_inventory_revenue_and_points(self):
        ledger, term, _, agent = setup()
        sale = term.sell([("coffee", 2, 500)], member_id="M3")
        term.refund(sale)
        drain(agent)
        self.assertEqual(ledger.inventory["coffee"], 10)
        self.assertEqual(ledger.revenue_cents, 0)
        self.assertEqual(ledger.points["M3"], 0)

    def test_refund_of_unknown_original_rejected(self):
        ledger, term, _, _ = setup()
        sale = term.sell([("coffee", 1, 300)])
        refund = term.refund(sale)
        self.assertEqual(ledger.apply(refund), "rejected:unknown_original")

    def test_out_of_stock_blocked_locally(self):
        _, term, _, _ = setup()
        with self.assertRaises(ValueError):
            term.sell([("coffee", 11, 300)])

    def test_order_preserved(self):
        ledger, term, _, agent = setup(drop=3)
        keys = [term.sell([("coffee", 1, 100)]).key for _ in range(4)]
        drain(agent)
        self.assertEqual(list(ledger.txns), keys)


if __name__ == "__main__":
    unittest.main()
