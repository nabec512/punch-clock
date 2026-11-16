from datetime import datetime, time

import pytest

from punch_clock.hours import (
    BLOCK_MINUTES,
    DOUBLE_PUNCH_NOTE,
    SWAPPED_NOTE,
    Punch,
    Schedule,
    calculate_day,
    format_minutes,
    pair_punches,
    week_hours,
    weekly_total,
)

DAY_SHIFT = Schedule(time(8, 0), time(16, 30), frozenset(range(5)))
LONG_SHIFT = Schedule(time(7, 0), time(17, 30), frozenset(range(4)))
SATURDAY = Schedule(time(7, 30), time(12, 30), lunch=0)
SUNDAY = Schedule(time(9, 0), time(13, 0), lunch=0)
WEEKEND_SHIFT = Schedule(time(8, 0), time(16, 30), frozenset(range(5)), weekend=((5, SATURDAY), (6, SUNDAY)))


def day(*times, kinds=None, date=(2026, 3, 2)):
    """Punches alternating In/Out by default; each time is (hour, minute, second). 2 March 2026 is a Monday."""
    kinds = kinds or ["In" if i % 2 == 0 else "Out" for i in range(len(times))]
    return [Punch(kind, datetime(*date, *time)) for kind, time in zip(kinds, times)]


SATURDAY_DATE, SUNDAY_DATE = (2026, 3, 7), (2026, 3, 8)


def weekend_day(first, last, date=SATURDAY_DATE):
    weekday = datetime(*date).weekday()
    return calculate_day(
        day(first, last, date=date), schedule=WEEKEND_SHIFT, day_off=True, weekend=WEEKEND_SHIFT.weekend_for(weekday)
    )


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
        pytest.param((8, 6, 0), (16, 30, 0), 465, 0, id="6 minutes late counts from the punch, then rounds down"),
        pytest.param((8, 0, 0), (16, 25, 0), 465, 0, id="no grace for leaving early"),
        pytest.param((8, 5, 0), (16, 25, 0), 465, 0, id="late forgiven, early departure not"),
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


# --- 15-minute blocks -----------------------------------------------------------


@pytest.mark.parametrize(
    "first, last, regular, overtime",
    [
        pytest.param((8, 6, 0), (16, 30, 0), 465, 0, id="7:54 rounds down to 7:45"),
        pytest.param((8, 5, 0), (16, 30, 0), 480, 0, id="5 minutes late is still on time"),
        pytest.param((8, 0, 0), (16, 44, 0), 480, 0, id="under 15 minutes past isn't paid"),
        pytest.param((8, 0, 0), (16, 52, 0), 480, 15, id="22 minutes over is 15 of overtime"),
        pytest.param((8, 0, 0), (16, 59, 0), 480, 15, id="29 minutes over is still 15"),
        pytest.param((8, 0, 0), (17, 0, 0), 480, 30, id="30 minutes over"),
        pytest.param((8, 6, 0), (16, 52, 0), 480, 15, id="late, then stayed: overtime is past the full day"),
    ],
)
def test_regular_and_overtime_go_in_blocks_against_the_schedule(first, last, regular, overtime):
    hours = calculate_day(day(first, last), schedule=DAY_SHIFT)
    assert (hours.regular, hours.overtime, hours.paid) == (regular, overtime, regular + overtime)


def test_overtime_on_a_ten_hour_schedule_is_measured_from_ten_hours():
    hours = calculate_day(day((7, 0, 0), (17, 52, 0)), schedule=LONG_SHIFT)
    assert (hours.regular, hours.overtime) == (600, 15)


def test_no_schedule_rounds_down_too():
    hours = calculate_day(day((8, 0, 0), (16, 44, 0)))  # 8:14 net
    assert (hours.regular, hours.overtime, hours.paid) == (480, 0, 480)


@pytest.mark.parametrize("first, last", [((8, 6, 0), (16, 30, 0)), ((7, 0, 0), (18, 7, 0)), ((9, 0, 0), (9, 50, 0))])
def test_paid_is_always_whole_blocks_and_regular_plus_overtime(first, last):
    for schedule in (None, DAY_SHIFT, LONG_SHIFT):
        hours = calculate_day(day(first, last), schedule=schedule)
        assert hours.paid % BLOCK_MINUTES == 0 and hours.regular + hours.overtime == hours.paid


def test_rounding_alone_adds_no_note():
    assert calculate_day(day((8, 0, 0), (16, 30, 0)), schedule=DAY_SHIFT).pay_note == ""


def test_missing_hours_have_no_regular_hours():
    assert calculate_day(day((8, 0, 0))).regular is None


# --- Weekend hours --------------------------------------------------------------


def test_weekend_hours_have_no_lunch_and_are_all_overtime():
    hours = weekend_day((7, 30, 0), (12, 30, 0))
    assert (hours.gross, hours.lunch, hours.net) == (300, 0, 300)
    assert (hours.regular, hours.overtime, hours.paid) == (0, 300, 300)
    assert "Saturday hours, 7:30 AM to 12:30 PM" in hours.pay_note and "overtime" in hours.pay_note


