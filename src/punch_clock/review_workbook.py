"""Write the supervisor review workbook.

Formulas are stored with their calculated results, so totals still show in
Protected View and in Outlook or phone previews.
"""
from __future__ import annotations

from datetime import datetime, time
from pathlib import Path
from typing import Optional

import xlsxwriter
from xlsxwriter.utility import xl_rowcol_to_cell

from punch_clock.assignments import ReviewGroup
from punch_clock.hours import format_minutes, gap_minutes
from punch_clock.jibble_export import OVERTIME, DayRecord, Employee, WeeklyExport

REVIEW_SHEET = "Review"
PUNCH_SHEET = "Punches"

EMPLOYEE, DATE, CLOCK_IN, CLOCK_OUT, GROSS, LUNCH, NET = (
    "Employee", "Date", "Clock in", "Clock out", "Gross", "Lunch deduction", "Net",
)
ADJUSTMENT, APPROVED, COMMENT, REVIEWED, OVERTIME_LABEL, NOTES = (
    "Adjustment (minutes)", "Approved hours", "Comment", "Reviewed", "Jibble overtime", "Notes",
)
WEEK_TOTAL = "Week total"
INCOMPLETE = "Incomplete"

COLUMNS = [
    (EMPLOYEE, 24), (DATE, 12), (CLOCK_IN, 10), (CLOCK_OUT, 10), (GROSS, 11), (LUNCH, 11), (NET, 11),
    (ADJUSTMENT, 12), (APPROVED, 11), (COMMENT, 30), (REVIEWED, 10), (OVERTIME_LABEL, 9), (NOTES, 44),
]
COLUMN = {label: index for index, (label, _) in enumerate(COLUMNS)}

INSTRUCTIONS = [
    "Only the yellow and orange cells can be changed.",
    "Adjustment is in minutes, added to Net: 15 adds 15 minutes, -15 removes 15 minutes, 0 means no change.",
    "30 minutes of lunch is taken off every day worked, even if the employee also clocked out. "
    "If that's wrong, add the minutes back as an adjustment.",
    "Orange means the punches are incomplete: type the approved hours as h:mm, for example 7:30.",
    "When you've finished an employee, go to Reviewed in their Week total row, click the cell that says No, "
    "and choose Yes from the arrow.",
    "When everyone is done, save this file and return it to accounting.",
]
HEADER_ROW = len(INSTRUCTIONS) + 2  # zero-based, below the title, week and instructions


def write_review_workbook(export: WeeklyExport, group: ReviewGroup, path: str | Path) -> None:
    workbook = xlsxwriter.Workbook(str(path), {"remove_timezone": True})
    workbook.set_properties({"title": f"Timesheet review - {group.title}", "author": "", "comments": ""})
    formats = _formats(workbook)
    _write_review_sheet(workbook, formats, export, group)
    _write_punch_sheet(workbook, formats, export, group)
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
        "notes": make({"valign": "top", "text_wrap": True, "indent": 1}),
        "wrap": make({"valign": "top", "text_wrap": True}),
        "date": make({"num_format": "ddd mmm d", "align": "left", "valign": "top"}),
        "time": make({"num_format": "hh:mm:ss", "align": "left", "valign": "top"}),
        "duration": make(duration),
        "muted": make({"valign": "top", "bg_color": "#F4F4F4"}),
        "edit_text": make({**edit, "text_wrap": True}),
        "edit_number": make({**edit, "num_format": "+0;-0;0", "align": "right"}),
        "edit_choice": make({**edit, "align": "center"}),
        "edit_hours": make({**edit, "num_format": "[h]:mm", "align": "right", "bg_color": "#F8C98B"}),
        "total": make(total),
        "total_wrap": make({**total, "text_wrap": True, "indent": 1}),
        "total_duration": make({**total, **duration, "valign": "top"}),
        "total_number": make({**total, "num_format": "+0;-0;0", "align": "right"}),
        "bad": make({"font_color": "#9C0006", "bg_color": "#FFC7CE"}),
    }


