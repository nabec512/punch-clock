"""Receiving returned files into the accounting folder, and making payroll and agency files from it. All fictional."""
import csv
import shutil
from datetime import datetime, timedelta

import openpyxl
import pytest
from sample_export import COMPANY, WEEK_START, build_workbook, update_accounting
from test_payroll_files import EMPLOYEES, NEXT_WEDNESDAY, crew, read, setup_settings
from test_review_flow import Sheet

from punch_clock import settings
from punch_clock.agency_hours import make_agency_hours
from punch_clock.app import receive_summary
from punch_clock.archive import HISTORY, RECEIPTS, RETURNED, receive_files, received_weeks
from punch_clock.jibble_export import UnsupportedExport
from punch_clock.payroll_files import make_payroll_files
from punch_clock.reports import REVIEW_FOLDER, process_export
from punch_clock.review_workbook import ADJUSTMENT

WEEK = WEEK_START.isoformat()
KEPT = f"Example Co/{WEEK}"  # Windows doesn't allow a folder name ending in a dot
NOON = datetime(2026, 3, 9, 12, 0, 0)


def use_accounting_folder(folder):
    update_accounting(settings.file_path(), accounting_folder=str(folder))


@pytest.fixture
def setup(tmp_path):
    """A week's review files as sent to the supervisors, and an empty accounting folder."""
    setup_settings()
    accounting = tmp_path / "Accounting"
    accounting.mkdir()
    use_accounting_folder(accounting)
    sent = tmp_path / "Sent"
    sent.mkdir()
    source = sent / "export.xlsx"
    build_workbook(crew()).save(source)
    week = process_export(source, sent)
    return accounting, sorted((week.folder / REVIEW_FOLDER).glob("*.xlsx"))


