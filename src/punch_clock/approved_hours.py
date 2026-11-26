"""Read the hours a supervisor approved back from their returned review workbook.

The totals are worked out again from what a supervisor can change, their adjustments and the
hours they typed, with the same rules as ``hours``. The totals in the file aren't trusted: a
locked cell someone overwrote, or a file saved by a program that doesn't recalculate, would
otherwise send the wrong hours to payroll. Where the file does hold its own results, they must
agree, and each disagreement is listed rather than one figure quietly chosen.

Everything that keeps an employee's hours from being used is listed in plain words, for the
whole file at once, so accounting can fix them all in one go. A file that isn't a review file,
or whose rows have been moved, is refused outright, because its hours can't be matched to people.
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException

from punch_clock import __version__
from punch_clock.hours import BLOCK_MINUTES, DayHours, format_minutes, overtime_minutes, week_hours
from punch_clock.jibble_export import UnsupportedExport
from punch_clock.review_workbook import (
    ADJUSTMENT, COLUMNS, COMMENT, COMPANY, DATA_COLUMNS, DATA_FORMAT, DATA_SHEET, DATE, EMPLOYEE, FORMAT,
    MADE_WITH, NOTES, OVERTIME, REGULAR, REVIEW_GROUP, REVIEW_SHEET, REVIEWED, TOTAL, WEEK_START, WEEK_TOTAL,
)

FIRST_READABLE_VERSION = "0.11.0"  # review files from older versions have no data sheet
DAY_MINUTES = 1440
NEEDS_HOURS = "Needs hours"


@dataclass(frozen=True)
class ApprovedDay:
    day: date
    total: Optional[int]  # approved minutes, or None while incomplete punches have no hours typed in
    regular: Optional[int]
    overtime: Optional[int]
    adjustment: int  # minutes the supervisor added, or took off if negative
    typed: bool  # the punches were incomplete, so the supervisor typed the hours
    comment: str
    full_minutes: int = 0  # the scheduled paid hours; zero on a day off, which has no lunch


@dataclass(frozen=True)
class ApprovedEmployee:
    code: str  # Jibble member code
    name: str
    department: str
    days: tuple[ApprovedDay, ...]
    regular: Optional[int]  # the week's, after overtime makes up a short week; None while any day needs hours
    overtime: Optional[int]
    total: Optional[int]
    comment: str
    problems: tuple[str, ...] = ()  # this employee's share of the file's problems

    @property
    def days_without_hours(self) -> tuple[date, ...]:
        """Days whose hours can't be used yet: incomplete punches with no hours typed, or a mistake listed in problems."""
        return tuple(day.day for day in self.days if day.total is None)


@dataclass(frozen=True)
class ApprovedFile:
    path: Path
    company: str  # the Jibble organization, as the export named it
    start: date  # the Monday of the week
    group: str  # the supervisor, or Missing supervisor
    made_with: str  # the version of Punch Clock that made the file
    employees: tuple[ApprovedEmployee, ...]
    problems: tuple[str, ...]  # each names the employee and day; these hours can't be used until it's fixed

    @property
    def end(self) -> date:
        return self.start + timedelta(days=6)


@dataclass(frozen=True)
class _Day:
    """One row of the data sheet: what the review row was built from."""

    code: str
    name: str
    department: str
    day: date
    row: int
    week_row: int
    from_punches: bool  # the punches gave hours, so the total shows even without an adjustment
    incomplete: bool  # the supervisor types the total
    paid: Optional[int]
    full_minutes: int
    week_full_minutes: int


def read_approved_hours(path: str | Path) -> ApprovedFile:
    path = Path(path)
    try:
        # The results Excel saved with each formula, and the values typed into the input cells.
        workbook = openpyxl.load_workbook(path, data_only=True)
    except PermissionError:
        raise  # open in Excel: the window says to close it
    except (InvalidFileException, zipfile.BadZipFile, KeyError, OSError) as error:
        raise UnsupportedExport(f"{path.name} could not be opened. Make sure it's an Excel file.") from error
    if REVIEW_SHEET not in workbook.sheetnames or DATA_SHEET not in workbook.sheetnames:
        raise UnsupportedExport(
            f"{path.name} isn't a review file made by Punch Clock {FIRST_READABLE_VERSION} or later, so the hours in it "
            "can't be read. Use the Excel file Punch Clock made for that supervisor, as they sent it back."
        )
    about, rows = _read_data_sheet(workbook[DATA_SHEET], path)
    sheet = workbook[REVIEW_SHEET]
    _check_header(sheet, path)
    problems: list[str] = []
    employees = []
    for code in dict.fromkeys(row.code for row in rows):
        days = [row for row in rows if row.code == code]
        employees.append(_read_employee(sheet, path, days, problems))
    return ApprovedFile(
        path,
        about[COMPANY],
        about[WEEK_START],
        about[REVIEW_GROUP],
        about[MADE_WITH],
        tuple(employees),
        tuple(problems),
    )


def _refuse_changed(path: Path, detail: str) -> UnsupportedExport:
    return UnsupportedExport(
        f"{path.name} has been changed outside its yellow and orange cells ({detail}), so its hours can't be matched "
        "to the right people. Ask the supervisor for the file as it was sent, with only those cells filled in."
    )


