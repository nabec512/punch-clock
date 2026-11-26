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

It also says who pays each employee: a payroll, with their employee number there, or a staffing
agency. That follows the company on the books, not the organization they punch in, so each
employee is linked one by one. The payrolls and agencies are listed once at the top, so that a
misspelled one is caught instead of becoming a payroll of its own. Each agency is listed with the
company name and email its hours are sent to, and ``agency_pay`` holds the lunch charged per day
and the start of one two-week agency pay period. Each organization with agency staff says which
company sends those people's hours to the agency.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
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
PAYROLLS = "payrolls"
AGENCIES = "agencies"
AGENCY_PAY = "agency_pay"
AGENCIES_PAID_BY = "agencies_paid_by"
PERIOD_DAYS = 14  # agency staff are paid every two weeks
ORGANIZATION_SECTIONS = ("supervisors", "department_schedules", "member_schedules")


@dataclass(frozen=True)
class PayLink:
    """Who pays an employee: a payroll, with their employee number there, or a staffing agency."""

    name: str  # as the payroll or agency knows them, which can differ from Jibble
    payroll: str = ""  # spelled as in the file's list of payrolls
    number: str = ""  # their employee number in that payroll, which is only unique within it
    agency: str = ""  # spelled as in the file's list of agencies


@dataclass(frozen=True)
class Agency:
    name: str  # as listed in the settings file, and as each employee's link spells it
    legal_name: str  # the company the hours are sent to
    contact: str  # the email address the hours are sent to


