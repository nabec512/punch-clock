"""Each payroll's PowerPay import file for one week, from the returned review files. All values are fictional."""
import shutil
from datetime import date, timedelta

import openpyxl
import pytest
from sample_export import COMPANY, WEEK_START, Person, build_workbook, organization, write_settings
from test_review_flow import Sheet

from punch_clock import reports, settings
from punch_clock.app import payroll_summary
from punch_clock.jibble_export import UnsupportedExport
from punch_clock.payroll_files import last_full_week, make_payroll_files
from punch_clock.reports import REVIEW_FOLDER, process_export
from punch_clock.review_workbook import ADJUSTMENT, REVIEWED, WEEK_TOTAL

NEXT_WEDNESDAY = WEEK_START + timedelta(days=9)
EIGHT_TO_FOUR_THIRTY = {"start": "08:00", "end": "16:30"}
FOLDER = "Payroll files 2026-03-02 to 2026-03-08"


def shift(day, start="08:00:00", end="16:30:00"):
    return [(day, "In", start, ""), (day, "Out", end, "")]


def weekdays():
    return [punch for day in range(5) for punch in shift(day)]


def crew():
    return [
        # A long Monday and Saturday hours, all overtime.
        Person("Eve Staff", "ES-1", "Paint", shift(0, end="17:30:00") + [p for d in range(1, 5) for p in shift(d)] + shift(5, "07:30:00", "12:30:00")),
        Person("Cy Staff", "CS-1", "Office", weekdays()),
        Person("Fay Staff", "FS-1", "Office", []),  # off all week
        Person("Ann Temp", "AT-1", "Packing", weekdays()),  # through an agency, and in a file of her own
    ]


EMPLOYEES = {
    "ES-1": {"name": "STAFF, EVE", "payroll": "Second Payroll", "number": "12"},
    "CS-1": {"name": "STAFF, CY", "payroll": "Main Payroll", "number": "7"},
    "FS-1": {"name": "STAFF, FAY", "payroll": "Main Payroll", "number": "3"},
    "AT-1": {"name": "TEMP, ANN", "agency": "Temp Staffing Inc."},
}


def setup_settings(employees=EMPLOYEES, others=None):
    write_settings(
        settings.file_path(),
        {"Paint": "Bea Boss", "Office": "Ola Office"},
        {"Paint": EIGHT_TO_FOUR_THIRTY, "Packing": EIGHT_TO_FOUR_THIRTY, "Office": EIGHT_TO_FOUR_THIRTY},
        weekend={"Sat": {"start": "07:30", "end": "12:30"}},
        employees=employees,
        payrolls=["Main Payroll", "Second Payroll", "Third Payroll"],
        agencies=["Temp Staffing Inc."],
        others=others,
    )


@pytest.fixture
def returned(tmp_path):
    setup_settings()
    source = tmp_path / "export.xlsx"
    build_workbook(crew()).save(source)
    return tmp_path, process_export(source, tmp_path)


def review_file(result, part):
    return next(p for p in (result.folder / REVIEW_FOLDER).glob("*.xlsx") if part in p.name)


def read(path):
    return path.read_text(encoding="utf-8").splitlines()


def test_each_payroll_gets_its_peoples_regular_and_overtime_hours(returned):
    folder, _ = returned
    result = make_payroll_files(folder, today=NEXT_WEDNESDAY)
    assert result.start == WEEK_START and result.folder == folder / FOLDER
    assert sorted(p.name for p in result.folder.iterdir()) == [
        "Main Payroll 2026-03-02.csv", "Payroll summary 2026-03-02.txt", "Second Payroll 2026-03-02.csv",
    ]
    # Fay had no hours, so she isn't listed and nothing keyed for her is replaced. Ann is with an agency.
    assert read(result.folder / "Main Payroll 2026-03-02.csv") == ["employee_number,earning_code,hours,applicable_period", "7,RT,40.00,1"]
    # An hour on Monday and five on Saturday.
    assert read(result.folder / "Second Payroll 2026-03-02.csv") == [
        "employee_number,earning_code,hours,applicable_period", "12,RT,40.00,1", "12,OT,6.00,1",
    ]
    assert [(p.payroll, p.regular, p.overtime) for p in result.payrolls] == [("Main Payroll", 2400, 0), ("Second Payroll", 2400, 360)]
    assert "No one has hours this week in: Third Payroll, so there's no file for it." in result.warnings
    assert "Not marked Reviewed by their supervisor: STAFF, CY, STAFF, EVE, STAFF, FAY." in result.warnings


