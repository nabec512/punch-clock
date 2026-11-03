"""The list of who supervises each department, saved on this PC.

Each processed week also keeps its own copy, so changing the list later can't
change what that week expects back from its supervisors.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from punch_clock.jibble_export import UnsupportedExport


def list_path() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home()) / "Punch Clock" / "supervisors.json"


def read_file(path: Path) -> dict[str, str]:
    """Departments and their supervisors. A blank name means the department has none."""
    try:
        departments = json.loads(path.read_text(encoding="utf-8"))["departments"]
        return {str(department): str(name) for department, name in departments.items()}
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise UnsupportedExport(f"The supervisor list could not be read:\n\n{path}") from error


def write_file(path: Path, departments: dict[str, str]) -> None:
    """A failed save leaves the previous list in place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(".pending.json")
    try:
        pending.write_text(json.dumps({"departments": departments}, ensure_ascii=False, indent=2), encoding="utf-8")
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)


def load() -> dict[str, str]:
    path = list_path()
    return read_file(path) if path.exists() else {}


def save(departments: dict[str, str]) -> None:
    write_file(list_path(), departments)
