from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Event:
    tick: int
    event_type: str
    target: str
    value: float | None = None
