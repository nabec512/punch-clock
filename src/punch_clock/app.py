"""Entry point: a small window with no arguments, command line with arguments."""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from pathlib import Path
from typing import Callable, Optional, Sequence

from punch_clock import __version__, settings, updater
from punch_clock.agency_hours import AgencyResult, make_agency_hours, period_label
from punch_clock.payroll_files import PayrollResult, hours_text, make_payroll_files
from punch_clock.returned_files import week_label
from punch_clock.assignments import departments_without_supervisor
from punch_clock.hours import DOUBLE_PUNCH_NOTE
from punch_clock.jibble_export import UnsupportedExport, WeeklyExport
from punch_clock.reports import ProcessResult, process_export

APP_NAME = "Punch Clock"
POLL_MS = 100  # how often the window looks for background work to have finished
FONT_SIZE = 10  # points; Windows' usual 9 is hard to read for many of the people using the app


def _employees(count: int) -> str:
    return f"{count} employee" if count == 1 else f"{count} employees"


def _files(count: int) -> str:
    return f"{count} supervisor file" if count == 1 else f"{count} supervisor files"


def _missing_punches(export: WeeklyExport) -> list[str]:
    """Who has a day needing typed hours, and which days."""
    lines = []
    for employee in export.included:
        days = [f"{day:%a}" for day in export.dates if employee.days[day].punches and employee.days[day].hours.gross is None]
        if days:
            lines.append(f"  {employee.name}: {', '.join(days)}")
    return lines


def _maybe_swapped(export: WeeklyExport) -> list[str]:
    """Who Jibble may have the wrong way round as the export ends: still "in", or a last day that began with Out."""
    names = []
    for employee in export.included:
        worked = [employee.days[day] for day in export.dates if employee.days[day].punches]
        if not worked:
            continue
        last = worked[-1]
        fixed = last.hours.note == DOUBLE_PUNCH_NOTE
        if last.punches[-1].kind == "In" or (last.punches[0].kind == "Out" and not fixed):
            names.append(employee.name)
    return names


def process_summary(result: ProcessResult) -> str:
    export = result.export
    lines = [
        f"Done. The reports for {_employees(len(export.included))} are in this folder:",
        result.folder.name,
    ]
    if export.settings_note:
        lines += ["", export.settings_note]
    if result.groups:
        lines += ["", "Next, open the Supervisor files folder. Send each supervisor their PDF to print and their Excel file to fill in and send back:"]
    lines += [f"  {group.title}: {_employees(len(group.employees))}" for group in result.groups]
    if any(group.supervisor is None for group in result.groups):
        departments = ", ".join(departments_without_supervisor(export))
        lines += [
            "",
            f"The {export.company} section of the settings file has no supervisor for: {departments}. "
            "Accounting reviews those two Missing supervisor files.",
        ]
    if export.excluded:
        lines += ["", f"Not included because they have no position in Jibble: {', '.join(e.name for e in export.excluded)}"]
    if export.test_accounts:
        lines += ["", f"Not included because their position in Jibble is Test: {', '.join(e.name for e in export.test_accounts)}"]
    if export.unlinked:
        names = ", ".join(f"{e.name} ({e.code})" for e in export.employees if e.code in export.unlinked)
        lines += [
            "",
            f"The {export.company} section of the settings file doesn't say who pays: {names}. "
            "Add them under employees, with their payroll and employee number, or their agency.",
        ]
    missing = _missing_punches(export)
    if missing:
        lines += ["", "Missing a punch, so the hours need to be entered for these days:", *missing]
    swapped = _maybe_swapped(export)
    if swapped:
        lines += [
            "",
            f"Punches may be swapped for: {', '.join(swapped)}. If so, they should clock out and straight back in "
            "the next time they arrive. Someone who's simply at work right now can ignore this.",
        ]
    forgotten = missing or any(employee.days[day].hours.note for employee in export.included for day in export.dates)
    reason = " A forgotten punch can cause this, because Jibble counts the time until the next punch as worked." if forgotten else ""
    if export.review_count == 1:
        lines += ["", f"1 total doesn't match Jibble. Please check the Validation file.{reason}"]
    elif export.review_count:
        lines += ["", f"{export.review_count} totals don't match Jibble. Please check the Validation file.{reason}"]
    return "\n".join(lines)