def _read_data_sheet(sheet, path: Path) -> tuple[dict, list[_Day]]:
    rows = list(sheet.iter_rows(values_only=True))
    labels = {row[0]: row[1] for row in rows if row and len(row) > 1 and row[0] in (FORMAT, COMPANY, WEEK_START, REVIEW_GROUP, MADE_WITH)}
    data_format = labels.get(FORMAT)
    if isinstance(data_format, (int, float)) and data_format > DATA_FORMAT:
        raise UnsupportedExport(
            f"{path.name} was made by a newer version of Punch Clock ({labels.get(MADE_WITH)}) than this one "
            f"({__version__}). Close Punch Clock, open it again, and choose Yes when it offers to update."
        )
    try:
        about = {
            COMPANY: str(labels[COMPANY] or ""),
            WEEK_START: date.fromisoformat(str(labels[WEEK_START])),
            REVIEW_GROUP: str(labels[REVIEW_GROUP]),
            MADE_WITH: str(labels[MADE_WITH]),
        }
        header = next(index for index, row in enumerate(rows) if row and tuple(row[: len(DATA_COLUMNS)]) == DATA_COLUMNS)
        days = [_data_row(row) for row in rows[header + 1 :] if row and row[0] not in (None, "")]
    except (KeyError, StopIteration, TypeError, ValueError) as error:
        raise _refuse_changed(path, "its hidden data sheet can't be read") from error
    if data_format != DATA_FORMAT or not days or any(day.day - about[WEEK_START] not in _WEEK for day in days):
        raise _refuse_changed(path, "its hidden data sheet doesn't add up")
    return about, days


_WEEK = [timedelta(days=offset) for offset in range(7)]


def _data_row(row: tuple) -> _Day:
    code, name, department, day, review_row, week_row, from_punches, incomplete, paid, full, week_full = row[: len(DATA_COLUMNS)]
    return _Day(
        str(code),
        str(name),
        str(department or ""),
        date.fromisoformat(str(day)),
        int(review_row),
        int(week_row),
        bool(from_punches),
        bool(incomplete),
        None if paid in (None, "") else int(paid),
        int(full),
        int(week_full),
    )


HEADER_SEARCH_ROWS = 30  # the column headings are below the title and instructions
_LABELS = tuple(label for label, _ in COLUMNS)
# Files made before Reviewed was dropped have it before Notes, and one more line of instructions above the headings.
_LAYOUTS = (_LABELS, (*_LABELS[: _LABELS.index(NOTES)], REVIEWED, NOTES))


def _check_header(sheet, path: Path) -> None:
    """Finds the column headings, and remembers on the sheet which column each one is in."""
    for row in sheet.iter_rows(max_row=HEADER_SEARCH_ROWS, max_col=len(_LAYOUTS[-1]), values_only=True):
        if row and row[0] == EMPLOYEE:
            found = tuple(value for value in row if value is not None)
            if found in _LAYOUTS:
                sheet.punch_clock_columns = {label: index + 1 for index, label in enumerate(found)}
                return
            break
    raise _refuse_changed(path, "its column headings are different")


def _cell(sheet, row: int, label: str):
    return sheet.cell(row, sheet.punch_clock_columns[label]).value


def _label(day: _Day) -> str:
    """As review_workbook.employee_label writes it on every row."""
    return f"{day.name} - {day.department}" if day.department else day.name


def _day_label(day: date) -> str:
    return f"{day:%a %b} {day.day}"


def _read_employee(sheet, path: Path, days: list[_Day], problems: list[str]) -> ApprovedEmployee:
    first = days[0]
    week_row = first.week_row
    for day in days:
        shown = _cell(sheet, day.row, DATE)
        shown = shown.date() if isinstance(shown, datetime) else shown
        if _cell(sheet, day.row, EMPLOYEE) != _label(day) or shown != day.day or day.week_row != week_row:
            raise _refuse_changed(path, f"the row for {first.name} on {_day_label(day.day)} has moved")
    if _cell(sheet, week_row, EMPLOYEE) != _label(first) or _cell(sheet, week_row, DATE) != WEEK_TOTAL:
        raise _refuse_changed(path, f"the Week total row for {first.name} has moved")

    before = len(problems)
    approved = [_read_day(sheet, day, problems) for day in days]
    week = week_hours(DayHours((), None, None, None, paid=day.total, full_minutes=d.full_minutes) for day, d in zip(approved, days))
    if week.full_minutes != first.week_full_minutes:
        raise _refuse_changed(path, f"the scheduled week for {first.name} doesn't add up")
    # A day already listed would only be listed again here, less clearly.
    if len(problems) == before:
        for label, minutes in ((REGULAR, week.regular), (OVERTIME, week.overtime), (TOTAL, week.paid)):
            expected = NEEDS_HOURS if minutes is None else minutes
            _compare(sheet, week_row, label, expected, f"{first.name}, Week total", problems)
    return ApprovedEmployee(
        first.code,
        first.name,
        first.department,
        tuple(approved),
        week.regular,
        week.overtime,
        week.paid,
        _text(_cell(sheet, week_row, COMMENT)),
        tuple(problems[before:]),
    )


