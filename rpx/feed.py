"""GTFS-realtime-style trip update simulator.

Produces TripUpdate-like dicts (trip_id, stop_time_update[] with arrival
delay) and turns material changes into domain events:

* ``trip.delay_changed`` - predicted delay at a stop moved by >= threshold
* ``trip.platform_changed`` - assigned track/platform changed
* ``trip.stop_skipped`` - SKIPPED schedule relationship

The structure mirrors the public GTFS-realtime spec (TripUpdate /
StopTimeUpdate / ScheduleRelationship) without requiring protobuf.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional

from .events import Event, EventBus


@dataclass
class Stop:
    stop_id: str
    name: str
    scheduled_arrival: int  # seconds since service-day start
    platform: str = "1"


@dataclass
class Trip:
    trip_id: str
    route_name: str
    stops: List[Stop]


def trip_update(trip: Trip, delays: Dict[str, int], platforms: Dict[str, str],
                skipped: Optional[set] = None, ts: float = 0.0, from_idx: int = 0) -> dict:
    """Build a TripUpdate. Stops before ``from_idx`` are already served and,
    as in GTFS-realtime practice, are omitted from the update."""
    skipped = skipped or set()
    return {
        "header": {"gtfs_realtime_version": "2.0", "timestamp": ts},
        "trip_update": {
            "trip": {"trip_id": trip.trip_id, "route_name": trip.route_name},
            "stop_time_update": [
                {
                    "stop_id": s.stop_id,
                    "arrival": {"delay": delays.get(s.stop_id, 0),
                                "time": s.scheduled_arrival + delays.get(s.stop_id, 0)},
                    "platform": platforms.get(s.stop_id, s.platform),
                    "schedule_relationship": "SKIPPED" if s.stop_id in skipped else "SCHEDULED",
                }
                for s in trip.stops[from_idx:]
            ],
        },
    }


@dataclass
class FeedDiffer:
    """Turns successive feed snapshots into change events (debounced)."""

    bus: EventBus
    trip: Trip
    delay_threshold_s: int = 120
    _last: Dict[str, dict] = field(default_factory=dict)

    def ingest(self, feed: dict) -> List[Event]:
        out: List[Event] = []
        ts = feed["header"]["timestamp"]
        names = {s.stop_id: s.name for s in self.trip.stops}
        for stu in feed["trip_update"]["stop_time_update"]:
            sid = stu["stop_id"]
            prev = self._last.get(sid)
            base = {"trip_id": self.trip.trip_id, "route_name": self.trip.route_name,
                    "stop_id": sid, "stop_name": names.get(sid, sid),
                    "platform": stu["platform"],
                    "is_next_stop": stu is feed["trip_update"]["stop_time_update"][0]}
            if stu["schedule_relationship"] == "SKIPPED" and (
                    prev is None or prev["schedule_relationship"] != "SKIPPED"):
                out.append(Event("trip.stop_skipped", dict(base), ts))
            delay = stu["arrival"]["delay"]
            prev_delay = prev["arrival"]["delay"] if prev else 0
            if abs(delay - prev_delay) >= self.delay_threshold_s:
                out.append(Event("trip.delay_changed",
                                 dict(base, delay_s=delay, previous_delay_s=prev_delay,
                                      eta=stu["arrival"]["time"]), ts))
            if prev is not None and stu["platform"] != prev["platform"]:
                out.append(Event("trip.platform_changed",
                                 dict(base, previous_platform=prev["platform"]), ts))
            self._last[sid] = stu
        for e in out:
            self.bus.publish(e)
        return out


def simulate(trip: Trip, steps: int, seed: int = 7) -> Iterator[dict]:
    """Random-walk delays that propagate down the line (deterministic by seed)."""
    rng = random.Random(seed)
    delay = 0
    platforms: Dict[str, str] = {}
    for i in range(steps):
        delay = max(0, delay + rng.choice([-60, 0, 0, 60, 180, 300]))
        delays = {s.stop_id: delay for s in trip.stops}
        if i == steps // 2:
            last = trip.stops[-1]
            platforms[last.stop_id] = str(int(last.platform) + 2)
        from_idx = min(i * len(trip.stops) // steps, len(trip.stops) - 1)
        yield trip_update(trip, delays, platforms, ts=float(i * 30), from_idx=from_idx)
