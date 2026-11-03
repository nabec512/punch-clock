"""The round trip: process an export, supervisors edit their files, build the approved report."""
from datetime import date, datetime, time

import openpyxl
import pytest
from pypdf import PdfReader
from sample_export import Person, build_workbook

from punch_clock import reports, supervisor_list
from punch_clock.approvals import DayInput, approve_day
from punch_clock.assignments import (
    departments_without_supervisor,
    review_file_name,
    review_groups,
    safe_file_name,
    with_supervisors,
)
from punch_clock.hours import Punch, calculate_day
from punch_clock.jibble_export import UnsupportedExport, load_export
from punch_clock.reports import REVIEW_FOLDER, build_approved, process_export
from punch_clock.review_workbook import ADJUSTMENT, APPROVED, CODE, COMMENT, DATE, INFO_SHEET, REVIEWED, WEEK_TOTAL

MONDAY, TUESDAY = date(2026, 3, 2), date(2026, 3, 3)


def worked(name, code, position, days=(0,)):
    punches = []
    for day in days:
        punches += [(day, "In", "08:00:00", ""), (day, "Out", "16:30:00", "")]
    return Person(name, code, position, punches)


def crew():
    return [
        worked("Bea Boss", "BB-1", "Paint - Supervisor"),
        worked("Ann Painter", "AP-1", "Paint", (0, 1)),
        worked("Cal Painter", "CP-1", "Paint"),
        worked("Dee Solo", "DS-1", "Packing"),
        Person("Eli Blank", "EB-1", "", []),
    ]


@pytest.fixture(autouse=True)
def paint_has_a_supervisor():
    supervisor_list.save({"Paint": "Bea Boss"})


@pytest.fixture
def processed(tmp_path):
    source = tmp_path / "export.xlsx"
    build_workbook(crew()).save(source)
    return process_export(source)


def review_file(result, part):
    return next(p for p in (result.folder / REVIEW_FOLDER).glob("*.xlsx") if part in p.name)


class Sheet:
    """Edit a review file the way a supervisor would."""

    def __init__(self, path):
        self.path = path
        self.workbook = openpyxl.load_workbook(path)
        self.sheet = self.workbook["Review"]
        header = next(r for r in self.sheet.iter_rows() if any(c.value == CODE for c in r))
        self.columns = {c.value: c.column for c in header}
        self.first = header[0].row + 1

    def row_for(self, code, when):
        for number in range(self.first, self.sheet.max_row + 1):
            if self.sheet.cell(number, self.columns[CODE]).value != code:
                continue
            value = self.sheet.cell(number, self.columns[DATE]).value
            if value == when or (isinstance(value, datetime) and value.date() == when):
                return number
        raise AssertionError((code, when))

    def set(self, code, when, label, value):
        self.sheet.cell(self.row_for(code, when), self.columns[label], value)
        return self

    def save(self):
        self.workbook.save(self.path)


# --- Assignments ---------------------------------------------------------------


def test_supervisor_tag_is_part_of_position_not_department(tmp_path):
    export = _export(tmp_path, crew())
    boss = next(e for e in export.employees if e.code == "BB-1")
    assert boss.position == "Paint - Supervisor" and boss.department == "Paint" and boss.is_supervisor


@pytest.mark.parametrize("position", ["Paint-Supervisor", "Paint - supervisor", "Paint – Supervisor", "Paint  -  SUPERVISOR "])
def test_supervisor_tag_variants_are_recognised(tmp_path, position):
    export = _export(tmp_path, [worked("A", "A-1", position), worked("B", "B-1", "Paint")])
    assert {e.department for e in export.employees} == {"Paint"}
    assert next(e for e in export.employees if e.code == "A-1").is_supervisor


def test_a_position_merely_containing_the_word_is_not_a_supervisor(tmp_path):
    export = _export(tmp_path, [worked("A", "A-1", "Supervisor"), worked("B", "B-1", "Supervisor Training")])
    assert not any(e.is_supervisor for e in export.employees)


def test_each_supervisor_gets_only_their_department(tmp_path):
    groups = review_groups(_export(tmp_path, crew()))
    assert [(g.title, [e.code for e in g.employees]) for g in groups] == [
        ("Bea Boss", ["AP-1", "BB-1", "CP-1"]),  # includes the supervisor's own hours
        ("Missing supervisor", ["DS-1"]),  # a department with nobody tagged
    ]


