"""Who supervises each department and the work schedules, from one file outside the app.

The file has a section for each organization, named as Jibble names it at the top of the
export, because two organizations can each have a department with the same name. An export
from an organization the file doesn't list is refused rather than given another one's settings.

These stay out of the app because the repository and its installers are public. Each PC
remembers where its file is, usually a shared drive, and otherwise looks in the home folder.
The file is read once each time reports are made, and never in the background, to leave the
drive alone. Each good read is copied to this PC, to fall back on if the file can't be reached.

The file is edited by hand, so anything in it the app doesn't recognise is refused rather than
ignored: a misspelled setting would otherwise quietly change someone's pay. Every PC reads the
same file, so it can also name the oldest version of the app allowed to use it.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Optional

from punch_clock import __version__, version_numbers
from punch_clock.hours import BLOCK_MINUTES, DAY_NAMES, Schedule
from punch_clock.jibble_export import UnsupportedExport

FILE_NAME = "punch-clock-settings.json"
READ_TIMEOUT_SECONDS = 5  # a dropped network drive can otherwise hold the app up for a minute
WEEKDAYS = DAY_NAMES
DAY_LIST = "Mon, Tue, Wed, Thu, Fri, Sat or Sun"
MINIMUM_VERSION = "minimum_version"
ORGANIZATION_SECTIONS = ("supervisors", "department_schedules", "member_schedules")


@dataclass(frozen=True)
class Organization:
    name: str  # as written in the settings file
    supervisors: dict[str, str]  # a blank name means the department has none
    department_schedules: dict[str, Schedule]  # by _key of the department
    member_schedules: dict[str, Schedule]  # by _key of the member code; these override the department

    def schedule_for(self, code: str, department: str) -> Optional[Schedule]:
        return self.member_schedules.get(_key(code)) or self.department_schedules.get(_key(department))


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


class NeedsNewerApp(ValueError):
    """The settings file is meant for a newer version of the app than this one."""


def organization_key(name: str) -> str:
    """Capitals and extra spaces don't make a different organization."""
    return " ".join(name.split()).casefold()


def _key(name: str) -> str:
    """A space typed before or after a department or member code doesn't stop it matching."""
    return name.strip().casefold()


def _section(value: object, where: str) -> dict:
    if not isinstance(value, dict):
        raise LayoutMistake(f"{where} should be a list of settings between curly brackets, {{ and }}.")
    return value


def _known(
    value: object, where: str, required: tuple[str, ...], optional: tuple[str, ...] = (), may_be_empty: bool = False
) -> dict:
    """A section with every setting it needs, and none the app doesn't know: a misspelled one mustn't be ignored."""
    section = _section(value, where)
    for name in required:
        if name not in section:
            hint = f' If there is nothing to put in it, write "{name}": {{}}' if may_be_empty else ""
            raise LayoutMistake(f'{where} needs "{name}".{hint}')
    allowed = (*required, *optional)
    for name in section:
        if name not in allowed:
            raise LayoutMistake(
                f'{where}: "{name}" isn\'t a setting Punch Clock knows, so check its spelling. '
                f"The settings that can go here are: {', '.join(allowed)}."
            )
    return section


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


def _time(text: object, where: str) -> time:
    try:
        value = datetime.strptime(text, "%H:%M").time()
    except (TypeError, ValueError):
        raise LayoutMistake(
            f"{where}: {json.dumps(text)} isn't a time. Write each time in quotes on the 24-hour clock, "
            'like "08:00" or "16:30".'
        ) from None
    if value.minute % BLOCK_MINUTES:
        raise LayoutMistake(
            f"{where}: {text} isn't on the quarter hour. Hours are paid in 15-minute blocks, "
            "so each start and end must be on :00, :15, :30 or :45."
        )
    return value


def _times(entry: dict, where: str) -> tuple[time, time]:
    start, end = _time(entry["start"], where), _time(entry["end"], where)
    if end <= start:
        raise LayoutMistake(f"{where}: the end, {entry['end']}, must be later than the start, {entry['start']}.")
    return start, end


def _days(listed: object, where: str) -> frozenset[int]:
    if not isinstance(listed, list) or not listed:
        raise LayoutMistake(
            f'{where}: days should list the days worked between square brackets, like ["Mon", "Tue"]. '
            "Leave days out for Monday to Friday."
        )
    for day in listed:
        if day not in WEEKDAYS:
            raise LayoutMistake(f"{where}: {json.dumps(day)} isn't a day. Use {DAY_LIST}.")
    return frozenset(WEEKDAYS.index(day) for day in listed)