def payroll_summary(result: PayrollResult) -> str:
    which = f"{result.run} payroll files" if result.run else "payroll files"
    lines = [f"Done. The {which} for {week_label(result.start)} are in this folder:", result.folder.name, ""]
    for payroll in result.payrolls:
        lines.append(
            f"  {payroll.path.name}: {_employees(len(payroll.lines))}, {hours_text(payroll.regular)} regular hours, "
            f"{hours_text(payroll.overtime)} overtime"
        )
    lines += [
        "",
        f"Read {_files(len(result.files))}. Import each file into its payroll's run in PowerPay first, then key "
        f"holidays, sick days and vacation: an import replaces what's already keyed for the people in it. "
        f"{result.summary.name} lists everyone, to check against PowerPay.",
    ]
    for warning in result.warnings:
        lines += ["", warning]
    return "\n".join(lines)


def agency_summary(result: AgencyResult) -> str:
    lines = [f"Done. The agency hours for {period_label(result.start)} are in this folder:", result.folder.name, ""]
    for report, path in result.reports:
        lines.append(f"  {path.name}: {_employees(len(report.employees))}, to {report.agency.contact}")
    lines += [
        "",
        f"Read {_files(len(result.files))}. Lunch is ${result.reports[0][0].lunch_per_day:.2f} for each "
        "scheduled day worked. For anyone who didn't buy lunch, change their Lunch days under Detail by week before sending it.",
    ]
    for warning in result.warnings:
        lines += ["", warning]
    return "\n".join(lines)


def _show_error(parent, error: Exception) -> None:
    """Say what went wrong in a message, as the windowed app has no console to show a traceback."""
    from tkinter import messagebox

    if isinstance(error, UnsupportedExport):
        messagebox.showerror("This can't be used", str(error), parent=parent)
    elif isinstance(error, PermissionError):
        messagebox.showerror(
            "File is in use",
            f"Close this file if it is open, then try again:\n\n{error.filename2 or error.filename}",
            parent=parent,
        )
    else:
        messagebox.showerror(
            "Something went wrong",
            f"Nothing was finished. Show this message to your IT contact:\n\n{type(error).__name__}: {error}",
            parent=parent,
        )


def _show_errors(parent, action: Callable):
    """Run an action, turning failures into messages. Returns None if it failed."""
    try:
        return action()
    except Exception as error:
        _show_error(parent, error)
    return None


def choose_export(parent) -> Optional[Path]:
    from tkinter import filedialog

    source = filedialog.askopenfilename(
        parent=parent,
        title="Choose this week's file from Jibble",
        filetypes=[("Excel file", "*.xlsx")],
    )
    return Path(source) if source else None


def process_in_window(root, source: Path, working: Callable[[bool], None], finished: Callable) -> None:
    """Make the reports away from the window, so it can show that it's working instead of freezing.

    ``working`` is told when the work starts and stops. ``finished`` then gets the result, or
    None if the reports couldn't be made, after the reason has been shown.
    """

    def done(result: Optional[ProcessResult], error: Optional[Exception]) -> None:
        working(False)
        if error:
            _show_error(root, error)
        finished(result)

    working(True)
    _in_background(root, lambda: process_export(source), done)


def payroll_button_names(runs: Sequence[str]) -> list[tuple[str, Optional[str]]]:
    """Each payroll button's text and the run it makes, from the settings file's payroll_runs, or one for everyone."""
    return [(f"{run} Payroll Files...", run) for run in runs] or [("Make the payroll files...", None)]