def test_everyone_without_a_supervisor_shares_one_group(tmp_path):
    people = [worked("Bea", "B-1", "Paint - Supervisor"), worked("Dee", "D-1", "Packing"), worked("Gus", "G-1", "Shipping")]
    groups = review_groups(_export(tmp_path, people))
    assert [(g.title, [e.code for e in g.employees]) for g in groups] == [
        ("Bea Boss", ["B-1"]),
        ("Missing supervisor", ["D-1", "G-1"]),
    ]


def test_position_tag_alone_no_longer_makes_a_supervisor(tmp_path):
    supervisor_list.save({})
    groups = review_groups(_export(tmp_path, crew()))
    assert [g.title for g in groups] == ["Missing supervisor"]


def test_supervisor_does_not_need_to_be_in_jibble(tmp_path):
    source = tmp_path / "export.xlsx"
    build_workbook([worked("Dee", "D-1", "Packing")]).save(source)
    result = process_export(source, supervisors={"Packing": "Dana Smith"})
    assert [p.name for p in result.pdfs] == ["Dana Smith - Packing - 2026-03-02 - Printable.pdf"]
    assert (result.folder / REVIEW_FOLDER / "Dana Smith - Packing - 2026-03-02.xlsx").exists()
    text = pdf_text(result, "Dana")
    assert "Dee (D-1)" in text and "Dana Smith (" not in text  # named on the report, with no timesheet of their own
    assert "MISSING SUPERVISOR" not in text


def test_one_person_covering_two_departments_gets_one_set_of_files(tmp_path):
    source = tmp_path / "export.xlsx"
    build_workbook([worked("Dee", "D-1", "Packing"), worked("Gus", "G-1", "Shipping")]).save(source)
    # Spelling of the department and the person's capitals don't split them.
    result = process_export(source, supervisors={"packing": "Dana Smith", "SHIPPING": "dana smith "})
    assert [p.name for p in result.pdfs] == ["Dana Smith - Packing, Shipping - 2026-03-02 - Printable.pdf"]
    assert [[e.code for e in g.employees] for g in result.groups] == [["D-1", "G-1"]]
    first = " ".join(PdfReader(result.pdfs[0]).pages[0].extract_text().split())
    assert "Packing 1 1" in first and "Shipping 1 1" in first and "Total 2 2" in first


def test_changing_the_list_later_does_not_change_a_week_in_progress(processed):
    supervisor_list.save({"Paint": "Someone Else", "Packing": "Dana Smith"})
    result = build_approved(processed.folder)
    assert result.approvals.missing_files == []
    assert result.approvals.employees["AP-1"].reviewed_in == "Bea Boss"
    assert "MISSING SUPERVISOR" in " ".join(page.extract_text() for page in PdfReader(result.pdf).pages)


def test_week_made_before_the_list_existed_can_still_be_finished(processed):
    next(processed.folder.glob("Supervisor list*")).unlink()
    assert not build_approved(processed.folder).approvals.is_final
    Sheet(review_file(processed, "Bea Boss")) \
        .set("AP-1", WEEK_TOTAL, REVIEWED, "Yes").set("BB-1", WEEK_TOTAL, REVIEWED, "Yes").set("CP-1", WEEK_TOTAL, REVIEWED, "Yes").save()
    Sheet(review_file(processed, "Missing supervisor")).set("DS-1", WEEK_TOTAL, REVIEWED, "Yes").save()
    assert build_approved(processed.folder).approvals.is_final


def test_a_damaged_list_stops_with_a_plain_message(tmp_path):
    supervisor_list.list_path().write_text("not json")
    source = tmp_path / "export.xlsx"
    build_workbook(crew()).save(source)
    with pytest.raises(UnsupportedExport, match="supervisor list could not be read"):
        process_export(source)


def test_saved_list_survives_a_round_trip():
    supervisor_list.save({"Łódź": "Żak", "Packing": ""})
    assert supervisor_list.load() == {"Łódź": "Żak", "Packing": ""}


def test_supervisor_can_approve_their_own_hours(processed):
    Sheet(review_file(processed, "Bea Boss")).set("BB-1", MONDAY, ADJUSTMENT, 10).set("BB-1", WEEK_TOTAL, REVIEWED, "Yes").save()
    boss = build_approved(processed.folder).approvals.employees["BB-1"]
    assert boss.reviewed and boss.approved == 490 and boss.reviewed_in == "Bea Boss"


