"""Each payroll's PowerPay timesheet import file for one week, from the supervisors' returned review files.

Accounting chooses a week, by default the last full week, and every review file received for it
(or, with no accounting folder, every one in a chosen folder or below it) is read again. Everyone in those files must be linked to a payroll or an agency in the settings
file. Agency staff are left out, as they're paid every two weeks, and everyone else goes in their
payroll's file, which can draw on several Jibble organizations.

A PowerPay import replaces all the timesheet entries in the payroll run for each employee it
lists, so each file holds each person's complete hours for the week: a line of regular hours and,
if any, a line of overtime. Someone with no hours that week isn't listed, so nothing keyed for them
by hand is deleted. Accounting imports these before keying holidays, sick days and vacation.

Anything that would make a file wrong stops the run, and nothing is written: someone not linked,
a file found twice, or a file with hours that can't be used yet. A summary beside the files gives
each payroll's people and totals, to check against PowerPay after the import.
"""
from __future__ import annotations

import csv
import re
import shutil
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Optional

from punch_clock import archive, settings
from punch_clock.approved_hours import ApprovedFile
from punch_clock.assignments import safe_file_name
from punch_clock.jibble_export import UnsupportedExport
from punch_clock.returned_files import check_output, missing_files, new_folder, read_returned_files, shown_path, week_label

FOLDER_PREFIX = "Payroll files"
RECENT_WEEKS = 8  # the weeks offered when it can't be known which have files received
# The columns of the import template set up in PowerPay. They must match it exactly.
# employee_name is left unmatched, so PowerPay ignores it: it's there so accounting can tell who each line is.
COLUMNS = ("employee_name", "employee_number", "earning_code", "hours", "applicable_period")
# Letters that don't come apart into a plain letter and an accent.
PLAIN_LETTERS = str.maketrans({
    "ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D", "ß": "ss", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE",
})
REGULAR_CODE, OVERTIME_CODE = "RT", "OT"  # PowerPay's earning codes, the same on every payroll
WEEKLY = "1"  # PowerPay's applicable period for part or all of one week


@dataclass(frozen=True)
class PayrollLine:
    name: str  # as the payroll knows them
    number: str  # their employee number in that payroll
    regular: int  # minutes
    overtime: int
    organization: str  # the Jibble organization they punch in, for the summary


@dataclass(frozen=True)
class PayrollFile:
    payroll: str
    path: Path
    lines: tuple[PayrollLine, ...]

    @property
    def regular(self) -> int:
        return sum(line.regular for line in self.lines)

    @property
    def overtime(self) -> int:
        return sum(line.overtime for line in self.lines)


@dataclass(frozen=True)
class PayrollResult:
    folder: Path
    start: date
    run: Optional[str]  # the payroll button's name, or None for every organization
    payrolls: tuple[PayrollFile, ...]
    summary: Path
    files: tuple[ApprovedFile, ...]  # the review files read
    warnings: tuple[str, ...]


def last_full_week(today: date) -> date:
    """The Monday of the latest Monday-to-Sunday week that has ended before ``today``."""
    return today - timedelta(days=today.weekday() + 7)


def is_over(start: date, days: int, today: date) -> bool:
    """Whether the ``days`` from ``start`` have all gone by before ``today``."""
    return today >= start + timedelta(days=days)


def week_choices(today: date, received: Optional[Iterable[date]] = None) -> list[date]:
    """The weeks accounting can choose from, newest first: those with files received, or, when that can't be known,
    the last RECENT_WEEKS. The last full week is always one, as it's the usual choice, and a week yet to start never is.
    """
    this_week = last_full_week(today) + timedelta(days=7)
    if received is None:
        return [this_week - timedelta(days=7 * week) for week in range(RECENT_WEEKS)]
    weeks = {last_full_week(today), *(week for week in received if week.weekday() == 0 and week <= this_week)}
    return sorted(weeks, reverse=True)


def not_over_warning(what: str) -> str:
    return (
        f"{what} isn't over yet, so these files only have the hours in the supervisors' files so far. Make them again "
        "once it's over and the final files are received."
    )


def plain_name(name: str) -> str:
    """A name in plain letters, digits, spaces, hyphens and apostrophes, as PowerPay's import says nothing about
    accents or quoted commas: "ŻAK, ŁUCJA" becomes "ZAK LUCJA"."""
    letters = unicodedata.normalize("NFKD", name.translate(PLAIN_LETTERS))
    ascii_only = letters.encode("ascii", "ignore").decode("ascii")
    kept = re.sub(r"[^A-Za-z0-9 '\-]", " ", ascii_only)
    return " ".join(kept.split())


