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
from typing import Callable, Optional, Sequence

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException

from punch_clock.hours import DayHours, Punch, Schedule, calculate_day, pair_punches, weekly_total

BREAKS = ["Break Hours (paid)", "Break Hours (unpaid)"]
METRICS = ["Payroll Hours", "Regular Hours", *BREAKS, "Paid Time Off"]
TIMESHEET_COLUMNS = ["Date", "Day", "Full Name", "Member Code", "Position", "First In", "Last Out", *METRICS]
ENTRY_COLUMNS = ["Date", "Full Name", "Member Code", "Entry Type", "Time", "Timezone"]

TIMESHEETS, ENTRIES, TEAM = "Raw Timesheets", "Raw Time Entries", "Team Summary"

ScheduleLookup = Callable[[str, str], Optional[Schedule]]  # by member code and department

# Metric name -> column label on an individual employee summary sheet.
INDIVIDUAL_LABELS = {
    "Payroll Hours": "PAYROLL HRS",
    "Regular Hours": "REG. HRS",
    "Paid Time Off": "PTO",
}
# Metric name -> row label in the Team Summary totals block.
TEAM_LABELS = {
    "Payroll Hours": "Payroll",
    "Regular Hours": "Regular",
}

# "Assembly - Supervisor" belongs to the Assembly department. The tag only suggests who
# supervises it when the department is first set up: the saved supervisor list decides.
SUPERVISOR_POSITION = re.compile(r"^(.+?)\s*[-–—]\s*supervisor\s*$", re.IGNORECASE)

# Practice accounts. Jibble can still list them in an export after they're archived.
TEST_DEPARTMENT = "test"

BREAK_MODEL_MESSAGE = (
    "This file has break punches from Jibble. This app takes off a set lunch time instead, "
    "and it can't do both. Remove the break setting in Jibble, then use a file from a week "
    "after that change."
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
    schedule: Optional[Schedule] = None

    @property
    def hours(self) -> DayHours:
        day_off = self.schedule is not None and self.day.weekday() not in self.schedule.days
        return calculate_day(self.punches, self.row is not None, self.schedule, day_off)


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
    def is_test(self) -> bool:
        return self.department.casefold() == TEST_DEPARTMENT

    @property
    def in_reports(self) -> bool:
        return self.has_position and not self.is_test

    @property
    def has_punches(self) -> bool:
        return any(record.punches for record in self.days.values())

    def total(self, metric: str) -> Optional[int]:
        return weekly_total(record.metrics.get(metric) for record in self.days.values())


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
    # Punches by people the export leaves out, as a position filter in Jibble does.
    skipped_entry_rows: int = 0
    skipped_positions: list[str] = field(default_factory=list)
    supervisors: dict[str, str] = field(default_factory=dict)  # lowercased department to supervisor name
    settings_note: str = ""  # set when the settings came from the copy on this PC

    @property
    def dates(self) -> list[date]:
        return [self.start + timedelta(days=i) for i in range(7)]

    @property
    def included(self) -> list[Employee]:
        """Employees with a recorded position other than Test, by department then name."""
        return sorted(
            (e for e in self.employees if e.in_reports),
            key=lambda e: (e.department.casefold(), e.name.casefold(), e.code),
        )

    @property
    def excluded(self) -> list[Employee]:
        return [e for e in self.employees if not e.has_position]

    @property
    def test_accounts(self) -> list[Employee]:
        return [e for e in self.employees if e.is_test]

    @property
    def review_count(self) -> int:
        return sum(not check.match for check in self.checks)


def _no_schedule(_code: str, _department: str) -> None:
    return None


def load_export(path: str | Path, schedule_for: ScheduleLookup = _no_schedule) -> WeeklyExport:
    path = Path(path)
    data = path.read_bytes()
    try:
        workbook = openpyxl.load_workbook(path, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, KeyError) as error:
        raise UnsupportedExport(f"{path.name} could not be opened. Make sure it's an Excel file.") from error
    return read_workbook(workbook, path.name, hashlib.sha256(data).hexdigest(), schedule_for)


def read_workbook(workbook, source_name: str, digest: str = "", schedule_for: ScheduleLookup = _no_schedule) -> WeeklyExport:
    for sheet in (TIMESHEETS, ENTRIES, TEAM):
        if sheet not in workbook:
            raise UnsupportedExport(f"This file is missing a sheet called {sheet}. Export it from Jibble again with all the options turned on.")
    team_rows = _values(workbook[TEAM])
    timesheet_headers, timesheet_rows = _read_table(workbook[TIMESHEETS], TIMESHEET_COLUMNS)
    entry_headers, entry_rows = _read_table(workbook[ENTRIES], ENTRY_COLUMNS)

    period, start = _read_week(team_rows)
    dates = [start + timedelta(days=i) for i in range(7)]
    employees = _read_employees(timesheet_rows, timesheet_headers, dates)
    timezone, skipped = _attach_punches(employees, entry_rows, dates)

    checks: list[Check] = []
    for employee in employees.values():
        _check_days(employee, dates)
        assign_schedule(employee, schedule_for)
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
        skipped_entry_rows=len(skipped),
        skipped_positions=sorted({_text(c["Position"]) or "(blank)" for c in skipped}, key=str.casefold),
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
            f"{where}: can't read the time {value!r}. In Jibble, export times as hours and minutes (for example, 1h 06m)."
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
            f"{sheet}: some column headings are missing or changed. It needs {', '.join(required)}. "
            "Export it from Jibble again with all the options turned on."
        )
    return found[0]