def choose_returned_folder(parent, weeks: str) -> Optional[Path]:
    from tkinter import filedialog

    chosen = filedialog.askdirectory(
        parent=parent,
        title=f"Choose the folder with the supervisors' files for {weeks}",
        mustexist=True,
    )
    return Path(chosen) if chosen else None


def choose_settings_file(parent) -> Optional[Path]:
    """Ask where this PC's settings file is. Returns it if it's good, and otherwise nothing changes."""
    from tkinter import filedialog

    chosen = filedialog.askopenfilename(
        parent=parent,
        title="Choose the Punch Clock settings file",
        initialdir=str(settings.file_path().parent),
        filetypes=[("Settings file", "*.json")],
    )
    if not chosen:
        return None
    path = Path(chosen)
    return path if _show_errors(parent, lambda: settings.use_file(path)) else None


def _in_background(root, work: Callable, finished: Callable) -> None:
    """Run slow work without freezing the window. Tk may only be used from its own thread.

    ``finished`` gets the result and no error, or no result and the error. Every error is passed
    on, because one that went missing here would leave the window waiting for ever.
    """
    outcome: list = []

    def run() -> None:
        try:
            outcome.append((work(), None))
        except Exception as error:
            outcome.append((None, error))

    def wait() -> None:
        if outcome:
            finished(*outcome[0])
        elif root.winfo_exists():
            root.after(POLL_MS, wait)

    threading.Thread(target=run, daemon=True).start()
    wait()


def _offer_update(root, status, buttons: Sequence, is_busy: Callable[[], bool]) -> None:
    """Look for a newer version and offer it. Being offline is normal, so a failed check stays silent."""
    from tkinter import messagebox

    def checked(update: Optional[updater.Update], _error) -> None:
        if update:
            offer(update)

    def offer(update: updater.Update) -> None:
        if not root.winfo_exists():
            return
        if is_busy():  # don't close the app under someone choosing a file
            root.after(POLL_MS, offer, update)
        elif messagebox.askyesno(
            "Update available",
            f"A new version of {APP_NAME} is ready (you have {__version__}, the new one is {update.version}).\n\n"
            "Update now? It takes about a minute, and the app reopens by itself.",
            parent=root,
        ):
            start(update)

    def start(update: updater.Update) -> None:
        before = status.get()
        for button in buttons:
            button.state(["disabled"])
        status.set("Downloading the update. Punch Clock will close and reopen by itself.")

        def downloaded(installer: Optional[Path], error) -> None:
            try:
                if error:
                    raise error
                updater.install(installer)
            except Exception:
                status.set(before)
                for button in buttons:
                    button.state(["!disabled"])
                messagebox.showerror(
                    "Update didn't finish",
                    f"You can keep using this version. {APP_NAME} will try again the next time you open it.",
                    parent=root,
                )
            else:
                root.destroy()

        _in_background(root, lambda: updater.download(update), downloaded)

    _in_background(root, updater.find_update, checked)


def _style_window(root) -> None:
    """Larger text and roomier buttons throughout the window, and Enter presses the button with focus."""
    from tkinter import font, ttk

    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont", "TkTooltipFont"):
        font.nametofont(name).configure(size=FONT_SIZE)
    heading = font.nametofont("TkDefaultFont").copy()
    heading.configure(weight="bold")
    root.heading_font = heading  # Tk forgets a font once Python lets go of it
    style = ttk.Style(root)
    style.configure("TButton", padding=(12, 8))
    style.configure("Heading.TLabel", font=heading)
    style.configure("Note.TLabel", foreground="#444444")
    root.bind_class("TButton", "<Return>", lambda event: event.widget.invoke())


