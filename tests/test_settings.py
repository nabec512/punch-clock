"""The settings file, where it is, and the copy saved on this PC. All values are fictional."""
import threading
from datetime import date, time
from pathlib import Path
from time import monotonic

import pytest
from sample_export import COMPANY, Person, build_workbook, organization, write_settings

from punch_clock import settings
from punch_clock.app import process_summary
from punch_clock.jibble_export import UnsupportedExport, read_workbook
from punch_clock.reports import REVIEW_FOLDER, process_export

DAY_SHIFT = {"start": "08:00", "end": "16:30"}
LONG_SHIFT = {"start": "07:00", "end": "17:30", "days": ["Mon", "Tue", "Wed", "Thu"]}


def share(supervisors=None, departments=None, members=None):
    write_settings(settings.file_path(), supervisors, departments, members)


def make_reports(tmp_path, people=None):
    source = tmp_path / "export.xlsx"
    build_workbook(people).save(source)
    return process_export(source)


def test_the_app_looks_in_the_home_folder_until_told_otherwise():
    assert settings.file_path() == Path.home() / "punch-clock-settings.json"


def test_a_chosen_file_is_remembered_and_read_from_then_on(tmp_path):
    chosen = tmp_path / "any name.json"
    write_settings(chosen, {"Assembly": "Dana Smith"})
    settings.use_file(chosen)
    assert settings.file_path() == chosen
    assert settings.load().organization(COMPANY).supervisors == {"Assembly": "Dana Smith"}
    write_settings(chosen, {"Assembly": "Morgan Blake"})
    assert settings.load().organization(COMPANY).supervisors == {"Assembly": "Morgan Blake"}


def test_choosing_a_file_replaces_the_copy_of_the_previous_one(tmp_path):
    share({"Assembly": "Old Name"})
    settings.load()
    chosen = tmp_path / "new.json"
    write_settings(chosen, {"Assembly": "New Name"})
    settings.use_file(chosen)
    chosen.unlink()
    assert settings.load().organization(COMPANY).supervisors == {"Assembly": "New Name"}


def test_choosing_a_file_with_a_mistake_changes_nothing(tmp_path):
    before = settings.file_path()
    chosen = tmp_path / "bad.json"
    chosen.write_text("not json")
    with pytest.raises(UnsupportedExport, match="has a mistake in it"):
        settings.use_file(chosen)
    assert settings.file_path() == before


def test_choosing_a_file_that_cant_be_opened_changes_nothing(tmp_path):
    before = settings.file_path()
    with pytest.raises(UnsupportedExport, match="couldn't be opened"):
        settings.use_file(tmp_path / "gone.json")
    assert settings.file_path() == before


def test_a_blank_remembered_location_means_the_home_folder():
    settings.location_path().parent.mkdir(parents=True, exist_ok=True)
    settings.location_path().write_text("  \n")
    assert settings.file_path() == Path.home() / "punch-clock-settings.json"


def test_schedules_are_read_from_the_file():
    share(departments={"Assembly": DAY_SHIFT, "Welding": LONG_SHIFT})
    loaded = settings.load().organization(COMPANY)
    day = loaded.schedule_for("anyone", "Assembly")
    assert (day.start, day.end, day.days, day.full_minutes) == (time(8), time(16, 30), frozenset(range(5)), 480)
    long = loaded.schedule_for("anyone", "Welding")
    assert (long.days, long.full_minutes) == (frozenset(range(4)), 600)


@pytest.mark.parametrize("code", ["XY-1", "xy-1"])
def test_a_member_schedule_overrides_their_department(code):
    share(departments={"Assembly": DAY_SHIFT}, members={"XY-1": LONG_SHIFT})
    assert settings.load().organization(COMPANY).schedule_for(code, "Assembly").start == time(7)


def test_department_names_ignore_capitals_and_unknown_ones_have_no_schedule():
    share(departments={"Assembly": DAY_SHIFT})
    assert settings.load().organization(COMPANY).schedule_for("x", "aSsEmBlY").start == time(8)
    assert settings.load().organization(COMPANY).schedule_for("x", "Elsewhere") is None