def _read_table(sheet, required: Sequence[str]) -> tuple[list[str], list[dict]]:
    rows = _values(sheet)
    header_index, names = _find_header(rows, required, sheet.title)
    labels = [name for name in names if name]
    if len(labels) != len(set(labels)):
        raise UnsupportedExport(f"{sheet.title}: two columns have the same heading.")
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
        raise UnsupportedExport(f"{TEAM}: can't tell which week this file covers.") from error
    if first.weekday() != 0 or last - first != timedelta(days=6):
        raise UnsupportedExport("This file must cover one full week, Monday to Sunday. Export it from Jibble again.")
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
            raise UnsupportedExport(f"{where}: this date isn't valid, or it's outside the week.")
        day = when.date()
        if cells["Day"] != day.strftime("%A"):
            raise UnsupportedExport(f"{where}: the day of the week doesn't match the date.")
        code, name = _text(cells["Member Code"]), _text(cells["Full Name"])
        if not code or not name:
            raise UnsupportedExport(f"{where}: the employee's member code or name is missing.")
        employee = employees.setdefault(code, Employee(code, name))
        if employee.name != name:
            raise UnsupportedExport(f"{where}: member code {code} has two different names.")
        if day in employee.days:
            raise UnsupportedExport(f"{where}: employee {code} appears twice for {day}.")
        if any(cells.get(column) not in (None, "") for column in break_columns):
            raise UnsupportedExport(BREAK_MODEL_MESSAGE)
        positions[code].add(_text(cells["Position"]))
        for column in ("First In", "Last Out"):
            if cells[column] is not None and not isinstance(cells[column], datetime):
                raise UnsupportedExport(f"{where}: can't read the time in {column}.")
        employee.days[day] = DayRecord(
            day=day,
            row=cells["_row"],
            metrics={metric: _minutes(cells[metric], f"{where}, {metric}") for metric in METRICS},
            first_in=cells["First In"],
            last_out=cells["Last Out"],
        )
    for code, employee in employees.items():
        if len(positions[code]) > 1:
            raise UnsupportedExport(f"{code} has more than one position this week. Fix this in Jibble, then export again.")
        employee.position = next(iter(positions[code]))
    return employees


def _department_of(position) -> str:
    text = _text(position)
    match = SUPERVISOR_POSITION.match(text)
    return (match[1] if match else text).casefold()


def _outside_export(employees: dict[str, Employee], cells: dict, where: str) -> bool:
    """True for a punch by someone the export leaves out, so it can be skipped.

    Jibble's position filter leaves people out of every sheet except Raw Time Entries.
    Skipping is only safe when that person's whole department is left out: someone missing
    from a department the file does cover would lose hours from that department's report.
    That happens when someone changes position: the filter picks people by their position
    now, but each punch keeps the position they had when they made it.
    """
    code = _text(cells["Member Code"])
    if not code or code in employees:
        return False
    person = f"{_text(cells['Full Name'])} ({code})"
    if "Position" not in cells:
        raise UnsupportedExport(
            f"{where}: {person} has punches but isn't in the {TIMESHEETS} sheet. Export the file from Jibble again."
        )
    covered = {e.department.casefold() for e in employees.values()}
    if _department_of(cells["Position"]) not in covered:
        return True
    raise UnsupportedExport(
        f"{where}: {person} has punches in {_text(cells['Position'])}, but Jibble left them out of the rest "
        "of this file, so their hours would be missing from the reports. This happens when someone's position "
        "in Jibble changes after they punch. Export again with their current position selected too."
    )


