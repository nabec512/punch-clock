from tkinter import filedialog, messagebox

import pytest
from sample_export import build_workbook

from punch_clock import __version__, app


@pytest.fixture
def dialogs(monkeypatch):
    """Replace the message boxes, recording what the user would have seen."""
    seen = {"error": []}
    monkeypatch.setattr(messagebox, "showerror", lambda title, text, parent: seen["error"].append((title, text)))
    return seen


def choose_file(monkeypatch, source):
    monkeypatch.setattr(filedialog, "askopenfilename", lambda **_: str(source))


def choose_folder(monkeypatch, folder):
    monkeypatch.setattr(filedialog, "askdirectory", lambda **_: str(folder))


def test_cancelling_the_file_picker_does_nothing(monkeypatch, dialogs, tmp_path):
    choose_file(monkeypatch, "")
    assert app.choose_and_process(None) is None
    assert dialogs == {"error": []}
    assert list(tmp_path.iterdir()) == []


def test_cancelling_the_folder_picker_does_nothing(monkeypatch, dialogs):
    choose_folder(monkeypatch, "")
    assert app.choose_and_approve(None) is None
    assert dialogs == {"error": []}


def test_process_then_approve_through_the_dialogs(monkeypatch, dialogs, tmp_path):
    source = tmp_path / "export.xlsx"
    build_workbook().save(source)
    choose_file(monkeypatch, source)
    processed = app.choose_and_process(None)
    assert processed.pdf.exists()
    summary = app.process_summary(processed)
    assert "3 employees" in summary and "Riley Chen" in summary and "Assembly - Avery Lee" in summary

    choose_folder(monkeypatch, processed.folder)
    approved = app.choose_and_approve(None)
    assert approved.pdf.exists() and approved.summary.exists()
    assert "PROVISIONAL" in app.approved_summary(approved)
    assert dialogs == {"error": []}


def test_mismatches_are_called_out_in_the_summary(monkeypatch, dialogs, tmp_path):
    source = tmp_path / "export.xlsx"
    workbook = build_workbook()
    sheet = workbook["Team Summary"]
    row = next(c.row for c in sheet["C"] if c.value == "Payroll")
    sheet[f"K{row}"] = "1h 00m"
    workbook.save(source)
    choose_file(monkeypatch, source)
    assert "1 comparison(s) with Jibble's totals need review." in app.process_summary(app.choose_and_process(None))


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


def test_command_line_process_and_approve(tmp_path, capsys):
    source = tmp_path / "export.xlsx"
    build_workbook().save(source)
    assert app.main([str(source), "--output-dir", str(tmp_path / "out")]) == 0
    assert '"employees": 3' in capsys.readouterr().out
    folder = next((tmp_path / "out").iterdir())
    assert app.main(["--approve", str(folder)]) == 0
    assert '"final": false' in capsys.readouterr().out


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
