"""Reading the approved hours back from a returned review file. All values are fictional."""
from datetime import date, timedelta

import openpyxl
import pytest
from sample_export import COMPANY, Person, build_workbook, write_settings
from test_review_flow import Sheet, review_file

from punch_clock import settings
from punch_clock.approved_hours import read_approved_hours
from punch_clock.hours import week_hours
from punch_clock.jibble_export import UnsupportedExport
from punch_clock.reports import SOURCE_PREFIX, process_export
from punch_clock.review_workbook import ADJUSTMENT, COMMENT, DATA_SHEET, EMPLOYEE, NOTES, REVIEWED, TOTAL, WEEK_TOTAL

MONDAY = date(2026, 3, 2)
TUESDAY, SATURDAY = MONDAY + timedelta(days=1), MONDAY + timedelta(days=5)


def shift(day, start="08:00:00", end="16:30:00"):
    return [(day, "In", start, ""), (day, "Out", end, "")]


def crew():
    return [
        # A long Monday, a normal Tuesday, and Saturday hours, which are all overtime.
        Person("Ann Painter", "AP-1", "Paint", shift(0, end="17:30:00") + shift(1) + shift(5, "07:30:00", "12:30:00")),
        # Forgot to clock out on Tuesday, so the supervisor types the hours.
        Person("Cal Painter", "CP-1", "Paint", shift(0) + [(1, "In", "08:00:00", "")]),
        Person("Dee Packer", "DP-1", "Packing", shift(2)),
    ]


@pytest.fixture
def result(tmp_path):
    weekend = {"Sat": {"start": "07:30", "end": "12:30"}}
    write_settings(
        settings.file_path(),
        {"Paint": "Bea Boss"},
        {"Paint": {"start": "08:00", "end": "16:30"}, "Packing": {"start": "08:00", "end": "16:30"}},
        weekend=weekend,
    )
    source = tmp_path / "export.xlsx"
    build_workbook(crew()).save(source)
    return process_export(source)


def test_an_untouched_file_gives_the_hours_worked_out_from_the_punches(result):
    path = review_file(result, "Bea Boss")
    approved = read_approved_hours(path)
    assert (approved.company, approved.start, approved.end, approved.group) == (COMPANY, MONDAY, MONDAY + timedelta(days=6), "Bea Boss")
    assert [(e.code, e.name, e.department) for e in approved.employees] == [
        ("AP-1", "Ann Painter", "Paint"),
        ("CP-1", "Cal Painter", "Paint"),
    ]
    exported = {e.code: e for e in result.export.employees}
    for employee in approved.employees:
        days = [exported[employee.code].days[d].hours for d in result.export.dates]
        for read, made in zip(employee.days, days):
            assert (read.total, read.regular, read.overtime) == (made.paid, made.regular, made.overtime)
        week = week_hours(days)
        assert (employee.regular, employee.overtime, employee.total) == (week.regular, week.overtime, week.paid)
    ann = approved.employees[0]
    assert ann.total == 480 + 540 + 300 - 30 * 0  # paid by the schedule: 9:00 Monday, 8:00 Tuesday, 5:00 Saturday
    assert ann.days[5].overtime == 300 and ann.days[5].regular == 0
    # Cal's Tuesday has no hours yet, and that is all that's wrong with the file.
    assert approved.employees[1].days_without_hours == (TUESDAY,)
    assert approved.employees[1].total is None
    assert approved.problems == ("Cal Painter, Tue Mar 3: the punches are incomplete and no hours were typed in Total approved hours.",)


def test_adjustments_typed_hours_and_comments_count(result):
    path = review_file(result, "Bea Boss")
    sheet = Sheet(path)
    sheet.set("Ann Painter", MONDAY, ADJUSTMENT, -60).set("Ann Painter", MONDAY, COMMENT, "Left early, not on Jibble")
    sheet.set("Ann Painter", MONDAY + timedelta(days=3), ADJUSTMENT, 300)  # forgot to punch on Thursday
    sheet.set("Cal Painter", TUESDAY, TOTAL, 7.5 / 24)  # typed as 7:30
    sheet.set("Ann Painter", WEEK_TOTAL, COMMENT, "OK")
    sheet.save()  # openpyxl keeps no formula results, like a program that doesn't recalculate

    approved = read_approved_hours(path)
    assert approved.problems == ()
    ann, cal = approved.employees
    monday, thursday = ann.days[0], ann.days[3]
    assert (monday.total, monday.adjustment, monday.overtime, monday.comment) == (480, -60, 0, "Left early, not on Jibble")
    assert (thursday.total, thursday.regular, thursday.overtime) == (300, 300, 0)
    assert ann.comment == "OK"
    assert ann.total == 480 + 480 + 300 + 300
    # Saturday's overtime first makes up the 2:30 the week is short of its scheduled 40:00, as in the file.
    assert (ann.regular, ann.overtime) == (1560, 0)
    tuesday = cal.days[1]
    assert (tuesday.total, tuesday.typed, cal.total) == (450, True, 480 + 450)


