# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Punch Clock is a Windows Tkinter app that turns a weekly Jibble timesheet export into a printable PDF and a review spreadsheet per supervisor. The README covers the pay rules, the export format and the weekly workflow in detail.

## Privacy

This repo and its release installers are public, and installed copies update from those releases.

- Never put real employee or supervisor names, the company name, member codes or real work schedules anywhere in the repo, including tests, docs, fixtures and commit messages. Use fictional values, like those in `tests/sample_export.py`.
- Never commit real exports or generated reports. `.gitignore` blocks them, and a test in `tests/test_reports.py` fails if any are tracked.
- Anything bundled by `packaging/punch_clock.spec` ends up in a public installer, so bundling is the same as publishing.
- The real supervisors and schedules live only in the settings file outside the app (see `settings.py`), with a local copy in `private/`, which git ignores. Don't read values from them into anything tracked. The real file's location is private too: published code only knows the home-folder default.

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
- **`settings.py`** finds the settings file (the location saved per PC by the **Settings file...** button, otherwise the home folder) and reads it once per run of `process_export`, never in the background. If it can't be reached in time, it falls back to a copy in `%APPDATA%\Punch Clock\`, and `WeeklyExport.settings_note` carries that fact onto every report. A mistake in the file stops the run instead.
- **`assignments.py`** builds the review groups from the department (the Jibble position, without any `- Supervisor` ending) and the supervisors in the settings. Employees without a supervisor go in a `Missing supervisor` group for accounting.
- **`reports.py`** builds each week's folder under a `.tmp` name and renames it when finished, so a failed run never looks complete. A rerun creates a new folder ending in `(2)` rather than overwriting.
- **`review_workbook.py`** writes with XlsxWriter, and approved hours and overtime are live Excel formulas with cached values. A pay rule therefore lives in both `hours.py` and these formulas, so change both.
- **`pdf_report.py`, `review_workbook.py` and `validation_report.py`** each describe the rules in words, so update that wording when a rule changes.
- **`updater.py`** reads the latest GitHub release with no token, which is why the repo is public. It verifies `SHA256SUMS.txt` and installs silently, and it only runs in the packaged app (`sys.frozen`).

## Conventions

- The people using the app aren't technical, so keep text in the window, PDFs and spreadsheets plain.
- Keep clock times and durations clearly different in code, UI and messages: `8:00 AM` is a time and `8h 00m` is a length of time.
- There are no night shifts, and employees don't punch out for lunch: a flat 30 minutes is deducted on each worked day.

## Testing notes

- `tests/conftest.py` redirects `APPDATA` and `USERPROFILE` for every test, so tests never touch this PC's real settings file, saved copy or remembered location. Use `sample_export.write_settings` to set up fictional supervisors and schedules. It also lifts the Excel path-length limit for pytest's long temp paths.
- If a test needs Tk, share one root per module with a module-scoped fixture, because repeated `tk.Tk()` calls make tests flaky.
- To check a workbook's formulas for real, open it in LibreOffice headless or in Excel through COM. Excel's `ExportAsFixedFormat` over COM has hung and left hidden Excel processes behind, so render PDFs with LibreOffice instead.
