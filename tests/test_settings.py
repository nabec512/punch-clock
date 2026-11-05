"""The settings file, where it is, and the copy saved on this PC. All values are fictional."""
import threading
from datetime import date, time
from pathlib import Path
from time import monotonic

import pytest
from sample_export import Person, build_workbook, write_settings

from punch_clock import settings
from punch_clock.app import process_summary
from punch_clock.jibble_export import UnsupportedExport, read_workbook
from punch_clock.reports import process_export

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
    assert settings.load().supervisors == {"Assembly": "Dana Smith"}
    write_settings(chosen, {"Assembly": "Morgan Blake"})
    assert settings.load().supervisors == {"Assembly": "Morgan Blake"}


def test_choosing_a_file_replaces_the_copy_of_the_previous_one(tmp_path):
    share({"Assembly": "Old Name"})
    settings.load()
    chosen = tmp_path / "new.json"
    write_settings(chosen, {"Assembly": "New Name"})
    settings.use_file(chosen)
    chosen.unlink()
    assert settings.load().supervisors == {"Assembly": "New Name"}


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
    loaded = settings.load()
    day = loaded.schedule_for("anyone", "Assembly")
    assert (day.start, day.end, day.days, day.full_minutes) == (time(8), time(16, 30), frozenset(range(5)), 480)
    long = loaded.schedule_for("anyone", "Welding")
    assert (long.days, long.full_minutes) == (frozenset(range(4)), 600)


@pytest.mark.parametrize("code", ["XY-1", "xy-1"])
def test_a_member_schedule_overrides_their_department(code):
    share(departments={"Assembly": DAY_SHIFT}, members={"XY-1": LONG_SHIFT})
    assert settings.load().schedule_for(code, "Assembly").start == time(7)


def test_department_names_ignore_capitals_and_unknown_ones_have_no_schedule():
    share(departments={"Assembly": DAY_SHIFT})
    assert settings.load().schedule_for("x", "aSsEmBlY").start == time(8)
    assert settings.load().schedule_for("x", "Elsewhere") is None


def test_employees_get_their_schedule_including_supervisors():
    share(departments={"Assembly": DAY_SHIFT, "Welding": LONG_SHIFT}, members={"XY-1": DAY_SHIFT})
    people = [
        Person("Ann", "A-1", "Assembly - Supervisor", [(0, "In", "07:40:00", ""), (0, "Out", "16:30:00", "")]),
        Person("Tom", "XY-1", "Welding", [(0, "In", "08:00:00", ""), (0, "Out", "16:30:00", "")]),
    ]
    export = read_workbook(build_workbook(people), "sample.xlsx", schedule_for=settings.load().schedule_for)
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
    assert loaded.supervisors == {"Assembly": "Dana Smith"} and "saved on this PC" in loaded.note


def test_a_new_good_file_replaces_the_saved_copy(tmp_path):
    share({"Assembly": "Old Name"})
    settings.load()
    share({"Assembly": "New Name"})
    settings.load()
    settings.file_path().unlink()
    assert settings.load().supervisors == {"Assembly": "New Name"}


@pytest.mark.parametrize(
    "broken",
    [
        b"not json",
        b"[]",
        b'{"supervisors": {}}',
        b'{"supervisors": {"A": null}, "department_schedules": {}, "member_schedules": {}}',
        b'{"supervisors": {}, "department_schedules": {"A": {"start": "8am", "end": "16:30"}}, "member_schedules": {}}',
        b'{"supervisors": {}, "department_schedules": {"A": {"start": "16:30", "end": "08:00"}}, "member_schedules": {}}',
        b'{"supervisors": {}, "department_schedules": {"A": {"start": "08:00", "end": "16:30", "days": ["Monday"]}}, "member_schedules": {}}',
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
    path.write_bytes(b"\xef\xbb\xbf" + '{"supervisors": {"Łódź": "Żak"}, "department_schedules": {}, "member_schedules": {}}'.encode())
    assert settings.load().supervisors == {"Łódź": "Żak"}
