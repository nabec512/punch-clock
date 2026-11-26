"""Each agency's hours for a two-week pay period, from the returned review files. All values are fictional."""
import shutil
from datetime import date, timedelta

import openpyxl
import pytest
from sample_export import COMPANY, WEEK_START, Person, agency_details, build_workbook, organization, update_accounting, write_settings
from test_review_flow import Sheet

from punch_clock import settings
from punch_clock.agency_hours import make_agency_hours
from punch_clock.agency_workbook import DETAIL_TITLE, HEADER_ROW, SHEET
from punch_clock.agency_workbook import TOTAL as TOTAL_ROW
from punch_clock.app import agency_summary
from punch_clock.jibble_export import UnsupportedExport
from punch_clock.reports import REVIEW_FOLDER, process_export
from punch_clock.review_workbook import TOTAL

FIRST, SECOND = WEEK_START, WEEK_START + timedelta(days=7)
PAYDAY = WEEK_START + timedelta(days=16)  # the Wednesday after the period
EIGHT_TO_FOUR_THIRTY = {"start": "08:00", "end": "16:30"}
TEMP, SECOND_AGENCY = "Temp Staffing Inc.", "Second Agency"
OTHER_ORG = "Other Org"


def shift(day, start="08:00:00", end="16:30:00"):
    return [(day, "In", start, ""), (day, "Out", end, "")]


def week(*days, **changed):
    """Monday to Friday, with any day's (start, end) changed by its offset."""
    punches = []
    for day in days:
        punches += shift(day, *changed.get(f"d{day}", ()))
    return punches


def crews():
    """The first week, then the second."""
    first = [
        Person("Ann Temp", "AT-1", "Paint", week(0, 1, 2, 3, 4)),
        Person("Bo Temp", "BT-1", "Packing", week(0)),
        Person("Cy Staff", "CS-1", "Office", week(0, 1, 2, 3, 4)),
    ]
    second = [
        # A long Monday and Saturday hours: overtime, and no lunch on Saturday.
        Person("Ann Temp", "AT-1", "Paint", week(0, 1, 2, 3, 4, d0=("08:00:00", "17:30:00")) + shift(5, "07:30:00", "12:30:00")),
        Person("Bo Temp", "BT-1", "Packing", []),
        Person("Cy Staff", "CS-1", "Office", week(0, 1, 2, 3, 4)),
    ]
    return first, second


EMPLOYEES = {
    "AT-1": {"name": "TEMP, ANN", "agency": TEMP},
    "BT-1": {"name": "TEMP, BO", "agency": SECOND_AGENCY},
    "CS-1": {"name": "STAFF, CY", "payroll": "Main Payroll", "number": "7"},
}


def setup_settings(employees=EMPLOYEES, others=None):
    write_settings(
        settings.file_path(),
        {"Paint": "Bea Boss", "Office": "Ola Office"},
        {"Paint": EIGHT_TO_FOUR_THIRTY, "Packing": EIGHT_TO_FOUR_THIRTY, "Office": EIGHT_TO_FOUR_THIRTY},
        weekend={"Sat": {"start": "07:30", "end": "12:30"}},
        employees=employees,
        payrolls=["Main Payroll"],
        agencies=[TEMP, SECOND_AGENCY],
        others=others,
    )


def make_week(folder, people, start, company=COMPANY):
    source = folder / f"export {company} {start}.xlsx"
    build_workbook(people, week_start=start, company=company).save(source)
    return process_export(source, folder)


@pytest.fixture
def returned(tmp_path):
    """Both weeks' review files, as made, in one folder."""
    setup_settings()
    first, second = crews()
    weeks = [make_week(tmp_path, first, FIRST), make_week(tmp_path, second, SECOND)]
    return tmp_path, weeks


def review_files(result, part):
    return [p for p in (result.folder / REVIEW_FOLDER).glob("*.xlsx") if part in p.name]


def _table(sheet, first_row):
    found = []
    for row in sheet.iter_rows(min_row=first_row, values_only=True):
        if row[0] in (None, TOTAL_ROW):
            return found
        found.append(tuple(round(v, 2) if isinstance(v, float) else v for v in row[:7]))
    return found


