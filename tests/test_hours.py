from datetime import datetime, time

import pytest

from punch_clock.hours import (
    DOUBLE_PUNCH_NOTE,
    SWAPPED_NOTE,
    Punch,
    Schedule,
    calculate_day,
    format_minutes,
    pair_punches,
    weekly_total,
)

DAY_SHIFT = Schedule(time(8, 0), time(16, 30), frozenset(range(5)))
LONG_SHIFT = Schedule(time(7, 0), time(17, 30), frozenset(range(4)))


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
        (day((9, 0, 0)), "Only one punch"),
        (day((9, 0, 0), kinds=["Out"]), "Only one punch"),
        (day((9, 0, 0), (10, 0, 0), (17, 0, 0)), "A punch is missing"),
        (day((9, 0, 0), (9, 0, 0)), "same time"),
    ],
)
def test_invalid_sequences_leave_hours_unavailable(punches, problem):
    assert problem in " ".join(pair_punches(punches)[1])
    hours = calculate_day(punches)
    assert (hours.gross, hours.lunch, hours.net) == (None, None, None)


@pytest.mark.parametrize(
    "kinds",
    [["In", "Out"], ["Out", "In"], ["In", "In"], ["Out", "Out"]],
)
def test_two_punches_are_a_shift_whatever_their_labels_say(kinds):
    hours = calculate_day(day((8, 0, 0), (16, 30, 0), kinds=kinds))
    assert (hours.gross, hours.lunch, hours.net) == (510, 30, 480)


def test_swapped_labels_are_noted_but_normal_ones_are_not():
    assert calculate_day(day((8, 0, 0), (16, 30, 0), kinds=["Out", "In"])).note == SWAPPED_NOTE
    assert calculate_day(day((8, 0, 0), (16, 30, 0))).note == ""
    assert calculate_day([]).note == ""


def test_a_swapped_day_with_a_mid_day_clock_out_pairs_in_order():
    hours = calculate_day(day((8, 0, 0), (12, 0, 0), (13, 0, 0), (16, 0, 0), kinds=["Out", "In", "Out", "In"]))
    assert hours.gross == 420 and len(hours.sessions) == 2 and hours.note == SWAPPED_NOTE


def test_punching_again_to_fix_a_forgotten_punch_counts_as_one():
    hours = calculate_day(day((8, 0, 10), (8, 0, 20), (16, 30, 0), kinds=["Out", "In", "Out"]))
    assert hours.sessions[0].start == datetime(2026, 3, 2, 8, 0, 10)  # when they really arrived
    assert (hours.gross, hours.net) == (510, 480) and hours.note == DOUBLE_PUNCH_NOTE


def test_punching_again_at_the_end_of_the_day_keeps_the_real_departure():
    hours = calculate_day(day((8, 0, 0), (16, 30, 0), (16, 33, 0), kinds=["Out", "In", "Out"]))
    assert hours.sessions[0].end == datetime(2026, 3, 2, 16, 30) and hours.gross == 510


def test_three_punches_far_apart_still_need_a_person():
    hours = calculate_day(day((8, 0, 0), (12, 0, 0), (13, 0, 0)))
    assert hours.gross is None and hours.sessions[-1].end is None


def test_a_lone_punch_stays_unpaired_whatever_its_label():
    for kind in ("In", "Out"):
        hours = calculate_day(day((7, 30, 0), kinds=[kind]))
        assert hours.gross is None and hours.sessions[0].start == datetime(2026, 3, 2, 7, 30)


def test_missing_source_row_leaves_hours_unavailable():
    assert calculate_day([], has_source_row=False).gross is None


@pytest.mark.parametrize(
    "start, end, overtime",
    [
        pytest.param((8, 0, 0), (16, 30, 0), 0, id="a normal day: 8:30 there, 8:00 paid"),
        pytest.param((8, 0, 0), (16, 0, 0), 0, id="short day"),
        pytest.param((8, 0, 0), (16, 35, 0), 0, id="5 minutes over: grace period"),
        pytest.param((8, 0, 0), (16, 44, 0), 0, id="14 minutes over: paid, but not overtime yet"),
        pytest.param((8, 0, 0), (16, 45, 0), 15, id="15 minutes over: overtime starts, from 8:00"),
        pytest.param((8, 0, 0), (17, 0, 0), 30, id="30 minutes over"),
        pytest.param((7, 0, 0), (18, 0, 0), 150, id="long day"),
    ],
)
def test_overtime_is_anything_over_eight_paid_hours(start, end, overtime):
    assert calculate_day(day(start, end)).overtime == overtime