def hours_text(minutes: int) -> str:
    """Decimal hours, as PowerPay takes them. Paid hours are in 15-minute blocks, so two places are exact."""
    return f"{minutes / 60:.2f}"


def collect(
    files: list[ApprovedFile], current: settings.Settings, folder: Path, payrolls: tuple[str, ...]
) -> tuple[dict[str, list[PayrollLine]], list[str]]:
    """Everyone's hours by payroll, and the warnings to show. Stops on anything that would make a file wrong."""
    unlinked: list[str] = []
    problems: list[str] = []
    by_payroll: dict[str, list[PayrollLine]] = {payroll: [] for payroll in payrolls}
    for file in files:
        organization = current.organization(file.company)
        paid_here = []
        for employee in file.employees:
            link = organization.pay_link(employee.code)
            if link is None:
                unlinked.append(f"{employee.name} ({employee.code}, {file.company})")
            elif link.payroll:
                paid_here.append((employee, link))
        # Only the payroll staff's own problems matter here. Agency staff's are for the agency files.
        found = [problem for employee, _ in paid_here for problem in employee.problems]
        if found:
            problems += [f"{shown_path(file.path, folder)}:", *(f"  {problem}" for problem in found)]
            continue
        for employee, link in paid_here:
            by_payroll[link.payroll].append(
                PayrollLine(link.name, link.number, employee.regular or 0, employee.overtime or 0, file.company)
            )
    if unlinked:
        raise UnsupportedExport(
            "The settings file doesn't say who pays these people, so the payroll files can't be complete. Add them under "
            "employees, with their payroll and employee number, or their agency, then try again:\n\n" + "\n".join(unlinked)
        )
    if problems:
        raise UnsupportedExport(
            "These supervisor files have payroll staff whose hours can't be used yet. Fix these in the files, save them, "
            "and try again:"
            "\n\n" + "\n".join(problems)
        )
    warnings = _numbers_in_two_places(by_payroll)
    return by_payroll, warnings


def _numbers_in_two_places(by_payroll: dict[str, list[PayrollLine]]) -> list[str]:
    """Someone who moved organization has a member code in each, linked to one employee number. Hours under both in
    one week can't be paid from these files, as each organization's file worked out overtime on its own part of the
    week. So they're left out, which leaves PowerPay's entries for them alone, and listed to enter by hand."""
    warnings = []
    for payroll, lines in by_payroll.items():
        places: dict[int, list[PayrollLine]] = {}
        for line in lines:
            if line.regular or line.overtime:
                places.setdefault(int(line.number), []).append(line)
        for number, found in places.items():
            if len(found) > 1:
                lines[:] = [line for line in lines if int(line.number) != number]
                where = " and ".join(sorted({line.organization for line in found}))
                warnings.append(
                    f"Left out of {payroll}: {found[0].name} ({found[0].number}) has hours this week in both {where}. "
                    "Enter their hours in PowerPay by hand, after the import. If they're two people, give one their own "
                    "number in the settings file."
                )
    return warnings


