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
from punch_clock.assignments import departments_without_supervisor
from punch_clock.hours import DOUBLE_PUNCH_NOTE
from punch_clock.jibble_export import UnsupportedExport, WeeklyExport
from punch_clock.reports import ProcessResult, process_export

APP_NAME = "Punch Clock"
UPDATE_POLL_MS = 500


def _employees(count: int) -> str:
    return f"{count} employee" if count == 1 else f"{count} employees"


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
    return _show_errors(parent, lambda: process_export(source)) if source else None


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
    """Run slow network work without freezing the window. Tk may only be used from its own thread."""
    outcome: list = []

    def run() -> None:
        try:
            outcome.append((work(), None))
        except (OSError, ValueError) as error:
            outcome.append((None, error))

    def wait() -> None:
        if outcome:
            finished(*outcome[0])
        elif root.winfo_exists():
            root.after(UPDATE_POLL_MS, wait)

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
            root.after(UPDATE_POLL_MS, offer, update)
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
            except (OSError, ValueError):
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


def run_window() -> int:
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title(f"{APP_NAME} {__version__}")
    root.minsize(520, 360)
    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(2, weight=1)
    status = tk.StringVar(value="The reports are saved in a new folder next to that file.")
    settings_location = tk.StringVar(value=f"Settings file: {settings.file_path()}")
    last_folder: dict[str, Path] = {}
    busy = False

    def while_busy(action: Callable) -> Callable:
        def run() -> None:
            nonlocal busy
            busy = True
            try:
                action()
            finally:
                busy = False

        return run

    def on_process() -> None:
        result = choose_and_process(root)
        if result:
            status.set(process_summary(result))
            last_folder["path"] = result.folder
            open_button.state(["!disabled"])
            os.startfile(result.folder)

    def on_settings_file() -> None:
        chosen = choose_settings_file(root)
        if chosen:
            settings_location.set(f"Settings file: {chosen}")

    ttk.Label(frame, text="When you have this week's file from Jibble:").grid(row=0, column=0, sticky="w")
    process_button = ttk.Button(frame, text="Make this week's reports...", command=while_busy(on_process))
    process_button.grid(row=1, column=0, sticky="ew", pady=(4, 12))
    ttk.Label(frame, textvariable=status, wraplength=480, justify="left", anchor="nw").grid(row=2, column=0, sticky="nsew")
    ttk.Label(frame, textvariable=settings_location, wraplength=480, justify="left").grid(row=3, column=0, sticky="w", pady=(12, 0))
    bottom = ttk.Frame(frame)
    bottom.grid(row=4, column=0, sticky="ew", pady=(8, 0))
    settings_button = ttk.Button(bottom, text="Settings file...", command=while_busy(on_settings_file))
    settings_button.pack(side="left")
    open_button = ttk.Button(bottom, text="Open folder", command=lambda: os.startfile(last_folder["path"]))
    open_button.state(["disabled"])
    open_button.pack(side="right")
    if updater.is_packaged():
        _offer_update(root, status, [process_button, settings_button], lambda: busy)
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
    except (OSError, ValueError) as error:
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
