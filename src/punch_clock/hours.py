"""Hours rules: pair punches into sessions and work out gross, lunch and net.

All durations are whole minutes. ``None`` means "unavailable until reviewed" and
is never treated as zero.

Punches are paired by time, not by their In/Out labels. Each punch simply flips the
clock, so one forgotten punch swaps the labels on every later punch until another one
is missed. No shift crosses midnight, so each day can be judged on its own.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Iterable, Optional

LUNCH_MINUTES = 30  # unpaid lunch per worked day, even if the employee also clocked out; none on weekend hours
FULL_DAY_MINUTES = 480  # paid hours in a full day for anyone with no schedule
GRACE_MINUTES = 5  # arriving this late still counts as arriving on time
OVERTIME_STARTS_MINUTES = 15  # overtime counts once a day is this far over its paid hours, then from those hours
BLOCK_MINUTES = 15  # paid hours go in blocks this long, always rounded down
WEEK_MINUTES = 2400  # most regular hours in a week; overtime first makes up any shortfall up to here
DOUBLE_PUNCH_SECONDS = 300  # punching again this soon is someone fixing a forgotten punch
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SWAPPED_NOTE = "In and Out were swapped, probably after a forgotten punch. Hours use the times in order."
MADE_UP_NOTE = "{made_up} of overtime counted as regular hours, to bring the week up to its scheduled {full}."
DOUBLE_PUNCH_NOTE ="Two punches moments apart were counted as one, probably someone fixing a forgotten punch."


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
class Schedule:
    start: time
    end: time
    days: frozenset[int] = frozenset()  # weekdays worked, where Monday is 0
    lunch: int = LUNCH_MINUTES
    # Hours on days off, by weekday: no lunch, and all of it is overtime.
    weekend: tuple[tuple[int, "Schedule"], ...] = ()

    @property
    def full_minutes(self) -> int:
        """Paid hours in a scheduled day: the time at work, less lunch."""
        span = datetime.combine(datetime.min, self.end) - datetime.combine(datetime.min, self.start)
        return int(span.total_seconds()) // 60 - self.lunch

    @property
    def label(self) -> str:
        return f"{clock_time(self.start)} to {clock_time(self.end)}"

    def weekend_for(self, weekday: int) -> Optional["Schedule"]:
        """The hours for this weekday when it's a day off on this schedule, if any are set."""
        return None if weekday in self.days else dict(self.weekend).get(weekday)

    @property
    def days_off_label(self) -> str:
        return ", ".join(f"{DAY_NAMES[day]} {hours.label}" for day, hours in self.weekend if day not in self.days)


@dataclass(frozen=True)
class DayHours:
    sessions: tuple[Session, ...]
    gross: Optional[int]
    lunch: Optional[int]
    net: Optional[int]
    note: str = ""  # why these hours may not match the punch labels
    paid: Optional[int] = None  # net hours after the schedule's rules, in whole blocks: regular plus overtime
    full_minutes: int = FULL_DAY_MINUTES  # overtime is measured from here; zero on a day off
    pay_note: str = ""  # why paid may differ from net
    lunch_capped: bool = False  # less was worked than the lunch, so only that much was deducted

    @property
    def gaps(self) -> list[tuple[datetime, datetime]]:
        return clocked_out_gaps(self.sessions)

    @property
    def overtime(self) -> Optional[int]:
        return None if self.paid is None else overtime_minutes(self.paid, self.full_minutes)

    @property
    def regular(self) -> Optional[int]:
        return None if self.paid is None else self.paid - self.overtime


@dataclass(frozen=True)
class WeekHours:
    """A week's totals, where overtime first makes up any regular hours short of the scheduled week."""

    regular: Optional[int]
    overtime: Optional[int]
    paid: Optional[int]
    made_up: Optional[int]  # overtime counted as regular hours instead
    full_minutes: int  # the scheduled week's regular hours


def week_full_minutes(days: Iterable[DayHours]) -> int:
    """The employee's own scheduled week, but never over 40 hours, as with no schedule every day counts as full."""
    return min(WEEK_MINUTES, sum(day.full_minutes for day in days))


def week_hours(days: Iterable[DayHours]) -> WeekHours:
    days = list(days)
    full = week_full_minutes(days)
    regular = weekly_total(day.regular for day in days)
    overtime = weekly_total(day.overtime for day in days)
    if regular is None or overtime is None:
        return WeekHours(None, None, None, None, full)
    made_up = made_up_minutes(regular, overtime, full)
    return WeekHours(regular + made_up, overtime - made_up, regular + overtime, made_up, full)


def made_up_minutes(regular: int, overtime: int, full_minutes: int) -> int:
    """Overtime moved to regular hours, so a short day elsewhere in the week doesn't leave the week short."""
    return min(overtime, max(0, full_minutes - regular))


def overtime_minutes(paid: int, full_minutes: int) -> int:
    over = paid - full_minutes
    return round_down_to_block(over) if over >= OVERTIME_STARTS_MINUTES else 0


