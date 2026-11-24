"""Automated announcement generator.

Turns domain events into templated, multilingual announcement scripts with a
priority. Emergency/crew PA always pre-empts automated messages; automated
messages are rate-limited per stop so passengers are not spammed.
Output text feeds a TTS engine and the PIDS ticker (ADA: audio + visual).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from .events import Event, EventBus

PRIORITY = {"emergency": 0, "crew": 1, "service_change": 2, "info": 3}

TEMPLATES = {
    "en": {
        "trip.delay_changed": "Attention passengers: we are now expected to arrive at {stop_name} "
                              "about {mins} minutes late. We apologize for the delay.",
        "trip.platform_changed": "Track change: at {stop_name}, this train will now arrive on track {platform}.",
        "trip.stop_skipped": "Service change: this train will not stop at {stop_name}.",
    },
    "es": {
        "trip.delay_changed": "Estimados pasajeros: llegaremos a {stop_name} con unos {mins} minutos de retraso. "
                              "Disculpe las molestias.",
        "trip.platform_changed": "Cambio de vía: en {stop_name}, este tren llegará por la vía {platform}.",
        "trip.stop_skipped": "Cambio de servicio: este tren no se detendrá en {stop_name}.",
    },
}


@dataclass(order=True)
class Announcement:
    priority: int
    ts: float
    topic: str = field(compare=False)
    text: Dict[str, str] = field(compare=False, default_factory=dict)


@dataclass
class AnnouncementGenerator:
    bus: EventBus
    languages: List[str] = field(default_factory=lambda: ["en", "es"])
    min_interval_s: float = 120.0
    queue: List[Announcement] = field(default_factory=list)
    _last_by_key: Dict[str, float] = field(default_factory=dict)
    suppressed: int = 0

    def __post_init__(self) -> None:
        for t in TEMPLATES["en"]:
            self.bus.subscribe(t, self.on_event)

    def on_event(self, e: Event) -> None:
        if e.topic == "trip.delay_changed":
            if not e.payload.get("is_next_stop", True):
                return  # downstream stops update PIDS only; audio is about the next stop
            if e.payload["delay_s"] < 300:
                return  # under 5 min: display only, no audio
            key = f"{e.topic}:{e.payload['trip_id']}"
        else:
            key = f"{e.topic}:{e.payload['stop_id']}"
        last = self._last_by_key.get(key)
        if last is not None and e.ts - last < self.min_interval_s:
            self.suppressed += 1
            return
        self._last_by_key[key] = e.ts
        ctx = dict(e.payload, mins=round(e.payload.get("delay_s", 0) / 60))
        text = {lang: TEMPLATES[lang][e.topic].format(**ctx) for lang in self.languages}
        self.queue.append(Announcement(PRIORITY["service_change"], e.ts, e.topic, text))
        self.queue.sort()

    def crew_override(self, text: str, ts: float, emergency: bool = False) -> None:
        pr = PRIORITY["emergency" if emergency else "crew"]
        self.queue.append(Announcement(pr, ts, "crew.pa", {"en": text}))
        self.queue.sort()

    def next(self) -> Announcement | None:
        return self.queue.pop(0) if self.queue else None
