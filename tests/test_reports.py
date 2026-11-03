import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest
from pypdf import PdfReader
from sample_export import Person, build_workbook, default_people

from punch_clock.assignments import review_groups, with_supervisors
from punch_clock.jibble_export import UnsupportedExport, read_workbook
from punch_clock.pdf_report import page_count, render
from punch_clock.reports import process_export

REPO_ROOT = Path(__file__).resolve().parents[1]


def pdf_pages(path):
    return [page.extract_text() for page in PdfReader(path).pages]


def report_text(report):
    return "\n".join(page for path in report.pdfs for page in pdf_pages(path))


def make_report(tmp_path, people=None, supervisors=None):
    source = tmp_path / "export.xlsx"
    build_workbook(people).save(source)
    return process_export(source, supervisors=supervisors)


def full_week(code, name, position):
    punches = []
    for day in range(5):
        punches += [(day, "In", "08:00:00", ""), (day, "Out", "16:30:00", "")]
    return Person(name, code, position, punches)


def test_every_punch_and_total_is_printed(tmp_path):
    text = report_text(make_report(tmp_path))
    for expected in [
        "08:00:10", "11:30:20", "12:45:05", "16:30:00",  # both of Avery's sessions
        "08:05:42", "16:20:19",
        "09:00:00", "12:00:00", "12:20:00", "17:00:00",
        "Avery Lee (AL-1)", "Sam Ortiz (SO-1)",
    ]:
        assert expected in text, expected


def test_multiple_sessions_gap_and_note_are_explained(tmp_path):
    text = report_text(make_report(tmp_path))
    assert "clocked out 11:30:20-12:45:05 (1:15); already excluded from gross. 0:30 lunch also deducted." in text
    assert 'Jibble note: "dentist appointment"' in text


def test_first_page_explains_lunch_is_always_deducted(tmp_path):
    first = " ".join(pdf_pages(make_report(tmp_path).pdfs[0])[0].split())
    assert "deducted even if the employee also clocked out" in first
    assert "count toward" not in first


def test_no_punch_days_are_not_printed_as_zero(tmp_path):
    text = report_text(make_report(tmp_path))
    assert "No punches" in text
    assert "0:00 0:00 0:00" not in text


def test_names_outside_basic_latin_print_correctly(tmp_path):
    text = report_text(make_report(tmp_path))
    assert "Łucja Żak" in text
    assert "■" not in text  # the box printed by fonts missing the glyph


def test_headcount_page_counts_only_the_employees_in_that_pdf(tmp_path):
    report = make_report(tmp_path, supervisors={"Assembly": "Avery Lee"})
    assembly, missing = [" ".join(pdf_pages(path)[0].split()) for path in report.pdfs]
    assert "Assembly 2 2" in assembly and "Total 2 2" in assembly
    assert "Receiving 1 1" in missing and "Total 1 1" in missing
    assert "Riley Chen" not in assembly + missing


def test_employee_without_position_is_left_out(tmp_path):
    assert "Riley Chen" not in report_text(make_report(tmp_path))


def test_employees_stay_in_department_then_name_order_two_per_page(tmp_path):
    people = [full_week(f"E-{i}", f"Worker {i}", "Assembly") for i in range(5)]
    report = make_report(tmp_path, people)
    pages = pdf_pages(report.pdfs[0])
    assert len(pages) == 4  # headcount + 5 employees at two per page
    assert all(page.mediabox.width == 612 and page.mediabox.height == 792 for page in PdfReader(report.pdfs[0]).pages)
    first_detail = pages[1]
    assert first_detail.index("Worker 0") < first_detail.index("Worker 1")
    assert "Worker 2" not in first_detail
    assert "Worker 4" in pages[3]


def test_long_record_gets_its_own_page_and_keeps_every_punch(tmp_path):
    busy = Person("Busy Person", "B-1", "Assembly", [])
    for day in range(5):
        for session in range(2):
            busy.punches += [
                (day, "In", f"{8 + session * 2:02d}:00:0{day}", ""),
                (day, "Out", f"{9 + session * 2:02d}:00:0{day}", f"note {day}-{session}"),
            ]
    people = [full_week("A-1", "Aaron First", "Assembly"), busy, full_week("Z-1", "Zoe Last", "Assembly")]
    report = make_report(tmp_path, people)
    pages = pdf_pages(report.pdfs[0])
    assert "Aaron First" in pages[1] and "Busy Person" not in pages[1]
    assert "Busy Person" in pages[2] and "Zoe Last" not in pages[2]
    for day in range(5):
        for session in range(2):
            assert f"{8 + session * 2:02d}:00:0{day}" in pages[2]
            assert f"note {day}-{session}" in pages[2]


def test_record_too_long_for_a_page_stops_with_a_clear_message(tmp_path):
    busy = Person("Very Busy", "V-1", "Assembly", [])
    for session in range(40):
        minute = f"{session:02d}"
        busy.punches += [(0, "In", f"08:{minute}:00", ""), (0, "Out", f"08:{minute}:30", "")]
    source = tmp_path / "export.xlsx"
    build_workbook([busy]).save(source)
    with pytest.raises(UnsupportedExport, match="too much information"):
        process_export(source)
    assert [p.name for p in tmp_path.iterdir()] == ["export.xlsx"]


def test_no_eligible_employees_still_explains_itself(tmp_path):
    people = [Person("Riley Chen", "RC-1", "", [])]
    report = make_report(tmp_path, people)
    assert [p.name for p in report.pdfs] == ["Printable timesheets 2026-03-02.pdf"]
    pages = pdf_pages(report.pdfs[0])
    assert len(pages) == 1
    assert "No employees have a recorded position" in pages[0]


def test_page_count_matches_render(tmp_path):
    export = read_workbook(build_workbook(), "sample.xlsx")
    render(export, tmp_path / "r.pdf")
    assert len(PdfReader(tmp_path / "r.pdf").pages) == page_count(export)
    for group in review_groups(with_supervisors(export, {"Assembly": "Avery Lee"})):
        render(export, tmp_path / "g.pdf", group=group)
        assert len(PdfReader(tmp_path / "g.pdf").pages) == page_count(export, group=group)


def test_validation_file_records_source_and_results(tmp_path):
    report = make_report(tmp_path)
    text = report.validation.read_text(encoding="utf-8")
    source_hash = hashlib.sha256((tmp_path / "export.xlsx").read_bytes()).hexdigest()
    assert source_hash in text
    assert "Excluded (blank position): Riley Chen / RC-1" in text
    assert "REVIEW:" not in text
    assert "AL-1 2026-03-02: gross 7:15, lunch 0:30, net 6:45" in text
    assert "LZ-1 2026-03-04: gross 7:40, lunch 0:30, net 7:10" in text


def test_source_file_is_not_modified(tmp_path):
    source = tmp_path / "export.xlsx"
    build_workbook().save(source)
    before = source.read_bytes()
    process_export(source)
    assert source.read_bytes() == before


def test_repository_tracks_no_exports_or_reports():
    """Real exports hold names and hours; they must never reach the public repo."""
    if not shutil.which("git") or not (REPO_ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    result = subprocess.run(
        ["git", "ls-files", "--cached", "*.xlsx", "*.xls", "*.xlsm", "*.csv", "*.pdf", "*.validation.txt"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == ""
