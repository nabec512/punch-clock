"""Read a detailed weekly Jibble export and cross-check its sheets.

Columns and sections are located by their labels, never by fixed positions, so a
changed layout produces a clear error instead of wrong numbers. The source file
is only ever read.
"""
from __future__ import annotations

import hashlib
import re
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, Sequence

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException

from punch_clock.hours import DayHours, Punch, calculate_day, pair_punches, weekly_total

OVERTIME = ["Daily OT", "Daily Double OT", "Weekly OT", "Rest Day OT", "Public Holiday OT"]
BREAKS = ["Break Hours (paid)", "Break Hours (unpaid)"]
METRICS = ["Payroll Hours", "Regular Hours", *OVERTIME, *BREAKS, "Paid Time Off"]
TIMESHEET_COLUMNS = ["Date", "Day", "Full Name", "Member Code", "Position", "First In", "Last Out", *METRICS]
ENTRY_COLUMNS = ["Date", "Full Name", "Member Code", "Entry Type", "Time", "Timezone"]

TIMESHEETS, ENTRIES, TEAM = "Raw Timesheets", "Raw Time Entries", "Team Summary"

# Metric name -> column label on an individual employee summary sheet.
INDIVIDUAL_LABELS = {
    "Payroll Hours": "PAYROLL HRS",
    "Regular Hours": "REG. HRS",
    "Daily OT": "DAILY OT",
    "Daily Double OT": "DOUBLE OT",
    "Weekly OT": "WEEKLY OT",
    "Rest Day OT": "REST DAY OT",
    "Public Holiday OT": "PUBLIC HOLIDAY OT",
    "Paid Time Off": "PTO",
}
# Metric name -> row label in the Team Summary totals block.
TEAM_LABELS = {
    "Payroll Hours": "Payroll",
    "Regular Hours": "Regular",
    "Daily OT": "Daily OT",
    "Daily Double OT": "Double OT",
    "Weekly OT": "Weekly OT",
    "Rest Day OT": "Rest Day OT",
    "Public Holiday OT": "Public Holiday OT",
}

# "Assembly - Supervisor" means a supervisor of the Assembly department.
SUPERVISOR_POSITION = re.compile(r"^(.+?)\s*[-–—]\s*supervisor\s*$", re.IGNORECASE)

BREAK_MODEL_MESSAGE = (
    "This export contains break punches. This tool deducts a fixed lunch instead of using "
    "Jibble breaks, and the two cannot be mixed. Remove the configured break in Jibble, "
    "then select an export from a week recorded after that change."
)


class UnsupportedExport(ValueError):
    """The file cannot safely be reported on. The message is written for the end user."""


@dataclass(frozen=True)
class Check:
    """One comparison between a value and the source total it should agree with."""

    label: str
    calculated: Optional[int]
    source: Optional[int]

    @property
    def match(self) -> bool:
        return self.calculated == self.source


@dataclass
class DayRecord:
    day: date
    row: Optional[int] = None  # None when Jibble has no daily row for this date
    metrics: dict[str, Optional[int]] = field(default_factory=dict)
    first_in: Optional[datetime] = None
    last_out: Optional[datetime] = None
    punches: list[Punch] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    @property
    def hours(self) -> DayHours:
        return calculate_day(self.punches, self.row is not None)


@dataclass
class Employee:
    code: str
    name: str
    position: str = ""
    days: dict[date, DayRecord] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def has_position(self) -> bool:
        return bool(self.position)

    @property
    def department(self) -> str:
        match = SUPERVISOR_POSITION.match(self.position)
        return match[1] if match else self.position

    @property
    def is_supervisor(self) -> bool:
        return bool(SUPERVISOR_POSITION.match(self.position))

    @property
    def has_punches(self) -> bool:
        return any(record.punches for record in self.days.values())

    def total(self, metric: str) -> Optional[int]:
        return weekly_total(record.metrics.get(metric) for record in self.days.values())

    @property
    def overtime(self) -> Optional[int]:
        return weekly_total(self.total(metric) for metric in OVERTIME)


