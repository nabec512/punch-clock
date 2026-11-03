from datetime import date, datetime

import pytest
from sample_export import Person, build_workbook, default_people

from punch_clock.jibble_export import UnsupportedExport, load_export, read_workbook


def read(workbook=None):
    return read_workbook(workbook or build_workbook(), "sample.xlsx")


def employee(export, code):
    return next(e for e in export.employees if e.code == code)


def column_letter(sheet, label):
    header = next(row for row in sheet.iter_rows() if any(c.value == label for c in row))
    return next(c.column_letter for c in header if c.value == label)


def first_row_for(sheet, code):
    code_column = column_letter(sheet, "Member Code")
    return next(c.row for c in sheet[code_column] if c.value == code)


def test_clean_export_reconciles_everywhere():
    export = read()
    assert export.company == "Example Manufacturing Inc."
    assert export.start == date(2026, 3, 2)
    assert export.timezone == "America/Vancouver"
    assert export.exported.startswith("Exported on ")
    assert export.timesheet_rows == 28
    assert export.review_count == 0, [c for c in export.checks if not c.match]


def test_selection_is_position_then_name_and_excludes_blank_positions():
    export = read()
    assert [e.code for e in export.included] == ["AL-1", "SO-1", "LZ-1"]
    assert [e.code for e in export.excluded] == ["RC-1"]


def test_whitespace_position_counts_as_blank():
    workbook = build_workbook()
    sheet = workbook["Raw Timesheets"]
    code, position = column_letter(sheet, "Member Code"), column_letter(sheet, "Position")
    for row in range(3, sheet.max_row + 1):
        if sheet[f"{code}{row}"].value == "SO-1":
            sheet[f"{position}{row}"] = "   "
    assert "SO-1" in [e.code for e in read(workbook).excluded]


def test_calculated_gross_is_compared_to_jibble_payroll():
    workbook = build_workbook()
    sheet = workbook["Raw Timesheets"]
    row = first_row_for(sheet, "AL-1")
    sheet[f"{column_letter(sheet, 'Payroll Hours')}{row}"] = "1h 00m"
    failed = [c.label for c in read(workbook).checks if not c.match]
    assert any("calculated gross vs Jibble payroll" in label for label in failed)


def test_overtime_sums_all_five_categories_once():
    workbook = build_workbook()
    sheet = workbook["Raw Timesheets"]
    row = first_row_for(sheet, "AL-1")
    sheet[f"{column_letter(sheet, 'Daily OT')}{row}"] = "0h 30m"
    sheet[f"{column_letter(sheet, 'Weekly OT')}{row}"] = "1h 00m"
    assert employee(read(workbook), "AL-1").overtime == 90


def test_blank_duration_is_missing_not_zero():
    workbook = build_workbook()
    sheet = workbook["Raw Timesheets"]
    row = first_row_for(sheet, "AL-1")
    sheet[f"{column_letter(sheet, 'Payroll Hours')}{row}"] = None
    person = employee(read(workbook), "AL-1")
    assert person.total("Payroll Hours") is None
    assert "Payroll Hours is missing." in person.days[date(2026, 3, 2)].issues


def test_missing_daily_row_is_reported_not_dropped():
    workbook = build_workbook()
    sheet = workbook["Raw Timesheets"]
    sheet.delete_rows(first_row_for(sheet, "RC-1"))
    record = employee(read(workbook), "RC-1").days[date(2026, 3, 2)]
    assert record.row is None and "Daily source row is missing." in record.issues


def test_incomplete_punches_are_flagged():
    people = default_people()
    people[1].punches = [(0, "In", "08:00:00", "")]
    export = read(build_workbook(people))
    record = employee(export, "SO-1").days[date(2026, 3, 2)]
    assert "Final clock-out is missing." in record.issues
    assert record.hours.gross is None


def test_team_total_mismatch_is_preserved_not_forced():
    workbook = build_workbook()
    sheet = workbook["Team Summary"]
    row = next(c.row for c in sheet["C"] if c.value == "Payroll")
    sheet[f"K{row}"] = "1h 00m"
    failed = [c for c in read(workbook).checks if not c.match]
    assert [c.label for c in failed] == ["Team Payroll: employee sum vs Jibble team total"]


def test_break_punches_are_rejected():
    people = default_people()
    people[0].punches = [
        (0, "In", "08:00:00", ""),
        (0, "StartBreak", "12:00:00", ""),
        (0, "In", "12:30:00", ""),
        (0, "Out", "16:30:00", ""),
    ]
    with pytest.raises(UnsupportedExport, match="break punches"):
        read(build_workbook(people))


