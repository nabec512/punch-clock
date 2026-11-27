# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Punch Clock is a Windows Tkinter app that turns a weekly Jibble timesheet export into a printable PDF and a review spreadsheet per supervisor. The README covers the pay rules, the export format and the weekly workflow in detail.

## Privacy

This repo and its release installers are public, and installed copies update from those releases.

- Never put real employee or supervisor names, the company name, member codes or real work schedules anywhere in the repo, including tests, docs, fixtures and commit messages. Use fictional values, like those in `tests/sample_export.py`.
- Never commit real exports or generated reports. `.gitignore` blocks them, and a test in `tests/test_reports.py` fails if any are tracked.
- Anything bundled by `packaging/punch_clock.spec` ends up in a public installer, so bundling is the same as publishing.
- The real supervisors and schedules live only in the settings file outside the app, and who pays each employee only in the accounting settings file (see `settings.py`), with local copies in `private/`, which git ignores. Don't read values from them into anything tracked. The real file's location is private too: published code only knows the home-folder default.

## Commands

Windows only, using the repo's virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r packaging\requirements.txt   # pinned versions, used by CI and releases
.venv\Scripts\python -m pip install -e . --no-deps

.venv\Scripts\python -m pytest                                      # all tests
.venv\Scripts\python -m pytest tests/test_hours.py -k "14:59"       # one file, filtered by test id

.venv\Scripts\punch-clock                                           # open the window
.venv\Scripts\punch-clock <export.xlsx> --output-dir <folder>       # process an export without the window
.venv\Scripts\python tests\sample_export.py <out.xlsx> <settings.json>   # write a fictional export and settings to try