@dataclass
class WeeklyExport:
    company: str
    period: str
    start: date
    end: date
    exported: str
    timezone: str
    employees: list[Employee]
    checks: list[Check]
    source_name: str
    sha256: str
    timesheet_rows: int
    entry_rows: int
    column_counts: dict[str, int]

    @property
    def dates(self) -> list[date]:
        return [self.start + timedelta(days=i) for i in range(7)]

    @property
    def included(self) -> list[Employee]:
        """Employees with a recorded position, by department then name."""
        return sorted(
            (e for e in self.employees if e.has_position),
            key=lambda e: (e.department.casefold(), e.name.casefold(), e.code),
        )

    @property
    def excluded(self) -> list[Employee]:
        return [e for e in self.employees if not e.has_position]

    @property
    def review_count(self) -> int:
        return sum(not check.match for check in self.checks)


def load_export(path: str | Path) -> WeeklyExport:
    path = Path(path)
    data = path.read_bytes()
    try:
        workbook = openpyxl.load_workbook(path, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, KeyError) as error:
        raise UnsupportedExport(f"{path.name} could not be opened as an Excel workbook.") from error
    return read_workbook(workbook, path.name, hashlib.sha256(data).hexdigest())


def read_workbook(workbook, source_name: str, digest: str = "") -> WeeklyExport:
    for sheet in (TIMESHEETS, ENTRIES, TEAM):
        if sheet not in workbook:
            raise UnsupportedExport(f"Missing worksheet: {sheet}. Export all detailed options from Jibble.")
    team_rows = _values(workbook[TEAM])
    timesheet_headers, timesheet_rows = _read_table(workbook[TIMESHEETS], TIMESHEET_COLUMNS)
    entry_headers, entry_rows = _read_table(workbook[ENTRIES], ENTRY_COLUMNS)

    period, start = _read_week(team_rows)
    dates = [start + timedelta(days=i) for i in range(7)]
    employees = _read_employees(timesheet_rows, timesheet_headers, dates)
    timezone = _attach_punches(employees, entry_rows, dates)

    checks: list[Check] = []
    for employee in employees.values():
        _check_days(employee, dates)
    _check_individual_sheets(workbook, employees, dates, checks)
    _check_team_summary(team_rows, employees, checks)
    _check_calculated_gross(employees, dates, checks)

    return WeeklyExport(
        company=_read_company(team_rows),
        period=period,
        start=start,
        end=dates[-1],
        exported=_read_exported_text(team_rows),
        timezone=timezone,
        employees=sorted(employees.values(), key=lambda e: e.name.casefold()),
        checks=checks,
        source_name=source_name,
        sha256=digest,
        timesheet_rows=len(timesheet_rows),
        entry_rows=len(entry_rows),
        column_counts={
            TIMESHEETS: len([h for h in timesheet_headers if h]),
            ENTRIES: len([h for h in entry_headers if h]),
        },
    )


# --- Sheet helpers -----------------------------------------------------------


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _values(sheet) -> list[tuple]:
    return list(sheet.iter_rows(values_only=True))


def _minutes(value, where: str) -> Optional[int]:
    """Parse "1h 06m". A blank stays None: it is missing, not zero."""
    if value is None or value == "":
        return None
    match = re.fullmatch(r"(\d+)h\s+(\d{2})m", str(value).strip())
    if not match or int(match[2]) > 59:
        raise UnsupportedExport(
            f"{where}: unsupported duration {value!r}. Export durations as hours and minutes (e.g. 1h 06m)."
        )
    return int(match[1]) * 60 + int(match[2])


def _team_minutes(value, where: str) -> Optional[int]:
    """Team Summary shows a dash for zero."""
    return 0 if value == "-" else _minutes(value, where)


def _find_header(rows: Sequence[tuple], required: Sequence[str], sheet: str, scan: int = 20) -> tuple[int, list[str]]:
    """Return the index and labels of the single row holding all required labels."""
    found = [
        (index, names)
        for index, names in ((i, [_text(v) for v in row]) for i, row in enumerate(rows[:scan]))
        if set(required) <= set(names)
    ]
    if len(found) != 1:
        raise UnsupportedExport(
            f"{sheet}: expected one header row containing {', '.join(required)}. "
            "Re-export from Jibble with all detailed options."
        )
    return found[0]