def _write_csv(path: Path, lines: list[PayrollLine]) -> None:
    # Plain ASCII, with nothing that needs quoting, as the import's handling of anything else isn't documented.
    with open(path, "w", encoding="ascii", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(COLUMNS)
        for line in lines:
            name = plain_name(line.name)
            if line.regular:
                writer.writerow((name, line.number, REGULAR_CODE, hours_text(line.regular), WEEKLY))
            if line.overtime:
                writer.writerow((name, line.number, OVERTIME_CODE, hours_text(line.overtime), WEEKLY))


def summary_text(
    start: date, payrolls: list[PayrollFile], files: list[ApprovedFile], warnings: list[str], folder: Path,
    run: Optional[str] = None,
) -> str:
    lines = [f"{run + ' p' if run else 'P'}ayroll hours for {week_label(start)}", ""]
    lines += ["Hours are decimals: 7.75 is 7 hours 45 minutes. RT is regular hours, OT is overtime.", ""]
    for payroll in payrolls:
        lines.append(
            f"{payroll.payroll}: {len(payroll.lines)} {'person' if len(payroll.lines) == 1 else 'people'}, {hours_text(payroll.regular)} RT, "
            f"{hours_text(payroll.overtime)} OT. File: {payroll.path.name}"
        )
        for line in payroll.lines:
            lines.append(
                f"  {line.number:>6}  {line.name:<30} {hours_text(line.regular):>7} RT {hours_text(line.overtime):>7} OT"
                f"   {line.organization}"
            )
        lines.append("")
    lines += ["Supervisor files read:", *(f"  {shown_path(file.path, folder)}" for file in files)]
    if warnings:
        lines += ["", "To check:", *(f"  {warning}" for warning in warnings)]
    return "\n".join(lines) + "\n"


def _file_name(payroll: str, start: date) -> str:
    return safe_file_name(f"{payroll} {start}") + ".csv"


def make_payroll_files(
    folder: Optional[str | Path] = None, today: Optional[date] = None, run: Optional[str] = None,
    start: Optional[date] = None,
) -> PayrollResult:
    """Read the week starting on the Monday ``start``, by default the last full week before ``today``, and write each
    payroll's import file. A week that isn't over yet is read too, with a warning, as its files may change.

    With the settings file's accounting folder, the files received there are read and the payroll files are made
    there. Otherwise every review file in ``folder`` and below it is read, and they're made in ``folder``.
    ``run`` is one of the settings file's payroll_runs: only its organizations' files are read. Without one, every
    organization's are.
    """
    current = settings.load_full()
    if not current.payrolls:
        raise UnsupportedExport(f"The settings file doesn't list any payrolls yet, so there's no one to pay:\n\n{current.path}")
    if run is not None and run not in current.payroll_runs:
        raise UnsupportedExport(
            f"The settings file no longer has {run} under {settings.PAYROLL_RUNS}. Close Punch Clock and open it again."
        )
    only = set(current.payroll_runs[run]) if run else None
    others = [o.name for key, o in current.organizations.items() if only is not None and key not in only]
    today = today or date.today()
    if start is None:
        start = last_full_week(today)
    elif start.weekday() != 0:
        raise UnsupportedExport(f"A week starts on a Monday, and {start:%A %b} {start.day} isn't one.")
    if start > today:
        raise UnsupportedExport(f"{week_label(start)} hasn't started yet, so there are no hours to pay.")
    if current.accounting_folder is not None:
        files, skipped = archive.read_archive(current, (start,), week_label(start), only)
        folder, parent = current.accounting_folder / archive.RETURNED, archive.output_parent(current, archive.PAYROLL)
    elif folder is None:
        raise UnsupportedExport("Choose the folder with the supervisors' returned files.")
    else:
        folder = parent = Path(folder)
        files, skipped = read_returned_files(folder, (start,), week_label(start), only, others)
    by_payroll, warnings = collect(files, current, folder, current.payrolls_in(run))
    warnings = skipped + missing_files(files, current, (start,), only) + warnings
    if not is_over(start, 7, today):
        warnings.insert(0, not_over_warning(week_label(start)))
    if current.note:
        warnings.insert(0, current.note)
    paid = {payroll: lines for payroll, lines in by_payroll.items() if any(line.regular or line.overtime for line in lines)}
    if not paid:
        raise UnsupportedExport(f"No one paid through a payroll has hours in the supervisors' files for {week_label(start)}.")
    idle = [payroll for payroll in by_payroll if payroll not in paid]
    if idle:
        warnings.append(f"No one has hours this week in: {', '.join(idle)}, so there's no file for it.")
    for payroll in paid:
        shared = [other for other in current.payroll_runs if other != run and payroll in current.payrolls_in(other)]
        if run and shared:
            warnings.append(
                f"{payroll} also pays people in {', '.join(shared)}. Import that file too: each import only replaces "
                "the hours of the people in it."
            )

    label = f"{safe_file_name(run)} " if run else ""
    output = new_folder(parent, f"{FOLDER_PREFIX} {label}{start} to {start + timedelta(days=6)}")
    summary_name = f"Payroll summary {start}.txt"
    check_output(output.with_name(output.name + ".tmp"), [_file_name(payroll, start) for payroll in paid] + [summary_name])
    building = output.with_name(output.name + ".tmp")
    building.mkdir()
    payrolls = []
    try:
        for payroll, lines in paid.items():
            lines = sorted((line for line in lines if line.regular or line.overtime), key=lambda line: int(line.number))
            name = _file_name(payroll, start)
            _write_csv(building / name, lines)
            payrolls.append(PayrollFile(payroll, output / name, tuple(lines)))
        (building / summary_name).write_text(summary_text(start, payrolls, files, warnings, folder, run), encoding="utf-8")
        building.rename(output)
    except BaseException:
        shutil.rmtree(building, ignore_errors=True)
        raise
    return PayrollResult(output, start, run, tuple(payrolls), output / summary_name, tuple(files), tuple(warnings))
