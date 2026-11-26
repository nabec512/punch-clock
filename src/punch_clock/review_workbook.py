"""Write the supervisor review workbook.

Formulas are stored with their calculated results, so totals still show in
Protected View and in Outlook or phone previews.

A very hidden sheet records who each row is and the fixed figures its formulas were
built from, so that ``approved_hours`` can read the returned file and work the
approved hours out again rather than trust the totals in it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Optional

import xlsxwriter
from xlsxwriter.utility import xl_rowcol_to_cell

from punch_clock.assignments import ReviewGroup
from punch_clock import __version__
from punch_clock.hours import (
    BLOCK_MINUTES, MADE_UP_NOTE, OVERTIME_STARTS_MINUTES, clock_time, format_minutes, gap_minutes, week_full_minutes, week_hours,
)
from punch_clock.jibble_export import DayRecord, Employee, WeeklyExport

REVIEW_SHEET = "Review"
PUNCH_SHEET = "Punches"
DATA_SHEET = "Punch Clock data"
DATA_FORMAT = 1  # raise when the data sheet changes in a way an older reader would misread

EMPLOYEE, DATE, CLOCK_IN, CLOCK_OUT, GROSS, LUNCH, NET = (
    "Employee", "Date", "Clock in", "Clock out", "Gross", "Lunch deduction", "Net",
)
ADJUSTMENT, REGULAR, OVERTIME, TOTAL, COMMENT, NOTES = (
    "Adjustment (minutes)", "Regular hours", "Overtime hours", "Total approved hours", "Comment", "Notes",
)
REVIEWED = "Reviewed"  # a column before Notes in files made before it was dropped, which can still be read back
WEEK_TOTAL = "Week total"
INCOMPLETE = "Incomplete"

COLUMNS = [
    (EMPLOYEE, 34), (DATE, 12), (CLOCK_IN, 10), (CLOCK_OUT, 10), (GROSS, 11), (LUNCH, 11), (NET, 11),
    (ADJUSTMENT, 12), (REGULAR, 11), (OVERTIME, 11), (TOTAL, 14), (COMMENT, 30), (NOTES, 44),
]
COLUMN = {label: index for index, (label, _) in enumerate(COLUMNS)}

INSTRUCTIONS = [
    "Each employee starts with a shaded row with their name, then one row per day, then their Week total row. "
    "The purple cells in the Week total row are the employee's regular, overtime and total approved hours for the week.",
    "Only the yellow and orange cells can be changed.",
    "Hours are paid in 15-minute blocks, rounded down. Total approved hours = Regular hours + Overtime hours.",
    "Adjustment is in minutes, in steps of 15, added to the total approved hours: 15 adds 15 minutes, "
    "-15 removes 15 minutes, 0 means no change. If someone forgot to punch, add their time here, for example 300 for 5 hours.",
    "30 minutes of lunch is taken off every day worked, even if the employee also clocked out. "
    "If that's wrong, add the minutes back as an adjustment. Weekend hours have no lunch.",
    "Orange means the punches are incomplete: type the total approved hours as h:mm in 15-minute steps, for example 7:30.",
    "Hours follow the schedule: arriving early isn't paid, and arriving up to 5 minutes late counts as on time.",
    "Overtime is worked out for you, and starts 15 minutes past the employee's scheduled hours. "
    "All hours on a day off, such as the weekend, are overtime. An adjustment or typed hours change it too.",
    "If the week's regular hours come to less than the employee's scheduled week (at most 40:00), overtime makes up "
    "the difference first, so the Week total row can show more regular and less overtime than the days added up.",
    "When everyone is done, save this file and return it to accounting.",
]
HEADER_ROW = len(INSTRUCTIONS) + 2  # zero-based, below the title, week and instructions

# The data sheet: these labels, one per row, then a table with a row for each employee's day.
FORMAT, COMPANY, WEEK_START, REVIEW_GROUP, MADE_WITH = "Format", "Company", "Week start", "Review group", "Made with"
DATA_COLUMNS = (
    "Member code", "Name", "Department", "Date", "Review row", "Week total row", "Hours from punches",
    "Punches incomplete", "Paid minutes", "Scheduled minutes", "Week scheduled minutes",
)


@dataclass(frozen=True)
class _DayRow:
    """Where one employee's day was written, for the data sheet. Rows are numbered as Excel shows them."""

    employee: Employee
    record: DayRecord
    row: int
    week_row: int


