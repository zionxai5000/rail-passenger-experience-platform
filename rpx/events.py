"""Minimal in-process event bus.

On a real train this would be a lightweight broker on the onboard edge
server (e.g. MQTT/NATS); in the ground cloud a managed stream. The contract
(topic + immutable event dict) is what matters for the architecture.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List

Handler = Callable[["Event"], None]


@dataclass(frozen=True)
class Event:
    topic: str
    payload: Dict[str, Any]
    ts: float = 0.0


@dataclass
class EventBus:
    _subs: Dict[str, List[Handler]] = field(default_factory=lambda: defaultdict(list))
    log: List[Event] = field(default_factory=list)

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._subs[topic].append(handler)

    def publish(self, event: Event) -> None:
        self.log.append(event)
        for handler in list(self._subs.get(event.topic, [])) + list(self._subs.get("*", [])):
            handler(event)