def test_supervisor_alone_in_a_department_still_gets_a_file(tmp_path):
    groups = review_groups(_export(tmp_path, [worked("Bea", "B-1", "Paint - Supervisor")]))
    assert [(g.title, [e.code for e in g.employees]) for g in groups] == [("Bea Boss", ["B-1"])]


def test_departments_without_a_supervisor_are_listed(tmp_path):
    assert departments_without_supervisor(_export(tmp_path, crew())) == ["Packing"]


def pdf_text(result, part):
    path = next(p for p in result.pdfs if part in p.name)
    return " ".join("\n".join(page.extract_text() for page in PdfReader(path).pages).split())


def test_headcount_counts_supervisor_in_their_department(processed):
    first = " ".join(PdfReader(processed.pdfs[0]).pages[0].extract_text().split())
    assert "Bea Boss" in first and "Paint 3 3" in first and "Total 3 3" in first
    assert "Packing" not in first and "Supervisor" not in first


def test_each_supervisor_gets_a_pdf_of_only_their_department(processed):
    assert [p.name for p in processed.pdfs] == [
        "Bea Boss - Paint - 2026-03-02 - Printable.pdf",
        "Missing supervisor - 2026-03-02 - Printable.pdf",
    ]
    paint, missing = pdf_text(processed, "Bea Boss"), pdf_text(processed, "Missing")
    assert "Bea Boss (BB-1)" in paint and "Ann Painter (AP-1)" in paint and "Cal Painter (CP-1)" in paint
    assert "Dee Solo" not in paint
    assert "Dee Solo (DS-1)" in missing and "Bea Boss" not in missing


def test_only_employees_without_a_supervisor_are_tagged_in_the_pdfs(processed):
    assert "MISSING SUPERVISOR" not in pdf_text(processed, "Bea Boss")
    missing = pdf_text(processed, "Missing")
    assert "Packing 1 1" in missing and "MISSING SUPERVISOR" in missing and "accounting reviews them" in missing


def test_employee_without_a_position_is_in_no_pdf(processed):
    assert not any("Eli Blank" in pdf_text(processed, part) for part in ("Bea Boss", "Missing"))


def test_missing_supervisor_tag_carries_into_the_approved_report(processed):
    result = build_approved(processed.folder)
    text = " ".join("\n".join(page.extract_text() for page in PdfReader(result.pdf).pages).split())
    before, _ = text.split("MISSING SUPERVISOR")  # only one employee is tagged
    assert before.endswith("Dee Solo (DS-1) Packing ")


def test_excel_lists_the_group_as_missing_a_supervisor(processed):
    workbook = openpyxl.load_workbook(review_file(processed, "Missing supervisor"))
    assert workbook["Review"]["A1"].value.endswith("timesheet review: Missing supervisor")


def test_a_long_list_of_departments_is_shortened_in_file_names(tmp_path):
    people = [worked(f"Worker {i}", f"W-{i}", f"Department number {i}") for i in range(6)]
    supervisor_list.save({f"Department number {i}": "Dana Smith" for i in range(6)})
    export = _export(tmp_path, people)
    assert review_file_name(review_groups(export)[0], export) == "Dana Smith - Department number 0 and 5 more - 2026-03-02.xlsx"


def test_file_names_are_safe_for_windows():
    assert safe_file_name('A/B: "C"  D?') == "A B C D"


def _export(tmp_path, people):
    path = tmp_path / "e.xlsx"
    build_workbook(people).save(path)
    return with_supervisors(load_export(path), supervisor_list.load())


# --- Output folder --------------------------------------------------------------


def test_output_folder_holds_everything_for_the_week(processed):
    folder = processed.folder
    assert folder.name == "Jibble timesheets 2026-03-02 to 2026-03-08"
    names = {p.name for p in folder.iterdir()}
    assert {"Validation 2026-03-02.txt", "Source export 2026-03-02.xlsx", "Supervisor list 2026-03-02.json", REVIEW_FOLDER} == names
    files = {p.name for p in (folder / REVIEW_FOLDER).iterdir()}
    assert files == {
        "Bea Boss - Paint - 2026-03-02 - Printable.pdf",
        "Bea Boss - Paint - 2026-03-02.xlsx",
        "Missing supervisor - 2026-03-02 - Printable.pdf",
        "Missing supervisor - 2026-03-02.xlsx",
    }


def test_rerunning_never_overwrites_a_folder_with_returned_files(processed, tmp_path):
    edited = review_file(processed, "Bea Boss")
    Sheet(edited).set("AP-1", MONDAY, ADJUSTMENT, 15).save()
    before = edited.read_bytes()
    again = process_export(tmp_path / "export.xlsx")
    assert again.folder.name.endswith("(2)")
    assert edited.read_bytes() == before