def run_window() -> int:
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title(f"{APP_NAME} {__version__}")
    _style_window(root)
    root.minsize(640, 620)
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(7, weight=1)
    status = tk.StringVar(value="The reports are saved in a new folder next to that file.")
    settings_location = tk.StringVar(value=f"Settings file: {settings.file_path()}")
    last_folder: dict[str, Path] = {}
    busy = False
    making_reports = False

    def while_busy(action: Callable) -> Callable:
        def run() -> None:
            nonlocal busy
            busy = True
            try:
                action()
            finally:
                busy = False

        return run

    def show_working(working: bool) -> None:
        nonlocal making_reports
        making_reports = working
        for button in controls:
            button.state(["disabled" if working else "!disabled"])
        if working:
            progress.grid()
            progress.start(12)
        else:
            progress.stop()
            progress.grid_remove()

    def on_process() -> None:
        nonlocal busy
        busy = True  # until the reports are made, so an update isn't offered part-way through
        source = choose_export(root)
        if not source:
            busy = False
            return
        before = status.get()
        status.set(f"Making the reports from {source.name}. This usually takes a few seconds...")

        def finished(result: Optional[ProcessResult]) -> None:
            nonlocal busy
            busy = False
            if not result:
                status.set(before)
                return
            status.set(process_summary(result))
            last_folder["path"] = result.folder
            open_button.state(["!disabled"])
            os.startfile(result.folder)

        process_in_window(root, source, show_working, finished)

    def from_returned_files(weeks: str, making: str, make: Callable, summary: Callable) -> Callable[[], None]:
        """A button that reads the supervisors' returned files in a folder, and makes what's sent on from them."""

        def run() -> None:
            nonlocal busy
            busy = True
            try:
                folder = choose_returned_folder(root, weeks)
            except BaseException:
                busy = False  # or an update would never be offered
                raise
            if not folder:
                busy = False
                return
            before = status.get()
            status.set(f"Reading the supervisors' files and making the {making}...")

            def done(result, error: Optional[Exception]) -> None:
                nonlocal busy
                busy = False
                show_working(False)
                if error:
                    _show_error(root, error)
                    status.set(before)
                    return
                status.set(summary(result))
                last_folder["path"] = result.folder
                open_button.state(["!disabled"])
                os.startfile(result.folder)

            show_working(True)
            _in_background(root, lambda: make(folder), done)

        return run

    def on_close() -> None:
        if not making_reports:  # closing part-way would leave a half-made folder behind
            root.destroy()

    def on_settings_file() -> None:
        chosen = choose_settings_file(root)
        if chosen:
            settings_location.set(f"Settings file: {chosen}")
            read_payroll_runs()

    def show_payroll_buttons(runs: Sequence[str]) -> None:
        """One button per payroll run in the settings file, so each company makes only its own files."""
        for child in payroll_frame.winfo_children():
            child.destroy()
        buttons = []
        for column, (text, run) in enumerate(payroll_button_names(runs)):
            make = (lambda folder, run=run: make_payroll_files(folder, run=run))
            button = ttk.Button(
                payroll_frame, text=text,
                command=from_returned_files("last week", f"{run + ' ' if run else ''}payroll files", make, payroll_summary),
            )
            button.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 8, 0))
            payroll_frame.columnconfigure(column, weight=1, uniform="payroll")
            if making_reports:
                button.state(["disabled"])
            buttons.append(button)
        controls[:] = [process_button, *buttons, agency_button, settings_button]

    def read_payroll_runs() -> None:
        """Once when the window opens, and when the settings file changes. If it can't be read, the one button
        stays, and clicking it explains why."""

        def loaded(current: Optional[settings.Settings], _error) -> None:
            if current is not None and root.winfo_exists():
                show_payroll_buttons(list(current.payroll_runs))

        _in_background(root, settings.load, loaded)

    ttk.Label(frame, text="1. When you have this week's file from Jibble:", style="Heading.TLabel").grid(
        row=0, column=0, sticky="w")
    process_button = ttk.Button(frame, text="Make this week's reports...", command=on_process)
    process_button.grid(row=1, column=0, sticky="ew", pady=(6, 18))
    ttk.Label(frame, text="2. When the supervisors have sent back last week's files:", style="Heading.TLabel").grid(
        row=2, column=0, sticky="w")
    payroll_frame = ttk.Frame(frame)
    payroll_frame.grid(row=3, column=0, sticky="ew", pady=(6, 18))
    ttk.Label(frame, text="3. On agency payday, for the last two weeks:", style="Heading.TLabel").grid(
        row=4, column=0, sticky="w")
    agency_button = ttk.Button(
        frame,
        text="Make the agency hours...",
        command=from_returned_files("the last two weeks", "agency hours", make_agency_hours, agency_summary),
    )
    agency_button.grid(row=5, column=0, sticky="ew", pady=(6, 18))
    progress = ttk.Progressbar(frame, mode="indeterminate")  # moves while the reports are being made
    progress.grid(row=6, column=0, sticky="ew", pady=(0, 12), ipady=4)
    progress.grid_remove()
    status_label = ttk.Label(frame, textvariable=status, wraplength=600, justify="left", anchor="nw")
    status_label.grid(row=7, column=0, sticky="nsew")
    ttk.Separator(frame).grid(row=8, column=0, sticky="ew", pady=(12, 0))
    settings_label = ttk.Label(frame, textvariable=settings_location, wraplength=600, justify="left", style="Note.TLabel")
    settings_label.grid(row=9, column=0, sticky="w", pady=(10, 0))

    def wrap_text(event) -> None:  # long messages fill the window's width, however wide it is
        width = max(event.width - 2 * 20, 200)
        status_label.configure(wraplength=width)
        settings_label.configure(wraplength=width)

    frame.bind("<Configure>", wrap_text)
    bottom = ttk.Frame(frame)
    bottom.grid(row=10, column=0, sticky="ew", pady=(10, 0))
    settings_button = ttk.Button(bottom, text="Settings file...", command=while_busy(on_settings_file))
    settings_button.pack(side="left")
    open_button = ttk.Button(bottom, text="Open folder", command=lambda: os.startfile(last_folder["path"]))
    open_button.state(["disabled"])
    open_button.pack(side="right")
    controls: list = []  # every button that's disabled while something is being made, kept up to date
    show_payroll_buttons([])
    read_payroll_runs()
    process_button.focus_set()
    if updater.is_packaged():
        _offer_update(root, status, controls, lambda: busy)
    root.protocol("WM_DELETE_WINDOW", on_close)
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
        "settings_note": result.export.settings_note,
    }
    _emit(sys.stdout, json.dumps(report, indent=2))
    return 0


def run_update() -> int:
    """Update without asking, for running from a command prompt or a scheduled task."""
    if not updater.is_packaged():
        _emit(sys.stderr, "Error: updating only works from an installed copy of the app.")
        return 1
    try:
        update = updater.find_update()
        if not update:
            _emit(sys.stdout, f"{APP_NAME} {__version__} is up to date.")
            return 0
        updater.install(updater.download(update), reopen=False)
    except Exception as error:  # the windowed app has no console to show a traceback
        _emit(sys.stderr, f"Error: the update didn't finish. {error}")
        return 1
    _emit(sys.stdout, f"Installing {APP_NAME} {update.version}.")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="punch-clock", description=__doc__)
    parser.add_argument("source", nargs="?", type=Path, help="weekly Jibble export (.xlsx) to process")
    parser.add_argument("--output-dir", type=Path, help="where to create the week's folder (default: beside the export)")
    parser.add_argument("--update", action="store_true", help="install the latest release, if there's a newer one")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    args = parser.parse_args(argv)
    if args.update:
        return run_update()
    if args.source:
        return run_command_line(args.source, args.output_dir)
    return run_window()


if __name__ == "__main__":
    raise SystemExit(main())