def test_the_summary_lists_everyone_to_check_against_powerpay(returned):
    folder, _ = returned
    result = make_payroll_files(folder, today=NEXT_WEDNESDAY)
    text = result.summary.read_text(encoding="utf-8")
    assert "Payroll hours for Mon Mar 2 to Sun Mar 8, 2026" in text
    assert "Second Payroll: 1 person, 40.00 RT, 6.00 OT. File: Second Payroll 2026-03-02.csv" in text
    assert "12  STAFF, EVE" in text and "6.00 OT   Example Co.   (not marked Reviewed)" in text
    assert "Third Payroll" in text  # under To check
    window = payroll_summary(result)
    assert "Main Payroll 2026-03-02.csv: 1 employee, 40.00 regular hours, 0.00 overtime" in window
    assert "Import each file into its payroll's run in PowerPay first" in window


def test_hours_come_from_what_the_supervisor_approved(returned):
    folder, week = returned
    sheet = Sheet(review_file(week, "Bea Boss"))
    sheet.set("Eve Staff", WEEK_START, ADJUSTMENT, -60).set("Eve Staff", WEEK_TOTAL, REVIEWED, "Yes").save()
    result = make_payroll_files(folder, today=NEXT_WEDNESDAY)
    assert read(result.folder / "Second Payroll 2026-03-02.csv")[1:] == ["12,RT,40.00,1", "12,OT,5.00,1"]
    assert "STAFF, EVE" not in next(w for w in result.warnings if w.startswith("Not marked Reviewed"))


def test_someone_not_linked_stops_it(returned):
    folder, _ = returned
    setup_settings({code: link for code, link in EMPLOYEES.items() if code != "FS-1"})
    with pytest.raises(UnsupportedExport, match="doesn't say who pays these people") as stopped:
        make_payroll_files(folder, today=NEXT_WEDNESDAY)
    assert "Fay Staff (FS-1, Example Co.)" in str(stopped.value)
    assert not list(folder.glob("Payroll files*"))


def test_mistakes_in_a_file_with_payroll_staff_stop_it(returned):
    folder, week = returned
    Sheet(review_file(week, "Ola Office")).set("Cy Staff", WEEK_START, ADJUSTMENT, 7).save()
    with pytest.raises(UnsupportedExport, match="Cy Staff, Mon Mar 2: the adjustment, 7, isn't in steps of 15 minutes"):
        make_payroll_files(folder, today=NEXT_WEDNESDAY)
    assert not list(folder.glob("Payroll files*"))


def test_mistakes_in_a_file_of_agency_staff_only_dont_stop_it(returned):
    folder, week = returned
    Sheet(review_file(week, "Missing supervisor")).set("Ann Temp", WEEK_START, ADJUSTMENT, 7).save()
    assert len(make_payroll_files(folder, today=NEXT_WEDNESDAY).payrolls) == 2


def test_a_file_found_twice_is_refused(returned):
    folder, week = returned
    (folder / "Returned").mkdir()
    shutil.copy2(review_file(week, "Bea Boss"), folder / "Returned")
    with pytest.raises(UnsupportedExport, match="Bea Boss's file for the week of Mar 2 is in two files"):
        make_payroll_files(folder, today=NEXT_WEDNESDAY)


def test_an_organization_with_no_files_is_listed(returned):
    folder, _ = returned
    setup_settings(others={"Other Org": organization({"Paint": "Pia Other"}, {"Paint": EIGHT_TO_FOUR_THIRTY})})
    result = make_payroll_files(folder, today=NEXT_WEDNESDAY)
    assert "There are no files from Other Org for the week of Mar 2." in result.warnings


def test_only_the_last_full_week_is_read(returned):
    folder, _ = returned
    with pytest.raises(UnsupportedExport, match="no supervisor review files for Mon Mar 9 to Sun Mar 15, 2026"):
        make_payroll_files(folder, today=WEEK_START + timedelta(days=16))


def test_the_last_full_week_ends_on_the_sunday_before():
    assert last_full_week(date(2026, 11, 25)) == date(2026, 11, 16)  # a Wednesday
    assert last_full_week(date(2026, 11, 23)) == date(2026, 11, 16)  # the Monday after
    assert last_full_week(date(2026, 11, 22)) == date(2026, 11, 9)  # that Sunday, the week isn't over


def test_making_them_again_makes_a_new_folder(returned):
    folder, _ = returned
    first = make_payroll_files(folder, today=NEXT_WEDNESDAY)
    assert make_payroll_files(folder, today=NEXT_WEDNESDAY).folder == first.folder.with_name(FOLDER + " (2)")