def _read_table(sheet, required: Sequence[str]) -> tuple[list[str], list[dict]]:
    rows = _values(sheet)
    header_index, names = _find_header(rows, required, sheet.title)
    labels = [name for name in names if name]
    if len(labels) != len(set(labels)):
        raise UnsupportedExport(f"{sheet.title}: duplicate column labels.")
    table = []
    for number, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        if any(value is not None and value != "" for value in row):
            cells = {names[i]: value for i, value in enumerate(row) if names[i]}
            cells["_row"] = number
            table.append(cells)
    return names, table


def _read_week(team_rows: Sequence[tuple]) -> tuple[str, date]:
    period = next((row[1] for row in team_rows if len(row) > 1 and row[0] == "Week"), None)
    try:
        first, last = (datetime.strptime(part, "%d %B %Y").date() for part in period.split(" - "))
    except (AttributeError, ValueError) as error:
        raise UnsupportedExport(f"{TEAM}: unreadable reporting week.") from error
    if first.weekday() != 0 or last - first != timedelta(days=6):
        raise UnsupportedExport("This tool requires an export of one Monday-Sunday week.")
    return period, first


def _read_company(team_rows: Sequence[tuple]) -> str:
    """The company name sits to the right of the report title in the first row."""
    for row in team_rows[:10]:
        cells = [_text(v) for v in row if _text(v)]
        if len(cells) > 1 and cells[0] == "Weekly Timesheets":
            return cells[-1]
    return ""


def _read_exported_text(team_rows: Sequence[tuple]) -> str:
    for row in team_rows:
        for value in row:
            if isinstance(value, str) and value.startswith("Exported on "):
                return value
    return "Export date unavailable"


# --- Raw sheets --------------------------------------------------------------


def _read_employees(rows: list[dict], headers: Sequence[str], dates: list[date]) -> dict[str, Employee]:
    employees: dict[str, Employee] = {}
    positions: dict[str, set[str]] = defaultdict(set)
    break_columns = [h for h in headers if h.endswith(" Start") or h.endswith(" End")]
    for cells in rows:
        where = f"{TIMESHEETS} row {cells['_row']}"
        when = cells["Date"]
        if not isinstance(when, datetime) or when.date() not in dates:
            raise UnsupportedExport(f"{where}: date outside the reporting week, or invalid.")
        day = when.date()
        if cells["Day"] != day.strftime("%A"):
            raise UnsupportedExport(f"{where}: weekday disagrees with date.")
        code, name = _text(cells["Member Code"]), _text(cells["Full Name"])
        if not code or not name:
            raise UnsupportedExport(f"{where}: missing member code or name; cannot safely match the employee.")
        employee = employees.setdefault(code, Employee(code, name))
        if employee.name != name:
            raise UnsupportedExport(f"{where}: conflicting names for member code {code}.")
        if day in employee.days:
            raise UnsupportedExport(f"{where}: duplicate employee/date {code} {day}.")
        if any(cells.get(column) not in (None, "") for column in break_columns):
            raise UnsupportedExport(BREAK_MODEL_MESSAGE)
        positions[code].add(_text(cells["Position"]))
        for column in ("First In", "Last Out"):
            if cells[column] is not None and not isinstance(cells[column], datetime):
                raise UnsupportedExport(f"{where}: unsupported timestamp in {column}.")
        employee.days[day] = DayRecord(
            day=day,
            row=cells["_row"],
            metrics={metric: _minutes(cells[metric], f"{where}, {metric}") for metric in METRICS},
            first_in=cells["First In"],
            last_out=cells["Last Out"],
        )
    for code, employee in employees.items():
        if len(positions[code]) > 1:
            raise UnsupportedExport(f"{code}: conflicting position values in the week.")
        employee.position = next(iter(positions[code]))
    return employees