def test_recorded_break_columns_are_rejected():
    workbook = build_workbook()
    sheet = workbook["Raw Timesheets"]
    column = sheet.max_column + 1
    sheet.cell(2, column, "Lunch Start")
    sheet.cell(3, column, datetime(2026, 3, 2, 12, 0))
    with pytest.raises(UnsupportedExport, match="break punches"):
        read(workbook)


def test_empty_break_columns_are_accepted():
    workbook = build_workbook()
    sheet = workbook["Raw Timesheets"]
    sheet.cell(2, sheet.max_column + 1, "Lunch Start")
    assert read(workbook).review_count == 0


@pytest.mark.parametrize("sheet", ["Raw Timesheets", "Raw Time Entries", "Team Summary"])
def test_missing_sheet_is_rejected(sheet):
    workbook = build_workbook()
    del workbook[sheet]
    with pytest.raises(UnsupportedExport, match="missing a sheet"):
        read(workbook)


def _duplicate_daily_row(workbook):
    sheet = workbook["Raw Timesheets"]
    sheet.append([c.value for c in sheet[3]])


def _decimal_duration(workbook):
    sheet = workbook["Raw Timesheets"]
    sheet[f"{column_letter(sheet, 'Payroll Hours')}3"] = "1.02"


def _unknown_entry_type(workbook):
    sheet = workbook["Raw Time Entries"]
    sheet[f"{column_letter(sheet, 'Entry Type')}3"] = "Unknown"


def _blank_member_code(workbook):
    sheet = workbook["Raw Timesheets"]
    sheet[f"{column_letter(sheet, 'Member Code')}3"] = None


def _mixed_timezones(workbook):
    sheet = workbook["Raw Time Entries"]
    sheet[f"{column_letter(sheet, 'Timezone')}3"] = "UTC"


def _renamed_column(workbook):
    sheet = workbook["Raw Timesheets"]
    sheet[f"{column_letter(sheet, 'Payroll Hours')}2"] = "Paid Hours"


def _renamed_individual_column(workbook):
    sheet = workbook["Avery Lee (AL-1) Summary"]
    sheet[f"{column_letter(sheet, 'PAYROLL HRS')}10"] = "PAID"


def _partial_week(workbook):
    workbook["Team Summary"]["B3"] = "02 March 2026 - 06 March 2026"


def _missing_individual_sheet(workbook):
    del workbook["Avery Lee (AL-1) Summary"]


def _roster_mismatch(workbook):
    sheet = workbook["Team Summary"]
    sheet["B10"] = "XX-9"


@pytest.mark.parametrize(
    "change, message",
    [
        (_duplicate_daily_row, "appears twice"),
        (_decimal_duration, "can't read the time"),
        (_unknown_entry_type, "unknown entry type"),
        (_blank_member_code, "member code or name is missing"),
        (_mixed_timezones, "different or missing time zones"),
        (_renamed_column, "column headings"),
        (_renamed_individual_column, "column headings"),
        (_partial_week, "Monday to Sunday"),
        (_missing_individual_sheet, "own sheet"),
        (_roster_mismatch, "list of employees"),
    ],
)
def test_unsafe_exports_are_rejected_with_a_clear_message(change, message):
    workbook = build_workbook()
    change(workbook)
    with pytest.raises(UnsupportedExport, match=message):
        read(workbook)


def test_moved_rows_and_columns_are_still_found_by_label():
    workbook = build_workbook()
    workbook["Avery Lee (AL-1) Summary"].insert_rows(9, 2)
    workbook["Team Summary"].insert_rows(1, 2)
    workbook["Raw Timesheets"].insert_cols(1)
    export = read(workbook)
    assert export.review_count == 0
    assert export.company == "Example Manufacturing Inc."


def test_long_names_with_truncated_sheet_titles_still_match():
    people = [Person("Alexandria Montgomery-Fitzgerald", "AM-1", "Assembly", [(0, "In", "08:00:00", ""), (0, "Out", "16:00:00", "")])]
    assert read(build_workbook(people)).review_count == 0


def test_not_a_workbook_is_rejected(tmp_path):
    path = tmp_path / "notes.xlsx"
    path.write_text("not a workbook")
    with pytest.raises(UnsupportedExport, match="could not be opened"):
        load_export(path)
