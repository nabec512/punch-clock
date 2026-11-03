import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import pytest
from sample_export import build_workbook

from punch_clock.jibble_export import read_workbook
from punch_clock import __version__, app, supervisor_list


@pytest.fixture
def dialogs(monkeypatch):
    """Replace the message boxes, recording what the user would have seen."""
    seen = {"error": []}
    monkeypatch.setattr(messagebox, "showerror", lambda title, text, parent: seen["error"].append((title, text)))
    monkeypatch.setattr(app, "edit_supervisors", lambda parent, export=None: True)
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
    supervisor_list.save({"Assembly": "Avery Lee", "Receiving": ""})
    processed = app.choose_and_process(None)
    assert len(processed.pdfs) == 2 and all(pdf.exists() for pdf in processed.pdfs)
    summary = app.process_summary(processed)
    assert "3 employees" in summary and "Riley Chen" in summary and "Avery Lee: 2 employees" in summary
    assert "Missing supervisor: 1 employee" in summary and "accounting reviews" in summary

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


def test_a_new_department_is_asked_about_before_making_reports(monkeypatch, dialogs, tmp_path):
    source = tmp_path / "export.xlsx"
    build_workbook().save(source)
    choose_file(monkeypatch, source)
    asked = []
    monkeypatch.setattr(app, "edit_supervisors", lambda parent, export=None: asked.append(export) or False)
    assert app.choose_and_process(None) is None  # cancelling makes no reports
    assert len(asked) == 1
    assert [p.name for p in tmp_path.iterdir()] == ["export.xlsx"]


def test_known_departments_are_not_asked_about_again(monkeypatch, dialogs, tmp_path):
    source = tmp_path / "export.xlsx"
    build_workbook().save(source)
    choose_file(monkeypatch, source)
    supervisor_list.save({"assembly": "Avery Lee", "Receiving": ""})  # a blank is still an answer
    monkeypatch.setattr(app, "edit_supervisors", lambda parent, export=None: pytest.fail("asked again"))
    assert app.choose_and_process(None)


def _in_window(root, press, fill=None):
    """Run once the dialog is open: change its boxes, then press one of its buttons."""

    def walk(widget):
        for child in widget.winfo_children():
            yield child
            yield from walk(child)

    def act():
        widgets = list(walk(root))
        boxes = [w for w in widgets if isinstance(w, ttk.Combobox)]
        if fill:
            fill(boxes)
        next(w for w in widgets if isinstance(w, ttk.Button) and w.cget("text") == press).invoke()

    root.after(100, act)


@pytest.fixture(scope="module")
def tk_root():
    """Shared, as the app has only one: creating Tk repeatedly in one process fails now and then."""
    root = tk.Tk()
    yield root
    root.destroy()


def test_saving_the_window_stores_names_and_blanks(tk_root):
    export = read_workbook(build_workbook(), "sample.xlsx")
    seen = []

    def fill(boxes):
        seen.extend(box.get() for box in boxes)
        boxes[1].set("  Dana Smith ")

    _in_window(tk_root, "Save", fill)
    assert app.edit_supervisors(tk_root, export) is True
    assert seen == ["Avery Lee", ""]  # the "- Supervisor" position fills in the first guess
    assert supervisor_list.load() == {"Assembly": "Avery Lee", "Receiving": "Dana Smith"}


def test_saved_blank_is_not_replaced_by_the_position_guess(tk_root):
    supervisor_list.save({"Assembly": ""})
    export = read_workbook(build_workbook(), "sample.xlsx")
    seen = []
    _in_window(tk_root, "Cancel", lambda boxes: seen.extend(box.get() for box in boxes))
    assert app.edit_supervisors(tk_root, export) is False
    assert seen == ["", ""]
    assert supervisor_list.load() == {"Assembly": ""}  # cancelling changes nothing


def test_opening_the_list_before_any_export_explains_itself(tk_root, monkeypatch):
    shown = []
    monkeypatch.setattr(messagebox, "showinfo", lambda title, text, parent: shown.append(text))
    assert app.edit_supervisors(tk_root) is False
    assert "after you choose a Jibble file" in shown[0]


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