def _attach_punches(employees: dict[str, Employee], rows: list[dict], dates: list[date]) -> str:
    """Attach In/Out punches to each employee's days. Returns the single timezone."""
    punches: dict[tuple[str, date], list[Punch]] = defaultdict(list)
    zones = set()
    for cells in rows:
        where = f"{ENTRIES} row {cells['_row']}"
        code, when, time = _text(cells["Member Code"]), cells["Date"], cells["Time"]
        kind = _text(cells["Entry Type"])
        if "break" in kind.casefold():
            raise UnsupportedExport(BREAK_MODEL_MESSAGE)
        if kind not in ("In", "Out"):
            raise UnsupportedExport(f"{where}: unsupported entry type {kind!r}.")
        if (
            code not in employees
            or not isinstance(when, datetime)
            or when.date() not in dates
            or not isinstance(time, datetime)
        ):
            raise UnsupportedExport(f"{where}: unknown employee or date, or missing timestamp.")
        if _text(cells["Full Name"]) != employees[code].name:
            raise UnsupportedExport(f"{where}: employee name disagrees with {TIMESHEETS}.")
        zones.add(_text(cells["Timezone"]))
        punches[(code, when.date())].append(Punch(kind, time, _text(cells.get("Notes")), cells["_row"]))
    if len(zones) > 1 or "" in zones:
        raise UnsupportedExport("Mixed or missing punch timezones need review before a report can be made.")
    for (code, day), day_punches in punches.items():
        record = employees[code].days.setdefault(day, DayRecord(day=day))
        record.punches = sorted(day_punches, key=lambda p: (p.time, p.row))
    return next(iter(zones), "No punches")


# --- Cross-checks ------------------------------------------------------------


def _check_days(employee: Employee, dates: list[date]) -> None:
    if not employee.has_position:
        employee.notes.append("Position is missing in Jibble.")
    for day in dates:
        record = employee.days.setdefault(day, DayRecord(day=day))
        issues = record.issues
        if record.row is None:
            issues.append("Daily source row is missing.")
        punches = record.punches
        if len({(p.time, p.kind) for p in punches}) != len(punches):
            issues.append("Duplicate raw punch event.")
        if any(p.time.date() != day for p in punches):
            issues.append("Punch crosses date boundary; review raw entries.")
        sessions, problems = pair_punches(punches)
        issues.extend(problems)
        starts = [s.start for s in sessions if s.start]
        ends = [s.end for s in sessions if s.end]
        if record.first_in != (starts[0] if starts else None):
            issues.append("First In disagrees with raw punch events.")
        if record.last_out != (ends[-1] if ends else None):
            issues.append("Last Out disagrees with raw punch events.")
        if record.first_in and record.last_out and record.last_out < record.first_in:
            issues.append("Last out is earlier than first in.")
        for metric in METRICS:
            if record.metrics.get(metric) is None:
                issues.append(f"{metric} is missing.")
        if record.metrics.get("Payroll Hours") and not punches:
            issues.append("Payroll hours have no raw punch events; review adjustments/time off.")
        if any(record.metrics.get(metric) for metric in BREAKS):
            issues.append("Break duration exists without recorded break timestamps.")
        record.issues = list(dict.fromkeys(issues))
    silent = sum(not employee.days[day].punches for day in dates[:5])
    if silent:
        employee.notes.append(f"No punches recorded on {silent} of 5 weekdays. Reason is not supplied.")


def _individual_sheets(workbook) -> dict[str, list]:
    """Find employee summary sheets by their Member/Code labels; sheet names get truncated."""
    sheets: dict[str, list] = defaultdict(list)
    for sheet in workbook.worksheets:
        if sheet.title in (TIMESHEETS, ENTRIES, TEAM):
            continue
        labels = {_text(row[0]): row[1] for row in _values(sheet)[:10] if len(row) > 1}
        if "Member" in labels and "Code" in labels:
            sheets[_text(labels["Code"])].append(sheet)
    return sheets


def _check_individual_sheets(workbook, employees: dict[str, Employee], dates: list[date], checks: list[Check]) -> None:
    sheets = _individual_sheets(workbook)
    unknown = set(sheets) - set(employees)
    if unknown:
        raise UnsupportedExport(f"Individual summary for an unknown member code: {', '.join(sorted(unknown))}.")
    for code, employee in employees.items():
        if len(sheets.get(code, [])) != 1:
            raise UnsupportedExport(f"{code}: missing or duplicate individual summary sheet.")
        _check_individual_sheet(sheets[code][0], employee, dates, checks)