def rows(path):
    """Each person as (name, week 1 regular and overtime, week 2 regular and overtime, the two weeks' regular and
    overtime, lunch days, lunch), from the main table and the detail by week."""
    sheet = openpyxl.load_workbook(path, data_only=True)[SHEET]
    main = _table(sheet, HEADER_ROW + 2)
    title = next(row[0].row for row in sheet.iter_rows() if row[0].value == DETAIL_TITLE)
    detail = _table(sheet, title + 3)
    assert [row[0] for row in main] == [row[0] for row in detail]
    return [
        (name, d[1], d[2], d[4], d[5], regular, overtime, d[3] + d[6], lunch)
        for (name, regular, overtime, lunch, *_), d in zip(main, detail)
    ]


def cells(path, data_only=True):
    sheet = openpyxl.load_workbook(path, data_only=data_only)[SHEET]
    return {cell.coordinate: cell.value for row in sheet.iter_rows() for cell in row if cell.value is not None}


def test_each_agency_gets_both_weeks_hours_and_lunch_in_one_file(returned):
    folder, _ = returned
    result = make_agency_hours(folder, today=PAYDAY)
    assert result.start == FIRST and result.folder == folder / "Agency hours 2026-03-02 to 2026-03-15"
    assert sorted(p.name for p in result.folder.iterdir()) == [
        "Second Agency 2026-03-02 to 2026-03-15.xlsx",
        "Temp Staffing Inc. 2026-03-02 to 2026-03-15.xlsx",
    ]
    temp = result.folder / "Temp Staffing Inc. 2026-03-02 to 2026-03-15.xlsx"
    # Week 1: 40 regular. Week 2: 40 regular, and 1 hour on Monday plus 5 on Saturday as overtime.
    # Lunch on the ten weekdays, but not on Saturday: 10 x $3.00.
    assert rows(temp) == [("TEMP, ANN", 40, 0, 40, 6, 80, 6, 10, -30)]
    top = cells(temp)
    assert (top["A1"], top["A2"], top["A3"]) == ("TO:", "Temp Staffing Inc. Holdings", agency_details(TEMP)["contact"])
    assert (top["A5"], top["A6"]) == ("FROM:", COMPANY)
    assert top["B8"] == "Mon Mar 2 to Sun Mar 15, 2026" and "A9" not in top  # the lunch rate isn't shown
    assert (top["A10"], top["B10"], top["C10"], top["D10"]) == ("Employee", "Regular", "Overtime", "Lunch")
    assert top["A12"] == "Total" and (top["B12"], top["C12"], top["D12"]) == (80, 6, -30)
    assert top["A15"] == "Detail by week" and (top["B16"], top["E16"]) == ("Week of Mar 2", "Week of Mar 9")
    assert (top["B17"], top["C17"], top["D17"]) == ("Regular", "Overtime", "Lunch days")
    # The whole Total row stands out, as it's what the agency is paid for.
    sheet = openpyxl.load_workbook(temp)[SHEET]
    assert {sheet.cell(12, column).fill.fgColor.rgb for column in range(1, 5)} == {"FFC6E0B4"}
    # Bo only worked in the first week, and the payroll employee isn't in either file.
    assert rows(result.folder / "Second Agency 2026-03-02 to 2026-03-15.xlsx") == [("TEMP, BO", 8, 0, 0, 0, 8, 0, 1, -3)]


def test_totals_and_lunch_are_formulas_so_accounting_can_change_lunch(returned):
    folder, _ = returned
    result = make_agency_hours(folder, today=PAYDAY)
    formulas = cells(result.reports[1][1], data_only=False)
    assert result.reports[1][0].agency.name == TEMP
    # The main table adds up the detail by week, where each week's lunch days can be changed.
    assert (formulas["B11"], formulas["C11"]) == ("=B18+E18", "=C18+F18")
    assert (formulas["D18"], formulas["G18"]) == (5, 5)
    assert formulas["D11"] == "=-ROUND((D18+G18)*3.00,2)"
    assert (formulas["B12"], formulas["D12"]) == ("=SUM(B11:B11)", "=SUM(D11:D11)")