def _read_day(sheet, day: _Day, problems: list[str]) -> ApprovedDay:
    where = f"{day.name}, {_day_label(day.day)}"
    adjustment_cell = _cell(sheet, day.row, ADJUSTMENT)
    comment = _text(_cell(sheet, day.row, COMMENT))
    if day.incomplete:
        # The adjustment is locked on these days, and Total approved hours is typed instead.
        if not _blank(adjustment_cell):
            problems.append(f"{where}: there's an adjustment, but the punches are incomplete, so type the total approved hours instead.")
        typed = _cell(sheet, day.row, TOTAL)
        total = None
        if _blank(typed):
            problems.append(f"{where}: the punches are incomplete and no hours were typed in Total approved hours.")
        else:
            total = _typed_hours(typed, where, problems)
        regular, overtime = _split(total, day.full_minutes)
        return ApprovedDay(day.day, total, regular, overtime, 0, True, comment, day.full_minutes)

    adjustment = _adjustment(adjustment_cell, day.paid or 0, where, problems)
    total = (day.paid or 0) + (adjustment or 0)
    regular, overtime = _split(total, day.full_minutes)
    if adjustment is None:
        # The adjustment can't be used, so neither can the day's hours. They aren't compared either.
        return ApprovedDay(day.day, None, None, None, 0, False, comment, day.full_minutes)
    # Without punches or an adjustment, the cells are blank rather than zero.
    blank = not day.from_punches and _blank(adjustment_cell)
    for label, minutes in ((REGULAR, regular), (OVERTIME, overtime), (TOTAL, total)):
        _compare(sheet, day.row, label, "" if blank else minutes, where, problems)
    return ApprovedDay(day.day, total, regular, overtime, adjustment, False, comment, day.full_minutes)


def _split(total: Optional[int], full_minutes: int) -> tuple[Optional[int], Optional[int]]:
    if total is None:
        return None, None
    overtime = overtime_minutes(total, full_minutes)
    return total - overtime, overtime


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _minutes(value) -> Optional[float]:
    """A length of time as Excel or LibreOffice stores it, in minutes, or None if it isn't one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value * DAY_MINUTES
    if isinstance(value, timedelta):
        return value.total_seconds() / 60
    if isinstance(value, time):
        return value.hour * 60 + value.minute + value.second / 60
    return None


def _whole(minutes: float) -> Optional[int]:
    """Whole minutes, allowing for how spreadsheets store fractions of a day."""
    rounded = round(minutes)
    return rounded if abs(minutes - rounded) < 0.01 else None


def _adjustment(value, paid: int, where: str, problems: list[str]) -> Optional[int]:
    """Minutes, in steps of 15, as the cell's own check allows. Pasting gets around that check, so it's checked again."""
    if _blank(value):
        return 0
    minutes = value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    whole = None if minutes is None else _whole(minutes)
    if whole is None:
        problems.append(f"{where}: the adjustment, {value}, isn't a number of minutes.")
    elif whole % BLOCK_MINUTES:
        problems.append(f"{where}: the adjustment, {whole}, isn't in steps of {BLOCK_MINUTES} minutes.")
    elif abs(whole) > DAY_MINUTES:
        problems.append(f"{where}: the adjustment, {whole} minutes, is more than a whole day.")
    elif paid + whole < 0:
        problems.append(f"{where}: the adjustment, {whole}, would take the approved hours below zero.")
    else:
        return whole
    return None


def _typed_hours(value, where: str, problems: list[str]) -> Optional[int]:
    minutes = _minutes(value)
    whole = None if minutes is None else _whole(minutes)
    if whole is None or not 0 <= whole < DAY_MINUTES or whole % BLOCK_MINUTES:
        problems.append(
            f"{where}: the typed hours, {_shown(value)}, aren't a length of time in {BLOCK_MINUTES}-minute steps, such as 7:30."
        )
        return None
    return whole


def _shown(value) -> str:
    if isinstance(value, str):
        return f'"{value}"' if value else "nothing"
    minutes = _minutes(value)
    whole = None if minutes is None else _whole(minutes)
    return format_minutes(whole) if whole is not None else str(value)


def _compare(sheet, row: int, label: str, expected, where: str, problems: list[str]) -> None:
    """The result the file saved must match the one worked out again. A file with no saved results isn't compared."""
    saved = _cell(sheet, row, label)
    if saved is None:
        return
    if isinstance(expected, str):
        agrees = isinstance(saved, str) and saved.strip() == expected
    else:
        minutes = _minutes(saved)
        agrees = minutes is not None and _whole(minutes) == expected
    if not agrees:
        wanted = format_minutes(expected) if isinstance(expected, int) else (f'"{expected}"' if expected else "nothing")
        problems.append(
            f"{where}: {label} shows {_shown(saved)}, but the adjustments and the pay rules give {wanted}. "
            "A locked cell may have been changed, or the file wasn't saved in Excel. Make changes with the Adjustment instead."
        )