def receipts(accounting):
    with open(accounting / RETURNED / RECEIPTS, encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def named(files, part):
    return next(path for path in files if part in path.name)


def test_received_files_are_kept_by_organization_and_week_with_a_receipt(setup):
    accounting, returned = setup
    result = receive_files(returned, now=NOON)
    kept = sorted(p.relative_to(accounting / RETURNED).as_posix() for p in (accounting / RETURNED).rglob("*.xlsx"))
    assert kept == [
        f"{KEPT}/Example Co. - Bea Boss - {WEEK}.xlsx",
        f"{KEPT}/Example Co. - Missing supervisor - {WEEK}.xlsx",
        f"{KEPT}/Example Co. - Ola Office - {WEEK}.xlsx",
    ]
    rows = receipts(accounting)
    assert [row["file"] for row in rows] == kept
    assert rows[0]["received_at"] == "2026-03-09T12:00:00" and rows[0]["week"] == WEEK and rows[0]["organization"] == COMPANY
    assert len(rows[0]["sha256"]) == 64 and rows[0]["replaced"] == ""
    assert not result.warnings
    assert receive_summary(result).startswith("Received 3 supervisor files:")


def test_the_weeks_with_files_received_are_listed(setup):
    accounting, returned = setup
    assert received_weeks(accounting) == set()  # nothing received yet, so no receipt log
    receive_files(returned, now=NOON)
    assert received_weeks(accounting) == {WEEK_START}


def test_receiving_the_same_file_again_changes_nothing(setup):
    accounting, returned = setup
    receive_files(returned, now=NOON)
    again = receive_files(returned[:1], now=NOON + timedelta(hours=1))
    assert again.received[0].unchanged and len(receipts(accounting)) == 3
    assert "Already received, and unchanged:" in receive_summary(again)


def test_a_corrected_file_replaces_the_one_before_which_is_kept_in_history(setup):
    accounting, returned = setup
    receive_files(returned, now=NOON)
    corrected = named(returned, "Bea Boss")
    Sheet(corrected).set("Eve Staff", WEEK_START, ADJUSTMENT, -60).save()
    result = receive_files([corrected], now=NOON + timedelta(days=1))
    history = accounting / RETURNED / KEPT / HISTORY
    assert [p.name for p in history.iterdir()] == [f"Example Co. - Bea Boss - {WEEK} (replaced 2026-03-10 120000).xlsx"]
    assert receipts(accounting)[-1]["replaced"] == f"{KEPT}/{HISTORY}/{next(history.iterdir()).name}"
    assert "replacing the one received before" in receive_summary(result)
    payroll = make_payroll_files(today=NEXT_WEDNESDAY)
    assert read(payroll.folder / "Second Payroll 2026-03-02.csv")[1:] == ["STAFF EVE,12,RT,40.00,1", "STAFF EVE,12,OT,5.00,1"]


def test_a_renamed_file_is_still_kept_under_its_proper_name(setup, tmp_path):
    accounting, returned = setup
    renamed = tmp_path / "RE Hours week 10 (2).xlsx"
    shutil.copy2(named(returned, "Ola Office"), renamed)
    result = receive_files([renamed], now=NOON)
    assert result.received[0].path.name == f"Example Co. - Ola Office - {WEEK}.xlsx"


def test_payroll_files_are_read_from_and_made_in_the_accounting_folder(setup):
    accounting, returned = setup
    receive_files(returned, now=NOON)
    result = make_payroll_files(today=NEXT_WEDNESDAY)
    assert result.folder == accounting / "Payroll files" / "Payroll files 2026-03-02 to 2026-03-08"
    assert read(result.folder / "Main Payroll 2026-03-02.csv")[1:] == ["STAFF CY,7,RT,40.00,1"]


def test_a_file_changed_in_the_accounting_folder_is_refused(setup):
    accounting, returned = setup
    receive_files(returned, now=NOON)
    kept = accounting / RETURNED / KEPT / f"Example Co. - Ola Office - {WEEK}.xlsx"
    Sheet(kept).set("Cy Staff", WEEK_START, ADJUSTMENT, 60).save()
    with pytest.raises(UnsupportedExport, match="changed, or put there, without going through Receive returned files") as stopped:
        make_payroll_files(today=NEXT_WEDNESDAY)
    assert "Ola Office" in str(stopped.value)


def test_a_file_put_in_the_accounting_folder_by_hand_is_refused(setup):
    accounting, returned = setup
    receive_files(returned[:2], now=NOON)
    shutil.copy2(returned[2], accounting / RETURNED / KEPT / returned[2].name)
    with pytest.raises(UnsupportedExport, match="without going through Receive returned files"):
        make_payroll_files(today=NEXT_WEDNESDAY)


def test_nothing_received_yet_says_so(setup):
    with pytest.raises(UnsupportedExport, match="No supervisor files have been received for Mon Mar 2 to Sun Mar 8, 2026 yet"):
        make_payroll_files(today=NEXT_WEDNESDAY)


def test_a_batch_with_a_file_that_isnt_a_review_file_keeps_nothing(setup, tmp_path):
    accounting, returned = setup
    other = tmp_path / "budget.xlsx"
    openpyxl.Workbook().save(other)
    with pytest.raises(UnsupportedExport):
        receive_files([*returned, other], now=NOON)
    assert not list((accounting / RETURNED).rglob("*.xlsx"))


def test_the_same_supervisor_twice_in_one_batch_is_refused(setup, tmp_path):
    _, returned = setup
    copy = tmp_path / "copy.xlsx"
    shutil.copy2(returned[0], copy)
    with pytest.raises(UnsupportedExport, match="is in two files"):
        receive_files([returned[0], copy], now=NOON)


def test_mistakes_are_reported_when_the_file_is_received(setup):
    _, returned = setup
    Sheet(named(returned, "Ola Office")).set("Cy Staff", WEEK_START, ADJUSTMENT, 7).save()
    result = receive_files(returned, now=NOON)
    assert len(result.received) == 3
    assert any("needs fixing before payday" in w and "the adjustment, 7, isn't in steps of 15" in w for w in result.warnings)


def test_people_nobody_pays_are_reported_when_the_file_is_received(setup):
    _, returned = setup
    setup_settings({code: link for code, link in EMPLOYEES.items() if code != "CS-1"})
    use_accounting_folder(setup[0])
    result = receive_files(returned, now=NOON)
    assert any("doesn't say who pays these people in Ola Office's file" in w and "Cy Staff" in w for w in result.warnings)


def test_an_accounting_folder_that_cant_be_reached_stops_everything(setup, tmp_path):
    _, returned = setup
    use_accounting_folder(tmp_path / "Not there")
    with pytest.raises(UnsupportedExport, match="accounting folder can't be reached"):
        receive_files(returned, now=NOON)
    with pytest.raises(UnsupportedExport, match="accounting folder can't be reached"):
        make_payroll_files(today=NEXT_WEDNESDAY)
    assert not (tmp_path / "Not there").exists()


def test_receiving_needs_the_accounting_folder_in_the_settings(tmp_path):
    setup_settings()
    with pytest.raises(UnsupportedExport, match='Add "accounting_folder"'):
        receive_files([], now=NOON)


def test_the_accounting_folder_must_be_a_full_location(tmp_path):
    setup_settings()
    use_accounting_folder("Accounting")
    with pytest.raises(UnsupportedExport, match="accounting_folder must be the full location of a folder"):
        settings.load_full()


def test_agency_hours_are_read_from_and_made_in_the_accounting_folder(setup, tmp_path):
    accounting, returned = setup
    receive_files(returned, now=NOON)
    second = tmp_path / "Sent 2"
    second.mkdir()
    source = second / "export.xlsx"
    build_workbook(crew(), week_start=WEEK_START + timedelta(days=7)).save(source)
    receive_files(sorted((process_export(source, second).folder / REVIEW_FOLDER).glob("*.xlsx")), now=NOON)
    result = make_agency_hours(today=WEEK_START + timedelta(days=16))
    assert result.folder.parent == accounting / "Agency hours"
    assert len(result.files) == 6 and [r.agency.name for r, _ in result.reports] == ["Temp Staffing Inc."]
