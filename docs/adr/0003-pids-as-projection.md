# ADR 0003: PIDS and announcements as projections of one event stream

- Status: Accepted (reference architecture)
- Author: Anthony Blow

## Context
Inconsistent information across app, station signs, onboard screens and audio erodes trust. Screens reboot; links drop.

## Decision
Every passenger information surface is a projection of the same trip events. Displays hold no hidden state: a rebooted screen replays the log and converges. Announcements are generated from the same events with rules (next-stop only, threshold for audio, per-trip rate limit) and a priority queue in which crew and emergency PA always pre-empt automation. Every automated message has a visual equivalent for accessibility.

## Consequences
- + One source of truth; consistent multilingual messaging; easy to audit.
- − Requires disciplined event contracts and template governance in a central CMS.

Prototype: `rpx/feed.py`, `rpx/pids.py`, `rpx/announcements.py`.