def test_employees_get_their_schedule_including_supervisors():
    share(departments={"Assembly": DAY_SHIFT, "Welding": LONG_SHIFT}, members={"XY-1": DAY_SHIFT})
    people = [
        Person("Ann", "A-1", "Assembly - Supervisor", [(0, "In", "07:40:00", ""), (0, "Out", "16:30:00", "")]),
        Person("Tom", "XY-1", "Welding", [(0, "In", "08:00:00", ""), (0, "Out", "16:30:00", "")]),
    ]
    export = read_workbook(build_workbook(people), "sample.xlsx", schedule_for=settings.load().organization(COMPANY).schedule_for)
    assert all(employee.days[export.dates[0]].hours.paid == 480 for employee in export.employees)


def test_supervisors_and_schedules_reach_the_reports(tmp_path):
    share({"Assembly": "Dana Smith"}, {"Assembly": DAY_SHIFT})
    result = make_reports(tmp_path, [Person("Ann", "A-1", "Assembly", [(0, "In", "07:40:00", ""), (0, "Out", "16:30:00", "")])])
    assert [group.title for group in result.groups] == ["Dana Smith"]
    assert result.export.employees[0].days[result.export.dates[0]].hours.paid == 480
    assert "Assembly: 8:00 AM to 4:30 PM" in result.validation.read_text(encoding="utf-8")


def test_making_reports_reads_the_shared_file_once(monkeypatch, tmp_path):
    """However many employees there are, as the drive shouldn't be read more than it has to be."""
    share({"Assembly": "Dana Smith"}, {"Assembly": DAY_SHIFT})
    reads = []
    real_read = settings._read_file
    monkeypatch.setattr(settings, "_read_file", lambda path: reads.append(path) or real_read(path))
    people = [Person(f"Worker {i}", f"W-{i}", "Assembly", [(0, "In", "08:00:00", ""), (0, "Out", "16:30:00", "")]) for i in range(8)]
    make_reports(tmp_path, people)
    assert reads == [settings.file_path()]


def test_no_drive_and_no_copy_stops_with_a_plain_message(tmp_path):
    settings.file_path().unlink()
    with pytest.raises(UnsupportedExport, match="couldn't reach its settings file") as stopped:
        make_reports(tmp_path)
    assert str(settings.file_path()) in str(stopped.value)
    assert [path.name for path in tmp_path.iterdir()] == ["export.xlsx"]


def test_no_drive_uses_the_saved_copy_and_says_so_everywhere(tmp_path):
    share({"Assembly": "Dana Smith", "Receiving": "Dana Smith"}, {"Assembly": DAY_SHIFT})
    settings.load()
    settings.file_path().unlink()
    result = make_reports(tmp_path)

    note = f"saved on this PC on {date.today()}"
    assert [group.title for group in result.groups] == ["Dana Smith"]
    assert note in result.export.settings_note
    assert note in process_summary(result)
    assert note in result.validation.read_text(encoding="utf-8")


def test_a_normal_run_mentions_no_saved_copy(tmp_path):
    result = make_reports(tmp_path)
    assert result.export.settings_note == ""
    assert "saved on this PC" not in process_summary(result)