def test_overlong_location_stops_with_a_plain_message(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "EXCEL_PATH_LIMIT", 218)
    source = tmp_path / "export.xlsx"
    build_workbook(crew()).save(source)
    with pytest.raises(UnsupportedExport, match="too long"):
        process_export(source, tmp_path / ("x" * 180))
    assert [p.name for p in tmp_path.iterdir()] == ["export.xlsx"]


def test_validation_keeps_the_original_export_name(processed):
    assert "Source: export.xlsx" in processed.validation.read_text(encoding="utf-8")


def test_failed_run_leaves_no_folder(tmp_path):
    source = tmp_path / "bad.xlsx"
    source.write_text("nope")
    with pytest.raises(UnsupportedExport):
        process_export(source)
    assert [p.name for p in tmp_path.iterdir()] == ["bad.xlsx"]


def test_source_copy_is_identical(processed, tmp_path):
    assert (processed.folder / "Source export 2026-03-02.xlsx").read_bytes() == (tmp_path / "export.xlsx").read_bytes()


# --- Review workbook ------------------------------------------------------------


def test_supervisor_file_contains_only_their_staff(processed):
    workbook = openpyxl.load_workbook(review_file(processed, "Bea Boss"))
    text = " ".join(str(c) for sheet in workbook.worksheets for row in sheet.iter_rows(values_only=True) for c in row if c)
    assert "Ann Painter" in text and "Cal Painter" in text and "BB-1" in text
    assert "Dee Solo" not in text and "Eli Blank" not in text


def test_only_input_cells_are_unlocked(processed):
    sheet = Sheet(review_file(processed, "Bea Boss"))
    assert sheet.sheet.protection.sheet
    day = sheet.row_for("AP-1", MONDAY)
    total = sheet.row_for("AP-1", WEEK_TOTAL)
    unlocked = lambda row, label: not sheet.sheet.cell(row, sheet.columns[label]).protection.locked
    assert unlocked(day, ADJUSTMENT) and unlocked(day, COMMENT)
    assert not unlocked(day, APPROVED) and not unlocked(day, "Net") and not unlocked(day, REVIEWED)
    assert unlocked(total, REVIEWED) and not unlocked(total, APPROVED)


def test_incomplete_day_unlocks_approved_instead_of_adjustment(tmp_path):
    people = [worked("Bea", "B-1", "Paint - Supervisor"), Person("Ann", "A-1", "Paint", [(0, "In", "08:00:00", "")])]
    source = tmp_path / "export.xlsx"
    build_workbook(people).save(source)
    sheet = Sheet(review_file(process_export(source), "Bea"))
    row = sheet.row_for("A-1", MONDAY)
    assert not sheet.sheet.cell(row, sheet.columns[APPROVED]).protection.locked
    assert sheet.sheet.cell(row, sheet.columns[ADJUSTMENT]).protection.locked


def test_daily_totals_are_not_repeated_for_multiple_punch_pairs(tmp_path):
    people = [
        worked("Bea", "B-1", "Paint - Supervisor"),
        Person("Ann", "A-1", "Paint", [
            (0, "In", "08:00:00", ""), (0, "Out", "12:00:00", ""), (0, "In", "13:00:00", ""), (0, "Out", "16:00:00", ""),
        ]),
    ]
    source = tmp_path / "export.xlsx"
    build_workbook(people).save(source)
    sheet = Sheet(review_file(process_export(source), "Bea"))
    rows = [r for r in range(sheet.first, sheet.sheet.max_row + 1) if sheet.sheet.cell(r, sheet.columns[CODE]).value == "A-1"]
    assert len(rows) == 6  # five weekdays plus the week total, not one row per punch pair
    assert "08:00:00-12:00:00, 13:00:00-16:00:00" in sheet.sheet.cell(rows[0], sheet.columns["Punch pairs"]).value


def test_formulas_store_their_results_for_previews(processed):
    values = openpyxl.load_workbook(review_file(processed, "Bea Boss"), data_only=True)["Review"]
    formulas = Sheet(review_file(processed, "Bea Boss"))
    row = formulas.row_for("AP-1", MONDAY)
    assert str(formulas.sheet.cell(row, formulas.columns[APPROVED]).value).startswith("=")
    assert round(_as_minutes(values.cell(row, formulas.columns[APPROVED]).value)) == 480


