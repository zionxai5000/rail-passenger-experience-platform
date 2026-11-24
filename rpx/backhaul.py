"""Onboard connectivity manager: multi-link backhaul selection and failover.

Models the policy engine that sits on the onboard router/edge gateway and
decides which WAN link(s) each traffic class uses as the train moves:

* links: two cellular carriers (LTE/5G), LEO satellite, trackside/wayside
  radio fed by corridor fiber
* traffic classes: ``ops`` (crew apps, telemetry, PIDS content), ``pos``
  (payments; tiny but must be reliable), ``passenger`` (bulk Wi-Fi; cost aware)

Design choices (see docs/adr/0002-backhaul-policy.md):
* score each healthy link per class from measured throughput/latency/loss and
  cost per GB, with class-specific weights
* hysteresis + minimum dwell time to avoid flapping at coverage edges
* fast failover: a down or badly lossy primary is replaced on the next probe
* ``ops`` gets a primary + standby on a *different* bearer type
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class LinkSample:
    up: bool
    throughput_mbps: float
    latency_ms: float
    loss_pct: float


@dataclass
class Link:
    name: str
    bearer: str              # cellular | satellite | trackside
    cost_per_gb: float
    coverage: List[Tuple[float, float]]  # (start_km, end_km) with service
    peak_mbps: float
    base_latency_ms: float

    def sample(self, km: float, rng: random.Random) -> LinkSample:
        covered = any(a <= km <= b for a, b in self.coverage)
        if not covered:
            return LinkSample(False, 0.0, 9999.0, 100.0)
        # fade toward the coverage edge
        edge = min(min(abs(km - a), abs(b - km)) for a, b in self.coverage if a <= km <= b)
        fade = min(1.0, edge / 5.0)
        tput = self.peak_mbps * (0.3 + 0.7 * fade) * rng.uniform(0.8, 1.0)
        lat = self.base_latency_ms * (1.0 + (1 - fade)) * rng.uniform(0.9, 1.2)
        loss = (1 - fade) * 3.0 * rng.uniform(0.5, 1.0)
        return LinkSample(True, tput, lat, loss)


WEIGHTS = {
    #            tput  latency loss  cost
    "ops":       (0.2,  0.3,   0.4,  0.1),
    "pos":       (0.05, 0.25,  0.6,  0.1),
    "passenger": (0.5,  0.1,   0.1,  0.3),
}


def score(s: LinkSample, link: Link, cls: str) -> float:
    if not s.up:
        return -math.inf
    wt, wl, wloss, wc = WEIGHTS[cls]
    t = min(1.0, s.throughput_mbps / 200.0)
    lat = 1.0 - min(1.0, s.latency_ms / 600.0)
    loss = 1.0 - min(1.0, s.loss_pct / 5.0)
    cost = 1.0 - min(1.0, link.cost_per_gb / 10.0)
    return wt * t + wl * lat + wloss * loss + wc * cost


@dataclass
class Assignment:
    primary: Optional[str]
    standby: Optional[str] = None


@dataclass
class LinkSelector:
    links: List[Link]
    hysteresis: float = 0.08          # challenger must beat incumbent by this
    min_dwell_s: float = 30.0
    state: Dict[str, Assignment] = field(default_factory=dict)
    _since: Dict[str, float] = field(default_factory=dict)
    _fails: Dict[str, int] = field(default_factory=dict)
    switches: List[Tuple[float, str, Optional[str], Optional[str], str]] = field(default_factory=list)

    def _healthy(self, samples: Dict[str, LinkSample]) -> Dict[str, LinkSample]:
        ok = {}
        for name, s in samples.items():
            self._fails[name] = 0 if s.up else self._fails.get(name, 0) + 1
            if s.up and s.loss_pct < 20:
                ok[name] = s
        return ok

    def decide(self, t: float, samples: Dict[str, LinkSample]) -> Dict[str, Assignment]:
        by_name = {l.name: l for l in self.links}
        healthy = self._healthy(samples)
        for cls in WEIGHTS:
            ranked = sorted(healthy, key=lambda n: score(healthy[n], by_name[n], cls), reverse=True)
            cur = self.state.get(cls, Assignment(None))
            best = ranked[0] if ranked else None
            new_primary = cur.primary
            reason = ""
            if cur.primary is None or cur.primary not in healthy:
                # fast failover: an unhealthy primary is replaced on this probe,
                # bypassing dwell time (dwell only damps "better link" moves)
                if best != cur.primary:
                    new_primary, reason = best, "failover" if cur.primary else "initial"
            elif best and best != cur.primary:
                gain = score(healthy[best], by_name[best], cls) - score(
                    healthy[cur.primary], by_name[cur.primary], cls)
                if gain > self.hysteresis and t - self._since.get(cls, -1e9) >= self.min_dwell_s:
                    new_primary, reason = best, f"better(+{gain:.2f})"
            standby = None
            if cls == "ops" and new_primary:
                pb = by_name[new_primary].bearer
                standby = next((n for n in ranked if by_name[n].bearer != pb), None)
            if new_primary != cur.primary:
                self.switches.append((t, cls, cur.primary, new_primary, reason))
                self._since[cls] = t
            self.state[cls] = Assignment(new_primary, standby)
        return self.state


def default_links() -> List[Link]:
    """A notional 300 km corridor: urban ends, a rural middle, a fiber-fed segment."""
    return [
        Link("cell-a", "cellular", 2.0, [(0, 120), (190, 300)], 150, 45),
        Link("cell-b", "cellular", 2.5, [(0, 90), (150, 300)], 120, 50),
        Link("leo-sat", "satellite", 4.0, [(0, 300)], 100, 40),
        Link("trackside", "trackside", 0.5, [(20, 70)], 400, 15),
    ]


def run_journey(selector: LinkSelector, km_total: float = 300, speed_kmh: float = 130,
                dt_s: float = 10, seed: int = 3, outage: Optional[Tuple[str, float, float]] = None):
    """Drive the selector over a journey. ``outage`` = (link, start_km, end_km)."""
    rng = random.Random(seed)
    by_name = {l.name: l for l in selector.links}
    t, km = 0.0, 0.0
    timeline = []
    while km <= km_total:
        samples = {n: l.sample(km, rng) for n, l in by_name.items()}
        if outage and outage[0] in samples and outage[1] <= km <= outage[2]:
            samples[outage[0]] = LinkSample(False, 0, 9999, 100)
        st = selector.decide(t, samples)
        timeline.append((t, km, {c: a.primary for c, a in st.items()}))
        t += dt_s
        km += speed_kmh * dt_s / 3600
    return timeline