def write_review_workbook(export: WeeklyExport, group: ReviewGroup, path: str | Path) -> None:
    workbook = xlsxwriter.Workbook(str(path), {"remove_timezone": True})
    workbook.set_properties({"title": f"Timesheet review - {group.title}", "author": "", "comments": ""})
    formats = _formats(workbook)
    days = _write_review_sheet(workbook, formats, export, group)
    _write_punch_sheet(workbook, formats, export, group)
    _write_data_sheet(workbook, export, group, days)
    workbook.close()


def _formats(workbook) -> dict:
    duration = {"num_format": "[h]:mm", "align": "right", "valign": "top"}
    total = {"bold": True, "bg_color": "#EDF2F4", "top": 1, "valign": "top"}
    edit = {"locked": False, "bg_color": "#FFF7CC", "border": 1, "border_color": "#D6C98A", "valign": "top"}
    make = workbook.add_format
    return {
        "title": make({"bold": True, "font_size": 14}),
        "note": make({"font_color": "#52616A"}),
        "header": make({"bold": True, "bg_color": "#183340", "font_color": "#FFFFFF", "text_wrap": True, "valign": "vcenter"}),
        "text": make({"valign": "top"}),
        "name": make({"valign": "top", "font_color": "#7A868C"}),
        "banner": make({"bold": True, "font_size": 12, "bg_color": "#C9DCE5", "top": 2, "top_color": "#183340", "valign": "vcenter"}),
        "notes": make({"valign": "top", "text_wrap": True, "indent": 1}),
        "wrap": make({"valign": "top", "text_wrap": True}),
        "date": make({"num_format": "ddd mmm d", "align": "left", "valign": "top"}),
        "time": make({"num_format": "hh:mm:ss", "align": "left", "valign": "top"}),
        "duration": make(duration),
        "overtime": make({**duration, "num_format": "[h]:mm;;"}),  # a day with none stays blank
        "overtime_marked": make({"bg_color": "#D9EAD3", "bold": True}),
        "muted": make({"valign": "top", "bg_color": "#F4F4F4"}),
        "edit_text": make({**edit, "text_wrap": True}),
        "edit_number": make({**edit, "num_format": "+0;-0;0", "align": "right"}),
        "edit_hours": make({**edit, "num_format": "[h]:mm", "align": "right", "bg_color": "#F8C98B"}),
        "total": make(total),
        "total_wrap": make({**total, "text_wrap": True, "indent": 1}),
        "total_duration": make({**total, **duration, "valign": "top"}),
        # The figures accounting looks for, in a color nothing else on the sheet uses.
        "week_hours": make({**total, **duration, "bg_color": "#E3D7F4", "border": 1, "border_color": "#7B5EA7", "top": 2}),
        "total_number": make({**total, "num_format": "+0;-0;0", "align": "right"}),
        "bad": make({"font_color": "#9C0006", "bg_color": "#FFC7CE"}),
    }


def _as_days(minutes: Optional[int]) -> Optional[float]:
    return None if minutes is None else minutes / 1440


def employee_label(employee: Employee) -> str:
    """The name and department, on every row so filtering by employee keeps their rows together."""
    return f"{employee.name} - {employee.department}" if employee.department else employee.name


def _clock(value) -> str:
    return "Missing" if value is None else clock_time(value)


def _day_notes(record: DayRecord) -> str:
    hours = record.hours
    notes = []
    if hours.gross is None:
        notes.append("Punches incomplete: enter the total approved hours.")
    elif not record.punches and record.schedule and hours.full_minutes == 0:
        notes.append("Day off. If they worked, add their time as an adjustment, for example 300 for 5 hours.")
    elif not record.punches:
        notes.append("No punches.")
    if hours.note:
        notes.append(hours.note)
    if hours.pay_note:
        notes.append(hours.pay_note)
    for out, back in hours.gaps:
        notes.append(f"Clocked out {_clock(out)} to {_clock(back)} ({format_minutes(gap_minutes(out, back))}), not counted in Gross.")
    if hours.gaps and hours.lunch:
        notes.append(f"{format_minutes(hours.lunch)} lunch also deducted.")
    if hours.lunch_capped:
        notes.append("Lunch capped at gross hours.")
    notes.extend(f'Jibble note: "{p.note}"' for p in record.punches if p.note)
    notes.extend(record.issues)
    return " ".join(dict.fromkeys(notes))