powershell -ExecutionPolicy Bypass -File packaging\build.ps1        # tests, PyInstaller, smoke test, zip, installer
```

To run the app on fictional settings, set `USERPROFILE` and `APPDATA` to a scratch folder, with that file in it as `punch-clock-settings.json`, so this PC's real settings aren't used or overwritten. There's no linter or formatter configured. CI runs `pytest` on Windows with Python 3.12.

To release, set `__version__` in `src/punch_clock/__init__.py`, add a `CHANGELOG.md` entry, commit, then push a tag. The workflow fails unless the tag is exactly `v` + `__version__`. Each version must be higher than the last, or installed copies won't see it as an update.

## Architecture

The flow is `app.py` -> `reports.process_export` -> `jibble_export.load_export` -> one PDF and one workbook per review group.

- **`jibble_export.py`** finds columns by label, not position, and cross-checks the sheets against each other. It refuses a suspect file with a plain message rather than risk a wrong report. Its `DayRecord.hours` property calls `hours.calculate_day`, passing the day's schedule.
- **`hours.py`** is the only place pay is calculated, and its rule constants are at the top. Jibble's In/Out labels can't be trusted, because punches simply toggle: each day's punches are paired in time order, and an odd count asks a person for the hours. Jibble's overtime isn't used.
- **`settings.py`** finds the settings file (the location saved per PC by the **Settings file...** button, otherwise the home folder) and reads it once per run of `process_export`, `make_payroll_files` or `make_agency_hours`, and once when the window opens (or the file is changed) to show a button per `payroll_runs` entry. It's never polled. If it can't be reached in time, it falls back to a copy in `%APPDATA%\Punch Clock\`, and `WeeklyExport.settings_note` carries that fact onto every report. A mistake in the file stops the run instead. It has a section per organization, keyed by the company name Jibble puts in the export (`WeeklyExport.company`), because organizations share department names. Everything to do with pay is in a second file, the accounting settings file (`load_accounting`/`load_full`, location saved per PC by **Accounting settings file...**), which is never copied to the PC; the shared file refuses any of it, so department supervisors' PCs never hold pay data. `split_settings` (and `punch-clock --split-settings`) splits an older file that holds both. `process_export` picks the export's section, then assigns schedules with `jibble_export.assign_schedules`. An organization with no section stops the run, and must never fall back to another organization's settings. The file is edited by hand, so every section lists the settings it allows and refuses any other: add a new setting to that list, and never ignore an unknown one. Every PC reads the same file on whatever version it has, so the file's optional `minimum_version` is checked before anything else, to make an older app ask for an update rather than call a newer setting a mistake. Each section's optional `employees` says who pays each member code (a `PayLink`: a payroll and employee number, or a staffing agency), because the company on the books can differ from the organization someone punches in. Those payrolls and agencies must be listed in the top-level `payrolls` and `agencies`, and an employee number is unique within its payroll across the whole file. This is groundwork for the payroll and agency step described in `docs/payroll-and-agencies.md`.
- **`assignments.py`** builds the review groups from the department (the Jibble position, without any `- Supervisor` ending) and the supervisors in the export's organization. Employees without a supervisor go in a `Missing supervisor` group for accounting.
- **`reports.py`** builds each week's folder under a `.tmp` name and renames it when finished, so a failed run never looks complete. A rerun creates a new folder ending in `(2)` rather than overwriting.
- **`review_workbook.py`** writes with XlsxWriter, and approved hours and overtime are live Excel formulas with cached values. A pay rule therefore lives in both `hours.py` and these formulas, so change both. A very hidden, protected `Punch Clock data` sheet records each day row's member code, Excel row and the fixed figures its formulas use (paid and scheduled minutes, whether punches were incomplete). Bump `DATA_FORMAT` if its layout changes in a way an older reader would misread.
- **`archive.py`** looks after the accounting folder named by `accounting_folder` in the settings file: `receive_files` checks each returned review file with `approved_hours`, files it as `Returned files/<organization>/<week>/<organization> - <group> - <week>.xlsx` (an earlier version moves to `history`), and appends a line with its SHA-256 to `receipts.csv`. `read_archive` gives the payroll and agency steps the received files for their weeks, refusing any whose fingerprint doesn't match its latest receipt. Nothing falls back to a local copy if the folder can't be reached.
- **`returned_files.py`** finds the returned review files in a chosen folder (and below it) for given weeks, reads them with `approved_hours`, and refuses a supervisor or employee found twice in a week. Payroll and agency steps both use it.
- **`payroll_files.py`** makes one PowerPay Employee Timesheet import CSV per payroll for the week chosen in the window (`start`, by default the last full week; `week_choices` lists those with files received, from `archive.received_weeks`, and one not over yet gets a warning; `agency_hours.period_choices` does the same for pay periods) (columns and the `RT`/`OT` earning codes are constants at the top, matching the template set up in PowerPay). A PowerPay import replaces each listed employee's entries in the run, so each file holds everyone's complete hours and leaves out anyone with none. Anyone not linked, or problems in a file with payroll staff, stop the run.
- **`agency_hours.py`** makes the agency files every two weeks for the last agency pay period that has ended, and groups agency staff by agency and by the organization's `agencies_paid_by`. Each week's figures are added, never worked out again together. A file found twice, or problems in a file with agency staff, stop the run. **`agency_workbook.py`** writes each file, with totals and lunch as live formulas so accounting can change lunch days.
- **`approved_hours.py`** reads a returned review workbook for the payroll and agency step. It reads only the supervisor's inputs (adjustments, typed hours, Reviewed, comments), recomputes each day and week with `hours.overtime_minutes` and `hours.week_hours`, and compares that with any results the file saved. Mistakes and disagreements are collected as plain sentences in `ApprovedFile.problems`, never silently resolved. A file whose rows moved, or with no data sheet (made before 0.11.0), is refused.
- **`pdf_report.py`, `review_workbook.py` and `validation_report.py`** each describe the rules in words, so update that wording when a rule changes.
- **`app.py`** makes the reports on a background thread, through `process_in_window`, so the window can show a moving bar. Tk is only ever touched from its own thread, and the window won't close part-way through.
- **`updater.py`** reads the latest GitHub release with no token, which is why the repo is public. It verifies `SHA256SUMS.txt` and installs silently, and it only runs in the packaged app (`sys.frozen`).

## Conventions

- The people using the app aren't technical, so keep text in the window, PDFs and spreadsheets plain.
- Keep clock times and durations clearly different in code, UI and messages: `8:00 AM` is a time and `8h 00m` is a length of time.
- There are no night shifts, and employees don't punch out for lunch: a flat 30 minutes is deducted on each worked day, except on weekend hours (a day off with hours in the settings file), which have no lunch and are all overtime.
- Paid hours go in 15-minute blocks, always rounded down, and overtime is measured against each employee's own schedule. The review sheet shows Regular hours, Overtime hours and Total approved hours, and the total is the sum of the other two.

## Testing notes

- `tests/conftest.py` redirects `APPDATA` and `USERPROFILE` for every test, so tests never touch this PC's real settings file, saved copy or remembered location. Use `sample_export.write_settings` to set up fictional supervisors and schedules for the sample's organization, `COMPANY`, and its `others` argument for more organizations. It also lifts the Excel path-length limit, and points pytest's temp folder at a short path, because Windows refuses paths over 260 characters.
- If a test needs Tk, share one root per module with a module-scoped fixture, because repeated `tk.Tk()` calls make tests flaky.
- To check a workbook's formulas for real, open it in LibreOffice headless or in Excel through COM. Excel's `ExportAsFixedFormat` over COM has hung and left hidden Excel processes behind, so render PDFs with LibreOffice instead.