@pytest.mark.parametrize(
    "first, last, paid",
    [
        pytest.param((7, 25, 0), (12, 35, 0), 300, id="early and lingering aren't paid"),
        pytest.param((7, 35, 0), (12, 30, 0), 300, id="5 minutes late is on time"),
        pytest.param((7, 40, 0), (12, 30, 0), 285, id="10 minutes late rounds down"),
        pytest.param((7, 30, 0), (12, 52, 0), 315, id="staying 22 minutes more"),
    ],
)
def test_weekend_hours_follow_their_own_schedule(first, last, paid):
    hours = weekend_day(first, last)
    assert (hours.paid, hours.overtime) == (paid, paid)


def test_saturday_and_sunday_can_have_different_hours():
    assert weekend_day((7, 30, 0), (12, 30, 0), SUNDAY_DATE).paid == 210  # Sunday starts at 9:00, so 9:00 to 12:30
    assert "Sunday hours, 9:00 AM to 1:00 PM" in weekend_day((9, 0, 0), (13, 0, 0), SUNDAY_DATE).pay_note


def test_a_short_weekend_day_isnt_flagged_for_lunch():
    assert not weekend_day((7, 30, 0), (7, 50, 0)).lunch_capped
    assert calculate_day(day((7, 30, 0), (7, 50, 0)), schedule=DAY_SHIFT).lunch_capped


def test_weekend_hours_only_apply_on_a_day_off():
    assert WEEKEND_SHIFT.weekend_for(5) is SATURDAY
    assert Schedule(time(8), time(16, 30), frozenset(range(6)), weekend=((5, SATURDAY),)).weekend_for(5) is None


def test_a_day_off_without_weekend_hours_works_as_before():
    hours = calculate_day(day((7, 0, 0), (11, 0, 0)), schedule=DAY_SHIFT, day_off=True)
    assert (hours.lunch, hours.paid, hours.overtime) == (30, 210, 210)


# --- Week totals ----------------------------------------------------------------


def scheduled_week(*days_out, schedule=DAY_SHIFT):
    """A Monday-to-Sunday week starting 8:00 AM, with each day's clock-out as (hour, minute), or None for no punches."""
    week = []
    for index, out in enumerate(days_out + (None,) * (7 - len(days_out))):
        date = (2026, 3, 2 + index)
        punches = day((8, 0, 0), (*out, 0), date=date) if out else []
        week.append(calculate_day(punches, schedule=schedule, day_off=index not in schedule.days))
    return week


def test_overtime_makes_up_a_short_day_to_a_full_week():
    # Three 11-hour days, a 5-hour Thursday and a 9-hour Friday: 37:00 regular and 10:00 overtime.
    days = scheduled_week((19, 30), (19, 30), (19, 30), (13, 30), (17, 30))
    assert (sum(d.regular for d in days), sum(d.overtime for d in days)) == (2220, 600)
    week = week_hours(days)
    assert (week.regular, week.overtime, week.paid, week.made_up) == (2400, 420, 2820, 180)


def test_a_full_week_keeps_all_its_overtime():
    week = week_hours(scheduled_week((17, 0), (16, 30), (16, 30), (16, 30), (16, 30)))
    assert (week.regular, week.overtime, week.made_up) == (2400, 30, 0)


def test_overtime_short_of_the_gap_all_becomes_regular():
    week = week_hours(scheduled_week((17, 30), (16, 30), (12, 30)))
    assert (week.regular, week.overtime, week.paid, week.made_up) == (1260, 0, 1260, 60)


def test_weekend_overtime_also_makes_up_the_week():
    days = scheduled_week((16, 30), (16, 30), (16, 30), (16, 30), (12, 30))
    days[5] = weekend_day((7, 30, 0), (12, 30, 0))  # 5:00, all overtime on the day
    week = week_hours(days)
    assert (week.regular, week.overtime, week.made_up) == (2400, 60, 240)


def test_the_week_is_the_employees_own_schedule():
    four_tens = week_hours(scheduled_week((17, 30), (17, 30), (17, 30), (13, 0), schedule=LONG_SHIFT))
    assert (four_tens.full_minutes, four_tens.regular, four_tens.overtime) == (2400, 1890, 0)  # starting at 8:00, an hour late
    part_time = Schedule(time(8, 0), time(12, 0), frozenset(range(5)), lunch=0)
    assert week_hours(scheduled_week(schedule=part_time)).full_minutes == 1200


def test_with_no_schedule_the_week_is_40_hours_not_every_day():
    # Every day counts 8:00 as full, so Saturday's 4:00 is regular and the week is already past 40:00.
    outs = [(17, 0, 0)] * 5 + [(12, 30, 0)]
    week = week_hours(calculate_day(day((8, 0, 0), out, date=(2026, 3, 2 + i))) for i, out in enumerate(outs))
    assert (week.full_minutes, week.regular, week.overtime, week.made_up) == (2400, 2640, 150, 0)


def test_an_incomplete_week_has_no_totals():
    days = scheduled_week((19, 30))
    days[1] = calculate_day(day((8, 0, 0), date=(2026, 3, 3)), schedule=DAY_SHIFT)
    week = week_hours(days)
    assert (week.regular, week.overtime, week.paid, week.made_up) == (None, None, None, None)