def _write_review_sheet(workbook, formats, export: WeeklyExport, group: ReviewGroup) -> list[_DayRow]:
    sheet = workbook.add_worksheet(REVIEW_SHEET)
    sheet.write(0, 0, f"{export.company or 'Weekly'} timesheet review: {group.title}", formats["title"])
    version = f"{export.period}  |  Punch Clock {__version__}"
    sheet.write(1, 0, f"{version}  |  {export.settings_note}" if export.settings_note else version, formats["note"])
    for index, line in enumerate(INSTRUCTIONS):
        sheet.write(2 + index, 0, line, formats["note"])
    for column, (label, width) in enumerate(COLUMNS):
        sheet.set_column(column, column, width)
        sheet.write(HEADER_ROW, column, label, formats["header"])
    sheet.set_row(HEADER_ROW, 32)

    row = HEADER_ROW + 1
    days: list[_DayRow] = []
    for index, employee in enumerate(group.employees):
        if index:
            row += 1  # an empty row between employees
        row = _write_employee(sheet, formats, export, employee, row, days)

    last = row - 1
    sheet.autofilter(HEADER_ROW, 0, max(last, HEADER_ROW), len(COLUMNS) - 1)
    # Only the names stay put when scrolling sideways. Freezing the top would hold the instructions on screen too.
    sheet.freeze_panes(0, 1)
    sheet.conditional_format(
        HEADER_ROW + 1, COLUMN[TOTAL], max(last, HEADER_ROW + 1), COLUMN[TOTAL],
        {"type": "cell", "criteria": "<", "value": 0, "format": formats["bad"]},
    )
    first_overtime = xl_rowcol_to_cell(HEADER_ROW + 1, COLUMN[OVERTIME])
    first_date = xl_rowcol_to_cell(HEADER_ROW + 1, COLUMN[DATE], col_abs=True)
    sheet.conditional_format(
        HEADER_ROW + 1, COLUMN[OVERTIME], max(last, HEADER_ROW + 1), COLUMN[OVERTIME],
        {"type": "formula", "criteria": f'=AND({first_date}<>"{WEEK_TOTAL}",ISNUMBER({first_overtime}),{first_overtime}>0)', "format": formats["overtime_marked"]},
    )
    sheet.protect("", {"autofilter": True, "format_columns": True, "format_rows": True})
    sheet.set_landscape()
    sheet.set_paper(1)  # Letter
    sheet.fit_to_pages(1, 0)
    sheet.repeat_rows(HEADER_ROW)
    sheet.set_footer("&CPage &P of &N")
    return days


def _write_employee(sheet, formats, export: WeeklyExport, employee: Employee, row: int, days: list[_DayRow]) -> int:
    # A name row heads each employee, so the bold Week total row isn't read as the heading of the next one.
    # It carries the same label as their other rows, so filtering by employee keeps it.
    sheet.set_row(row, 22)
    sheet.write(row, COLUMN[EMPLOYEE], employee_label(employee), formats["banner"])
    for column in range(1, len(COLUMNS)):
        sheet.write_blank(row, column, None, formats["banner"])
    row += 1
    first = row
    needs_hours: list[str] = []
    # Every day, so that a weekend shift with forgotten punches still has a row to enter it on.
    for day in export.dates:
        cell = _write_day(sheet, formats, employee, employee.days[day], row)
        if cell:
            needs_hours.append(cell)
        days.append(_DayRow(employee, employee.days[day], row + 1, first + len(export.dates) + 1))
        row += 1
    _write_week_total(sheet, formats, export, employee, first, row, needs_hours)
    return row + 1


