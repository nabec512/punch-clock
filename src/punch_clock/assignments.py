"""Decide who reviews whom.

The saved supervisor list names who reviews each department. A supervisor needn't
be in Jibble, and one person can cover several departments. Everyone in a department
with no supervisor is grouped together as missing one, for accounting to review.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Mapping, Optional

from punch_clock.jibble_export import Employee, WeeklyExport

MISSING_SUPERVISOR_TITLE = "Missing supervisor"
LONGEST_DEPARTMENTS_IN_FILE_NAME = 60  # someone covering many departments mustn't hit Excel's path limit


@dataclass(frozen=True)
class ReviewGroup:
    title: str
    supervisor: Optional[str]
    employees: tuple[Employee, ...]


def with_supervisors(export: WeeklyExport, departments: Mapping[str, str]) -> WeeklyExport:
    named = {department.casefold(): name.strip() for department, name in departments.items() if name.strip()}
    return replace(export, supervisors=named)


def department_names(export: WeeklyExport) -> list[str]:
    names = {e.department.casefold(): e.department for e in export.included}
    return [names[key] for key in sorted(names)]


def review_groups(export: WeeklyExport) -> list[ReviewGroup]:
    """One group per supervisor, then the missing-supervisor group if it has anyone."""
    names: dict[str, str] = {}
    members: dict[str, list[Employee]] = {}
    remaining = []
    for employee in export.included:
        name = export.supervisors.get(employee.department.casefold())
        if name:
            names.setdefault(name.casefold(), name)
            members.setdefault(name.casefold(), []).append(employee)
        else:
            remaining.append(employee)
    groups = [ReviewGroup(names[key], names[key], tuple(members[key])) for key in names]
    if remaining:
        groups.append(ReviewGroup(MISSING_SUPERVISOR_TITLE, None, tuple(remaining)))
    return groups


def missing_supervisor_codes(export: WeeklyExport) -> set[str]:
    return {e.code for group in review_groups(export) if group.supervisor is None for e in group.employees}


def departments_without_supervisor(export: WeeklyExport) -> list[str]:
    return [name for name in department_names(export) if name.casefold() not in export.supervisors]


def safe_file_name(text: str) -> str:
    """Remove what Windows forbids in file names and collapse repeated spaces."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", text)
    return re.sub(r"\s+", " ", cleaned).strip(" .")


def _file_name_start(group: ReviewGroup, export: WeeklyExport) -> str:
    """The supervisor, their departments and the week. The missing-supervisor group has no one to name."""
    if group.supervisor is None:
        return f"{group.title} - {export.start}"
    names = {e.department.casefold(): e.department for e in group.employees}
    ordered = [names[key] for key in sorted(names)]
    departments = ", ".join(ordered)
    if len(ordered) > 1 and len(departments) > LONGEST_DEPARTMENTS_IN_FILE_NAME:
        departments = f"{ordered[0]} and {len(ordered) - 1} more"
    return f"{group.title} - {departments} - {export.start}"


def review_file_name(group: ReviewGroup, export: WeeklyExport) -> str:
    return safe_file_name(_file_name_start(group, export)) + ".xlsx"


def printable_file_name(group: ReviewGroup, export: WeeklyExport) -> str:
    return safe_file_name(f"{_file_name_start(group, export)} - Printable") + ".pdf"