def test_a_drive_that_hangs_falls_back_instead_of_holding_up_the_app(monkeypatch):
    share({"Assembly": "Dana Smith"})
    settings.load()
    shared, release, real_read = settings.file_path(), threading.Event(), Path.read_bytes

    def hang_on_the_drive(path):
        if path == shared:
            release.wait(30)
            raise OSError("the drive went away")
        return real_read(path)

    monkeypatch.setattr(settings, "READ_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(Path, "read_bytes", hang_on_the_drive)
    started = monotonic()
    try:
        loaded = settings.load()
    finally:
        release.set()
    assert monotonic() - started < 5
    assert loaded.organization(COMPANY).supervisors == {"Assembly": "Dana Smith"} and "saved on this PC" in loaded.note


def test_a_new_good_file_replaces_the_saved_copy(tmp_path):
    share({"Assembly": "Old Name"})
    settings.load()
    share({"Assembly": "New Name"})
    settings.load()
    settings.file_path().unlink()
    assert settings.load().organization(COMPANY).supervisors == {"Assembly": "New Name"}


@pytest.mark.parametrize(
    "broken",
    [
        b"not json",
        b"[]",
        b"{}",
        b'{"organizations": {"Org": {"supervisors": {}}}}',
        b'{"organizations": {"Org": {"supervisors": {"A": null}, "department_schedules": {}, "member_schedules": {}}}}',
        b'{"organizations": {"Org": {"supervisors": {}, "department_schedules": {"A": {"start": "8am", "end": "16:30"}}, "member_schedules": {}}}}',
        b'{"organizations": {"Org": {"supervisors": {}, "department_schedules": {"A": {"start": "16:30", "end": "08:00"}}, "member_schedules": {}}}}',
        b'{"organizations": {"Org": {"supervisors": {}, "department_schedules": {"A": {"start": "08:00", "end": "16:30", "days": ["Monday"]}}, "member_schedules": {}}}}',
        # The layout from before organizations, which would give every organization the same supervisors.
        b'{"supervisors": {}, "department_schedules": {}, "member_schedules": {}}',
        # JSON would otherwise quietly keep only the second.
        b'{"organizations": {"Org": {"supervisors": {}, "department_schedules": {}, "member_schedules": {}}, "Org": {"supervisors": {}, "department_schedules": {}, "member_schedules": {}}}}',
        b'{"organizations": {"Org": {"supervisors": {}, "department_schedules": {}, "member_schedules": {}}, " ORG ": {"supervisors": {}, "department_schedules": {}, "member_schedules": {}}}}',
        b'{"organizations": {"Org": {"supervisors": {"Paint": "A", "paint": "B"}, "department_schedules": {}, "member_schedules": {}}}}',
        b"\xff\xfe",
    ],
)
def test_a_mistake_in_the_file_stops_rather_than_using_old_settings(broken):
    share({"Assembly": "Dana Smith"})
    settings.load()
    good_copy = settings.saved_copy_path().read_bytes()
    settings.file_path().write_bytes(broken)
    with pytest.raises(UnsupportedExport, match="has a mistake in it"):
        settings.load()
    assert settings.saved_copy_path().read_bytes() == good_copy  # a bad file never replaces a good copy


def test_a_damaged_saved_copy_is_treated_as_no_copy():
    settings.file_path().unlink()
    settings.saved_copy_path().parent.mkdir(parents=True, exist_ok=True)
    settings.saved_copy_path().write_text("not json")
    with pytest.raises(UnsupportedExport, match="couldn't reach its settings file"):
        settings.load()


def test_notepads_byte_order_mark_and_accents_are_fine():
    path = settings.file_path()
    path.write_bytes(
        b"\xef\xbb\xbf"
        + '{"organizations": {"Zakład Łódź": {"supervisors": {"Łódź": "Żak"}, "department_schedules": {}, "member_schedules": {}}}}'.encode()
    )
    assert settings.load().organization("Zakład Łódź").supervisors == {"Łódź": "Żak"}


def test_the_old_layout_says_how_to_fix_it():
    settings.file_path().write_text('{"supervisors": {}, "department_schedules": {}, "member_schedules": {}}')
    with pytest.raises(UnsupportedExport, match="laid out the old way") as stopped:
        settings.load()
    assert "organizations" in str(stopped.value) and "Details" not in str(stopped.value)


# --- More than one organization ------------------------------------------------

OTHER = "Second Example Ltd."
PRODUCTION = [Person("Ann", "A-1", "Production", [(0, "In", "07:00:00", ""), (0, "Out", "16:00:00", "")])]


def two_organizations():
    """Both have a Production department, with different supervisors and hours."""
    write_settings(
        settings.file_path(),
        {"Production": "Dana Smith"},
        {"Production": {"start": "06:30", "end": "15:00"}},
        others={OTHER: organization({"Production": "Morgan Blake"}, {"Production": {"start": "07:00", "end": "15:30"}})},
    )


def reports_for(tmp_path, company, people=PRODUCTION):
    source = tmp_path / f"export {len(list(tmp_path.glob('*.xlsx')))}.xlsx"
    build_workbook(people, company=company).save(source)
    return process_export(source)


@pytest.mark.parametrize(
    "company, supervisor, expected",
    [(COMPANY, "Dana Smith", "6:30 AM to 3:00 PM"), (OTHER, "Morgan Blake", "7:00 AM to 3:30 PM")],
)
def test_each_organization_gets_its_own_supervisor_and_schedule(tmp_path, company, supervisor, expected):
    two_organizations()
    result = reports_for(tmp_path, company)
    assert [group.title for group in result.groups] == [supervisor]
    assert result.export.employees[0].days[result.export.dates[0]].schedule.label == expected
    validation = result.validation.read_text(encoding="utf-8")
    assert f"{company} section of the settings file" in validation and f"Production: {expected}" in validation


def test_a_department_name_another_organization_uses_doesnt_borrow_its_settings(tmp_path):
    two_organizations()
    write_settings(
        settings.file_path(),
        {"Production": "Dana Smith"},
        {"Production": {"start": "06:30", "end": "15:00"}},
        others={OTHER: organization()},
    )
    result = reports_for(tmp_path, OTHER)
    assert [group.supervisor for group in result.groups] == [None]
    assert result.export.employees[0].days[result.export.dates[0]].schedule is None


def test_an_organization_missing_from_the_settings_is_refused_by_name(tmp_path):
    two_organizations()
    with pytest.raises(UnsupportedExport) as stopped:
        reports_for(tmp_path, "Third Example LLC")
    message = str(stopped.value)
    assert 'no section for "Third Example LLC"' in message
    assert f"{COMPANY}, {OTHER}" in message and str(settings.file_path()) in message
    assert [path.name for path in tmp_path.iterdir()] == ["export 0.xlsx"]  # nothing half-made


def test_an_export_that_doesnt_name_its_organization_is_refused(tmp_path):
    with pytest.raises(UnsupportedExport, match="doesn't say which organization"):
        reports_for(tmp_path, "")


def test_organization_names_ignore_capitals_and_extra_spaces(tmp_path):
    two_organizations()
    result = reports_for(tmp_path, "  second   EXAMPLE ltd. ")
    assert [group.title for group in result.groups] == ["Morgan Blake"]


def test_files_say_which_organization_they_are_for(tmp_path):
    """Each organization's week can be in one folder, and someone can supervise in more than one."""
    two_organizations()
    first, second = reports_for(tmp_path, COMPANY), reports_for(tmp_path, OTHER)
    assert first.folder.name == "Jibble timesheets Example Co 2026-03-02 to 2026-03-08"
    assert second.folder.name == "Jibble timesheets Second Example Ltd 2026-03-02 to 2026-03-08"
    assert sorted(path.name for path in (second.folder / REVIEW_FOLDER).iterdir()) == [
        "Second Example Ltd. - Morgan Blake - Production - 2026-03-02 - Printable.pdf",
        "Second Example Ltd. - Morgan Blake - Production - 2026-03-02.xlsx",
    ]


# --- Weekend hours ---------------------------------------------------------------

SATURDAY = {"start": "07:30", "end": "12:30"}
SUNDAY = {"start": "09:00", "end": "13:00"}
EARLY = {"start": "04:30", "end": "09:30"}


def weekend_hours(code="anyone", department="Assembly"):
    schedule = settings.load().organization(COMPANY).schedule_for(code, department)
    return [schedule.weekend_for(day).label if schedule.weekend_for(day) else None for day in range(7)]


def test_the_organizations_weekend_hours_reach_every_schedule():
    write_settings(settings.file_path(), departments={"Assembly": DAY_SHIFT}, weekend={"Sat": SATURDAY, "Sun": SUNDAY})
    hours = weekend_hours()
    assert hours[5] == "7:30 AM to 12:30 PM" and hours[6] == "9:00 AM to 1:00 PM"
    assert hours[0] is None  # a working day
    sat = settings.load().organization(COMPANY).schedule_for("anyone", "Assembly").weekend_for(5)
    assert (sat.lunch, sat.full_minutes) == (0, 300)


def test_a_department_can_change_one_weekend_day():
    departments = {"Assembly": DAY_SHIFT, "Shipping": {**DAY_SHIFT, "weekend": {"Sat": EARLY}}}
    write_settings(settings.file_path(), departments=departments, weekend={"Sat": SATURDAY, "Sun": SUNDAY})
    assert weekend_hours(department="Shipping")[5:] == ["4:30 AM to 9:30 AM", "9:00 AM to 1:00 PM"]
    assert weekend_hours(department="Assembly")[5] == "7:30 AM to 12:30 PM"


def test_a_member_can_change_their_weekend_hours():
    members = {"XY-1": {**DAY_SHIFT, "weekend": {"Sun": EARLY}}}
    write_settings(settings.file_path(), departments={"Assembly": DAY_SHIFT}, members=members, weekend={"Sat": SATURDAY})
    assert weekend_hours("XY-1")[5:] == ["7:30 AM to 12:30 PM", "4:30 AM to 9:30 AM"]


def test_friday_hours_only_apply_to_a_crew_with_friday_off():
    write_settings(settings.file_path(), departments={"Assembly": DAY_SHIFT, "Welding": LONG_SHIFT}, weekend={"Fri": SATURDAY})
    assert weekend_hours(department="Assembly")[4] is None
    assert weekend_hours(department="Welding")[4] == "7:30 AM to 12:30 PM"


def test_without_weekend_hours_a_day_off_works_as_before():
    share(departments={"Assembly": DAY_SHIFT})
    assert set(weekend_hours()) == {None}


@pytest.mark.parametrize(
    "departments, weekend, message",
    [
        pytest.param({"Assembly": {"start": "08:10", "end": "16:30"}}, None, "08:10 isn't on the quarter hour", id="schedule"),
        pytest.param({}, {"Sat": {"start": "07:30", "end": "12:20"}}, "12:20 isn't on the quarter hour", id="weekend"),
        pytest.param({}, {"Saturday": SATURDAY}, '"Saturday" isn\'t a day', id="day name"),
        pytest.param({}, {"Sat": {"start": "07:30"}}, "need a start and an end", id="missing end"),
    ],
)
def test_weekend_and_quarter_hour_mistakes_are_explained(departments, weekend, message):
    write_settings(settings.file_path(), departments=departments, weekend=weekend)
    with pytest.raises(UnsupportedExport, match=message):
        settings.load()


# --- Mistakes the file's editor can make ------------------------------------------


def mistake(text):
    settings.file_path().write_text(text, encoding="utf-8")
    with pytest.raises(UnsupportedExport, match="has a mistake in it") as stopped:
        settings.load()
    assert "Details" not in str(stopped.value)  # in plain words, not Python's
    return str(stopped.value)


def section(supervisors="{}", departments="{}", members="{}", extra=""):
    return (
        '{"organizations": {"Org": {"supervisors": %s, "department_schedules": %s, "member_schedules": %s%s}}}'
        % (supervisors, departments, members, extra)
    )


@pytest.mark.parametrize(
    "text, message",
    [
        # A crew working Monday to Thursday would otherwise be paid as Monday to Friday.
        (section(departments='{"A": {"start": "07:00", "end": "17:30", "day": ["Mon"]}}'), '"day" isn\'t a setting'),
        (section(departments='{"A": {"start": "08:00", "end": "16:30", "weekends": {}}}'), '"weekends" isn\'t a setting'),
        (section(extra=', "weekend_schedules": {}'), '"weekend_schedules" isn\'t a setting'),
        ('{"organizations": {}, "organisations": {}}', '"organisations" isn\'t a setting'),
    ],
)
def test_a_misspelled_setting_is_refused_not_ignored(text, message):
    found = mistake(text)
    assert message in found and "check its spelling" in found


@pytest.mark.parametrize(
    "text, message",
    [
        ("not json", "on line 1"),
        ('{"organizations": {\n"Org": {"supervisors": {"A": "B",},\n"department_schedules": {}, "member_schedules": {}}}}', "on line 2"),
        ("[]", "should start with {"),
        ("{}", 'needs "organizations"'),
        ('{"organizations": {"Org": {"supervisors": {}, "department_schedules": {}}}}', 'Org needs "member_schedules"'),
        ('{"organizations": {"Org": []}}', "Org should be a list of settings"),
        (section(supervisors="[]"), "Org, supervisors should be a list of settings"),
        (section(departments='{"A": {"start": "8am", "end": "16:30"}}'), '"8am" isn\'t a time'),
        (section(departments='{"A": {"start": 8, "end": "16:30"}}'), "8 isn't a time"),
        (section(departments='{"A": {"start": "08:00"}}'), 'Org, A needs "end"'),
        (section(departments='{"A": {"start": "16:30", "end": "08:00"}}'), "must be later than the start"),
        (section(departments='{"A": {"start": "08:00", "end": "08:15"}}'), "leaves no paid hours"),
        (section(departments='{"A": {"start": "08:00", "end": "16:30", "days": ["Monday"]}}'), '"Monday" isn\'t a day'),
        (section(departments='{"A": {"start": "08:00", "end": "16:30", "days": []}}'), "days should list the days worked"),
        (section(departments='{"A": {"start": "08:00", "end": "16:30", "days": "Mon"}}'), "days should list the days worked"),
        (section(extra=', "weekend_schedule": []'), "weekend_schedule should be a list of settings"),
    ],
)
def test_common_mistakes_are_explained_in_plain_words(text, message):
    assert message in mistake(text)


def test_a_file_not_saved_as_plain_text_says_how_to_save_it():
    settings.file_path().write_bytes(b"\xff\xfe")
    with pytest.raises(UnsupportedExport, match="Encoding to UTF-8"):
        settings.load()


def test_a_space_around_a_department_or_member_code_still_matches(tmp_path):
    share({" Assembly ": "Dana Smith"}, {"Assembly ": DAY_SHIFT}, {" XY-1": LONG_SHIFT})
    loaded = settings.load().organization(COMPANY)
    assert loaded.supervisors == {"Assembly": "Dana Smith"}
    assert loaded.schedule_for("anyone", "Assembly").start == time(8)
    assert loaded.schedule_for("XY-1", "Assembly").start == time(7)
    result = make_reports(tmp_path)
    assert "Dana Smith" in [group.title for group in result.groups]


# --- The oldest version of the app the file allows ---------------------------------


def with_minimum(version, rest='"organizations": {}'):
    settings.file_path().write_text('{"minimum_version": %s, %s}' % (version, rest), encoding="utf-8")


@pytest.mark.parametrize("version", ['"0.0.1"', f'"{settings.__version__}"', f'"v{settings.__version__}"'])
def test_a_file_for_this_version_or_an_older_one_is_used(version):
    with_minimum(version)
    assert settings.load().organizations == {}


def test_a_file_for_a_newer_version_asks_for_the_update_and_makes_nothing(tmp_path):
    share({"Assembly": "Dana Smith"})
    settings.load()
    good_copy = settings.saved_copy_path().read_bytes()
    with_minimum('"99.0.0"')
    with pytest.raises(UnsupportedExport, match="needs Punch Clock 99.0.0 or newer") as stopped:
        make_reports(tmp_path)
    message = str(stopped.value)
    assert settings.__version__ in message and "offers to update" in message and "mistake" not in message
    assert [path.name for path in tmp_path.iterdir()] == ["export.xlsx"]
    assert settings.saved_copy_path().read_bytes() == good_copy  # the older copy never stands in


def test_a_newer_file_asks_for_the_update_rather_than_calling_its_new_settings_mistakes():
    with_minimum('"99.0.0"', '"organizations": {}, "something_new": {}')
    with pytest.raises(UnsupportedExport, match="needs Punch Clock 99.0.0 or newer"):
        settings.load()


@pytest.mark.parametrize("version", ['"soon"', '"1.0"', "9", '""'])
def test_a_minimum_version_that_isnt_a_version_is_a_mistake(version):
    with_minimum(version)
    with pytest.raises(UnsupportedExport, match="should be a version number in quotes"):
        settings.load()


# --- member_departments --------------------------------------------------------


def test_member_departments_are_optional_and_match_any_spelling_of_the_code_and_department():
    share({"Assembly": "Dana Smith"})
    assert settings.load().organization(COMPANY).member_departments == {}
    write_settings(settings.file_path(), {"Assembly": "Dana Smith"}, {"Welding": DAY_SHIFT}, moved={" xy-1 ": "assembly", "Z-1": "WELDING"})
    assert settings.load().organization(COMPANY).member_departments == {"xy-1": "Assembly", "z-1": "Welding"}


@pytest.mark.parametrize(
    "moved, message",
    [
        # A misspelled department would give the person no schedule, or the wrong one.
        ('{"XY-1": "Asembly"}', '"Asembly" for XY-1 isn\'t one of the departments in supervisors or department_schedules'),
        ('{"XY-1": ""}', "the department for XY-1 must be a department name in quotes"),
        ('{"XY-1": ["Assembly"]}', "the department for XY-1 must be a department name in quotes"),
        ('["XY-1"]', "Org, member_departments should be a list of settings"),
        ('{"XY-1": "Assembly", "xy-1": "Assembly"}', '"xy-1" appears twice'),
    ],
)
def test_member_department_mistakes_are_refused(moved, message):
    assert message in mistake(section(supervisors='{"Assembly": ""}', extra=f', "member_departments": {moved}'))


def test_a_filtered_export_puts_someone_jibble_still_shows_in_their_old_position_in_their_new_one(tmp_path):
    """Filtered to Receiving, with someone moved there whose rows Jibble still shows as Assembly."""
    write_settings(
        settings.file_path(),
        {"Assembly": "Dana Smith", "Receiving": "Lee Park"},
        {"Assembly": DAY_SHIFT, "Receiving": LONG_SHIFT},
        moved={"CM-1": "Receiving"},
    )
    moved = Person("Casey Moss", "CM-1", "Assembly", [(0, "In", "07:00:00", ""), (0, "Out", "17:30:00", "")])
    assembly = Person("Ann", "A-1", "Assembly", [(0, "In", "08:00:00", ""), (0, "Out", "16:30:00", "")])
    source = tmp_path / "export.xlsx"
    build_workbook([moved], filtered_out=[assembly]).save(source)
    result = process_export(source)
    assert [(group.title, [e.code for e in group.employees]) for group in result.groups] == [("Lee Park", ["CM-1"])]
    assert result.export.employees[0].days[result.export.dates[0]].hours.paid == 600  # Receiving's 10-hour day
    text = result.validation.read_text(encoding="utf-8")
    assert "Department set by the settings file: Casey Moss / CM-1 in Receiving (Jibble: Assembly)" in text
    assert "Casey Moss / CM-1 / Receiving" in text


# --- Who pays each employee: a payroll and employee number, or an agency ------------

PAYROLL_LINKS = {
    "AL-1": {"name": "LEE, AVERY", "payroll": "Main Payroll", "number": "1001"},
    "SO-1": {"name": "Sam Ortiz", "agency": "Temp Staffing Inc."},
}


def links(employees, payrolls='["Main Payroll", "Second Payroll"]', agencies='["Temp Staffing Inc."]'):
    top = "".join(f', "{key}": {value}' for key, value in (("payrolls", payrolls), ("agencies", agencies)) if value)
    organization = '"Org": {"supervisors": {}, "department_schedules": {}, "member_schedules": {}, "employees": %s}' % employees
    return '{"organizations": {%s}%s}' % (organization, top)


def test_who_pays_is_optional():
    share({"Assembly": "Dana Smith"})
    loaded = settings.load()
    assert not loaded.links_pay and loaded.payrolls == () and loaded.agencies == ()
    assert loaded.organization(COMPANY).pay_link("AL-1") is None


def test_each_employee_is_linked_to_a_payroll_number_or_an_agency():
    write_settings(
        settings.file_path(),
        employees={
            " al-1 ": {"name": " LEE,  AVERY ", "payroll": "main payroll", "number": "0012"},
            "SO-1": {"name": "Sam Ortiz", "agency": "TEMP STAFFING INC."},
            "LZ-1": {"name": "ZAK, LUCJA", "payroll": "Second Payroll", "number": 12},
        },
        payrolls=["Main Payroll", "Second Payroll"],
        agencies=["Temp Staffing Inc."],
    )
    loaded = settings.load()
    assert loaded.links_pay
    assert loaded.payrolls == ("Main Payroll", "Second Payroll") and loaded.agencies == ("Temp Staffing Inc.",)
    organization = loaded.organization(COMPANY)
    # Spelled as listed at the top, whatever the capitals, and the number kept as written.
    assert organization.pay_link("AL-1") == settings.PayLink("LEE, AVERY", "Main Payroll", "0012")
    assert organization.pay_link("so-1") == settings.PayLink("Sam Ortiz", agency="Temp Staffing Inc.")
    # Numbers are only unique within a payroll, so 12 in another one is someone else.
    assert organization.pay_link("LZ-1") == settings.PayLink("ZAK, LUCJA", "Second Payroll", "12")


@pytest.mark.parametrize(
    "text, message",
    [
        # A misspelled payroll or agency would otherwise become one of its own.
        (links('{"A-1": {"name": "Ann", "payroll": "Main Payrol", "number": "1"}}'), '"Main Payrol" isn\'t one of the payrolls listed'),
        (links('{"A-1": {"name": "Ann", "payroll": "Main Payroll", "number": "1"}}', payrolls=""), 'needs to be listed in "payrolls"'),
        (links('{"A-1": {"name": "Ann", "agency": "Temp Staffing"}}'), '"Temp Staffing" isn\'t one of the agencies listed'),
        (links('{"A-1": {"name": "Ann", "agency": "Temp Staffing Inc.", "payroll": "Main Payroll", "number": "1"}}'), "not both"),
        (links('{"A-1": {"name": "Ann"}}'), 'Org, employees, A-1 needs "payroll" and "number", or "agency"'),
        (links('{"A-1": {"name": "Ann", "payroll": "Main Payroll"}}'), 'needs "number", their employee number in Main Payroll'),
        (links('{"A-1": {"name": "Ann", "payroll": "Main Payroll", "number": "1597.48"}}'), '"1597.48" isn\'t an employee number'),
        (links('{"A-1": {"name": "Ann", "payroll": "Main Payroll", "number": ""}}'), '"" isn\'t an employee number'),
        (links('{"A-1": {"name": "Ann", "payroll": "Main Payroll", "number": true}}'), "true isn't an employee number"),
        (links('{"A-1": {"payroll": "Main Payroll", "number": "1"}}'), 'Org, employees, A-1 needs "name"'),
        (links('{"A-1": {"name": " ", "agency": "Temp Staffing Inc."}}'), "name must be their name in quotes"),
        (links('{"A-1": "Main Payroll"}'), "Org, employees, A-1 should be a list of settings"),
        (links('{"A-1": {"name": "Ann", "payroll": "Main Payroll", "employee_number": "1"}}'), '"employee_number" isn\'t a setting'),
        (links("{}", payrolls='"Main Payroll"'), "payrolls should list names in quotes"),
        (links("{}", agencies='["Temp Staffing Inc.", ""]'), "agencies should list names in quotes"),
        (links("{}", payrolls='["Main Payroll", "main  payroll"]'), '"main  payroll" is listed twice'),
        ('{"organizations": {}, "payroll": []}', '"payroll" isn\'t a setting'),
        (section(extra=', "employee": {}'), '"employee" isn\'t a setting'),
    ],
)
def test_who_pays_mistakes_are_refused(text, message):
    assert message in mistake(text)


def test_one_employee_number_can_only_belong_to_one_person_in_the_whole_file():
    """Such as someone who moved organization and is still listed in the one they left."""
    write_settings(
        settings.file_path(),
        employees={"AL-1": {"name": "LEE, AVERY", "payroll": "Main Payroll", "number": "12"}},
        payrolls=["Main Payroll"],
        others={"Other Org": organization(employees={"XY-9": {"name": "LEE, AVERY", "payroll": "Main Payroll", "number": "0012"}})},
    )
    message = mistake_in_file()
    assert f"number 0012 in Main Payroll is given to both {COMPANY}, employees, AL-1 and Other Org, employees, XY-9" in message
    assert "take them out of the one they've left" in message


def mistake_in_file():
    with pytest.raises(UnsupportedExport, match="has a mistake in it") as stopped:
        settings.load()
    return str(stopped.value)


def test_until_the_file_says_who_pays_anyone_nobody_is_reported_missing(tmp_path):
    share({"Assembly": "Dana Smith"})
    result = make_reports(tmp_path)
    assert result.export.unlinked is None
    assert "who pays" not in process_summary(result)
    assert "The settings file doesn't say who pays anyone yet." in result.validation.read_text(encoding="utf-8")


def test_included_employees_nobody_pays_are_named_on_screen_and_in_the_validation_file(tmp_path):
    write_settings(
        settings.file_path(),
        {"Assembly": "Dana Smith"},
        employees=PAYROLL_LINKS,
        payrolls=["Main Payroll"],
        agencies=["Temp Staffing Inc."],
    )
    result = make_reports(tmp_path)
    # Riley Chen has no position, so isn't in the reports and isn't listed.
    assert result.export.unlinked == ("LZ-1",)
    assert (
        f"The {COMPANY} section of the settings file doesn't say who pays: Łucja Żak (LZ-1). "
        "Add them under employees, with their payroll and employee number, or their agency."
    ) in process_summary(result)
    text = result.validation.read_text(encoding="utf-8")
    assert "Linked: 2 of 3 included employees." in text and "Not linked: Łucja Żak / LZ-1" in text


def test_once_everyone_is_linked_nothing_is_reported(tmp_path):
    everyone = {**PAYROLL_LINKS, "LZ-1": {"name": "ZAK, LUCJA", "payroll": "Main Payroll", "number": "1002"}}
    write_settings(settings.file_path(), employees=everyone, payrolls=["Main Payroll"], agencies=["Temp Staffing Inc."])
    result = make_reports(tmp_path)
    assert result.export.unlinked == ()
    assert "who pays" not in process_summary(result)
    assert "Not linked: None" in result.validation.read_text(encoding="utf-8")


def test_an_organization_with_no_links_while_another_has_them_is_reported_in_full(tmp_path):
    write_settings(
        settings.file_path(),
        payrolls=["Main Payroll"],
        others={"Other Org": organization(employees={"XY-9": {"name": "Pat", "payroll": "Main Payroll", "number": "5"}})},
    )
    result = make_reports(tmp_path)
    assert sorted(result.export.unlinked) == ["AL-1", "LZ-1", "SO-1"]
