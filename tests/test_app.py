from tkinter import filedialog, messagebox

import pytest
from sample_export import Person, build_workbook, write_settings

from punch_clock.reports import process_export
from punch_clock import __version__, app, settings


@pytest.fixture
def dialogs(monkeypatch):
    """Replace the message boxes, recording what the user would have seen."""
    seen = {"error": []}
    monkeypatch.setattr(messagebox, "showerror", lambda title, text, parent: seen["error"].append((title, text)))
    return seen


def choose_file(monkeypatch, source):
    monkeypatch.setattr(filedialog, "askopenfilename", lambda **_: str(source))


def test_cancelling_the_file_picker_does_nothing(monkeypatch, dialogs, tmp_path):
    choose_file(monkeypatch, "")
    assert app.choose_and_process(None) is None
    assert dialogs == {"error": []}
    assert list(tmp_path.iterdir()) == []


def test_process_through_the_dialogs(monkeypatch, dialogs, tmp_path):
    source = tmp_path / "export.xlsx"
    build_workbook().save(source)
    choose_file(monkeypatch, source)
    write_settings(settings.file_path(), {"Assembly": "Avery Lee", "Receiving": ""})
    processed = app.choose_and_process(None)
    assert len(processed.pdfs) == 2 and all(pdf.exists() for pdf in processed.pdfs)
    summary = app.process_summary(processed)
    assert "3 employees" in summary and "Riley Chen" in summary and "Avery Lee: 2 employees" in summary
    assert "Missing supervisor: 1 employee" in summary and "no supervisor for: Receiving" in summary
    assert "Accounting reviews" in summary

    assert dialogs == {"error": []}


def test_mismatches_are_called_out_in_the_summary(monkeypatch, dialogs, tmp_path):
    source = tmp_path / "export.xlsx"
    workbook = build_workbook()
    sheet = workbook["Team Summary"]
    row = next(c.row for c in sheet["C"] if c.value == "Payroll")
    sheet[f"K{row}"] = "1h 00m"
    workbook.save(source)
    choose_file(monkeypatch, source)
    assert "1 total doesn't match Jibble." in app.process_summary(app.choose_and_process(None))


def _summary(tmp_path, punches):
    source = tmp_path / "export.xlsx"
    build_workbook([Person("Ann", "A-1", "Paint", punches)]).save(source)
    return app.process_summary(process_export(source))


FULL_DAY = [(0, "In", "08:00:00", ""), (0, "Out", "16:30:00", "")]


def test_summary_names_who_is_missing_a_punch_and_who_may_be_swapped(tmp_path):
    summary = _summary(tmp_path, [*FULL_DAY, (1, "In", "08:00:00", ""), (2, "Out", "07:30:00", "")])
    assert "Ann: Tue, Wed" in summary
    assert "may be swapped for: Ann" in summary


@pytest.mark.parametrize(
    "punches",
    [
        pytest.param(FULL_DAY, id="normal"),
        pytest.param(
            [*FULL_DAY, (1, "Out", "08:00:10", ""), (1, "In", "08:00:20", ""), (1, "Out", "16:30:00", "")],
            id="already fixed by punching twice",
        ),
    ],
)
def test_summary_says_nothing_when_back_in_sync(tmp_path, punches):
    assert "swapped" not in _summary(tmp_path, punches)


def _mismatched_summary(tmp_path, punches):
    source = tmp_path / "export.xlsx"
    workbook = build_workbook([Person("Ann", "A-1", "Paint", punches)])
    sheet = workbook["Team Summary"]
    row = next(c.row for c in sheet["C"] if c.value == "Payroll")
    sheet[f"K{row}"] = "1h 00m"
    workbook.save(source)
    return app.process_summary(process_export(source))


def test_summary_explains_mismatches_only_when_a_punch_was_forgotten(tmp_path):
    assert "forgotten punch can cause this" in _mismatched_summary(tmp_path, [(0, "In", "08:00:00", "")])
    (tmp_path / "plain").mkdir()
    assert "forgotten punch" not in _mismatched_summary(tmp_path / "plain", FULL_DAY)


def _choose_settings(monkeypatch, chosen):
    monkeypatch.setattr(filedialog, "askopenfilename", lambda **_: str(chosen))
    return app.choose_settings_file(None)


def test_cancelling_the_settings_file_picker_changes_nothing(monkeypatch, dialogs):
    before = settings.file_path()
    assert _choose_settings(monkeypatch, "") is None
    assert settings.file_path() == before and dialogs == {"error": []}


def test_choosing_a_settings_file_is_used_for_the_next_reports(monkeypatch, dialogs, tmp_path):
    chosen = tmp_path / "shared" / "my settings.json"
    chosen.parent.mkdir()
    write_settings(chosen, {"Assembly": "Morgan Blake"})
    assert _choose_settings(monkeypatch, chosen.as_posix()) == chosen
    source = tmp_path / "export.xlsx"
    build_workbook().save(source)
    assert "Morgan Blake: 2 employees" in app.process_summary(process_export(source))
    assert dialogs == {"error": []}


def test_choosing_a_bad_settings_file_explains_and_changes_nothing(monkeypatch, dialogs, tmp_path):
    before = settings.file_path()
    chosen = tmp_path / "bad.json"
    chosen.write_text("not json")
    assert _choose_settings(monkeypatch, chosen) is None
    assert "has a mistake in it" in dialogs["error"][0][1]
    assert settings.file_path() == before


def test_unusable_export_shows_a_plain_message(monkeypatch, dialogs, tmp_path):
    source = tmp_path / "export.xlsx"
    source.write_text("not a workbook")
    choose_file(monkeypatch, source)
    assert app.choose_and_process(None) is None
    assert "could not be opened" in dialogs["error"][0][1]


def test_open_file_names_the_file_to_close(monkeypatch, dialogs, tmp_path):
    source, output = tmp_path / "export.xlsx", tmp_path / "report.pdf"
    build_workbook().save(source)
    choose_file(monkeypatch, source)

    def locked(*_, **__):
        raise PermissionError(5, "Access is denied", str(output.with_suffix(".pending.pdf")), None, str(output))

    monkeypatch.setattr(app, "process_export", locked)
    assert app.choose_and_process(None) is None
    title, text = dialogs["error"][0]
    assert title == "File is in use"
    assert str(output) in text and "pending" not in text


def test_unexpected_error_is_shown_not_swallowed(monkeypatch, dialogs, tmp_path):
    source = tmp_path / "export.xlsx"
    build_workbook().save(source)
    choose_file(monkeypatch, source)

    def broken(*_, **__):
        raise RuntimeError("boom")

    monkeypatch.setattr(app, "process_export", broken)
    assert app.choose_and_process(None) is None
    assert "RuntimeError: boom" in dialogs["error"][0][1]


def test_command_line_process(tmp_path, capsys):
    source = tmp_path / "export.xlsx"
    build_workbook().save(source)
    assert app.main([str(source), "--output-dir", str(tmp_path / "out")]) == 0
    assert '"employees": 3' in capsys.readouterr().out


def test_command_line_reports_failure(tmp_path, capsys):
    source = tmp_path / "export.xlsx"
    source.write_text("not a workbook")
    assert app.main([str(source)]) == 1
    assert "could not be opened" in capsys.readouterr().err


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as stopped:
        app.main(["--version"])
    assert stopped.value.code == 0
    assert __version__ in capsys.readouterr().out
