import random
import unittest

from rpx.backhaul import Link, LinkSample, LinkSelector, default_links, run_journey, score

UP = lambda tput=100, lat=50, loss=0.1: LinkSample(True, tput, lat, loss)
DOWN = LinkSample(False, 0, 9999, 100)


def links():
    return [Link("cell", "cellular", 2.0, [(0, 100)], 150, 45),
            Link("sat", "satellite", 4.0, [(0, 100)], 100, 40),
            Link("track", "trackside", 0.5, [(0, 100)], 400, 15)]


class BackhaulTests(unittest.TestCase):
    def test_down_link_scores_negative_infinity(self):
        self.assertEqual(score(DOWN, links()[0], "ops"), float("-inf"))

    def test_class_weights_differ(self):
        l = links()
        cheap_fast_lossy = UP(tput=200, loss=3.0)
        clean_slow = UP(tput=10, loss=0.0)
        # passenger favors throughput, pos favors low loss
        self.assertGreater(score(cheap_fast_lossy, l[2], "passenger"), score(clean_slow, l[1], "passenger"))
        self.assertGreater(score(clean_slow, l[1], "pos"), score(cheap_fast_lossy, l[2], "pos"))

    def test_fast_failover_ignores_dwell(self):
        sel = LinkSelector(links(), min_dwell_s=1e9)
        sel.decide(0, {"cell": UP(), "sat": UP(tput=50), "track": DOWN})
        first = sel.state["passenger"].primary
        samples = {"cell": UP(), "sat": UP(tput=50), "track": DOWN}
        samples[first] = DOWN
        sel.decide(10, samples)
        self.assertNotEqual(sel.state["passenger"].primary, first)
        self.assertEqual(sel.switches[-1][-1], "failover")

    def test_hysteresis_prevents_flapping(self):
        sel = LinkSelector(links(), min_dwell_s=0, hysteresis=0.5)
        sel.decide(0, {"cell": UP(tput=100), "sat": UP(tput=90), "track": DOWN})
        n = len(sel.switches)
        for t in range(1, 20):
            a, b = (100, 110) if t % 2 else (110, 100)
            sel.decide(t, {"cell": UP(tput=a), "sat": UP(tput=b), "track": DOWN})
        self.assertEqual(len(sel.switches), n)

    def test_ops_standby_uses_diverse_bearer(self):
        sel = LinkSelector(links())
        sel.decide(0, {"cell": UP(), "sat": UP(), "track": UP(tput=300, lat=15)})
        a = sel.state["ops"]
        bearer = {l.name: l.bearer for l in links()}
        self.assertIsNotNone(a.standby)
        self.assertNotEqual(bearer[a.primary], bearer[a.standby])

    def test_journey_always_connected_with_satellite_fallback(self):
        sel = LinkSelector(default_links())
        tl = run_journey(sel, outage=("cell-a", 60, 110))
        self.assertTrue(all(p["ops"] and p["pos"] and p["passenger"] for _, _, p in tl))
        for _, km, p in tl:
            if 60 <= km <= 110:
                self.assertNotEqual(p["ops"], "cell-a")

    def test_sample_outside_coverage_is_down(self):
        self.assertFalse(links()[0].sample(150, random.Random(0)).up)


if __name__ == "__main__":
    unittest.main()
