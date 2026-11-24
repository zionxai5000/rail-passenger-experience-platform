"""Passenger Information Display System (PIDS) projection.

Keeps a per-stop, per-language display model that both onboard screens and
station signs render from. Display state is a pure projection of events, so
any screen can rebuild it after a reboot or link loss by replaying the log.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from .events import Event, EventBus


def fmt_clock(seconds: int) -> str:
    seconds %= 86400
    h, m = divmod(seconds // 60, 60)
    suffix = "AM" if h < 12 else "PM"
    return f"{(h % 12) or 12}:{m:02d} {suffix}"


@dataclass
class DisplayRow:
    stop_name: str
    status: str
    eta: str
    platform: str


@dataclass
class PIDSService:
    bus: EventBus
    rows: Dict[str, DisplayRow] = field(default_factory=dict)
    renders: int = 0

    def __post_init__(self) -> None:
        for t in ("trip.delay_changed", "trip.platform_changed", "trip.stop_skipped"):
            self.bus.subscribe(t, self.on_event)

    def on_event(self, e: Event) -> None:
        p = e.payload
        row = self.rows.get(p["stop_id"]) or DisplayRow(p["stop_name"], "On time", "--", p.get("platform", "--"))
        if e.topic == "trip.delay_changed":
            mins = round(p["delay_s"] / 60)
            row.status = "On time" if mins <= 1 else f"Delayed {mins} min"
            row.eta = fmt_clock(p["eta"])
        elif e.topic == "trip.platform_changed":
            row.platform = p["platform"]
            row.status = f"{row.status} | Track change"
        elif e.topic == "trip.stop_skipped":
            row.status = "Not stopping"
        self.rows[p["stop_id"]] = row
        self.renders += 1

    def render(self) -> List[str]:
        lines = [f"{'STOP':<22}{'STATUS':<30}{'ETA':<10}TRACK"]
        for r in self.rows.values():
            lines.append(f"{r.stop_name:<22}{r.status:<30}{r.eta:<10}{r.platform}")
        return lines
