"""Entry point: a small window with no arguments, command line with arguments."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Callable, Optional, Sequence

from punch_clock import __version__
from punch_clock.jibble_export import UnsupportedExport
from punch_clock.reports import ApprovedResult, ProcessResult, build_approved, process_export

APP_NAME = "Punch Clock"


def process_summary(result: ProcessResult) -> str:
    export = result.export
    lines = [
        f"Created the reports for {len(export.included)} employees in:",
        result.folder.name,
        "",
        "Print the PDF, or send each file in the Supervisor files folder to that supervisor.",
    ]
    lines += [f"  {group.title}: {len(group.employees)} employees" for group in result.groups]
    if export.excluded:
        lines += ["", f"Left out, no position in Jibble: {', '.join(e.name for e in export.excluded)}"]
    if export.review_count:
        lines += ["", f"{export.review_count} comparison(s) with Jibble's totals need review. See the Validation file."]
    return "\n".join(lines)


def approved_summary(result: ApprovedResult) -> str:
    approvals = result.approvals
    if approvals.is_final:
        lines = ["All employees are reviewed. Created the approved report:", result.pdf.name, result.summary.name]
    else:
        lines = ["Not everything is finished, so this report is PROVISIONAL:", result.pdf.name, result.summary.name, ""]
        waiting = approvals.not_reviewed
        if waiting:
            lines.append(f"Not reviewed yet: {len(waiting)} of {len(approvals.employees)} employees")
        needing_hours = [a for a in approvals.employees.values() if a.approved is None]
        if needing_hours:
            lines.append(f"Hours still needed: {', '.join(a.employee.name for a in needing_hours)}")
        if approvals.missing_files:
            lines.append(f"Files not found: {', '.join(approvals.missing_files)}")
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
        title="Select the weekly Jibble export",
        filetypes=[("Excel workbook", "*.xlsx")],
    )
    return _show_errors(parent, lambda: process_export(source)) if source else None


def choose_and_approve(parent) -> Optional[ApprovedResult]:
    from tkinter import filedialog

    folder = filedialog.askdirectory(parent=parent, title="Select the week's Jibble timesheets folder", mustexist=True)
    return _show_errors(parent, lambda: build_approved(folder)) if folder else None


def run_window() -> int:
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title(APP_NAME)
    root.minsize(520, 360)
    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(4, weight=1)
    status = tk.StringVar(value="Start with step 1 when you have the week's Jibble export.")
    last_folder: dict[str, Path] = {}

    def finish(result, folder: Path, text: str) -> None:
        status.set(text)
        last_folder["path"] = folder
        open_button.state(["!disabled"])
        os.startfile(folder)

    def on_process() -> None:
        result = choose_and_process(root)
        if result:
            finish(result, result.folder, process_summary(result))

    def on_approve() -> None:
        result = choose_and_approve(root)
        if result:
            finish(result, result.pdf.parent, approved_summary(result))

    ttk.Label(frame, text="Step 1: when the week's export is ready").grid(row=0, column=0, sticky="w")
    ttk.Button(frame, text="Process a Jibble export...", command=on_process).grid(row=1, column=0, sticky="ew", pady=(4, 12))
    ttk.Label(frame, text="Step 2: when supervisors have returned their files").grid(row=2, column=0, sticky="w")
    ttk.Button(frame, text="Build the approved report...", command=on_approve).grid(row=3, column=0, sticky="new", pady=(4, 12))
    ttk.Label(frame, textvariable=status, wraplength=480, justify="left", anchor="nw").grid(row=4, column=0, sticky="nsew")
    open_button = ttk.Button(frame, text="Open folder", command=lambda: os.startfile(last_folder["path"]))
    open_button.state(["disabled"])
    open_button.grid(row=5, column=0, sticky="e", pady=(12, 0))
    root.mainloop()
    return 0


def _emit(stream, text: str) -> None:
    if stream is not None:  # the windowed app has no console streams
        print(text, file=stream)


def run_command_line(source: Optional[Path], approve: Optional[Path], output_dir: Optional[Path]) -> int:
    try:
        if approve:
            result = build_approved(approve)
            report = {
                "pdf": str(result.pdf),
                "summary": str(result.summary),
                "final": result.approvals.is_final,
                "not_reviewed": [a.employee.code for a in result.approvals.not_reviewed],
            }
        else:
            result = process_export(source, output_dir)
            report = {
                "folder": str(result.folder),
                "pdf": str(result.pdf),
                "employees": len(result.export.included),
                "review_files": [group.title for group in result.groups],
                "needs_review": [check.label for check in result.export.checks if not check.match],
            }
    except (UnsupportedExport, PermissionError, FileNotFoundError) as error:
        _emit(sys.stderr, f"Error: {error}")
        return 1
    _emit(sys.stdout, json.dumps(report, indent=2))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="punch-clock", description=__doc__)
    parser.add_argument("source", nargs="?", type=Path, help="weekly Jibble export (.xlsx) to process")
    parser.add_argument("--output-dir", type=Path, help="where to create the week's folder (default: beside the export)")
    parser.add_argument("--approve", type=Path, metavar="FOLDER", help="build the approved report from a processed week's folder")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    args = parser.parse_args(argv)
    if args.source or args.approve:
        return run_command_line(args.source, args.approve, args.output_dir)
    return run_window()


if __name__ == "__main__":
    raise SystemExit(main())