def _as_minutes(value):
    return value.total_seconds() / 60 if hasattr(value, "total_seconds") else value * 1440


# --- Approved hours -------------------------------------------------------------


def hours_of(*times):
    kinds = ["In" if i % 2 == 0 else "Out" for i in range(len(times))]
    return calculate_day([Punch(k, datetime(2026, 3, 2, *t)) for k, t in zip(kinds, times)])


FULL_DAY = ((8, 0, 0), (16, 30, 0))  # net 8:00


@pytest.mark.parametrize(
    "adjustment, approved",
    [(None, 480), (0, 480), (15, 495), (-15, 465), (-480, 0)],
)
def test_adjustments_apply_to_net(adjustment, approved):
    assert approve_day(hours_of(*FULL_DAY), DayInput(adjustment=adjustment)).approved == approved


def test_adjustment_below_zero_is_a_problem_not_a_number():
    result = approve_day(hours_of(*FULL_DAY), DayInput(adjustment=-500))
    assert result.approved is None and result.unresolved and result.problems


def test_no_punches_with_no_entry_has_nothing_to_approve():
    result = approve_day(calculate_day([]), DayInput())
    assert result.approved is None and not result.unresolved


def test_no_punches_can_be_given_hours_by_adjustment():
    assert approve_day(calculate_day([]), DayInput(adjustment=480)).approved == 480


def test_incomplete_punches_need_typed_hours():
    incomplete = hours_of((8, 0, 0))
    assert approve_day(incomplete, DayInput()).unresolved
    result = approve_day(incomplete, DayInput(typed_hours=450))
    assert result.approved == 450 and not result.unresolved


# --- Round trip -----------------------------------------------------------------


def test_untouched_files_give_a_provisional_report(processed):
    result = build_approved(processed.folder)
    assert not result.approvals.is_final
    assert result.pdf.name == "Provisional timesheets 2026-03-02.pdf"
    assert "PROVISIONAL" in PdfReader(result.pdf).pages[0].extract_text()
    assert result.approvals.employees["AP-1"].approved == 960  # calculated hours still shown


def test_full_round_trip(processed):
    Sheet(review_file(processed, "Bea Boss")) \
        .set("AP-1", MONDAY, ADJUSTMENT, 15).set("AP-1", MONDAY, COMMENT, "Stayed to finish a batch") \
        .set("AP-1", TUESDAY, ADJUSTMENT, 0).set("AP-1", WEEK_TOTAL, REVIEWED, "Yes") \
        .set("BB-1", WEEK_TOTAL, REVIEWED, "Yes") \
        .set("CP-1", WEEK_TOTAL, REVIEWED, "Yes").set("CP-1", WEEK_TOTAL, COMMENT, "All good").save()
    build_approved(processed.folder)  # a provisional copy, replaced below
    Sheet(review_file(processed, "Missing supervisor")).set("DS-1", WEEK_TOTAL, REVIEWED, "yes").save()

    result = build_approved(processed.folder)
    approvals = result.approvals
    assert approvals.is_final
    assert result.pdf.name == "Approved timesheets 2026-03-02.pdf"
    assert not list(processed.folder.glob("Provisional*"))

    ann = approvals.employees["AP-1"]
    assert ann.approved == 975 and ann.adjustment_total == 15
    assert ann.days[TUESDAY].input.adjustment == 0  # an explicit zero survives
    assert approvals.employees["CP-1"].days[MONDAY].input.adjustment is None  # blank stays blank

    text = " ".join("\n".join(p.extract_text() for p in PdfReader(result.pdf).pages).split())
    assert "+15 min" in text and "0 min" in text
    assert 'supervisor comment: "Stayed to finish a batch"' in text
    assert 'Week comment: "All good"' in text
    assert "Reviewed in: Bea Boss" in text
    assert "PROVISIONAL" not in text

    summary = openpyxl.load_workbook(result.summary, data_only=True)
    assert summary.sheetnames == ["Summary", "Employees", "Adjustments"]
    adjustments = [r for r in summary["Adjustments"].iter_rows(min_row=2, values_only=True) if r[0]]
    assert any(r[1] == "AP-1" and r[4] == 15 and r[7] == "Stayed to finish a batch" for r in adjustments)
    assert any(r[1] == "AP-1" and r[4] == 0 for r in adjustments)


