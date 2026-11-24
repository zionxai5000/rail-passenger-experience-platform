import unittest

from rpx.announcements import AnnouncementGenerator, PRIORITY
from rpx.events import EventBus
from rpx.feed import FeedDiffer, Stop, Trip, simulate, trip_update
from rpx.pids import PIDSService, fmt_clock

TRIP = Trip("T1", "Test Line", [Stop("A", "Alpha", 8 * 3600), Stop("B", "Bravo", 9 * 3600, "2")])


def wire():
    bus = EventBus()
    return bus, PIDSService(bus), AnnouncementGenerator(bus), FeedDiffer(bus, TRIP)


class FeedTests(unittest.TestCase):
    def test_trip_update_shape_follows_gtfs_rt(self):
        f = trip_update(TRIP, {"A": 60}, {}, ts=1.0)
        stu = f["trip_update"]["stop_time_update"][0]
        self.assertEqual(f["header"]["gtfs_realtime_version"], "2.0")
        self.assertEqual(stu["arrival"]["delay"], 60)
        self.assertEqual(stu["arrival"]["time"], 8 * 3600 + 60)
        self.assertEqual(stu["schedule_relationship"], "SCHEDULED")

    def test_small_delay_changes_are_debounced(self):
        bus, _, _, d = wire()
        d.ingest(trip_update(TRIP, {"A": 60, "B": 60}, {}))
        self.assertEqual(bus.log, [])

    def test_delay_platform_and_skip_events(self):
        bus, _, _, d = wire()
        d.ingest(trip_update(TRIP, {}, {}))
        d.ingest(trip_update(TRIP, {"A": 600}, {"B": "4"}, skipped={"B"}, ts=30))
        topics = sorted(e.topic for e in bus.log)
        self.assertEqual(topics, ["trip.delay_changed", "trip.platform_changed", "trip.stop_skipped"])

    def test_simulation_is_deterministic(self):
        a = [f["trip_update"]["stop_time_update"][-1]["arrival"]["delay"] for f in simulate(TRIP, 10, seed=1)]
        b = [f["trip_update"]["stop_time_update"][-1]["arrival"]["delay"] for f in simulate(TRIP, 10, seed=1)]
        self.assertEqual(a, b)


class PIDSTests(unittest.TestCase):
    def test_display_projection(self):
        _, pids, _, d = wire()
        d.ingest(trip_update(TRIP, {}, {}))
        d.ingest(trip_update(TRIP, {"B": 900}, {"B": "5"}, ts=30))
        row = pids.rows["B"]
        self.assertTrue(row.status.startswith("Delayed 15 min"))
        self.assertIn("Track change", row.status)
        self.assertEqual(row.platform, "5")
        self.assertEqual(row.eta, "9:15 AM")

    def test_rebuild_by_replay(self):
        bus, pids, _, d = wire()
        d.ingest(trip_update(TRIP, {}, {}))
        d.ingest(trip_update(TRIP, {"A": 600, "B": 600}, {}, ts=30))
        fresh = PIDSService(EventBus())
        for e in bus.log:
            fresh.on_event(e)
        self.assertEqual(fresh.render(), pids.render())

    def test_clock(self):
        self.assertEqual(fmt_clock(0), "12:00 AM")
        self.assertEqual(fmt_clock(13 * 3600 + 5 * 60), "1:05 PM")


class AnnouncementTests(unittest.TestCase):
    def test_short_delay_is_display_only(self):
        _, _, ann, d = wire()
        d.ingest(trip_update(TRIP, {"A": 180, "B": 180}, {}))
        self.assertEqual(ann.queue, [])

    def test_bilingual_next_stop_only_and_rate_limited(self):
        _, _, ann, d = wire()
        d.ingest(trip_update(TRIP, {"A": 600, "B": 600}, {}, ts=0))
        self.assertEqual(len(ann.queue), 1)            # next stop only
        self.assertIn("Alpha", ann.queue[0].text["en"])
        self.assertIn("Alpha", ann.queue[0].text["es"])
        d.ingest(trip_update(TRIP, {"A": 900, "B": 900}, {}, ts=30))
        self.assertEqual(len(ann.queue), 1)
        self.assertEqual(ann.suppressed, 1)

    def test_emergency_preempts(self):
        _, _, ann, d = wire()
        d.ingest(trip_update(TRIP, {"A": 600}, {}, ts=0))
        ann.crew_override("Please remain seated.", ts=5, emergency=True)
        self.assertEqual(ann.next().priority, PRIORITY["emergency"])


if __name__ == "__main__":
    unittest.main()