def round_down_to_block(minutes: int) -> int:
    return minutes // BLOCK_MINUTES * BLOCK_MINUTES


def clock_time(value: time | datetime) -> str:
    return value.strftime("%I:%M %p").lstrip("0")


def round_to_minutes(seconds: int) -> int:
    return (seconds + 30) // 60


def format_minutes(minutes: Optional[int]) -> str:
    return "MISSING" if minutes is None else f"{minutes // 60}:{minutes % 60:02d}"


def weekly_total(values: Iterable[Optional[int]]) -> Optional[int]:
    """Sum durations, staying unavailable if any one of them is unavailable."""
    values = list(values)
    return None if any(v is None for v in values) else sum(values)


def _without_double_punch(times: list[datetime]) -> list[datetime]:
    """With an odd count, two punches moments apart are someone fixing a forgotten punch.

    The earlier one is when they really arrived or left, so the later one is dropped.
    """
    if len(times) % 2:
        for index, (earlier, later) in enumerate(zip(times, times[1:])):
            if (later - earlier).total_seconds() <= DOUBLE_PUNCH_SECONDS:
                return times[: index + 1] + times[index + 2 :]
    return times


def pair_punches(punches: Iterable[Punch]) -> tuple[list[Session], list[str]]:
    """Pair a day's punches in time order, returning the sessions and any problems."""
    times = _without_double_punch(sorted(p.time for p in punches))
    sessions = [Session(start, end) for start, end in zip(times[::2], times[1::2])]
    problems: list[str] = []
    if any(session.start == session.end for session in sessions):
        problems.append("Two punches have the same time.")
    if len(times) % 2:
        sessions.append(Session(times[-1], None))
        if len(times) == 1:
            problems.append("Only one punch: it could be the start or the end of the shift.")
        else:
            problems.append("A punch is missing.")
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


def _note(punches: list[Punch], sessions: list[Session]) -> str:
    if not sessions:
        return ""
    if len(sessions) * 2 < len(punches):
        return DOUBLE_PUNCH_NOTE
    return SWAPPED_NOTE if min(punches, key=lambda p: p.time).kind == "Out" else ""


def _paid_by_schedule(sessions: list[Session], schedule: Schedule) -> int:
    """Time before the start isn't paid, and neither is lingering just past the end."""
    first = sessions[0].start
    start = datetime.combine(first.date(), schedule.start)
    on_time = first.replace(second=0) <= start + timedelta(minutes=GRACE_MINUTES)
    seconds = 0
    for index, session in enumerate(sessions):
        # An on-time arrival counts from the start, even if the punch was a few minutes after it.
        begin = start if on_time and index == 0 else max(session.start, start if on_time else first)
        seconds += max(0, int((session.end - begin).total_seconds()))
    worked = round_to_minutes(seconds)
    paid = worked - min(schedule.lunch, worked)
    full = schedule.full_minutes
    # Checked before rounding, so that 14:59 past the end of the day stays unpaid.
    past_the_end = seconds - (full + schedule.lunch) * 60
    return full if 0 < past_the_end < OVERTIME_STARTS_MINUTES * 60 else paid


def calculate_day(
    punches: Iterable[Punch],
    has_source_row: bool = True,
    schedule: Optional[Schedule] = None,
    day_off: bool = False,
    weekend: Optional[Schedule] = None,
) -> DayHours:
    """``weekend`` is the hours for this day when it's a day off, if the settings give any."""
    punches = list(punches)
    sessions, problems = pair_punches(punches)
    weekend = weekend if day_off else None
    full = 0 if day_off else schedule.full_minutes if schedule else FULL_DAY_MINUTES
    if problems or not has_source_row:
        return DayHours(tuple(sessions), None, None, None, full_minutes=full)
    seconds = sum(int((s.end - s.start).total_seconds()) for s in sessions)
    gross = round_to_minutes(seconds)  # round the daily sum once, not each session
    lunch_rule = weekend.lunch if weekend else LUNCH_MINUTES
    lunch = min(lunch_rule, gross)  # net never goes below zero
    net = gross - lunch
    exact, pay_note = net, ""
    if sessions and weekend:
        exact = _paid_by_schedule(sessions, weekend)
        pay_note = (
            f"Day off: paid by the {sessions[0].start:%A} hours, {weekend.label}, with no lunch. All hours are overtime."
        )
    elif sessions and day_off:
        pay_note = "Day off on this schedule, so all hours are overtime."
    elif sessions and schedule:
        exact = _paid_by_schedule(sessions, schedule)
        if exact != net:
            pay_note = f"Paid by the schedule: {schedule.label}."
    elif sessions:
        pay_note = "No schedule for this department, so hours are paid as worked."
    # The schedule's full day is in whole blocks, so this splits evenly into regular and overtime.
    paid = round_down_to_block(exact)
    capped = bool(gross) and gross < lunch_rule
    return DayHours(tuple(sessions), gross, lunch, net, _note(punches, sessions), paid, full, pay_note, capped)