def _weekend(entry: dict, where: str) -> dict[int, Schedule]:
    """Hours for days off, by day name. They have no lunch, and all of their hours are overtime."""
    hours = {}
    for day, times in _section(entry, where).items():
        if day not in WEEKDAYS:
            raise LayoutMistake(f'{where}: "{day}" isn\'t a day. Use {DAY_LIST}.')
        if not isinstance(times, dict) or set(times) != {"start", "end"}:
            raise LayoutMistake(f"{where}: the hours for {day} need a start and an end, and nothing else.")
        hours[WEEKDAYS.index(day)] = Schedule(*_times(times, f"{where}, {day}"), lunch=0)
    return hours


def _schedule(entry: dict, where: str, weekend: dict[int, Schedule]) -> Schedule:
    """``weekend`` is the organization's hours for days off, which this schedule can change day by day."""
    entry = _known(entry, where, ("start", "end"), ("days", "weekend"))
    start, end = _times(entry, where)
    days = _days(entry.get("days", WEEKDAYS[:5]), where)
    own = _weekend(entry.get("weekend", {}), f"{where}, weekend")
    schedule = Schedule(start, end, days, weekend=tuple(sorted({**weekend, **own}.items(), key=lambda item: item[0])))
    if schedule.full_minutes <= 0:
        raise LayoutMistake(
            f"{where}: {entry['start']} to {entry['end']} leaves no paid hours once the "
            f"{schedule.lunch}-minute lunch is taken off."
        )
    return schedule


def _no_repeats(pairs: list[tuple[str, object]]) -> dict:
    """JSON would quietly keep only the last of two sections with the same name."""
    seen: set[str] = set()
    for key, _ in pairs:
        if organization_key(key) in seen:
            raise LayoutMistake(f'"{key}" appears twice in the same place.')
        seen.add(organization_key(key))
    return dict(pairs)


def _organization(name: str, entry: object) -> Organization:
    entry = _known(entry, name, ORGANIZATION_SECTIONS, ("weekend_schedule",), may_be_empty=True)
    supervisors = _section(entry["supervisors"], f"{name}, supervisors")
    if not all(isinstance(person, str) for person in supervisors.values()):
        raise LayoutMistake(f"{name}: each supervisor must be a name in quotes, or blank.")
    weekend = _weekend(entry.get("weekend_schedule", {}), f"{name}, weekend_schedule")
    departments = _section(entry["department_schedules"], f"{name}, department_schedules")
    members = _section(entry["member_schedules"], f"{name}, member_schedules")
    return Organization(
        name,
        {department.strip(): person for department, person in supervisors.items()},
        {_key(department): _schedule(hours, f"{name}, {department.strip()}", weekend) for department, hours in departments.items()},
        {_key(code): _schedule(hours, f"{name}, {code.strip()}", weekend) for code, hours in members.items()},
    )


def _check_version(wanted: object) -> None:
    """Every PC reads the same file, and an older app would quietly leave out settings it doesn't know."""
    if wanted is None:
        return
    needed = version_numbers(wanted) if isinstance(wanted, str) else None
    if needed is None:
        raise LayoutMistake(f'{MINIMUM_VERSION} should be a version number in quotes, like "{__version__}".')
    running = version_numbers(__version__)
    if running and running < needed:
        raise NeedsNewerApp(".".join(str(number) for number in needed))


def _parse(data: bytes, path: Path, note: str = "") -> Settings:
    """Accepts the byte order mark Notepad can add."""
    try:
        settings = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_no_repeats)
    except UnicodeDecodeError:
        raise LayoutMistake("It isn't saved as plain text. In Notepad, choose Save as, and set Encoding to UTF-8.") from None
    except json.JSONDecodeError as error:
        raise LayoutMistake(
            f"It can't be read as it's written. The problem is on line {error.lineno}, at or just before "
            f"character {error.colno}, or at the end of the line above. Look there for a missing or extra "
            "comma, quote mark or bracket. There's no comma after the last item in a list."
        ) from None
    if not isinstance(settings, dict):
        raise LayoutMistake("It should start with { and end with }.")
    # First, so that an older app asks to be updated instead of calling a newer setting a mistake.
    _check_version(settings.get(MINIMUM_VERSION))
    if "organizations" not in settings and "supervisors" in settings:
        raise LayoutMistake(
            "It's laid out the old way, for a single organization. Put each organization's supervisors, "
            "department_schedules and member_schedules in a section of its own under organizations."
        )
    _known(settings, "The file", ("organizations",), (MINIMUM_VERSION,))
    sections = _section(settings["organizations"], "organizations")
    organizations = {organization_key(name): _organization(name, entry) for name, entry in sections.items()}
    return Settings(organizations, path, note)


def _checked(data: bytes, path: Path) -> Settings:
    try:
        return _parse(data, path)
    except NeedsNewerApp as error:
        raise UnsupportedExport(
            f"The settings file needs Punch Clock {error} or newer, and this PC has {__version__}:\n\n{path}\n\n"
            "Close Punch Clock and open it again, and choose Yes when it offers to update. Then make the reports again. "
            "If it doesn't offer, install the latest version over this one."
        ) from error
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