def test_typed_hours_on_incomplete_day_flow_through(tmp_path):
    people = [worked("Bea", "B-1", "Paint - Supervisor"), Person("Ann", "A-1", "Paint", [(0, "In", "08:00:00", "")])]
    source = tmp_path / "export.xlsx"
    build_workbook(people).save(source)
    processed = process_export(source)
    path = review_file(processed, "Bea")

    assert build_approved(processed.folder).approvals.employees["A-1"].approved is None

    Sheet(path).set("A-1", MONDAY, APPROVED, time(7, 30)).set("A-1", WEEK_TOTAL, REVIEWED, "Yes").save()
    result = build_approved(processed.folder)
    assert result.approvals.employees["A-1"].approved == 450
    assert result.approvals.employees["A-1"].is_final


def test_bad_adjustment_is_reported_not_treated_as_zero(processed):
    Sheet(review_file(processed, "Bea Boss")).set("AP-1", MONDAY, ADJUSTMENT, "ten").set("AP-1", WEEK_TOTAL, REVIEWED, "Yes").save()
    result = build_approved(processed.folder)
    ann = result.approvals.employees["AP-1"]
    assert not ann.days[MONDAY].input.adjustment and ann.days[MONDAY].problems
    assert not result.approvals.is_final


def test_changed_calculated_value_is_ignored_and_flagged(processed):
    Sheet(review_file(processed, "Bea Boss")).set("AP-1", MONDAY, "Net", 1.0).save()
    ann = build_approved(processed.folder).approvals.employees["AP-1"]
    assert ann.days[MONDAY].approved == 480
    assert any("differs from the export" in p for p in ann.days[MONDAY].problems)


def test_file_from_another_week_is_refused(processed, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    source = other / "other.xlsx"
    build_workbook(crew()[:3]).save(source)
    stray = review_file(process_export(source), "Bea Boss")
    (processed.folder / REVIEW_FOLDER / "stray.xlsx").write_bytes(stray.read_bytes())
    with pytest.raises(UnsupportedExport, match="different Jibble file"):
        build_approved(processed.folder)


def test_two_copies_of_one_review_file_are_refused(processed):
    original = review_file(processed, "Bea Boss")
    (original.parent / "Copy of returned.xlsx").write_bytes(original.read_bytes())
    with pytest.raises(UnsupportedExport, match="Two files are for"):
        build_approved(processed.folder)


def test_an_unrelated_workbook_is_refused(processed):
    openpyxl.Workbook().save(processed.folder / REVIEW_FOLDER / "notes.xlsx")
    with pytest.raises(UnsupportedExport, match="isn't a Punch Clock review file"):
        build_approved(processed.folder)


def test_missing_review_file_keeps_the_report_provisional(processed):
    review_file(processed, "Missing supervisor").unlink()
    result = build_approved(processed.folder)
    assert result.approvals.missing_files == ["Missing supervisor"]
    assert not result.approvals.is_final
    assert "Missing supervisor" in " ".join(PdfReader(result.pdf).pages[0].extract_text().split())


def test_excel_lock_files_are_ignored(processed):
    (processed.folder / REVIEW_FOLDER / "~$Review.xlsx").write_bytes(b"lock")
    assert build_approved(processed.folder)


def test_choosing_the_wrong_folder_explains_itself(tmp_path):
    with pytest.raises(UnsupportedExport, match="isn't a week's folder"):
        build_approved(tmp_path)


def test_two_files_covering_one_employee_must_agree(tmp_path):
    """Older weeks could send one department to two supervisors."""
    source = tmp_path / "export.xlsx"
    build_workbook([worked("Ann", "A-1", "Paint")]).save(source)
    processed = process_export(source)
    first = review_file(processed, "Bea Boss")
    second = first.with_name("Review - Zed - 2026-03-02.xlsx")
    Sheet(first).set("A-1", MONDAY, ADJUSTMENT, 30).save()
    copy = openpyxl.load_workbook(first)
    info = next(row for row in copy[INFO_SHEET].iter_rows() if row[0].value == "group_key")
    info[1].value = "another"
    copy.save(second)
    Sheet(first).set("A-1", MONDAY, ADJUSTMENT, 15).save()
    ann = build_approved(processed.folder).approvals.employees["A-1"]
    assert any("different values" in p for p in ann.days[MONDAY].problems)


def test_review_file_name_uses_group_and_week(tmp_path):
    export = _export(tmp_path, crew())
    assert review_file_name(review_groups(export)[0], export) == "Bea Boss - Paint - 2026-03-02.xlsx"