def test_hours_come_from_what_the_supervisor_approved(returned):
    folder, weeks = returned
    sheet = Sheet(review_files(weeks[1], "Bea Boss")[0])
    sheet.set("Ann Temp", SECOND + timedelta(days=4), "Adjustment (minutes)", -480).save()  # Friday wasn't worked after all
    result = make_agency_hours(folder, today=PAYDAY)
    # Friday's 8 hours are gone, and overtime makes up the short week first. Friday had no lunch either.
    assert rows(result.reports[1][1]) == [("TEMP, ANN", 40, 0, 38, 0, 78, 0, 9, -27)]


def test_nothing_is_listed_when_every_file_is_there(returned):
    folder, _ = returned
    assert not make_agency_hours(folder, today=PAYDAY).warnings


def test_a_supervisor_missing_a_week_is_listed(returned):
    folder, weeks = returned
    review_files(weeks[1], "Bea Boss")[0].unlink()
    result = make_agency_hours(folder, today=PAYDAY)
    assert any(w.startswith("No file from Bea Boss (Example Co.) for the week of Mar 9.") for w in result.warnings)
    assert rows(result.reports[1][1]) == [("TEMP, ANN", 40, 0, 0, 0, 40, 0, 5, -15)]


def test_a_file_found_twice_is_refused(returned):
    folder, weeks = returned
    copy = folder / "Returned" / "by email"
    copy.mkdir(parents=True)
    shutil.copy2(review_files(weeks[0], "Bea Boss")[0], copy)
    with pytest.raises(UnsupportedExport, match="Bea Boss's file for the week of Mar 2 is in two files") as stopped:
        make_agency_hours(folder, today=PAYDAY)
    assert "by email" in str(stopped.value)
    assert not list(folder.glob("Agency hours*"))


def test_mistakes_in_a_file_with_agency_staff_stop_the_run(returned):
    folder, weeks = returned
    Sheet(review_files(weeks[0], "Missing supervisor")[0]).set("Bo Temp", FIRST, "Adjustment (minutes)", 7).save()
    with pytest.raises(UnsupportedExport, match="Bo Temp, Mon Mar 2: the adjustment, 7, isn't in steps of 15 minutes"):
        make_agency_hours(folder, today=PAYDAY)
    assert not list(folder.glob("Agency hours*"))


def test_mistakes_in_a_file_without_agency_staff_dont_stop_it(returned):
    folder, weeks = returned
    Sheet(review_files(weeks[0], "Ola Office")[0]).set("Cy Staff", FIRST, "Adjustment (minutes)", 7).save()
    assert len(make_agency_hours(folder, today=PAYDAY).reports) == 2


def test_typed_hours_for_incomplete_punches_count(tmp_path):
    setup_settings()
    first, second = crews()
    first[0] = Person("Ann Temp", "AT-1", "Paint", week(0, 1, 2, 3) + [(4, "In", "08:00:00", "")])
    weeks = [make_week(tmp_path, first, FIRST), make_week(tmp_path, second, SECOND)]
    with pytest.raises(UnsupportedExport, match="the punches are incomplete and no hours were typed"):
        make_agency_hours(tmp_path, today=PAYDAY)
    Sheet(review_files(weeks[0], "Bea Boss")[0]).set("Ann Temp", FIRST + timedelta(days=4), TOTAL, 4 / 24).save()
    result = make_agency_hours(tmp_path, today=PAYDAY)
    # Overtime makes up the short first week, so its regular is 36 hours.
    assert rows(result.reports[1][1])[0][1:3] == (36, 0)


def test_only_the_latest_period_that_has_ended_is_read(returned):
    folder, _ = returned
    # The Sunday the period ends, it hasn't ended yet, so the one before is wanted, and there are no files for it.
    with pytest.raises(UnsupportedExport, match="no supervisor review files for Mon Feb 16 to Sun Mar 1, 2026"):
        make_agency_hours(folder, today=SECOND + timedelta(days=6))
    assert make_agency_hours(folder, today=SECOND + timedelta(days=7)).start == FIRST