def test_settings_without_payrolls_are_refused(returned):
    folder, _ = returned
    write_settings(settings.file_path(), {"Paint": "Bea Boss"})
    with pytest.raises(UnsupportedExport, match="doesn't list any payrolls yet"):
        make_payroll_files(folder, today=NEXT_WEDNESDAY)


def test_the_company_is_named_in_each_unlinked_line(returned):
    folder, _ = returned
    setup_settings({code: link for code, link in EMPLOYEES.items() if code not in ("FS-1", "CS-1")})
    with pytest.raises(UnsupportedExport) as stopped:
        make_payroll_files(folder, today=NEXT_WEDNESDAY)
    assert str(stopped.value).count(COMPANY) == 2


def test_a_missing_supervisor_file_is_listed(returned):
    folder, week = returned
    review_file(week, "Ola Office").unlink()
    result = make_payroll_files(folder, today=NEXT_WEDNESDAY)
    assert (
        "No file from Ola Office (Example Co.) for the week of Mar 2. If they had people that week, their hours are missing."
    ) in result.warnings


@pytest.mark.parametrize(
    "name, content",
    [
        ("Example Co. - Ola Office - Office - 2026-03-02 (returned).xlsx", b"locked with a password"),
        ("Example Co. - Ola Office - Office - 2026-03-02.xls", b"old format"),
    ],
)
def test_a_file_from_the_week_that_cant_be_read_stops_it(returned, name, content):
    folder, _ = returned
    (folder / "Returned").mkdir()
    (folder / "Returned" / name).write_bytes(content)
    with pytest.raises(UnsupportedExport, match="may be supervisor files for Mon Mar 2 to Sun Mar 8, 2026") as stopped:
        make_payroll_files(folder, today=NEXT_WEDNESDAY)
    assert name in str(stopped.value) and "save it as an Excel Workbook (.xlsx)" in str(stopped.value)


def test_a_review_file_too_old_to_read_back_stops_it(returned):
    folder, week = returned
    path = review_file(week, "Ola Office")
    workbook = openpyxl.load_workbook(path)
    del workbook["Punch Clock data"]  # as made before 0.11.0
    workbook.save(path)
    with pytest.raises(UnsupportedExport, match="can't read them") as stopped:
        make_payroll_files(folder, today=NEXT_WEDNESDAY)
    assert "Ola Office" in str(stopped.value)


def test_an_agency_persons_mistake_doesnt_hold_up_payroll_in_the_same_file(tmp_path):
    setup_settings()
    people = crew()
    people[3] = Person("Ann Temp", "AT-1", "Office", weekdays())  # now in Ola's file, with Cy
    source = tmp_path / "export.xlsx"
    build_workbook(people).save(source)
    week = process_export(source, tmp_path)
    Sheet(review_file(week, "Ola Office")).set("Ann Temp", WEEK_START, ADJUSTMENT, 7).save()
    assert len(make_payroll_files(tmp_path, today=NEXT_WEDNESDAY).payrolls) == 2
    Sheet(review_file(week, "Ola Office")).set("Cy Staff", WEEK_START, ADJUSTMENT, 7).save()
    with pytest.raises(UnsupportedExport) as stopped:
        make_payroll_files(tmp_path, today=NEXT_WEDNESDAY)
    assert "Cy Staff, Mon Mar 2" in str(stopped.value) and "Ann Temp" not in str(stopped.value)


def test_two_payrolls_that_would_get_the_same_file_name_are_refused(returned):
    folder, _ = returned
    employees = {**EMPLOYEES, "ES-1": {"name": "STAFF, EVE", "payroll": "Main/Payroll", "number": "12"}}
    write_settings(
        settings.file_path(),
        {"Paint": "Bea Boss", "Office": "Ola Office"},
        {"Paint": EIGHT_TO_FOUR_THIRTY, "Packing": EIGHT_TO_FOUR_THIRTY, "Office": EIGHT_TO_FOUR_THIRTY},
        employees=employees,
        payrolls=["Main Payroll", "Main/Payroll"],
        agencies=["Temp Staffing Inc."],
    )
    with pytest.raises(UnsupportedExport, match='would both be called "Main Payroll 2026-03-02.csv"'):
        make_payroll_files(folder, today=NEXT_WEDNESDAY)
    assert not list(folder.glob("Payroll files*"))


def test_a_folder_too_deep_for_excel_is_refused(returned, monkeypatch):
    folder, _ = returned
    monkeypatch.setattr(reports, "EXCEL_PATH_LIMIT", len(str(folder)) + 20)
    with pytest.raises(UnsupportedExport, match="too long for Windows and Excel"):
        make_payroll_files(folder, today=NEXT_WEDNESDAY)
    assert not list(folder.glob("Payroll files*"))