def _as_days(minutes: Optional[int]) -> Optional[float]:
    return None if minutes is None else minutes / 1440


def _clock(value) -> str:
    return "Missing" if value is None else value.strftime("%I:%M %p").lstrip("0")


def _overtime(record: DayRecord) -> Optional[int]:
    values = [record.metrics.get(metric) for metric in OVERTIME]
    return None if any(v is None for v in values) else sum(values)


def _day_notes(record: DayRecord) -> str:
    hours = record.hours
    notes = []
    if hours.gross is None:
        notes.append("Punches incomplete: enter the approved hours.")
    elif not record.punches:
        notes.append("No punches.")
    for out, back in hours.gaps:
        notes.append(f"Clocked out {_clock(out)} to {_clock(back)} ({format_minutes(gap_minutes(out, back))}), not counted in Gross.")
    if hours.gaps and hours.lunch:
        notes.append(f"{format_minutes(hours.lunch)} lunch also deducted.")
    if hours.lunch_capped:
        notes.append("Lunch capped at gross hours.")
    notes.extend(f'Jibble note: "{p.note}"' for p in record.punches if p.note)
    notes.extend(record.issues)
    return " ".join(dict.fromkeys(notes))


def _write_review_sheet(workbook, formats, export: WeeklyExport, group: ReviewGroup) -> None:
    sheet = workbook.add_worksheet(REVIEW_SHEET)
    sheet.write(0, 0, f"{export.company or 'Weekly'} timesheet review: {group.title}", formats["title"])
    sheet.write(1, 0, export.period, formats["note"])
    for index, line in enumerate(INSTRUCTIONS):
        sheet.write(2 + index, 0, line, formats["note"])
    for column, (label, width) in enumerate(COLUMNS):
        sheet.set_column(column, column, width)
        sheet.write(HEADER_ROW, column, label, formats["header"])
    sheet.set_row(HEADER_ROW, 32)

    row = HEADER_ROW + 1
    for employee in group.employees:
        row = _write_employee(sheet, formats, export, employee, row)

    last = row - 1
    sheet.autofilter(HEADER_ROW, 0, max(last, HEADER_ROW), len(COLUMNS) - 1)
    sheet.freeze_panes(HEADER_ROW + 1, 1)
    sheet.conditional_format(
        HEADER_ROW + 1, COLUMN[APPROVED], max(last, HEADER_ROW + 1), COLUMN[APPROVED],
        {"type": "cell", "criteria": "<", "value": 0, "format": formats["bad"]},
    )
    sheet.protect("", {"autofilter": True, "format_columns": True, "format_rows": True})
    sheet.set_landscape()
    sheet.set_paper(1)  # Letter
    sheet.fit_to_pages(1, 0)
    sheet.repeat_rows(HEADER_ROW)
    sheet.set_footer("&CPage &P of &N")


def _write_employee(sheet, formats, export: WeeklyExport, employee: Employee, row: int) -> int:
    first = row
    needs_hours: list[str] = []
    for day in export.dates:
        record = employee.days[day]
        if day.weekday() < 5 or record.punches or record.issues:
            cell = _write_day(sheet, formats, employee, record, row)
            if cell:
                needs_hours.append(cell)
            row += 1
    _write_week_total(sheet, formats, export, employee, first, row, needs_hours)
    return row + 1


