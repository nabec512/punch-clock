"""Hours rules: pair punches into sessions and work out gross, lunch and net.

All durations are whole minutes. ``None`` means "unavailable until reviewed" and
is never treated as zero.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

LUNCH_MINUTES = 30  # unpaid lunch per worked day; clocked-out gaps count toward it


@dataclass(frozen=True)
class Punch:
    kind: str  # "In" or "Out"
    time: datetime
    note: str = ""
    row: int = 0  # source row in Raw Time Entries


@dataclass(frozen=True)
class Session:
    start: Optional[datetime]
    end: Optional[datetime]


@dataclass(frozen=True)
class DayHours:
    sessions: tuple[Session, ...]
    gross: Optional[int]
    lunch: Optional[int]
    net: Optional[int]

    @property
    def gaps(self) -> list[tuple[datetime, datetime]]:
        return clocked_out_gaps(self.sessions)

    @property
    def lunch_capped(self) -> bool:
        if not self.gross:
            return False
        return self.gross < LUNCH_MINUTES - gap_total(self.sessions)


def round_to_minutes(seconds: int) -> int:
    return (seconds + 30) // 60


def format_minutes(minutes: Optional[int]) -> str:
    return "MISSING" if minutes is None else f"{minutes // 60}:{minutes % 60:02d}"


def weekly_total(values: Iterable[Optional[int]]) -> Optional[int]:
    """Sum durations, staying unavailable if any one of them is unavailable."""
    values = list(values)
    return None if any(v is None for v in values) else sum(values)


def pair_punches(punches: Iterable[Punch]) -> tuple[list[Session], list[str]]:
    """Pair time-ordered punches, returning the sessions and any sequence problems."""
    sessions: list[Session] = []
    problems: list[str] = []
    opened: Optional[datetime] = None
    for punch in punches:
        if punch.kind == "In":
            if opened is not None:
                sessions.append(Session(opened, None))
                problems.append("Repeated clock-in without clock-out.")
            opened = punch.time
        elif opened is None:
            sessions.append(Session(None, punch.time))
            problems.append("Clock-out has no preceding clock-in.")
        else:
            sessions.append(Session(opened, punch.time))
            if punch.time <= opened:
                problems.append("Clock-out is not after clock-in.")
            opened = None
    if opened is not None:
        sessions.append(Session(opened, None))
        problems.append("Final clock-out is missing.")
    return sessions, problems


def clocked_out_gaps(sessions: Iterable[Session]) -> list[tuple[datetime, datetime]]:
    sessions = list(sessions)
    return [
        (earlier.end, later.start)
        for earlier, later in zip(sessions, sessions[1:])
        if earlier.end and later.start and later.start > earlier.end
    ]


def gap_minutes(out: datetime, back: datetime) -> int:
    return round_to_minutes(int((back - out).total_seconds()))


def gap_total(sessions: Iterable[Session]) -> int:
    """Add the day's gaps exactly, then round once, as with gross."""
    return round_to_minutes(
        sum(int((back - out).total_seconds()) for out, back in clocked_out_gaps(sessions))
    )


def calculate_day(punches: Iterable[Punch], has_source_row: bool = True) -> DayHours:
    sessions, problems = pair_punches(punches)
    if problems or not has_source_row:
        return DayHours(tuple(sessions), None, None, None)
    seconds = sum(int((s.end - s.start).total_seconds()) for s in sessions)
    gross = round_to_minutes(seconds)  # round the daily sum once, not each session
    lunch = min(max(0, LUNCH_MINUTES - gap_total(sessions)), gross) if seconds else 0
    return DayHours(tuple(sessions), gross, lunch, gross - lunch)
