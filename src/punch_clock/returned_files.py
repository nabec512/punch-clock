"""Find and check the supervisors' returned review files in a folder, for payroll and the agencies.

Accounting keeps the returned files wherever suits them, so each step is pointed at a folder
and reads every review file in it, or in the folders inside it, from the weeks it needs. Other
spreadsheets, and Excel's own lock files, are skipped. The same supervisor's file, or the same
employee, found twice in one week would pay those hours twice, so that's refused.

A file left out would leave people unpaid without a word, so nothing is skipped quietly that
might be one of the files wanted. A spreadsheet that can't be opened, such as one with a
password or saved in the old .xls format, or a review file from before Punch Clock could read
them back, stops the run if its name has one of the weeks' dates in it, as review files' names
do, and is listed otherwise. A supervisor in the settings file with no file for a week is listed.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Union

import openpyxl

from punch_clock import reports, settings
from punch_clock.approved_hours import FIRST_READABLE_VERSION, ApprovedFile, read_approved_hours
from punch_clock.jibble_export import UnsupportedExport
from punch_clock.review_workbook import COMPANY, DATA_SHEET, REVIEW_SHEET, WEEK_START
from punch_clock.settings import organization_key

LABEL_ROWS = 10  # the data sheet's labels are all within its first rows
SPREADSHEETS = (".xlsx", ".xlsm", ".xls")
UNREADABLE, TOO_OLD = "unreadable", "too old"


def day_label(day: date) -> str:
    return f"{day:%b} {day.day}"


def week_label(start: date) -> str:
    end = start + timedelta(days=6)
    return f"Mon {day_label(start)} to Sun {day_label(end)}, {end.year}"


def _peek(path: Path) -> Union[tuple[str, date], str, None]:
    """The organization and week of a review file, read quickly.

    UNREADABLE if it can't be opened, TOO_OLD if it's a review file Punch Clock can't read back,
    and None if it's some other spreadsheet.
    """
    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception:  # a password, the old .xls format, a damaged file, or one open in Excel
        return UNREADABLE
    try:
        if REVIEW_SHEET not in workbook.sheetnames:
            return None
        if DATA_SHEET not in workbook.sheetnames:
            return TOO_OLD
        labels = {}
        for row in workbook[DATA_SHEET].iter_rows(max_row=LABEL_ROWS, max_col=2, values_only=True):
            if row and row[0] in (COMPANY, WEEK_START):
                labels[row[0]] = row[1] if len(row) > 1 else None
        return str(labels[COMPANY] or ""), date.fromisoformat(str(labels[WEEK_START]))
    except Exception:
        return UNREADABLE
    finally:
        workbook.close()


def find_review_files(folder: Path, weeks: Iterable[date]) -> tuple[list[Path], list[Path], list[Path]]:
    """Every review file in ``folder`` or below it from these weeks, and the spreadsheets that couldn't be read.

    Those are split into the ones that may be from these weeks, as their names have one of the
    weeks' dates in them, and the rest.
    """
    weeks = set(weeks)
    dates = {week.isoformat() for week in weeks}
    found, wanted_unreadable, other_unreadable = [], [], []
    for path in sorted(folder.rglob("*")):
        if path.suffix.casefold() not in SPREADSHEETS or path.name.startswith("~$") or not path.is_file():
            continue
        about = _peek(path)
        if isinstance(about, tuple):
            if about[1] in weeks:
                found.append(path)
        elif about is not None:
            (wanted_unreadable if any(day in path.name for day in dates) else other_unreadable).append(path)
    return found, wanted_unreadable, other_unreadable


def shown_path(path: Path, folder: Path) -> str:
    """A file's path as the person who chose ``folder`` would look for it."""
    try:
        return str(path.relative_to(folder))
    except ValueError:
        return str(path)


