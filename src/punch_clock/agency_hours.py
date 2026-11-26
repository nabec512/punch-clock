"""Each staffing agency's hours for a two-week pay period, from the supervisors' returned review files.

Agency staff are paid every two weeks, while supervisors review a week at a time. So this reads
both weeks' returned review files again each time, rather than keeping anything between weeks, and
a correction made after the first week is included. Each week's regular and overtime hours are
the ones that week's file approved: overtime is worked out a week at a time, so the two weeks'
figures are added, never worked out again together.

Accounting points it at a folder, and every review file in it or below it from the pay period's two
weeks is read. A file found twice, or a file with mistakes that touch an agency employee's hours,
stops the run with a plain message. Anything that may still need a look, such as a supervisor whose
file is there for one week and not the other, is listed when the files are made.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Optional

import openpyxl

from punch_clock import settings
from punch_clock.agency_workbook import write_agency_workbook
from punch_clock.approved_hours import ApprovedEmployee, ApprovedFile, read_approved_hours
from punch_clock.assignments import safe_file_name
from punch_clock.jibble_export import UnsupportedExport
from punch_clock.review_workbook import COMPANY, DATA_SHEET, REVIEW_SHEET, WEEK_START
from punch_clock.settings import PERIOD_DAYS, Agency, organization_key

FOLDER_PREFIX = "Agency hours"
WEEKS = 2
LABEL_ROWS = 10  # the data sheet's labels are all within its first rows


@dataclass(frozen=True)
class AgencyWeek:
    regular: int = 0  # minutes
    overtime: int = 0
    lunch_days: int = 0  # scheduled days with approved hours, each charged a lunch


@dataclass(frozen=True)
class AgencyEmployee:
    name: str  # as the agency knows them
    code: str  # Jibble member code
    organization: str
    weeks: tuple[AgencyWeek, ...]  # one per week of the pay period, in order
    reviewed: bool  # marked Reviewed by the supervisor in every week they're in


@dataclass(frozen=True)
class AgencyReport:
    agency: Agency
    paid_by: str  # the company sending the hours
    start: date  # the Monday the pay period starts
    lunch_per_day: float
    employees: tuple[AgencyEmployee, ...]

    @property
    def week_starts(self) -> tuple[date, ...]:
        return tuple(self.start + timedelta(days=7 * week) for week in range(WEEKS))

    @property
    def end(self) -> date:
        return self.start + timedelta(days=PERIOD_DAYS - 1)


@dataclass(frozen=True)
class AgencyResult:
    folder: Path
    start: date
    reports: tuple[tuple[AgencyReport, Path], ...]
    files: tuple[ApprovedFile, ...]  # the review files read
    warnings: tuple[str, ...]  # worth a look before the hours are sent, but they don't stop them

    @property
    def end(self) -> date:
        return self.start + timedelta(days=PERIOD_DAYS - 1)


def day_label(day: date) -> str:
    return f"{day:%b} {day.day}"


def period_label(start: date) -> str:
    end = start + timedelta(days=PERIOD_DAYS - 1)
    return f"Mon {day_label(start)} to Sun {day_label(end)}, {end.year}"


def _peek(path: Path) -> Optional[tuple[str, date]]:
    """The organization and week of a review file, read quickly, or None if it isn't one."""
    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception:  # not an Excel file Punch Clock can open, so not a review file
        return None
    try:
        if DATA_SHEET not in workbook.sheetnames or REVIEW_SHEET not in workbook.sheetnames:
            return None
        labels = {}
        for row in workbook[DATA_SHEET].iter_rows(max_row=LABEL_ROWS, max_col=2, values_only=True):
            if row and row[0] in (COMPANY, WEEK_START):
                labels[row[0]] = row[1] if len(row) > 1 else None
        return str(labels[COMPANY] or ""), date.fromisoformat(str(labels[WEEK_START]))
    except (KeyError, TypeError, ValueError):
        return None
    finally:
        workbook.close()


def find_review_files(folder: Path, weeks: Iterable[date]) -> list[Path]:
    """Every review file in ``folder`` or below it from these weeks. Excel's own lock files are left out."""
    weeks = set(weeks)
    found = []
    for path in sorted(folder.rglob("*.xlsx")):
        if path.name.startswith("~$") or not path.is_file():
            continue
        about = _peek(path)
        if about and about[1] in weeks:
            found.append(path)
    return found


def _name(path: Path, folder: Path) -> str:
    try:
        return str(path.relative_to(folder))
    except ValueError:
        return str(path)


def _check_twice(files: list[ApprovedFile], folder: Path) -> None:
    """The same supervisor's file, or the same employee, twice in a week would pay those hours twice."""
    seen: dict[tuple, ApprovedFile] = {}
    for file in files:
        for key, what in (
            ((organization_key(file.company), file.start, file.group.casefold()), f"{file.group}'s file"),
            *(
                ((organization_key(file.company), file.start, employee.code.casefold()), employee.name)
                for employee in file.employees
            ),
        ):
            other = seen.setdefault(key, file)
            if other is not file:
                raise UnsupportedExport(
                    f"{what} for the week of {day_label(file.start)} is in two files:\n\n"
                    f"{_name(other.path, folder)}\n{_name(file.path, folder)}\n\n"
                    "Keep only the one the supervisor sent back in this folder, then try again."
                )


def _missing_weeks(files: list[ApprovedFile], weeks: tuple[date, ...]) -> list[str]:
    """A supervisor with a file for one week and not the other may have had one left out."""
    found: dict[tuple[str, str], set[date]] = {}
    for file in files:
        found.setdefault((file.company, file.group), set()).add(file.start)
    return [
        f"{group} ({company}) has no file for the week of {day_label(week)}."
        for (company, group), have in found.items()
        for week in weeks
        if week not in have
    ]