def _write_day(sheet, formats, employee: Employee, record: DayRecord, row: int) -> Optional[str]:
    """Write one day. Returns the Total approved cell if someone must type the hours."""
    hours = record.hours
    net_cell = xl_rowcol_to_cell(row, COLUMN[NET])
    adjust_cell = xl_rowcol_to_cell(row, COLUMN[ADJUSTMENT])
    total_cell = xl_rowcol_to_cell(row, COLUMN[TOTAL])
    overtime_cell = xl_rowcol_to_cell(row, COLUMN[OVERTIME])
    # Each pair gets its own line, so a clock-in sits level with its clock-out.
    no_times = "-" if hours.gross is not None else "Missing"

    sheet.write(row, COLUMN[EMPLOYEE], employee_label(employee), formats["name"])
    sheet.write_datetime(row, COLUMN[DATE], datetime.combine(record.day, time()), formats["date"])
    sheet.write(row, COLUMN[CLOCK_IN], "\n".join(_clock(s.start) for s in hours.sessions) or no_times, formats["wrap"])
    sheet.write(row, COLUMN[CLOCK_OUT], "\n".join(_clock(s.end) for s in hours.sessions) or no_times, formats["wrap"])

    has_hours = bool(hours.sessions) and hours.gross is not None
    for label, value in ((GROSS, hours.gross), (LUNCH, hours.lunch), (NET, hours.net)):
        if has_hours:
            sheet.write_number(row, COLUMN[label], value / 1440, formats["duration"])
        else:
            sheet.write_blank(row, COLUMN[label], None, formats["duration"])

    sheet.write_blank(row, COLUMN[COMMENT], None, formats["edit_text"])
    # From the total, so a supervisor's adjustment or typed hours count. In whole minutes, as times are fractions of a day.
    sheet.write_formula(
        row,
        COLUMN[OVERTIME],
        f'=IF({total_cell}="","",IF(ROUND({total_cell}*1440,0)-{hours.full_minutes}>={OVERTIME_STARTS_MINUTES},'
        f"(ROUND({total_cell}*1440,0)-{hours.full_minutes})/1440,0))",
        formats["overtime"],
        hours.overtime / 1440 if has_hours else "",
    )
    sheet.write_formula(
        row,
        COLUMN[REGULAR],
        f'=IF({total_cell}="","",{total_cell}-{overtime_cell})',
        formats["duration"],
        hours.regular / 1440 if has_hours else "",
    )
    sheet.write(row, COLUMN[NOTES], _day_notes(record), formats["notes"])

    if hours.gross is None:
        sheet.write_blank(row, COLUMN[ADJUSTMENT], None, formats["muted"])
        sheet.write_blank(row, COLUMN[TOTAL], None, formats["edit_hours"])
        sheet.data_validation(
            row, COLUMN[TOTAL], row, COLUMN[TOTAL],
            {
                "validate": "custom",
                "value": (
                    f"=AND(ISNUMBER({total_cell}),{total_cell}>=0,{total_cell}<1,"
                    f"MOD(ROUND({total_cell}*1440,0),{BLOCK_MINUTES})=0)"
                ),
                "error_title": "Total approved hours",
                "error_message": "Type the hours as h:mm in 15-minute steps, for example 7:30 or 7:45.",
            },
        )
        return total_cell

    sheet.write_blank(row, COLUMN[ADJUSTMENT], None, formats["edit_number"])
    sheet.data_validation(
        row, COLUMN[ADJUSTMENT], row, COLUMN[ADJUSTMENT],
        {
            "validate": "custom",
            "value": (
                f"=AND(ISNUMBER({adjust_cell}),MOD({adjust_cell},{BLOCK_MINUTES})=0,ABS({adjust_cell})<=1440,"
                f"{hours.paid}+{adjust_cell}>=0)"
            ),
            "error_title": "Adjustment",
            "error_message": "Enter minutes in steps of 15, such as 15, 30 or -15. Total approved hours can't go below zero.",
        },
    )
    sheet.write_formula(
        row,
        COLUMN[TOTAL],
        # The schedule's rules set the starting point. A supervisor's adjustment then counts in full.
        f'=IF(AND({net_cell}="",{adjust_cell}=""),"",{hours.paid}/1440+N({adjust_cell})/1440)',
        formats["duration"],
        hours.paid / 1440 if has_hours else "",
    )
    return None


