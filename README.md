# Punch Clock

Punch Clock is a small Windows app that turns a weekly [Jibble](https://www.jibble.io/) timesheet export into a printable report and a review spreadsheet for each supervisor. Once the supervisors have made their changes, it combines them into an approved report for accounting.

It isn't affiliated with or endorsed by Jibble.

## What you get

Each export gets its own dated folder, created beside it:

```text
Jibble timesheets 2026-03-02 to 2026-03-08\
    Printable timesheets 2026-03-02.pdf     headcount page, then two employees per page
    Validation 2026-03-02.txt               every comparison with Jibble's own totals
    Source export 2026-03-02.xlsx           an untouched copy of the export
    Supervisor files\
        Review - Assembly - Avery Lee - 2026-03-02.xlsx
        Review - Accounting - no supervisor - 2026-03-02.xlsx
```

Building the approved report adds these two files:

```text
    Approved timesheets 2026-03-02.pdf      with adjustments, approved hours and comments
    Approved hours 2026-03-02.xlsx          totals for payroll, plus every change made
```

Until every employee is reviewed, they're named `Provisional` and marked as such.

Your export is only ever read, and everything runs on your own PC. No data is sent anywhere. Processing the same export again creates a new folder ending in `(2)`, so returned files are never overwritten.

## Install

1. Open the [latest release](../../releases/latest).
2. Download and run `PunchClock-<version>-setup.exe`. It installs for the current user and doesn't need admin rights.
3. Start **Punch Clock** from the Start menu.

It runs on 64-bit Windows 10 and 11. Nothing else needs installing.

Or download `PunchClock-<version>-windows.zip`, extract the whole folder, and run `PunchClock.exe`.

The app isn't code-signed yet, so Windows may show a SmartScreen warning the first time. To continue, choose **More info**, then **Run anyway**. You can check your download against `SHA256SUMS.txt` in the release.

## What to export from Jibble

Export one full Monday to Sunday week from Timesheets as XLSX, with durations in hours and minutes (for example `1h 06m`). Turn on all three options:

| Jibble option | Sheet it creates | Used for |
|---|---|---|
| Timesheets list in single tabs | `Raw Timesheets` | Positions, payroll hours, overtime |
| Time entries list in single tabs | `Raw Time Entries` | Every In/Out punch and note |
| Timesheets per member in individual tabs | One sheet per member | Cross-checking the totals |

The `Team Summary` sheet is also used, for the week, company name and team totals.

## Weekly use

**Step 1: process the export.** Open Punch Clock, choose **Process a Jibble export**, and select the file. The week's folder opens when it's ready. Print the PDF if you need it, and send each file in `Supervisor files` to its supervisor.

**Step 2: supervisors review.** In their file, each supervisor:

- Enters any adjustment in minutes, added to Net: `15` adds 15 minutes, `-15` removes 15 minutes, and `0` means no change.
- Types the approved hours as `h:mm` on any orange row, where the punches are incomplete.
- Adds comments if needed.
- Chooses **Yes** under **Reviewed** in each employee's **Week total** row.

**Step 3: build the approved report.** Save each returned file over the original in `Supervisor files`, keeping one file per supervisor. Then choose **Build the approved report** and select the week's folder. You can run this at any time: it shows what's still outstanding, and you can run it again as more files come back.

To correct a punch or a position, fix it in Jibble, export again, and start from step 1.

## Who reviews whom

A position ending in `- Supervisor` makes that person the supervisor of the department before the tag. `Assembly - Supervisor` supervises everyone whose position is `Assembly`, and counts as part of the Assembly department.

| Who | Whose file they're in |
|---|---|
| Employees in a department with a supervisor | That supervisor's |
| Employees in a department with no supervisor | Accounting's |
| Supervisors themselves | Their own, along with their department |
| Employees with no position | Nobody's: they're left out and listed in the validation file |

Each supervisor's file holds only their own department.

## How hours are calculated

| Item | Rule |
|---|---|
| Gross | Sum of completed In/Out sessions, rounded once per day to the nearest minute. Clocked-out time isn't counted. |
| Lunch | 30 minutes unpaid per worked day, capped at gross. The day's clocked-out gaps count toward the 30 minutes, so only the remainder is deducted. |
| Net | Gross minus lunch. |
| Approved | Net plus the supervisor's adjustment. On an incomplete day, the hours the supervisor typed. |
| Overtime | Jibble's five recorded categories, added together. Never recalculated. |
| Incomplete punches | That day's and that week's gross and net show `MISSING` until reviewed. |
| No punches | Shown as `-`, not `0:00`. It doesn't confirm an absence. |

For an 8-hour span with a 20-minute gap, 10 minutes of lunch are deducted, so 30 minutes are unpaid in total. With a gap of 30 minutes or more, nothing further is deducted.

Approved hours are always recalculated from the source export and the supervisor's entries, so an edited formula in a returned file can't change the result.

To change the lunch length, edit `LUNCH_MINUTES` in [`hours.py`](src/punch_clock/hours.py) and the wording on the first page in [`pdf_report.py`](src/punch_clock/pdf_report.py).

## When a file is refused

The app stops with a plain message rather than risk a wrong report. It refuses an export with:

- Missing sheets or renamed columns
- Duplicate daily rows
- Conflicting names or positions for one member code
- Unknown entry types
- Mixed timezones
- Anything other than one Monday to Sunday week
- Jibble break punches, because the fixed lunch can't be mixed with Jibble's break tracking
- An employee with too many punches to fit on one printed page
- A folder path too long for Excel to open

It also refuses a review file from a different export, two copies of one supervisor's file, and any other workbook in `Supervisor files`.

A shift that crosses midnight is flagged for review. It may leave that day's hours unavailable, depending on how Jibble dates the punches.

## Privacy

Exports contain names, hours and locations. Don't commit them, and don't attach real ones to GitHub issues. `.gitignore` blocks spreadsheets, CSVs and PDFs, and a test fails if any are tracked. Tests use a fictional export built by [`tests/sample_export.py`](tests/sample_export.py).

## Development

You need Windows and Python 3.10 or later. Inno Setup is only needed to build the installer, not to install or run the app.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r packaging\requirements.txt
.venv\Scripts\python -m pytest
.venv\Scripts\python -m pip install -e . --no-deps
.venv\Scripts\punch-clock
```

| Module | Job |
|---|---|
| `hours.py` | Pairs punches and applies the gross, lunch and net rules |
| `jibble_export.py` | Reads the export by its labels and cross-checks the sheets |
| `assignments.py` | Decides who reviews whom |
| `pdf_report.py` | Lays out the printable and approved PDFs |
| `review_workbook.py` | Writes each supervisor's spreadsheet |
| `approvals.py` | Reads returned spreadsheets and works out approved hours |
| `summary_workbook.py` | Writes accounting's summary of approved hours |
| `validation_report.py` | Writes the validation file |
| `reports.py` | Runs the two jobs and manages the week's folder |
| `app.py` | The window and command line |

## Packaging

To rebuild the app after a change, double-click `packaging\build.cmd`, or run:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

This installs the pinned dependencies, runs the tests, builds the app, tries the packaged app on a sample export, and writes these files to `dist\`:

- `PunchClock\`, the app folder
- `PunchClock-<version>-windows.zip`
- `PunchClock-<version>-setup.exe`, if [Inno Setup 6](https://jrsoftware.org/isinfo.php) is installed
- `SHA256SUMS.txt`

## Releasing

1. Update `__version__` in [`src/punch_clock/__init__.py`](src/punch_clock/__init__.py) and add an entry to [`CHANGELOG.md`](CHANGELOG.md).
2. Commit, then tag and push:

   ```powershell
   git tag v0.2.0
   git push origin main v0.2.0
   ```

GitHub Actions then runs the same build and publishes the files as a GitHub Release. Installing a new version over an old one upgrades it in place.

## License

[MIT](LICENSE). The packaged app also includes Python, openpyxl, XlsxWriter, ReportLab, pypdf and Pillow, under their own licenses.
