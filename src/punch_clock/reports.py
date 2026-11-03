"""Process a Jibble export. Building the approved report is available from the command line."""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

from pypdf import PdfReader

from punch_clock import supervisor_list
from punch_clock.approvals import ApprovalSet, read_approvals
from punch_clock.assignments import (
    ReviewGroup,
    department_names,
    printable_file_name,
    review_file_name,
    review_groups,
    with_supervisors,
)
from punch_clock.jibble_export import UnsupportedExport, WeeklyExport, load_export
from punch_clock.pdf_report import page_count, render
from punch_clock.review_workbook import write_review_workbook
from punch_clock.summary_workbook import write_summary_workbook
from punch_clock.validation_report import build_validation_text

REVIEW_FOLDER = "Supervisor files"
SOURCE_PREFIX = "Source export "
EXCEL_PATH_LIMIT = 218  # Excel can't open a file whose full path is longer than this


@dataclass(frozen=True)
class ProcessResult:
    export: WeeklyExport
    folder: Path
    pdfs: tuple[Path, ...]  # one per review group
    validation: Path
    groups: tuple[ReviewGroup, ...]


@dataclass(frozen=True)
class ApprovedResult:
    export: WeeklyExport
    approvals: ApprovalSet
    pdf: Path
    summary: Path


def output_folder_name(export: WeeklyExport) -> str:
    return f"Jibble timesheets {export.start} to {export.end}"


def _new_folder(parent: Path, name: str) -> Path:
    """Never reuse a folder: it may already hold supervisors' returned files."""
    candidate = parent / name
    number = 2
    while candidate.exists():
        candidate = parent / f"{name} ({number})"
        number += 1
    return candidate


def _check_path_lengths(folder: Path, export: WeeklyExport, groups: tuple[ReviewGroup, ...]) -> None:
    names = [name(group, export) for group in groups for name in (review_file_name, printable_file_name)]
    longest = max(
        (folder / REVIEW_FOLDER / name for name in names),
        key=lambda path: len(str(path)),
        default=folder / f"Printable timesheets {export.start}.pdf",
    )
    if len(str(longest.absolute())) > EXCEL_PATH_LIMIT:
        raise UnsupportedExport(
            "This folder's location is too long for Windows and Excel to open the reports. "
            "Move the Jibble file somewhere simpler, such as Documents, and try again."
        )


def _write_pdf(
    export: WeeklyExport, path: Path, approvals: Optional[ApprovalSet] = None, group: Optional[ReviewGroup] = None
) -> None:
    """A failed run leaves no partial PDF."""
    pending = path.with_suffix(".pending.pdf")
    try:
        render(export, pending, approvals, group)
        if len(PdfReader(pending).pages) != page_count(export, approvals, group):
            raise ValueError("The PDF did not come out with the expected number of pages.")
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)


def _week_list_name(export: WeeklyExport) -> str:
    return f"Supervisor list {export.start}.json"


def process_export(
    source: str | Path, parent: str | Path | None = None, supervisors: Optional[Mapping[str, str]] = None
) -> ProcessResult:
    """Create the week's output folder beside the export, or inside ``parent``.

    Reviewers come from ``supervisors``, or from the saved list if none are given.
    """
    source = Path(source)
    export = with_supervisors(load_export(source), supervisor_list.load() if supervisors is None else supervisors)
    groups = tuple(review_groups(export))
    folder = _new_folder(Path(parent) if parent else source.parent, output_folder_name(export))
    _check_path_lengths(folder, export, groups)
    # Build under a temporary name so a failed run never looks like a finished folder.
    building = folder.with_name(folder.name + ".tmp")
    if building.exists():
        shutil.rmtree(building)
    (building / REVIEW_FOLDER).mkdir(parents=True)
    # With no groups, a single PDF still explains why no employee could be reported on.
    pdf_names = [Path(REVIEW_FOLDER) / printable_file_name(group, export) for group in groups] or [
        Path(f"Printable timesheets {export.start}.pdf")
    ]
    try:
        if not groups:
            _write_pdf(export, building / pdf_names[0])
        (building / f"Validation {export.start}.txt").write_text(build_validation_text(export), encoding="utf-8")
        shutil.copy2(source, building / f"{SOURCE_PREFIX}{export.start}.xlsx")
        week_list = {name: export.supervisors.get(name.casefold(), "") for name in department_names(export)}
        supervisor_list.write_file(building / _week_list_name(export), week_list)
        for group, pdf_name in zip(groups, pdf_names):
            _write_pdf(export, building / pdf_name, group=group)
            write_review_workbook(export, group, building / REVIEW_FOLDER / review_file_name(group, export))
        building.rename(folder)
    except BaseException:
        shutil.rmtree(building, ignore_errors=True)
        raise
    return ProcessResult(
        export,
        folder,
        tuple(folder / name for name in pdf_names),
        folder / f"Validation {export.start}.txt",
        groups,
    )


def _find_source(folder: Path) -> Path:
    sources = list(folder.glob(f"{SOURCE_PREFIX}*.xlsx"))
    if len(sources) != 1:
        raise UnsupportedExport(
            f"{folder.name} isn't a week's folder from this app. Choose the folder it made, "
            f'which has a "{SOURCE_PREFIX}" file and a "{REVIEW_FOLDER}" folder.'
        )
    return sources[0]


def build_approved(folder: str | Path) -> ApprovedResult:
    """Read the returned review files. Safe to rerun as more files come back."""
    folder = Path(folder)
    source = _find_source(folder)
    export = load_export(source)
    week_list = folder / _week_list_name(export)
    if week_list.exists():  # a week made before the list existed has no copy
        export = with_supervisors(export, supervisor_list.read_file(week_list))
    approvals = read_approvals(folder / REVIEW_FOLDER, export)
    label = "Approved" if approvals.is_final else "Provisional"
    pdf = folder / f"{label} timesheets {export.start}.pdf"
    summary = folder / f"{label} hours {export.start}.xlsx"
    _write_pdf(export, pdf, approvals)
    write_summary_workbook(export, approvals, summary)
    if approvals.is_final:
        # Earlier provisional copies are out of date once everything is approved.
        (folder / f"Provisional timesheets {export.start}.pdf").unlink(missing_ok=True)
        (folder / f"Provisional hours {export.start}.xlsx").unlink(missing_ok=True)
    return ApprovedResult(export, approvals, pdf, summary)
