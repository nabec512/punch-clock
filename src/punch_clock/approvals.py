"""Read returned review workbooks and work out the approved hours.

Only the supervisor's inputs are read. Approved hours are recalculated here from
the source export, so a formula changed in a returned file can't alter the result.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException

from punch_clock.assignments import review_groups
from punch_clock.hours import DayHours
from punch_clock.jibble_export import Employee, UnsupportedExport, WeeklyExport
from punch_clock.review_workbook import (
    ADJUSTMENT,
    APPROVED,
    CODE,
    COMMENT,
    DATE,
    FILE_FORMAT,
    INFO_SHEET,
    NET,
    REVIEW_SHEET,
    REVIEWED,
    WEEK_TOTAL,
)


@dataclass
class DayInput:
    """What a supervisor entered for one day. Blank stays None, so 0 is kept distinct."""

    adjustment: Optional[int] = None
    typed_hours: Optional[int] = None
    comment: str = ""
    problems: list[str] = field(default_factory=list)

    @property
    def has_input(self) -> bool:
        return self.adjustment is not None or self.typed_hours is not None or bool(self.comment)


@dataclass
class DayApproval:
    input: DayInput
    approved: Optional[int]
    unresolved: bool  # hours are still needed, as opposed to a day with nothing to approve
    problems: list[str]


@dataclass
class EmployeeApproval:
    employee: Employee
    reviewed_in: Optional[str]  # review file title; None when no file covers this employee
    reviewed: bool
    week_comment: str
    days: dict[date, DayApproval]
    problems: list[str]

    @property
    def approved(self) -> Optional[int]:
        if any(day.unresolved for day in self.days.values()):
            return None
        return sum(day.approved or 0 for day in self.days.values())

    @property
    def adjustment_total(self) -> int:
        return sum(day.input.adjustment or 0 for day in self.days.values())

    @property
    def is_final(self) -> bool:
        return self.reviewed and not self.problems and self.approved is not None


@dataclass
class ApprovalSet:
    employees: dict[str, EmployeeApproval]
    missing_files: list[str]
    read_files: list[str]

    @property
    def is_final(self) -> bool:
        return not self.missing_files and all(a.is_final for a in self.employees.values())

    @property
    def not_reviewed(self) -> list[EmployeeApproval]:
        return [a for a in self.employees.values() if not a.reviewed]


@dataclass
class _ReviewFile:
    path: Path
    key: str
    title: str
    days: dict[tuple[str, date], DayInput]
    reviewed: dict[str, bool]
    week_comments: dict[str, str]


def approve_day(hours: DayHours, entered: DayInput) -> DayApproval:
    problems = list(entered.problems)
    if hours.gross is None:
        # Incomplete punches: only hours typed by the supervisor can settle the day.
        return DayApproval(entered, entered.typed_hours, entered.typed_hours is None, problems)
    if not hours.sessions and entered.adjustment is None:
        return DayApproval(entered, None, False, problems)
    approved = (hours.net or 0) + (entered.adjustment or 0)
    if approved < 0:
        problems.append("Adjustment takes approved hours below zero.")
        return DayApproval(entered, None, True, problems)
    return DayApproval(entered, approved, False, problems)


def read_approvals(folder: str | Path, export: WeeklyExport) -> ApprovalSet:
    folder = Path(folder)
    files = [_read_file(path, export) for path in sorted(folder.glob("*.xlsx")) if not path.name.startswith("~$")]
    _reject_duplicate_groups(files)
    groups = review_groups(export)
    present = {f.key for f in files}
    missing = [group.title for group in groups if group.key not in present]

    employees: dict[str, EmployeeApproval] = {}
    for employee in export.included:
        covering = [f for f in files if any(key[0] == employee.code for key in f.days)]
        employees[employee.code] = _approve_employee(export, employee, covering)
    return ApprovalSet(employees, missing, [f.title for f in files])


def _reject_duplicate_groups(files: list[_ReviewFile]) -> None:
    seen: dict[str, Path] = {}
    for review_file in files:
        if review_file.key in seen:
            raise UnsupportedExport(
                f'Two files are for "{review_file.title}":\n{seen[review_file.key].name}\n{review_file.path.name}\n\n'
                "Keep only the one the supervisor returned, then try again."
            )
        seen[review_file.key] = review_file.path


def _approve_employee(export: WeeklyExport, employee: Employee, files: list[_ReviewFile]) -> EmployeeApproval:
    problems: list[str] = []
    days: dict[date, DayApproval] = {}
    for day in export.dates:
        record = employee.days[day]
        entered = _merge_day([f.days[(employee.code, day)] for f in files if (employee.code, day) in f.days])
        days[day] = approve_day(record.hours, entered)
        if files and (employee.code, day) not in files[0].days and (day.weekday() < 5 or record.punches or record.issues):
            problems.append(f"{day:%a}: row is missing from the returned file.")
    comments = list(dict.fromkeys(f.week_comments.get(employee.code, "") for f in files))
    return EmployeeApproval(
        employee=employee,
        reviewed_in=" / ".join(f.title for f in files) or None,
        reviewed=any(f.reviewed.get(employee.code, False) for f in files),
        week_comment=" ".join(c for c in comments if c),
        days=days,
        problems=problems,
    )


def _merge_day(entries: list[DayInput]) -> DayInput:
    """Two supervisors can share a department; their entries must agree."""
    filled = [e for e in entries if e.has_input or e.problems]
    if not filled:
        return DayInput()
    merged = filled[0]
    for other in filled[1:]:
        if (other.adjustment, other.typed_hours) != (merged.adjustment, merged.typed_hours):
            merged.problems.append("Supervisors entered different values for this day.")
    return merged


def _read_file(path: Path, export: WeeklyExport) -> _ReviewFile:
    try:
        workbook = openpyxl.load_workbook(path, data_only=False)
    except (InvalidFileException, zipfile.BadZipFile, KeyError) as error:
        raise UnsupportedExport(f"{path.name} could not be opened as an Excel workbook.") from error
    if INFO_SHEET not in workbook or REVIEW_SHEET not in workbook:
        raise UnsupportedExport(f"{path.name} isn't a Punch Clock review file. Move it out of this folder and try again.")
    info = {row[0]: row[1] for row in workbook[INFO_SHEET].iter_rows(values_only=True) if row[0]}
    if info.get("format") != FILE_FORMAT:
        raise UnsupportedExport(f"{path.name} was made by a different version of this app.")
    if info.get("source_sha256") != export.sha256:
        raise UnsupportedExport(
            f"{path.name} was made from a different Jibble export, so it can't be combined with this week's report."
        )
    return _read_review_sheet(path, workbook[REVIEW_SHEET], info, export)


def _read_review_sheet(path: Path, sheet, info: dict, export: WeeklyExport) -> _ReviewFile:
    rows = list(sheet.iter_rows(values_only=True))
    header_index = next((i for i, row in enumerate(rows) if CODE in row and ADJUSTMENT in row and REVIEWED in row), None)
    if header_index is None:
        raise UnsupportedExport(f"{path.name}: the review table's headings have changed.")
    labels = list(rows[header_index])
    missing = [x for x in (CODE, DATE, NET, ADJUSTMENT, APPROVED, COMMENT, REVIEWED) if x not in labels]
    if missing:
        raise UnsupportedExport(f"{path.name}: missing column {', '.join(missing)}.")
    column = {label: labels.index(label) for label in (CODE, DATE, NET, ADJUSTMENT, APPROVED, COMMENT, REVIEWED)}
    known = {e.code: e for e in export.included}

    result = _ReviewFile(path, info.get("group_key", ""), info.get("group_title", path.stem), {}, {}, {})
    for row in rows[header_index + 1 :]:
        code = str(row[column[CODE]] or "").strip()
        if not code:
            continue
        if code not in known:
            raise UnsupportedExport(f"{path.name}: unknown member code {code}.")
        when = row[column[DATE]]
        comment = str(row[column[COMMENT]] or "").strip()
        if when == WEEK_TOTAL:
            result.reviewed[code] = str(row[column[REVIEWED]] or "").strip().casefold() == "yes"
            result.week_comments[code] = comment
            continue
        if not isinstance(when, datetime) or when.date() not in export.dates:
            raise UnsupportedExport(f"{path.name}: unexpected date {when!r} for {code}.")
        day = when.date()
        if (code, day) in result.days:
            raise UnsupportedExport(f"{path.name}: {code} appears twice for {day}.")
        hours = known[code].days[day].hours
        entered = DayInput(comment=comment)
        entered.adjustment = _read_adjustment(row[column[ADJUSTMENT]], entered)
        if hours.gross is None:
            entered.typed_hours = _read_hours(row[column[APPROVED]], entered)
        elif _read_stored_net(row[column[NET]]) != (hours.net if hours.sessions else None):
            entered.problems.append("Net in the returned file differs from the export; the export's value was used.")
        result.days[(code, day)] = entered
    return result


def _read_adjustment(value, entered: DayInput) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        number = float(str(value).strip())
    except ValueError:
        number = None
    if number is None or number != int(number) or abs(number) > 1440:
        entered.problems.append(f"Adjustment {value!r} isn't a whole number of minutes.")
        return None
    return int(number)


def _read_hours(value, entered: DayInput) -> Optional[int]:
    if value is None or value == "":
        return None
    minutes = _duration_minutes(value)
    if minutes is None or minutes < 0:
        entered.problems.append(f"Approved hours {value!r} couldn't be read. Use h:mm.")
        return None
    return minutes


def _read_stored_net(value) -> Optional[int]:
    return None if value is None or value == "" else _duration_minutes(value)


def _duration_minutes(value) -> Optional[int]:
    """Excel durations reach openpyxl in several forms, depending on the number format."""
    if isinstance(value, timedelta):
        return round(value.total_seconds() / 60)
    if isinstance(value, datetime):
        return round((value - datetime(1899, 12, 30)).total_seconds() / 60)
    if isinstance(value, time):
        return value.hour * 60 + value.minute + round(value.second / 60)
    if isinstance(value, (int, float)):
        return round(value * 1440)
    match = re.fullmatch(r"(\d+):(\d{2})", str(value).strip())
    return int(match[1]) * 60 + int(match[2]) if match and int(match[2]) < 60 else None