def _write_week_total(sheet, formats, export, employee: Employee, first: int, row: int, needs_hours: list[str]) -> None:
    days = [employee.days[d].hours for d in export.dates]
    complete = all(h.gross is not None for h in days)
    last = row - 1

    def column_range(label: str) -> str:
        return f"{xl_rowcol_to_cell(first, COLUMN[label])}:{xl_rowcol_to_cell(last, COLUMN[label])}"

    sheet.write(row, COLUMN[EMPLOYEE], employee_label(employee), formats["total"])
    sheet.write(row, COLUMN[DATE], WEEK_TOTAL, formats["total"])
    sheet.write_blank(row, COLUMN[CLOCK_IN], None, formats["total"])
    sheet.write_blank(row, COLUMN[CLOCK_OUT], None, formats["total"])
    for label, attribute in ((GROSS, "gross"), (LUNCH, "lunch"), (NET, "net")):
        if complete:
            total = sum(getattr(h, attribute) for h in days)
            sheet.write_formula(row, COLUMN[label], f"=SUM({column_range(label)})", formats["total_duration"], total / 1440)
        else:
            sheet.write(row, COLUMN[label], INCOMPLETE, formats["total_duration"])
    adjustments = column_range(ADJUSTMENT)
    sheet.write_formula(
        row, COLUMN[ADJUSTMENT], f'=IF(COUNT({adjustments})=0,"",SUM({adjustments}))', formats["total_number"], ""
    )
    blanks = "+".join(f"COUNTBLANK({cell})" for cell in needs_hours)
    week = week_hours(days)
    # Overtime first makes up any regular hours the week is short of. In whole minutes, as times are fractions of a day.
    regular = f"ROUND(SUM({column_range(REGULAR)})*1440,0)"
    overtime = f"ROUND(SUM({column_range(OVERTIME)})*1440,0)"
    made_up = f"MIN({overtime},MAX(0,{week.full_minutes}-{regular}))"
    totals = (
        (REGULAR, f"({regular}+{made_up})/1440", week.regular),
        (OVERTIME, f"({overtime}-{made_up})/1440", week.overtime),
        (TOTAL, f"SUM({column_range(TOTAL)})", week.paid),
    )
    for label, expression, minutes in totals:
        if needs_hours:
            formula, cached = f'=IF({blanks}>0,"Needs hours",{expression})', "Needs hours"
        else:
            formula, cached = f"={expression}", minutes / 1440
        sheet.write_formula(row, COLUMN[label], formula, formats["week_hours"], cached)
    sheet.write_blank(row, COLUMN[COMMENT], None, formats["edit_text"])
    # h:mm built by hand, as TEXT's duration codes differ between languages of Excel.
    shown = f'INT({made_up}/60)&":"&TEXT(MOD({made_up},60),"00")'
    note = f'IF({made_up}>0,{shown}&"{MADE_UP_NOTE.format(made_up="", full=format_minutes(week.full_minutes))}","")'
    if needs_hours:
        incomplete = "Some punches are incomplete. Enter their hours to work out these totals."
        sheet.write_formula(row, COLUMN[NOTES], f'=IF({blanks}>0,"{incomplete}",{note})', formats["total_wrap"], incomplete)
    else:
        cached = MADE_UP_NOTE.format(made_up=format_minutes(week.made_up), full=format_minutes(week.full_minutes))
        sheet.write_formula(row, COLUMN[NOTES], f"={note}", formats["total_wrap"], cached if week.made_up else "")


def _write_punch_sheet(workbook, formats, export: WeeklyExport, group: ReviewGroup) -> None:
    """The source punches for this group only, so supervisors see just their own staff."""
    sheet = workbook.add_worksheet(PUNCH_SHEET)
    labels = [(EMPLOYEE, 24), (DATE, 12), ("Type", 6), ("Time", 10), ("Jibble note", 40)]
    for column, (label, width) in enumerate(labels):
        sheet.set_column(column, column, width)
        sheet.write(0, column, label, formats["header"])
    row = 1
    for employee in group.employees:
        for day in export.dates:
            for punch in employee.days[day].punches:
                sheet.write(row, 0, employee.name, formats["text"])
                sheet.write_datetime(row, 1, datetime.combine(day, time()), formats["date"])
                sheet.write(row, 2, punch.kind, formats["text"])
                sheet.write_datetime(row, 3, punch.time, formats["time"])
                sheet.write(row, 4, punch.note, formats["text"])
                row += 1
    sheet.autofilter(0, 0, max(row - 1, 0), len(labels) - 1)
    sheet.freeze_panes(1, 0)
    sheet.protect("", {"autofilter": True, "format_columns": True})


def _write_data_sheet(workbook, export: WeeklyExport, group: ReviewGroup, days: list[_DayRow]) -> None:
    """Very hidden, so it doesn't show in Excel's list of hidden sheets either, and protected."""
    sheet = workbook.add_worksheet(DATA_SHEET)
    sheet.write(0, 0, "Punch Clock reads this sheet to check the approved hours. Don't change it.")
    about = ((FORMAT, DATA_FORMAT), (COMPANY, export.company), (WEEK_START, export.start.isoformat()),
             (REVIEW_GROUP, group.title), (MADE_WITH, __version__))
    for index, (label, value) in enumerate(about, start=1):
        sheet.write(index, 0, label)
        sheet.write(index, 1, value)
    header = len(about) + 2
    for column, label in enumerate(DATA_COLUMNS):
        sheet.write(header, column, label)
    # Dates are written as text, so nothing depends on how a program stores dates.
    for index, day in enumerate(days, start=header + 1):
        hours = day.record.hours
        week = [day.employee.days[d].hours for d in export.dates]
        values = (
            day.employee.code, day.employee.name, day.employee.department, day.record.day.isoformat(), day.row,
            day.week_row, int(bool(hours.sessions) and hours.gross is not None), int(hours.gross is None),
            hours.paid, hours.full_minutes, week_full_minutes(week),
        )
        for column, value in enumerate(values):
            if value is None:
                sheet.write_blank(index, column, None)
            elif isinstance(value, str):
                sheet.write_string(index, column, value)  # a name starting with = stays a name
            else:
                sheet.write(index, column, value)
    sheet.protect("")
    sheet.very_hidden()
