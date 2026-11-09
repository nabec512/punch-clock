"""Who supervises each department and the work schedules, from one file outside the app.

The file has a section for each organization, named as Jibble names it at the top of the
export, because two organizations can each have a department with the same name. An export
from an organization the file doesn't list is refused rather than given another one's settings.

These stay out of the app because the repository and its installers are public. Each PC
remembers where its file is, usually a shared drive, and otherwise looks in the home folder.
The file is read once each time reports are made, and never in the background, to leave the
drive alone. Each good read is copied to this PC, to fall back on if the file can't be reached.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from punch_clock.hours import Schedule
from punch_clock.jibble_export import UnsupportedExport

FILE_NAME = "punch-clock-settings.json"
READ_TIMEOUT_SECONDS = 5  # a dropped network drive can otherwise hold the app up for a minute
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@dataclass(frozen=True)
class Organization:
    name: str  # as written in the settings file
    supervisors: dict[str, str]  # a blank name means the department has none
    department_schedules: dict[str, Schedule]  # by lowercase department
    member_schedules: dict[str, Schedule]  # by lowercase member code; these override the department

    def schedule_for(self, code: str, department: str) -> Optional[Schedule]:
        return self.member_schedules.get(code.casefold()) or self.department_schedules.get(department.casefold())


@dataclass(frozen=True)
class Settings:
    organizations: dict[str, Organization]  # by organization_key
    path: Path  # the settings file, for messages
    note: str = ""  # set when these came from the copy on this PC

    def organization(self, company: str) -> Organization:
        """The settings for the organization an export comes from, and never another one's."""
        if not company.strip():
            raise UnsupportedExport(
                "This file doesn't say which organization it's from, so Punch Clock can't tell whose "
                "supervisors and work schedules to use. Export it from Jibble again."
            )
        found = self.organizations.get(organization_key(company))
        if found is None:
            listed = ", ".join(o.name for o in self.organizations.values()) or "none yet"
            raise UnsupportedExport(
                f'This file is from {company}, but the settings file has no section for "{company}":'
                f"\n\n{self.path}\n\nAdd one under organizations, spelled as it is here, with its supervisors "
                f"and work schedules, then try again.\n\nOrganizations in the settings file: {listed}."
            )
        return found


class LayoutMistake(ValueError):
    """A mistake in the settings file, explained in words its editor can follow."""


def organization_key(name: str) -> str:
    """Capitals and extra spaces don't make a different organization."""
    return " ".join(name.split()).casefold()


def _app_data() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home()) / "Punch Clock"


def saved_copy_path() -> Path:
    return _app_data() / "saved-settings.json"


def location_path() -> Path:
    return _app_data() / "settings-location.txt"


def file_path() -> Path:
    """Where this PC was told the settings file is, or else the home folder."""
    try:
        chosen = location_path().read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        chosen = ""
    return Path(chosen) if chosen else Path.home() / FILE_NAME


def _schedule(entry: dict) -> Schedule:
    start = datetime.strptime(entry["start"], "%H:%M").time()
    end = datetime.strptime(entry["end"], "%H:%M").time()
    if end <= start:
        raise ValueError(f"The schedule ending at {entry['end']} doesn't end after it starts.")
    days = frozenset(WEEKDAYS.index(day) for day in entry.get("days", WEEKDAYS[:5]))
    return Schedule(start, end, days)


def _no_repeats(pairs: list[tuple[str, object]]) -> dict:
    """JSON would quietly keep only the last of two sections with the same name."""
    seen: set[str] = set()
    for key, _ in pairs:
        if organization_key(key) in seen:
            raise LayoutMistake(f'"{key}" appears twice in the same place.')
        seen.add(organization_key(key))
    return dict(pairs)


def _organization(name: str, entry: dict) -> Organization:
    supervisors = entry["supervisors"]
    if not all(isinstance(person, str) for person in supervisors.values()):
        raise LayoutMistake(f"{name}: each supervisor must be a name in quotes, or blank.")
    return Organization(
        name,
        supervisors,
        {department.casefold(): _schedule(hours) for department, hours in entry["department_schedules"].items()},
        {code.casefold(): _schedule(hours) for code, hours in entry["member_schedules"].items()},
    )


def _parse(data: bytes, path: Path, note: str = "") -> Settings:
    """Accepts the byte order mark Notepad can add."""
    settings = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_no_repeats)
    if "organizations" not in settings and "supervisors" in settings:
        raise LayoutMistake(
            "It's laid out the old way, for a single organization. Put each organization's supervisors, "
            "department_schedules and member_schedules in a section of its own under organizations."
        )
    organizations = {organization_key(name): _organization(name, entry) for name, entry in settings["organizations"].items()}
    return Settings(organizations, path, note)


def _checked(data: bytes, path: Path) -> Settings:
    try:
        return _parse(data, path)
    except LayoutMistake as error:
        raise UnsupportedExport(f"The settings file has a mistake in it:\n\n{path}\n\n{error}") from error
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise UnsupportedExport(f"The settings file has a mistake in it:\n\n{path}\n\nDetails: {error!r}") from error


def _read_file(path: Path) -> Optional[bytes]:
    """The file's contents, or None if they couldn't be had in time."""
    outcome: list[bytes] = []

    def read() -> None:
        try:
            outcome.append(path.read_bytes())
        except OSError:
            pass

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(READ_TIMEOUT_SECONDS)
    return outcome[0] if outcome else None


def _save_copy(data: bytes) -> None:
    """Not being able to save the copy shouldn't stop today's reports."""
    copy = saved_copy_path()
    pending = copy.with_suffix(".pending.json")
    try:
        copy.parent.mkdir(parents=True, exist_ok=True)
        pending.write_bytes(data)
        pending.replace(copy)
    except OSError:
        pending.unlink(missing_ok=True)


def _load_saved_copy(path: Path) -> Settings:
    copy = saved_copy_path()
    try:
        saved_on = date.fromtimestamp(copy.stat().st_mtime)
        return _parse(
            copy.read_bytes(),
            path,
            f"Used the settings saved on this PC on {saved_on}, because the settings file couldn't be reached.",
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise UnsupportedExport(
            "Punch Clock couldn't reach its settings file for the supervisors and work schedules:"
            f"\n\n{path}\n\nCheck that this PC is connected to the shared drive. "
            "If the file is somewhere else, choose Settings file... to show where it is."
        ) from error


def load() -> Settings:
    """A mistake in the file stops the run: the old copy may well be what it was meant to replace."""
    path = file_path()
    data = _read_file(path)
    if data is None:
        return _load_saved_copy(path)
    settings = _checked(data, path)
    _save_copy(data)
    return settings


def use_file(path: Path) -> Settings:
    """Remember this file for this PC, as long as it can be read and has no mistakes."""
    data = _read_file(path)
    if data is None:
        raise UnsupportedExport(f"That settings file couldn't be opened:\n\n{path}")
    settings = _checked(data, path)
    location = location_path()
    location.parent.mkdir(parents=True, exist_ok=True)
    location.write_text(str(path), encoding="utf-8")
    _save_copy(data)  # so that a copy of the previous file can never stand in for this one
    return settings
