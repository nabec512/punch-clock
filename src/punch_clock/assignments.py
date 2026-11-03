"""Decide who reviews whom.

A position tagged "- Supervisor" makes that person the reviewer of their whole
department, including their own hours. Departments with no tagged supervisor go
to accounting.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from punch_clock.jibble_export import Employee, WeeklyExport

ACCOUNTING_KEY = "accounting"
ACCOUNTING_TITLE = "Accounting - no supervisor"


@dataclass(frozen=True)
class ReviewGroup:
    key: str  # stable identity stored inside the review file
    title: str
    supervisor: Optional[Employee]
    employees: tuple[Employee, ...]


def review_groups(export: WeeklyExport) -> list[ReviewGroup]:
    """One group per supervisor, then accounting's group if it has anyone."""
    included = export.included
    supervisors = [e for e in included if e.is_supervisor]
    supervised = {s.department.casefold() for s in supervisors}
    groups = []
    for supervisor in supervisors:
        department = tuple(e for e in included if e.department.casefold() == supervisor.department.casefold())
        title = f"{supervisor.department} - {supervisor.name}"
        groups.append(ReviewGroup(supervisor.code, title, supervisor, department))
    remaining = tuple(e for e in included if e.department.casefold() not in supervised)
    if remaining:
        groups.append(ReviewGroup(ACCOUNTING_KEY, ACCOUNTING_TITLE, None, remaining))
    return groups


def departments_without_supervisor(export: WeeklyExport) -> list[str]:
    supervised = {e.department.casefold() for e in export.included if e.is_supervisor}
    names = {e.department for e in export.included if e.department.casefold() not in supervised}
    return sorted(names, key=str.casefold)


def safe_file_name(text: str) -> str:
    """Remove what Windows forbids in file names and collapse repeated spaces."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", text)
    return re.sub(r"\s+", " ", cleaned).strip(" .")


def review_file_name(group: ReviewGroup, export: WeeklyExport) -> str:
    return safe_file_name(f"Review - {group.title} - {export.start}") + ".xlsx"