@dataclass(frozen=True)
class AgencyPay:
    lunch_per_day: float  # dollars charged for each day with lunch
    period_starts: date  # the Monday one agency pay period starts; each lasts PERIOD_DAYS

    def period_before(self, day: date) -> date:
        """The Monday starting the latest pay period that has ended before ``day``."""
        current = self.period_starts + timedelta(days=(day - self.period_starts).days // PERIOD_DAYS * PERIOD_DAYS)
        return current - timedelta(days=PERIOD_DAYS)


@dataclass(frozen=True)
class Organization:
    name: str  # as written in the settings file
    supervisors: dict[str, str]  # a blank name means the department has none
    department_schedules: dict[str, Schedule]  # by _key of the department
    member_schedules: dict[str, Schedule]  # by _key of the member code; these override the department
    # The department each listed member is in, by _key of the member code, whatever their Jibble position says.
    # Spelled as in supervisors or department_schedules.
    member_departments: dict[str, str] = field(default_factory=dict)
    employees: dict[str, PayLink] = field(default_factory=dict)  # by _key of the member code
    agencies_paid_by: str = ""  # the company that sends this organization's agency staff hours to their agency

    def schedule_for(self, code: str, department: str) -> Optional[Schedule]:
        return self.member_schedules.get(_key(code)) or self.department_schedules.get(_key(department))

    def pay_link(self, code: str) -> Optional[PayLink]:
        return self.employees.get(_key(code))


@dataclass(frozen=True)
class Settings:
    organizations: dict[str, Organization]  # by organization_key
    path: Path  # the settings file, for messages
    note: str = ""  # set when these came from the copy on this PC
    payrolls: tuple[str, ...] = ()
    agencies: dict[str, Agency] = field(default_factory=dict)  # by name, as listed
    agency_pay: Optional[AgencyPay] = None  # set whenever any agency is listed

    @property
    def links_pay(self) -> bool:
        """Whether the file says who pays anyone yet. Until it does, nobody is reported as missing."""
        return any(organization.employees for organization in self.organizations.values())

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


def _organization(
    name: str, entry: object, payrolls: dict[str, str], agencies: dict[str, str], numbers: dict[tuple[str, int], str]
) -> Organization:
    entry = _known(
        entry, name, ORGANIZATION_SECTIONS, ("weekend_schedule", "member_departments", "employees", AGENCIES_PAID_BY),
        may_be_empty=True,
    )
    supervisors = _section(entry["supervisors"], f"{name}, supervisors")
    if not all(isinstance(person, str) for person in supervisors.values()):
        raise LayoutMistake(f"{name}: each supervisor must be a name in quotes, or blank.")
    weekend = _weekend(entry.get("weekend_schedule", {}), f"{name}, weekend_schedule")
    departments = _section(entry["department_schedules"], f"{name}, department_schedules")
    members = _section(entry["member_schedules"], f"{name}, member_schedules")
    known = {_key(department): department.strip() for department in (*departments, *supervisors)}
    employees = _pay_links(entry.get("employees", {}), f"{name}, employees", payrolls, agencies, numbers)
    paid_by = entry.get(AGENCIES_PAID_BY)
    if paid_by is not None and (not isinstance(paid_by, str) or not paid_by.strip()):
        raise LayoutMistake(f"{name}: {AGENCIES_PAID_BY} must be a company name in quotes.")
    if paid_by is None and any(link.agency for link in employees.values()):
        raise LayoutMistake(
            f'{name} has employees from an agency, so it needs "{AGENCIES_PAID_BY}": the name of the company that '
            "sends their hours to the agency, in quotes."
        )
    return Organization(
        name,
        {department.strip(): person for department, person in supervisors.items()},
        {_key(department): _schedule(hours, f"{name}, {department.strip()}", weekend) for department, hours in departments.items()},
        {_key(code): _schedule(hours, f"{name}, {code.strip()}", weekend) for code, hours in members.items()},
        _member_departments(entry.get("member_departments", {}), f"{name}, member_departments", known),
        employees,
        " ".join(paid_by.split()) if paid_by else "",
    )


def _names(value: object, section: str) -> dict[str, str]:
    """The payrolls or agencies listed at the top of the file, by organization_key, spelled as listed."""
    if not isinstance(value, list) or not all(isinstance(name, str) and name.strip() for name in value):
        raise LayoutMistake(f'{section} should list names in quotes between square brackets, like ["First", "Second"].')
    names: dict[str, str] = {}
    for name in value:
        if organization_key(name) in names:
            raise LayoutMistake(f'{section}: "{name.strip()}" is listed twice.')
        names[organization_key(name)] = " ".join(name.split())
    return names


def _text_setting(entry: dict, setting: str, where: str, what: str) -> str:
    value = entry[setting]
    if not isinstance(value, str) or not value.strip():
        raise LayoutMistake(f"{where}: {setting} must be {what} in quotes.")
    return " ".join(value.split())


def _agencies(value: object) -> dict[str, Agency]:
    """The agencies listed at the top of the file, by organization_key, each with where its hours are sent."""
    agencies: dict[str, Agency] = {}
    if isinstance(value, list):
        raise LayoutMistake(
            f'{AGENCIES} needs each agency\'s legal_name and contact, like "{AGENCIES}": '
            '{ "Agency": { "legal_name": "Agency Inc.", "contact": "name@example.com" } }'
        )
    for name, entry in _section(value, AGENCIES).items():
        if not name.strip():
            raise LayoutMistake(f"{AGENCIES}: each agency needs a name.")
        where = f"{AGENCIES}, {name.strip()}"
        entry = _known(entry, where, ("legal_name", "contact"))
        legal_name = _text_setting(entry, "legal_name", where, "the company name their hours are sent to")
        contact = _text_setting(entry, "contact", where, "the email address their hours are sent to")
        user, _, domain = contact.partition("@")
        if " " in contact or not user or "." not in domain.strip("."):
            raise LayoutMistake(f'{where}: contact must be the email address their hours are sent to, like "name@example.com".')
        agencies[organization_key(name)] = Agency(" ".join(name.split()), legal_name, contact)
    return agencies


def _agency_pay(value: object) -> AgencyPay:
    entry = _known(value, AGENCY_PAY, ("lunch_per_day", "period_starts"))
    lunch = entry["lunch_per_day"]
    if (
        isinstance(lunch, bool) or not isinstance(lunch, (int, float))
        or lunch < 0 or abs(lunch * 100 - round(lunch * 100)) > 1e-6
    ):
        raise LayoutMistake(
            f"{AGENCY_PAY}: lunch_per_day must be the dollars charged for each day's lunch, as a number without "
            "quotes or a $ sign, like 3.00."
        )
    try:
        starts = date.fromisoformat(entry["period_starts"])
    except (TypeError, ValueError):
        starts = None
    if starts is None or starts.weekday() != 0:
        raise LayoutMistake(
            f"{AGENCY_PAY}: period_starts must be the Monday any agency pay period started, in quotes and written "
            'year-month-day, like "2026-03-02". Every period is two weeks, Monday to Sunday, counted from there.'
        )
    return AgencyPay(round(float(lunch), 2), starts)


def _listed(value: object, where: str, listed: dict[str, str], section: str) -> str:
    """A misspelled payroll or agency would otherwise start a file of its own, so it has to be in the list."""
    if isinstance(value, str) and organization_key(value) in listed:
        return listed[organization_key(value)]
    if not listed:
        raise LayoutMistake(
            f'{where}: {json.dumps(value)} needs to be listed in "{section}" at the top of the file, beside "organizations".'
        )
    raise LayoutMistake(
        f"{where}: {json.dumps(value)} isn't one of the {section} listed at the top of the file, so check its "
        f"spelling. Listed: {', '.join(listed.values())}."
    )


def _employee_number(value: object, where: str) -> str:
    """Kept as written, as text, in case a payroll's numbers start with a zero."""
    text = str(value).strip() if isinstance(value, (str, int)) and not isinstance(value, bool) else ""
    if not (text.isascii() and text.isdigit()):
        raise LayoutMistake(f'{where}: {json.dumps(value)} isn\'t an employee number. Write it in quotes, digits only, like "1234".')
    return text


def _pay_links(
    entry: object, where: str, payrolls: dict[str, str], agencies: dict[str, str], numbers: dict[tuple[str, int], str]
) -> dict[str, PayLink]:
    """Who pays each listed member. ``numbers`` holds the employee numbers given out so far in the whole file."""
    links = {}
    for code, link in _section(entry, where).items():
        here = f"{where}, {code.strip()}"
        link = _known(link, here, ("name",), ("payroll", "number", "agency"))
        if not isinstance(link["name"], str) or not link["name"].strip():
            raise LayoutMistake(f"{here}: name must be their name in quotes, as their payroll or agency knows them.")
        name = " ".join(link["name"].split())
        if "agency" in link:
            if "payroll" in link or "number" in link:
                raise LayoutMistake(
                    f"{here}: someone is paid through a payroll or through an agency, not both. "
                    'Keep "payroll" and "number", or keep "agency".'
                )
            links[_key(code)] = PayLink(name, agency=_listed(link["agency"], f"{here}, agency", agencies, AGENCIES))
            continue
        if "payroll" not in link:
            raise LayoutMistake(f'{here} needs "payroll" and "number", or "agency" for someone an agency employs.')
        payroll = _listed(link["payroll"], f"{here}, payroll", payrolls, PAYROLLS)
        if "number" not in link:
            raise LayoutMistake(f'{here} needs "number", their employee number in {payroll}.')
        number = _employee_number(link["number"], here)
        # Two people with one number would have one person's hours paid to the other.
        taken = numbers.setdefault((payroll, int(number)), here)
        if taken != here:
            raise LayoutMistake(
                f"Employee number {number} in {payroll} is given to both {taken} and {here}. If someone has moved "
                "organization, take them out of the one they've left."
            )
        links[_key(code)] = PayLink(name, payroll, number)
    return links


def _member_departments(entry: object, where: str, known: dict[str, str]) -> dict[str, str]:
    """For someone Jibble shows in the wrong position. A misspelled department would change their hours, so it's refused."""
    moved = {}
    for code, department in _section(entry, where).items():
        if not isinstance(department, str) or not department.strip():
            raise LayoutMistake(f"{where}: the department for {code.strip()} must be a department name in quotes.")
        if _key(department) not in known:
            raise LayoutMistake(
                f'{where}: "{department.strip()}" for {code.strip()} isn\'t one of the departments in supervisors '
                "or department_schedules, so check its spelling."
            )
        moved[_key(code)] = known[_key(department)]
    return moved


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
    _known(settings, "The file", ("organizations",), (MINIMUM_VERSION, PAYROLLS, AGENCIES, AGENCY_PAY))
    payrolls = _names(settings.get(PAYROLLS, []), PAYROLLS)
    agency_list = _agencies(settings.get(AGENCIES, {}))
    agencies = {key: agency.name for key, agency in agency_list.items()}
    if agency_list and AGENCY_PAY not in settings:
        raise LayoutMistake(
            f'The file lists agencies, so it needs "{AGENCY_PAY}" beside them, with lunch_per_day and period_starts.'
        )
    agency_pay = _agency_pay(settings[AGENCY_PAY]) if AGENCY_PAY in settings else None
    numbers: dict[tuple[str, int], str] = {}
    sections = _section(settings["organizations"], "organizations")
    organizations = {
        organization_key(name): _organization(name, entry, payrolls, agencies, numbers) for name, entry in sections.items()
    }
    return Settings(
        organizations, path, note, tuple(payrolls.values()), {a.name: a for a in agency_list.values()}, agency_pay
    )


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
