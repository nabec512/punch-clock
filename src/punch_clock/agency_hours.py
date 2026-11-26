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
from typing import Optional

from punch_clock import archive, settings
from punch_clock.agency_workbook import write_agency_workbook
from punch_clock.approved_hours import ApprovedEmployee, ApprovedFile
from punch_clock.assignments import safe_file_name
from punch_clock.jibble_export import UnsupportedExport
from punch_clock.returned_files import check_output, day_label, missing_files, new_folder, read_returned_files, shown_path
from punch_clock.settings import PERIOD_DAYS, Agency, organization_key

FOLDER_PREFIX = "Agency hours"
WEEKS = 2


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


def period_label(start: date) -> str:
    end = start + timedelta(days=PERIOD_DAYS - 1)
    return f"Mon {day_label(start)} to Sun {day_label(end)}, {end.year}"


def _lunch_days(employee: ApprovedEmployee) -> int:
    """A day off, such as weekend hours, has no lunch."""
    return sum(1 for day in employee.days if day.total and day.full_minutes > 0)


def collect(files: list[ApprovedFile], current: settings.Settings, start: date, folder: Path) -> tuple[list[AgencyReport], list[str]]:
    """Each agency's report for the pay period, one per company sending hours, and the warnings to show."""
    weeks = tuple(start + timedelta(days=7 * week) for week in range(WEEKS))
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
        # Only the agency staff's own problems matter here. Payroll staff's are for the payroll files.
        found = [problem for employee, _ in agency_staff for problem in employee.problems]
        if found:
            problems += [f"{shown_path(file.path, folder)}:", *(f"  {problem}" for problem in found)]
            continue
        for employee, link in agency_staff:
            person = people.setdefault(
                (organization_key(file.company), employee.code.casefold()),
                {"link": link, "employee": employee, "organization": organization, "weeks": {}},
            )
            person["weeks"][file.start] = AgencyWeek(employee.regular or 0, employee.overtime or 0, _lunch_days(employee))
    if problems:
        raise UnsupportedExport(
            "These supervisor files have agency staff whose hours can't be used yet. "
            "Fix these in the files, save them, and try again:\n\n" + "\n".join(problems)
        )
    if not people:
        raise UnsupportedExport(
            f"No one in the supervisors' files for {period_label(start)} works through an agency, so there's nothing to send."
        )

    grouped: dict[tuple[str, str], list[AgencyEmployee]] = {}
    for person in people.values():
        link, employee, organization = person["link"], person["employee"], person["organization"]
        grouped.setdefault((link.agency, organization.agencies_paid_by), []).append(
            AgencyEmployee(
                link.name,
                employee.code,
                organization.name,
                tuple(person["weeks"].get(week, AgencyWeek()) for week in weeks),
            )
        )
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
    warnings = missing_files(files, current, weeks)
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


def make_agency_hours(folder: Optional[str | Path] = None, today: Optional[date] = None) -> AgencyResult:
    """Read the latest pay period that has ended before ``today``, and write each agency's file.

    With the settings file's accounting folder, the files received there are read and the agency files are made
    there. Otherwise every review file in ``folder`` and below it is read, and they're made in ``folder``.
    """
    current = settings.load()
    if not current.agencies or current.agency_pay is None:
        raise UnsupportedExport(
            f"The settings file doesn't list any agencies yet, so there's no one to send hours to:\n\n{current.path}"
        )
    start = current.agency_pay.period_before(today or date.today())
    weeks = tuple(start + timedelta(days=7 * week) for week in range(WEEKS))
    if current.accounting_folder is not None:
        files, skipped = archive.read_archive(current, weeks, period_label(start))
        folder, parent = current.accounting_folder / archive.RETURNED, archive.output_parent(current, archive.AGENCY)
    elif folder is None:
        raise UnsupportedExport("Choose the folder with the supervisors' returned files.")
    else:
        folder = parent = Path(folder)
        files, skipped = read_returned_files(folder, weeks, period_label(start))
    reports, warnings = collect(files, current, start, folder)
    warnings = skipped + warnings
    if current.note:
        warnings.insert(0, current.note)

    output = new_folder(parent, f"{FOLDER_PREFIX} {start} to {start + timedelta(days=PERIOD_DAYS - 1)}")
    check_output(output.with_name(output.name + ".tmp"), [file_name(report, reports) for report in reports])
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