def test_the_period_is_counted_in_two_weeks_from_the_settings():
    pay = settings.AgencyPay(3.0, date(2026, 3, 2))
    assert pay.period_before(date(2026, 3, 18)) == date(2026, 3, 2)  # the Wednesday after
    assert pay.period_before(date(2026, 3, 16)) == date(2026, 3, 2)
    assert pay.period_before(date(2026, 3, 15)) == date(2026, 2, 16)  # the period's last Sunday, so it hasn't ended
    assert pay.period_before(date(2026, 4, 1)) == date(2026, 3, 16)
    assert pay.period_before(date(2026, 1, 7)) == date(2025, 12, 22)  # before the date in the settings too


def test_an_agency_with_people_sent_from_two_companies_gets_a_file_from_each(tmp_path):
    other = organization(
        {"Paint": "Pia Other"}, {"Paint": EIGHT_TO_FOUR_THIRTY},
        employees={"ZT-1": {"name": "TEMP, ZOE", "agency": TEMP}}, paid_by="Other Holdings",
    )
    setup_settings(others={OTHER_ORG: other})
    first, second = crews()
    make_week(tmp_path, first, FIRST), make_week(tmp_path, second, SECOND)
    zoe = Person("Zoe Temp", "ZT-1", "Paint", week(0, 1))
    make_week(tmp_path, [zoe], FIRST, OTHER_ORG), make_week(tmp_path, [zoe], SECOND, OTHER_ORG)
    result = make_agency_hours(tmp_path, today=PAYDAY)
    names = sorted(path.name for _, path in result.reports)
    assert names == [
        "Second Agency 2026-03-02 to 2026-03-15.xlsx",
        "Temp Staffing Inc. from Example Co. 2026-03-02 to 2026-03-15.xlsx",
        "Temp Staffing Inc. from Other Holdings 2026-03-02 to 2026-03-15.xlsx",
    ]
    other_file = result.folder / names[2]
    assert cells(other_file)["A6"] == "Other Holdings"
    assert rows(other_file) == [("TEMP, ZOE", 16, 0, 16, 0, 32, 0, 4, -12)]


def test_people_the_settings_dont_link_are_listed(returned):
    folder, _ = returned
    setup_settings(employees={code: link for code, link in EMPLOYEES.items() if code != "CS-1"})
    result = make_agency_hours(folder, today=PAYDAY)
    assert any("doesn't say who pays these people" in w and "Cy Staff (CS-1, Example Co.)" in w for w in result.warnings)


def test_settings_without_agencies_are_refused(returned):
    folder, _ = returned
    write_settings(settings.file_path(), {"Paint": "Bea Boss"})
    update_accounting(settings.file_path())  # an accounting settings file with nothing in it yet
    with pytest.raises(UnsupportedExport, match="doesn't list any agencies yet"):
        make_agency_hours(folder, today=PAYDAY)


def test_files_that_arent_review_files_are_skipped(returned):
    folder, _ = returned
    (folder / "notes.xlsx").write_bytes(b"not a spreadsheet")
    openpyxl.Workbook().save(folder / "budget.xlsx")
    (folder / "~$open by Excel.xlsx").write_bytes(b"lock")
    result = make_agency_hours(folder, today=PAYDAY)
    assert len(result.files) == 6
    # One that can't be opened could be anything, so it's listed rather than skipped without a word.
    assert any("couldn't be opened" in w and "notes.xlsx" in w for w in result.warnings)


def test_making_them_again_makes_a_new_folder(returned):
    folder, _ = returned
    first = make_agency_hours(folder, today=PAYDAY)
    again = make_agency_hours(folder, today=PAYDAY)
    assert again.folder == first.folder.with_name(first.folder.name + " (2)")


def test_the_window_says_where_each_file_goes(returned):
    folder, _ = returned
    text = agency_summary(make_agency_hours(folder, today=PAYDAY))
    assert "Done. The agency hours for Mon Mar 2 to Sun Mar 15, 2026 are in this folder:" in text
    assert "Temp Staffing Inc. 2026-03-02 to 2026-03-15.xlsx: 1 employee, to hours@example.com" in text
    assert "Read 6 supervisor files. Lunch is $3.00 for each scheduled day worked." in text
