"""Entry point: a small window with no arguments, command line with arguments."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Callable, Optional, Sequence

from punch_clock import __version__, supervisor_list
from punch_clock.assignments import department_names
from punch_clock.jibble_export import UnsupportedExport, WeeklyExport, load_export
from punch_clock.reports import ProcessResult, process_export

APP_NAME = "Punch Clock"


def _employees(count: int) -> str:
    return f"{count} employee" if count == 1 else f"{count} employees"


def process_summary(result: ProcessResult) -> str:
    export = result.export
    lines = [
        f"Done. The reports for {_employees(len(export.included))} are in this folder:",
        result.folder.name,
    ]
    if result.groups:
        lines += ["", "Next, open the Supervisor files folder. Send each supervisor their PDF to print and their Excel file to fill in and send back:"]
    lines += [f"  {group.title}: {_employees(len(group.employees))}" for group in result.groups]
    if any(group.supervisor is None for group in result.groups):
        lines += ["", "The Missing supervisor group has no one on the Supervisors list, so accounting reviews those two files. To change this, add them to the list, then make the reports again."]
    if export.excluded:
        lines += ["", f"Not included because they have no position in Jibble: {', '.join(e.name for e in export.excluded)}"]
    if export.review_count == 1:
        lines += ["", "1 total doesn't match Jibble. Please check the Validation file."]
    elif export.review_count:
        lines += ["", f"{export.review_count} totals don't match Jibble. Please check the Validation file."]
    return "\n".join(lines)


def _show_errors(parent, action: Callable):
    """Run an action, turning failures into messages. Returns None if it failed."""
    from tkinter import messagebox

    try:
        return action()
    except UnsupportedExport as error:
        messagebox.showerror("This can't be used", str(error), parent=parent)
    except PermissionError as error:
        messagebox.showerror(
            "File is in use",
            f"Close this file if it is open, then try again:\n\n{error.filename2 or error.filename}",
            parent=parent,
        )
    except Exception as error:  # the windowed app has no console to show a traceback
        messagebox.showerror(
            "Something went wrong",
            f"Nothing was finished. Show this message to your IT contact:\n\n{type(error).__name__}: {error}",
            parent=parent,
        )
    return None


def choose_and_process(parent) -> Optional[ProcessResult]:
    from tkinter import filedialog

    source = filedialog.askopenfilename(
        parent=parent,
        title="Choose this week's file from Jibble",
        filetypes=[("Excel file", "*.xlsx")],
    )
    return _show_errors(parent, lambda: _process(parent, source)) if source else None


def _process(parent, source: str) -> Optional[ProcessResult]:
    """Ask about any department the list has never seen before making the reports."""
    export = load_export(source)
    known = {department.casefold() for department in supervisor_list.load()}
    if any(name.casefold() not in known for name in department_names(export)) and not edit_supervisors(parent, export):
        return None
    return process_export(source)


def edit_supervisors(parent, export: Optional[WeeklyExport] = None) -> bool:
    """Let the user choose who reviews each department. Returns True if they saved."""
    import tkinter as tk
    from tkinter import messagebox, ttk

    saved = supervisor_list.load()
    current = {department.casefold(): name for department, name in saved.items()}
    departments = {department.casefold(): department for department in saved}
    suggested: dict[str, str] = {}
    people = {name for name in saved.values() if name}
    if export:
        for name in department_names(export):
            departments.setdefault(name.casefold(), name)
        # A "- Supervisor" position only fills in the first guess.
        suggested = {e.department.casefold(): e.name for e in export.included if e.is_supervisor}
        people |= {e.name for e in export.employees}
    if not departments:
        messagebox.showinfo("Supervisors", "Departments appear here after you choose a Jibble file.", parent=parent)
        return False

    window = tk.Toplevel(parent)
    window.title("Supervisors")
    window.transient(parent)
    window.geometry(f"+{parent.winfo_rootx() + 30}+{parent.winfo_rooty() + 30}")
    frame = ttk.Frame(window, padding=16)
    frame.pack(fill="both", expand=True)
    ttk.Label(
        frame,
        text="Choose who reviews each department. You can type a name that isn't in Jibble.\n"
        "Leave it blank if there's no supervisor, and accounting will review those employees.\n"
        "Changes apply the next time you make a week's reports.",
        justify="left",
    ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

    canvas = tk.Canvas(frame, highlightthickness=0)
    rows = ttk.Frame(canvas)
    canvas.create_window((0, 0), window=rows, anchor="nw")
    canvas.grid(row=1, column=0, sticky="nsew")

    def on_wheel(event) -> str:
        canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"  # a combobox would otherwise change its name as the list scrolls past

    choices: dict[str, tk.StringVar] = {}
    ordered = sorted(departments, key=lambda key: departments[key].casefold())
    for number, key in enumerate(ordered):
        ttk.Label(rows, text=departments[key]).grid(row=number, column=0, sticky="w", padx=(0, 16), pady=3)
        choices[key] = tk.StringVar(value=current[key] if key in current else suggested.get(key, ""))
        box = ttk.Combobox(rows, textvariable=choices[key], values=sorted(people, key=str.casefold), width=32)
        box.grid(row=number, column=1, sticky="ew", pady=3)
        box.bind("<MouseWheel>", on_wheel)
    rows.update_idletasks()
    canvas.configure(width=rows.winfo_reqwidth(), height=min(rows.winfo_reqheight(), 360), scrollregion=(0, 0, rows.winfo_reqwidth(), rows.winfo_reqheight()))
    if rows.winfo_reqheight() > 360:
        bar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.grid(row=1, column=1, sticky="ns")
        window.bind("<MouseWheel>", on_wheel)

    was_saved = False

    def on_save() -> None:
        nonlocal was_saved
        supervisor_list.save({departments[key]: choices[key].get().strip() for key in ordered})
        was_saved = True
        window.destroy()

    buttons = ttk.Frame(frame)
    buttons.grid(row=2, column=0, columnspan=2, sticky="e", pady=(16, 0))
    ttk.Button(buttons, text="Save", command=lambda: _show_errors(window, on_save)).pack(side="left", padx=(0, 8))
    ttk.Button(buttons, text="Cancel", command=window.destroy).pack(side="left")
    window.bind("<Escape>", lambda _event: window.destroy())
    window.grab_set()
    window.focus_set()
    parent.wait_window(window)
    return was_saved


def run_window() -> int:
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title(APP_NAME)
    root.minsize(520, 360)
    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(2, weight=1)
    status = tk.StringVar(value="The reports are saved in a new folder next to that file.")
    last_folder: dict[str, Path] = {}
    last_export: dict[str, WeeklyExport] = {}

    def on_process() -> None:
        result = choose_and_process(root)
        if result:
            last_export["export"] = result.export
            status.set(process_summary(result))
            last_folder["path"] = result.folder
            open_button.state(["!disabled"])
            os.startfile(result.folder)

    ttk.Label(frame, text="When you have this week's file from Jibble:").grid(row=0, column=0, sticky="w")
    ttk.Button(frame, text="Make this week's reports...", command=on_process).grid(row=1, column=0, sticky="ew", pady=(4, 12))
    ttk.Label(frame, textvariable=status, wraplength=480, justify="left", anchor="nw").grid(row=2, column=0, sticky="nsew")
    bottom = ttk.Frame(frame)
    bottom.grid(row=3, column=0, sticky="ew", pady=(12, 0))
    ttk.Button(
        bottom, text="Supervisors...", command=lambda: _show_errors(root, lambda: edit_supervisors(root, last_export.get("export")))
    ).pack(side="left")
    open_button = ttk.Button(bottom, text="Open folder", command=lambda: os.startfile(last_folder["path"]))
    open_button.state(["disabled"])
    open_button.pack(side="right")
    root.mainloop()
    return 0


def _emit(stream, text: str) -> None:
    if stream is not None:  # the windowed app has no console streams
        print(text, file=stream)


def run_command_line(source: Path, output_dir: Optional[Path]) -> int:
    try:
        result = process_export(source, output_dir)
    except (UnsupportedExport, PermissionError, FileNotFoundError) as error:
        _emit(sys.stderr, f"Error: {error}")
        return 1
    report = {
        "folder": str(result.folder),
        "pdfs": [str(pdf) for pdf in result.pdfs],
        "employees": len(result.export.included),
        "review_files": [group.title for group in result.groups],
        "needs_review": [check.label for check in result.export.checks if not check.match],
    }
    _emit(sys.stdout, json.dumps(report, indent=2))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="punch-clock", description=__doc__)
    parser.add_argument("source", nargs="?", type=Path, help="weekly Jibble export (.xlsx) to process")
    parser.add_argument("--output-dir", type=Path, help="where to create the week's folder (default: beside the export)")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    args = parser.parse_args(argv)
    if args.source:
        return run_command_line(args.source, args.output_dir)
    return run_window()


if __name__ == "__main__":
    raise SystemExit(main())