def _check_individual_sheet(sheet, employee: Employee, dates: list[date], checks: list[Check]) -> None:
    rows = _values(sheet)
    required = ["DATE", "FIRST IN", "LAST OUT", *INDIVIDUAL_LABELS.values()]
    header_index, names = _find_header(rows, required, sheet.title)
    columns = {name: names.index(name) for name in required}
    daily: dict[date, tuple] = {}
    total_row = None
    for row in rows[header_index + 1 :]:
        if any(_text(value) == "Total Hours" for value in row):
            total_row = row
            break
        when = row[columns["DATE"]]
        if isinstance(when, datetime):
            daily[when.date()] = row
    if set(daily) != set(dates) or total_row is None:
        raise UnsupportedExport(f"{sheet.title}: unexpected daily date layout.")
    for day in dates:
        record = employee.days[day]
        row = daily[day]
        for metric, label in INDIVIDUAL_LABELS.items():
            value = _minutes(row[columns[label]], f"{sheet.title} {day} {label}")
            if value != record.metrics.get(metric):
                record.issues.append(f"{label} differs from individual summary.")
        if (row[columns["FIRST IN"]] or None) != record.first_in:
            record.issues.append("FIRST IN differs from individual summary.")
        if (row[columns["LAST OUT"]] or None) != record.last_out:
            record.issues.append("LAST OUT differs from individual summary.")
    for metric, label in INDIVIDUAL_LABELS.items():
        stated = _minutes(total_row[columns[label]], f"{sheet.title} total {label}")
        check = Check(f"{employee.code} {label} daily sum vs individual total", employee.total(metric), stated)
        checks.append(check)
        if not check.match:
            employee.notes.append(f"{label} individual total differs from the daily sum.")


def _check_team_summary(team_rows: Sequence[tuple], employees: dict[str, Employee], checks: list[Check]) -> None:
    header_index, names = _find_header(team_rows, ["MEMBER CODE", "TYPE", "TOTALS"], TEAM)
    code_column, type_column, total_column = names.index("MEMBER CODE"), names.index("TYPE"), names.index("TOTALS")
    body = [row for row in team_rows[header_index + 1 :] if len(row) > total_column]

    stated: dict[str, Optional[int]] = {}
    for row in body:
        if row[type_column] == "Payroll Hours":
            code = _text(row[code_column])
            if code in stated:
                raise UnsupportedExport(f"Duplicate employee in {TEAM}: {code}.")
            stated[code] = _team_minutes(row[total_column], f"{TEAM} total for {code}")
    if set(stated) != set(employees):
        raise UnsupportedExport(f"Employee roster differs between {TEAM} and {TIMESHEETS}.")
    for code, value in stated.items():
        check = Check(f"{code} payroll vs Team Summary employee total", employees[code].total("Payroll Hours"), value)
        checks.append(check)
        if not check.match:
            employees[code].notes.append("Payroll differs from Team Summary employee total.")

    for metric, label in TEAM_LABELS.items():
        matches = [row for row in body if row[type_column] == label]
        if len(matches) != 1:
            raise UnsupportedExport(f"{TEAM}: missing total for {label}.")
        team_total = _team_minutes(matches[0][total_column], f"{TEAM} {label}")
        employee_sum = weekly_total(e.total(metric) for e in employees.values())
        checks.append(Check(f"Team {label}: employee sum vs Jibble team total", employee_sum, team_total))


def _check_calculated_gross(employees: dict[str, Employee], dates: list[date], checks: list[Check]) -> None:
    for employee in employees.values():
        if not employee.has_position:
            continue
        for day in dates:
            record = employee.days[day]
            if record.punches:
                checks.append(
                    Check(
                        f"{employee.code} {day}: calculated gross vs Jibble payroll",
                        record.hours.gross,
                        record.metrics.get("Payroll Hours"),
                    )
                )