@pytest.mark.parametrize(
    "first, last, paid, overtime",
    [
        pytest.param((8, 0, 0), (16, 30, 0), 480, 0, id="on time"),
        pytest.param((7, 40, 0), (16, 30, 0), 480, 0, id="coffee before the buzzer isn't paid"),
        pytest.param((8, 5, 0), (16, 30, 0), 480, 0, id="5 minutes late is forgiven"),
        pytest.param((8, 5, 59), (16, 30, 0), 480, 0, id="still reads as 8:05"),
        pytest.param((8, 6, 0), (16, 30, 0), 474, 0, id="6 minutes late counts from the punch"),
        pytest.param((8, 0, 0), (16, 25, 0), 475, 0, id="no grace for leaving early"),
        pytest.param((8, 5, 0), (16, 25, 0), 475, 0, id="late forgiven, early departure not"),
        pytest.param((8, 0, 0), (16, 40, 0), 480, 0, id="lingering past the buzzer isn't paid"),
        pytest.param((8, 0, 0), (16, 44, 0), 480, 0, id="14 minutes past isn't paid"),
        pytest.param((8, 0, 0), (16, 44, 59), 480, 0, id="14:59 past isn't paid"),
        pytest.param((8, 0, 0), (16, 30, 30), 480, 0, id="seconds past aren't paid"),
        pytest.param((8, 0, 0), (16, 45, 0), 495, 15, id="15 minutes past is overtime"),
        pytest.param((8, 0, 0), (17, 0, 0), 510, 30, id="counted from the end of the day"),
        pytest.param((7, 40, 0), (16, 45, 0), 495, 15, id="coffee doesn't count toward overtime"),
    ],
)
def test_paid_hours_follow_the_schedule(first, last, paid, overtime):
    hours = calculate_day(day(first, last), schedule=DAY_SHIFT)
    assert (hours.paid, hours.overtime) == (paid, overtime)


def test_overtime_on_a_ten_hour_schedule_starts_past_ten_hours():
    assert calculate_day(day((7, 0, 0), (17, 30, 0)), schedule=LONG_SHIFT).paid == 600
    assert calculate_day(day((7, 0, 0), (17, 44, 0)), schedule=LONG_SHIFT).overtime == 0
    assert calculate_day(day((7, 0, 0), (17, 45, 0)), schedule=LONG_SHIFT).overtime == 15


def test_a_mid_day_clock_out_still_comes_off_paid_hours():
    hours = calculate_day(day((8, 0, 0), (11, 30, 0), (12, 30, 0), (16, 30, 0)), schedule=DAY_SHIFT)
    assert hours.gross == 450 and hours.paid == 420


def test_a_session_entirely_before_the_start_isnt_paid():
    hours = calculate_day(day((7, 30, 0), (7, 40, 0), (8, 0, 0), (16, 30, 0)), schedule=DAY_SHIFT)
    assert hours.paid == 480


def test_scheduled_hours_are_only_explained_when_they_change_the_pay():
    assert calculate_day(day((8, 0, 0), (16, 30, 0)), schedule=DAY_SHIFT).pay_note == ""
    assert "8:00 AM to 4:30 PM" in calculate_day(day((7, 40, 0), (16, 30, 0)), schedule=DAY_SHIFT).pay_note


def test_all_hours_on_a_day_off_are_overtime():
    hours = calculate_day(day((7, 0, 0), (11, 0, 0)), schedule=LONG_SHIFT, day_off=True)
    assert (hours.paid, hours.overtime) == (210, 210) and "Day off" in hours.pay_note


def test_no_schedule_pays_as_worked_and_says_so():
    hours = calculate_day(day((8, 0, 0), (17, 0, 0)))
    assert (hours.paid, hours.overtime) == (510, 30) and "No schedule" in hours.pay_note


def test_days_with_no_or_missing_hours():
    assert calculate_day([]).paid == 0
    assert calculate_day(day((8, 0, 0))).paid is None
    assert calculate_day(day((8, 0, 0)), schedule=DAY_SHIFT).overtime is None


def test_overtime_is_unavailable_when_the_hours_are():
    assert calculate_day(day((8, 0, 0))).overtime is None
    assert calculate_day([]).overtime == 0


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