def _write_day(sheet, formats, employee: Employee, record: DayRecord, row: int) -> Optional[str]:
    """Write one day. Returns the Approved cell if someone must type the hours."""
    hours = record.hours
    excel = row + 1
    net_cell = xl_rowcol_to_cell(row, COLUMN[NET])
    adjust_cell = xl_rowcol_to_cell(row, COLUMN[ADJUSTMENT])
    approved_cell = xl_rowcol_to_cell(row, COLUMN[APPROVED])
    # Each pair gets its own line, so a clock-in sits level with its clock-out.
    no_times = "-" if hours.gross is not None else "Missing"

    sheet.write(row, COLUMN[EMPLOYEE], employee.name, formats["text"])
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
    sheet.write_blank(row, COLUMN[REVIEWED], None, formats["muted"])
    overtime = _overtime(record)
    if overtime is None:
        sheet.write_blank(row, COLUMN[OVERTIME_LABEL], None, formats["duration"])
    else:
        sheet.write_number(row, COLUMN[OVERTIME_LABEL], overtime / 1440, formats["duration"])
    sheet.write(row, COLUMN[NOTES], _day_notes(record), formats["notes"])

    if hours.gross is None:
        sheet.write_blank(row, COLUMN[ADJUSTMENT], None, formats["muted"])
        sheet.write_blank(row, COLUMN[APPROVED], None, formats["edit_hours"])
        sheet.data_validation(
            row, COLUMN[APPROVED], row, COLUMN[APPROVED],
            {
                "validate": "time",
                "criteria": "between",
                "minimum": time(0, 0),
                "maximum": time(23, 59),
                "error_title": "Approved hours",
                "error_message": "Type the hours as h:mm, for example 7:30.",
            },
        )
        return approved_cell

    sheet.write_blank(row, COLUMN[ADJUSTMENT], None, formats["edit_number"])
    sheet.data_validation(
        row, COLUMN[ADJUSTMENT], row, COLUMN[ADJUSTMENT],
        {
            "validate": "custom",
            "value": (
                f"=AND(ISNUMBER({adjust_cell}),{adjust_cell}=INT({adjust_cell}),ABS({adjust_cell})<=1440,"
                f"ROUND(N({net_cell})*1440+{adjust_cell},0)>=0)"
            ),
            "error_title": "Adjustment",
            "error_message": "Enter whole minutes, such as 15 or -15. Approved hours can't go below zero.",
        },
    )
    sheet.write_formula(
        row,
        COLUMN[APPROVED],
        f'=IF(AND({net_cell}="",{adjust_cell}=""),"",N({net_cell})+N({adjust_cell})/1440)',
        formats["duration"],
        hours.net / 1440 if has_hours else "",
    )
    return None


def _write_week_total(sheet, formats, export, employee: Employee, first: int, row: int, needs_hours: list[str]) -> None:
    days = [employee.days[d].hours for d in export.dates]
    complete = all(h.gross is not None for h in days)
    last = row - 1

    def column_range(label: str) -> str:
        return f"{xl_rowcol_to_cell(first, COLUMN[label])}:{xl_rowcol_to_cell(last, COLUMN[label])}"

    sheet.write(row, COLUMN[EMPLOYEE], employee.name, formats["total"])
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
    approved_sum = f"SUM({column_range(APPROVED)})"
    if needs_hours:
        blanks = "+".join(f"COUNTBLANK({cell})" for cell in needs_hours)
        approved_formula, cached = f'=IF({blanks}>0,"Needs hours",{approved_sum})', "Needs hours"
    else:
        approved_formula, cached = f"={approved_sum}", sum(h.net for h in days) / 1440
    sheet.write_formula(row, COLUMN[APPROVED], approved_formula, formats["total_duration"], cached)
    sheet.write_blank(row, COLUMN[COMMENT], None, formats["edit_text"])
    sheet.write(row, COLUMN[REVIEWED], "No", formats["edit_choice"])
    sheet.data_validation(
        row, COLUMN[REVIEWED], row, COLUMN[REVIEWED],
        {
            "validate": "list",
            "source": ["Yes", "No"],
            "input_title": "Reviewed",
            "input_message": "Click the arrow and choose Yes when you've finished this employee.",
            "error_title": "Reviewed",
            "error_message": "Choose Yes or No.",
        },
    )
    overtime = employee.overtime
    if overtime is None:
        sheet.write(row, COLUMN[OVERTIME_LABEL], "MISSING", formats["total_duration"])
    else:
        sheet.write_number(row, COLUMN[OVERTIME_LABEL], overtime / 1440, formats["total_duration"])
    sheet.write(row, COLUMN[NOTES], "" if complete else "Some punches are incomplete, so these totals can't be worked out.", formats["total_wrap"])


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