def _attach_punches(employees: dict[str, Employee], rows: list[dict], dates: list[date]) -> tuple[str, list[dict]]:
    """Attach In/Out punches to each employee's days.

    Returns the single timezone, and the rows skipped because the export leaves those people out.
    """
    punches: dict[tuple[str, date], list[Punch]] = defaultdict(list)
    zones = set()
    skipped = []
    for cells in rows:
        where = f"{ENTRIES} row {cells['_row']}"
        if _outside_export(employees, cells, where):
            skipped.append(cells)
            continue
        code, when, time = _text(cells["Member Code"]), cells["Date"], cells["Time"]
        kind = _text(cells["Entry Type"])
        if "break" in kind.casefold():
            raise UnsupportedExport(BREAK_MODEL_MESSAGE)
        if kind not in ("In", "Out"):
            raise UnsupportedExport(f"{where}: unknown entry type {kind!r}. Only In and Out can be used.")
        if (
            code not in employees
            or not isinstance(when, datetime)
            or when.date() not in dates
            or not isinstance(time, datetime)
        ):
            raise UnsupportedExport(f"{where}: the employee, date or time is missing or not recognized.")
        if _text(cells["Full Name"]) != employees[code].name:
            raise UnsupportedExport(f"{where}: the employee's name doesn't match the {TIMESHEETS} sheet.")
        zones.add(_text(cells["Timezone"]))
        punches[(code, when.date())].append(Punch(kind, time, _text(cells.get("Notes")), cells["_row"]))
    if len(zones) > 1 or "" in zones:
        raise UnsupportedExport("Some punches have different or missing time zones, so a report can't be made.")
    for (code, day), day_punches in punches.items():
        record = employees[code].days.setdefault(day, DayRecord(day=day))
        record.punches = sorted(day_punches, key=lambda p: (p.time, p.row))
    return next(iter(zones), "No punches"), skipped


# --- Cross-checks ------------------------------------------------------------


def assign_schedule(employee: Employee, schedule_for: ScheduleLookup) -> None:
    """Schedules can be given once the export is read, as they depend on which organization it's from.

    Only paid hours and overtime depend on the schedule, and the cross-checks don't use them.
    """
    schedule = schedule_for(employee.code, employee.department)
    for record in employee.days.values():
        record.schedule = schedule


def assign_schedules(export: WeeklyExport, schedule_for: ScheduleLookup) -> None:
    for employee in export.employees:
        assign_schedule(employee, schedule_for)


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
        issues.extend(pair_punches(punches)[1])
        # Jibble's own columns follow its labels, even on a day where they're swapped.
        ins = [p.time for p in punches if p.kind == "In"]
        outs = [p.time for p in punches if p.kind == "Out"]
        if record.first_in != (ins[0] if ins else None):
            issues.append("First In disagrees with raw punch events.")
        if record.last_out != (outs[-1] if outs else None):
            issues.append("Last Out disagrees with raw punch events.")
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
        raise UnsupportedExport(f"Found an employee sheet for an unknown member code: {', '.join(sorted(unknown))}.")
    for code, employee in employees.items():
        if len(sheets.get(code, [])) != 1:
            raise UnsupportedExport(f"{code}: this employee's own sheet is missing or appears twice.")
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
        raise UnsupportedExport(f"{sheet.title}: the dates aren't laid out as expected.")
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
                raise UnsupportedExport(f"{TEAM}: employee {code} is listed twice.")
            stated[code] = _team_minutes(row[total_column], f"{TEAM} total for {code}")
    if set(stated) != set(employees):
        raise UnsupportedExport(f"The list of employees is different in the {TEAM} and {TIMESHEETS} sheets.")
    for code, value in stated.items():
        check = Check(f"{code} payroll vs Team Summary employee total", employees[code].total("Payroll Hours"), value)
        checks.append(check)
        if not check.match:
            employees[code].notes.append("Payroll differs from Team Summary employee total.")

    for metric, label in TEAM_LABELS.items():
        matches = [row for row in body if row[type_column] == label]
        if len(matches) != 1:
            raise UnsupportedExport(f"{TEAM}: the total for {label} is missing.")
        team_total = _team_minutes(matches[0][total_column], f"{TEAM} {label}")
        employee_sum = weekly_total(e.total(metric) for e in employees.values())
        checks.append(Check(f"Team {label}: employee sum vs Jibble team total", employee_sum, team_total))


def _check_calculated_gross(employees: dict[str, Employee], dates: list[date], checks: list[Check]) -> None:
    for employee in employees.values():
        if not employee.in_reports:
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
