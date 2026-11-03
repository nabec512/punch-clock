from datetime import datetime

import pytest

from punch_clock.hours import Punch, calculate_day, format_minutes, pair_punches, weekly_total


def day(*times, kinds=None):
    """Punches alternating In/Out by default; each time is (hour, minute, second)."""
    kinds = kinds or ["In" if i % 2 == 0 else "Out" for i in range(len(times))]
    return [Punch(kind, datetime(2026, 3, 2, *time)) for kind, time in zip(kinds, times)]


def totals(*times):
    hours = calculate_day(day(*times))
    return hours.gross, hours.lunch, hours.net


@pytest.mark.parametrize(
    "times, expected",
    [
        pytest.param([(9, 0, 0), (17, 0, 0)], (480, 30, 450), id="no gap: full lunch"),
        pytest.param([(9, 0, 0), (12, 0, 0), (12, 30, 0), (17, 0, 0)], (450, 30, 420), id="30-minute gap: full lunch"),
        pytest.param([(9, 0, 0), (12, 0, 0), (12, 20, 0), (17, 0, 0)], (460, 30, 430), id="20-minute gap: full lunch"),
        pytest.param([(9, 0, 0), (12, 0, 0), (12, 45, 0), (17, 0, 0)], (435, 30, 405), id="45-minute gap: full lunch"),
        pytest.param(
            [(9, 0, 0), (11, 0, 0), (11, 20, 0), (13, 0, 0), (13, 20, 0), (17, 0, 0)],
            (440, 30, 410),
            id="several gaps: one lunch",
        ),
        pytest.param([(9, 0, 0), (9, 30, 0)], (30, 30, 0), id="shift as long as lunch"),
        pytest.param([(9, 0, 0), (9, 10, 0)], (10, 10, 0), id="short shift: capped at gross"),
        pytest.param([(9, 0, 0), (9, 10, 0), (9, 15, 0), (9, 20, 0)], (15, 15, 0), id="short shift with gap: capped"),
    ],
)
def test_gross_lunch_net(times, expected):
    assert totals(*times) == expected


def test_daily_gross_is_rounded_once_not_per_session():
    # 1:00:20 + 1:00:20 = 2:00:40 rounds to 2:01; rounding each session would give 2:00.
    assert totals((9, 0, 0), (10, 0, 20), (11, 0, 0), (12, 0, 20))[0] == 121


def test_no_punches_is_zero_with_no_lunch():
    hours = calculate_day([])
    assert (hours.sessions, hours.gross, hours.lunch, hours.net) == ((), 0, 0, 0)


@pytest.mark.parametrize(
    "punches, problem",
    [
        (day((9, 0, 0)), "Final clock-out is missing."),
        (day((9, 0, 0), kinds=["Out"]), "Clock-out has no preceding clock-in."),
        (day((9, 0, 0), (10, 0, 0), kinds=["In", "In"]), "Repeated clock-in without clock-out."),
        (day((9, 0, 0), (9, 0, 0)), "Clock-out is not after clock-in."),
    ],
)
def test_invalid_sequences_leave_hours_unavailable(punches, problem):
    assert problem in pair_punches(punches)[1]
    hours = calculate_day(punches)
    assert (hours.gross, hours.lunch, hours.net) == (None, None, None)


def test_missing_source_row_leaves_hours_unavailable():
    assert calculate_day([], has_source_row=False).gross is None


def test_lunch_capped_flag():
    assert calculate_day(day((9, 0, 0), (9, 10, 0))).lunch_capped
    assert calculate_day(day((9, 0, 0), (9, 10, 0), (9, 15, 0), (9, 20, 0))).lunch_capped
    assert not calculate_day(day((9, 0, 0), (9, 30, 0))).lunch_capped
    assert not calculate_day(day((9, 0, 0), (17, 0, 0))).lunch_capped
    assert not calculate_day([]).lunch_capped


def test_unavailable_stays_unavailable_in_weekly_totals():
    assert weekly_total([60, 30]) == 90
    assert weekly_total([60, None]) is None


def test_format_minutes():
    assert format_minutes(232) == "3:52"
    assert format_minutes(5) == "0:05"
    assert format_minutes(None) == "MISSING"