def test_a_file_made_with_the_reviewed_column_can_still_be_read(result):
    """Review files made before Reviewed was dropped have it before Notes. Whatever it says is ignored."""
    path = review_file(result, "Bea Boss")
    workbook = openpyxl.load_workbook(path)
    sheet = workbook["Review"]
    header = next(row[0].row for row in sheet.iter_rows() if row[0].value == EMPLOYEE)
    notes = next(cell.column for cell in sheet[header] if cell.value == NOTES)
    sheet.insert_cols(notes)
    sheet.cell(header, notes, REVIEWED)
    workbook.save(path)
    Sheet(path).set("Ann Painter", WEEK_TOTAL, REVIEWED, "Yes").set("Ann Painter", MONDAY, ADJUSTMENT, -60).save()
    approved = read_approved_hours(path)
    assert approved.employees[0].total == 480 + 540 + 300 - 60


def test_every_problem_in_the_file_is_listed_at_once(result):
    path = review_file(result, "Bea Boss")
    sheet = Sheet(path)
    sheet.set("Ann Painter", MONDAY, ADJUSTMENT, 7)
    sheet.set("Ann Painter", TUESDAY, ADJUSTMENT, "half an hour")
    sheet.set("Ann Painter", MONDAY + timedelta(days=2), ADJUSTMENT, -15)  # no hours that day to take off
    sheet.set("Cal Painter", TUESDAY, TOTAL, 7 / 24 + 20 / 1440)  # 7:20
    sheet.set("Cal Painter", TUESDAY, ADJUSTMENT, 30)
    sheet.save()
    problems = read_approved_hours(path).problems
    assert problems == (
        "Ann Painter, Mon Mar 2: the adjustment, 7, isn't in steps of 15 minutes.",
        "Ann Painter, Tue Mar 3: the adjustment, half an hour, isn't a number of minutes.",
        "Ann Painter, Wed Mar 4: the adjustment, -15, would take the approved hours below zero.",
        "Cal Painter, Tue Mar 3: there's an adjustment, but the punches are incomplete, so type the total approved hours instead.",
        "Cal Painter, Tue Mar 3: the typed hours, 7:20, aren't a length of time in 15-minute steps, such as 7:30.",
    )


def test_typed_text_that_isnt_hours_is_listed(result):
    path = review_file(result, "Bea Boss")
    Sheet(path).set("Cal Painter", TUESDAY, TOTAL, "all day").save()
    assert read_approved_hours(path).problems == (
        'Cal Painter, Tue Mar 3: the typed hours, "all day", aren\'t a length of time in 15-minute steps, such as 7:30.',
    )


def test_a_locked_cell_typed_over_is_caught_rather_than_paid(result):
    path = review_file(result, "Bea Boss")
    Sheet(path).set("Ann Painter", TUESDAY, TOTAL, 10 / 24).save()
    approved = read_approved_hours(path)
    assert (
        "Ann Painter, Tue Mar 3: Total approved hours shows 10:00, but the adjustments and the pay rules give 8:00. "
        "A locked cell may have been changed, or the file wasn't saved in Excel. Make changes with the Adjustment instead."
    ) in approved.problems
    assert approved.employees[0].days[1].total == 480  # the rules' figure is kept, never the typed-over one


def test_moved_or_renamed_rows_are_refused(result):
    path = review_file(result, "Bea Boss")
    Sheet(path).set("Ann Painter", TUESDAY, EMPLOYEE, "Someone Else - Paint").save()
    with pytest.raises(UnsupportedExport, match="the row for Ann Painter on Tue Mar 3 has moved"):
        read_approved_hours(path)


def test_files_that_arent_review_files_are_refused(result, tmp_path):
    with pytest.raises(UnsupportedExport, match="isn't a review file made by Punch Clock 0.11.0 or later"):
        read_approved_hours(result.folder / f"{SOURCE_PREFIX}{MONDAY}.xlsx")
    text = tmp_path / "notes.xlsx"
    text.write_text("not a workbook")
    with pytest.raises(UnsupportedExport, match="could not be opened"):
        read_approved_hours(text)


def test_a_file_from_an_older_version_without_the_data_sheet_is_refused(result):
    path = review_file(result, "Bea Boss")
    workbook = openpyxl.load_workbook(path)
    del workbook[DATA_SHEET]
    workbook.save(path)
    with pytest.raises(UnsupportedExport, match="isn't a review file made by Punch Clock 0.11.0 or later"):
        read_approved_hours(path)


def test_a_file_from_a_newer_version_asks_for_the_update(result):
    path = review_file(result, "Bea Boss")
    workbook = openpyxl.load_workbook(path)
    data = workbook[DATA_SHEET]
    row = next(r for r in data.iter_rows() if r[0].value == "Format")
    row[1].value = 99
    workbook.save(path)
    with pytest.raises(UnsupportedExport, match="made by a newer version of Punch Clock"):
        read_approved_hours(path)


def test_the_missing_supervisor_file_is_read_too(result):
    approved = read_approved_hours(review_file(result, "Missing supervisor"))
    assert approved.group == "Missing supervisor"
    assert [(e.code, e.total) for e in approved.employees] == [("DP-1", 480)]
    assert approved.problems == ()