def check_twice(files: list[ApprovedFile], folder: Path) -> None:
    """The same supervisor's file, or the same employee, twice in a week would pay those hours twice."""
    seen: dict[tuple, ApprovedFile] = {}
    for file in files:
        for key, what in (
            (("group", organization_key(file.company), file.start, file.group.casefold()), f"{file.group}'s file"),
            *(
                (("employee", organization_key(file.company), file.start, employee.code.casefold()), employee.name)
                for employee in file.employees
            ),
        ):
            other = seen.setdefault(key, file)
            if other is not file:
                raise UnsupportedExport(
                    f"{what} for the week of {day_label(file.start)} is in two files:\n\n"
                    f"{shown_path(other.path, folder)}\n{shown_path(file.path, folder)}\n\n"
                    "Keep only the one the supervisor sent back in this folder, then try again."
                )


def read_returned_files(folder: Path, weeks: tuple[date, ...], period: str) -> tuple[list[ApprovedFile], list[str]]:
    """Every review file for these weeks, read and checked for duplicates, and the warnings about what was skipped.

    ``period`` names the weeks in messages.
    """
    paths, wanted_unreadable, other_unreadable = find_review_files(folder, weeks)
    if wanted_unreadable:
        raise UnsupportedExport(
            f"These files may be supervisor files for {period}, but Punch Clock can't read them:\n\n"
            + "\n".join(shown_path(path, folder) for path in wanted_unreadable)
            + "\n\nIf one is open in Excel, close it. If it has a password or was saved as another type of file, open it "
            "in Excel and save it as an Excel Workbook (.xlsx) without a password. A review file made before "
            f"Punch Clock {FIRST_READABLE_VERSION} can't be read back, so its hours are entered by hand. "
            "Otherwise, move the file out of this folder. Then try again."
        )
    if not paths:
        raise UnsupportedExport(
            f"There are no supervisor review files for {period} in this folder or the folders inside it:"
            f"\n\n{folder}\n\nChoose the folder that holds the files the supervisors sent back for that time."
        )
    files = [read_approved_hours(path) for path in paths]
    check_twice(files, folder)
    warnings = []
    if other_unreadable:
        warnings.append(
            "These spreadsheets couldn't be opened, so they were skipped. Check none of them is a supervisor's file for "
            f"this time: {', '.join(shown_path(path, folder) for path in other_unreadable)}."
        )
    return files, warnings


def missing_files(files: list[ApprovedFile], current: settings.Settings, weeks: tuple[date, ...]) -> list[str]:
    """Each organization with no files for a week, and each supervisor in the settings file with no file for a week.

    A supervisor with nobody in their departments that week has no file, so this can only be a warning.
    """
    found: dict[tuple[str, date], set[str]] = {}
    for file in files:
        found.setdefault((organization_key(file.company), file.start), set()).add(file.group.casefold())
    warnings = []
    for key, organization in current.organizations.items():
        supervisors = sorted({name for name in organization.supervisors.values() if name}, key=str.casefold)
        for week in weeks:
            groups = found.get((key, week))
            if groups is None:
                warnings.append(f"There are no files from {organization.name} for the week of {day_label(week)}.")
                continue
            missing = [name for name in supervisors if name.casefold() not in groups]
            if missing:
                warnings.append(
                    f"No file from {', '.join(missing)} ({organization.name}) for the week of {day_label(week)}. "
                    "If they had people that week, their hours are missing."
                )
    return warnings


def check_output(folder: Path, names: list[str]) -> None:
    """Before writing: two names that came out the same would overwrite each other, and Excel can't open long paths."""
    seen: dict[str, str] = {}
    for name in names:
        if name.casefold() in seen:
            raise UnsupportedExport(
                f'Two files would both be called "{name}", because Windows doesn\'t allow some characters in file names. '
                "Change one of the names in the settings file so they differ in more than punctuation."
            )
        seen[name.casefold()] = name
    longest = max((folder / name for name in names), key=lambda path: len(str(path)), default=folder)
    if len(str(longest.absolute())) > reports.EXCEL_PATH_LIMIT:
        raise UnsupportedExport(
            "This folder's location is too long for Windows and Excel to open the files. Move the supervisors' files "
            "somewhere simpler, such as Documents, and try again."
        )


def new_folder(parent: Path, name: str) -> Path:
    """Never reuse a folder: what's in it may already have been sent."""
    candidate, number = parent / name, 2
    while candidate.exists() or candidate.with_name(candidate.name + ".tmp").exists():
        candidate = parent / f"{name} ({number})"
        number += 1
    return candidate