def _lunch_days(employee: ApprovedEmployee) -> int:
    """A day off, such as weekend hours, has no lunch."""
    return sum(1 for day in employee.days if day.total and day.full_minutes > 0)


def collect(files: list[ApprovedFile], current: settings.Settings, start: date, folder: Path) -> tuple[list[AgencyReport], list[str]]:
    """Each agency's report for the pay period, one per company sending hours, and the warnings to show."""
    weeks = tuple(start + timedelta(days=7 * week) for week in range(WEEKS))
    _check_twice(files, folder)
    problems: list[str] = []
    unlinked: list[str] = []
    people: dict[tuple[str, str], dict] = {}  # by organization and member code
    for file in sorted(files, key=lambda f: f.start):
        organization = current.organization(file.company)
        agency_staff = []
        for employee in file.employees:
            link = organization.pay_link(employee.code)
            if link is None:
                if current.links_pay:
                    unlinked.append(f"{employee.name} ({employee.code}, {file.company})")
                continue
            if link.agency:
                agency_staff.append((employee, link))
        if agency_staff and file.problems:
            problems += [f"{_name(file.path, folder)}:", *(f"  {problem}" for problem in file.problems)]
            continue
        for employee, link in agency_staff:
            person = people.setdefault(
                (organization_key(file.company), employee.code.casefold()),
                {"link": link, "employee": employee, "organization": organization, "weeks": {}, "reviewed": True},
            )
            person["weeks"][file.start] = AgencyWeek(employee.regular or 0, employee.overtime or 0, _lunch_days(employee))
            person["reviewed"] = person["reviewed"] and employee.reviewed
    if problems:
        raise UnsupportedExport(
            "These supervisor files have hours that can't be used yet, and agency staff are in them. "
            "Fix these in the files, save them, and try again:\n\n" + "\n".join(problems)
        )
    if not people:
        raise UnsupportedExport(
            f"No one in the supervisors' files for {period_label(start)} works through an agency, so there's nothing to send."
        )

    grouped: dict[tuple[str, str], list[AgencyEmployee]] = {}
    not_reviewed = []
    for person in people.values():
        link, employee, organization = person["link"], person["employee"], person["organization"]
        grouped.setdefault((link.agency, organization.agencies_paid_by), []).append(
            AgencyEmployee(
                link.name,
                employee.code,
                organization.name,
                tuple(person["weeks"].get(week, AgencyWeek()) for week in weeks),
                person["reviewed"],
            )
        )
        if not person["reviewed"]:
            not_reviewed.append(link.name)
    reports = [
        AgencyReport(
            current.agencies[agency],
            paid_by,
            start,
            current.agency_pay.lunch_per_day,
            tuple(sorted(employees, key=lambda e: (e.name.casefold(), e.code))),
        )
        for (agency, paid_by), employees in sorted(grouped.items())
    ]
    warnings = _missing_weeks(files, weeks)
    if not_reviewed:
        warnings.append(f"Not marked Reviewed by their supervisor: {', '.join(sorted(not_reviewed, key=str.casefold))}.")
    if unlinked:
        warnings.append(
            "The settings file doesn't say who pays these people, so they're left out. If any of them are with an agency, "
            f"add them under employees and make the files again: {', '.join(unlinked)}."
        )
    return reports, warnings


def file_name(report: AgencyReport, reports: list[AgencyReport]) -> str:
    """Named for the company sending the hours too, when the agency has people from more than one."""
    senders = {r.paid_by for r in reports if r.agency == report.agency}
    sender = f" from {report.paid_by}" if len(senders) > 1 else ""
    return safe_file_name(f"{report.agency.name}{sender} {report.start} to {report.end}") + ".xlsx"


def _new_folder(parent: Path, name: str) -> Path:
    candidate, number = parent / name, 2
    while candidate.exists() or candidate.with_name(candidate.name + ".tmp").exists():
        candidate = parent / f"{name} ({number})"
        number += 1
    return candidate


def make_agency_hours(folder: str | Path, today: Optional[date] = None) -> AgencyResult:
    """Read the latest pay period that has ended before ``today`` from ``folder``, and write each agency's file there."""
    folder = Path(folder)
    current = settings.load()
    if not current.agencies or current.agency_pay is None:
        raise UnsupportedExport(
            f"The settings file doesn't list any agencies yet, so there's no one to send hours to:\n\n{current.path}"
        )
    start = current.agency_pay.period_before(today or date.today())
    weeks = tuple(start + timedelta(days=7 * week) for week in range(WEEKS))
    paths = find_review_files(folder, weeks)
    if not paths:
        raise UnsupportedExport(
            f"There are no supervisor review files for {period_label(start)} in this folder or the folders inside it:"
            f"\n\n{folder}\n\nChoose the folder that holds the files the supervisors sent back for those two weeks."
        )
    files = [read_approved_hours(path) for path in paths]
    reports, warnings = collect(files, current, start, folder)
    if current.note:
        warnings.insert(0, current.note)

    output = _new_folder(folder, f"{FOLDER_PREFIX} {start} to {start + timedelta(days=PERIOD_DAYS - 1)}")
    building = output.with_name(output.name + ".tmp")
    building.mkdir()
    written = []
    try:
        for report in reports:
            name = file_name(report, reports)
            write_agency_workbook(report, building / name)
            written.append((report, output / name))
        building.rename(output)
    except BaseException:
        shutil.rmtree(building, ignore_errors=True)
        raise
    return AgencyResult(output, start, tuple(written), tuple(files), tuple(warnings))
