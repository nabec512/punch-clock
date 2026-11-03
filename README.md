# Punch Clock

Punch Clock is a small Windows app that turns a weekly [Jibble](https://www.jibble.io/) timesheet export into a printable PDF and a review spreadsheet for each supervisor. The supervisors send their changes back to accounting, who process them from there.

It isn't affiliated with or endorsed by Jibble.

## What you get

Each export gets its own dated folder, created beside it:

```text
Jibble timesheets 2026-03-02 to 2026-03-08\
    Validation 2026-03-02.txt               every comparison with Jibble's own totals
    Source export 2026-03-02.xlsx           an untouched copy of the export
    Supervisor files\
        Avery Lee - Assembly - 2026-03-02 - Printable.pdf     headcount page, then two employees per page
        Avery Lee - Assembly - 2026-03-02.xlsx
        Missing supervisor - 2026-03-02 - Printable.pdf
        Missing supervisor - 2026-03-02.xlsx
```

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

**Step 1: process the export.** Open Punch Clock, choose **Make this week's reports**, and select the file. If the file has a department the app hasn't seen before, it asks who supervises it. The week's folder opens when it's ready. In `Supervisor files`, send each supervisor their PDF to print and their Excel file to fill in. Accounting keeps the two `Missing supervisor` files and reviews them.

**Step 2: supervisors review.** In their Excel file, each supervisor:

- Enters any adjustment in minutes, added to Net: `15` adds 15 minutes, `-15` removes 15 minutes, and `0` means no change.
- Types the approved hours as `h:mm` on any orange row, where the punches are incomplete.
- Adds comments if needed.
- Chooses **Yes** under **Reviewed** in each employee's **Week total** row.

**Step 3: accounting takes over.** Supervisors send their Excel files back to accounting, who process them from there.

To correct a punch or a position, fix it in Jibble, export again, and start from step 1.

## Who reviews whom

Choose **Supervisors** in the app to set who reviews each department. A supervisor doesn't need to be in Jibble, and one person can cover several departments, with one PDF and one Excel file for all of them. The list is saved on this PC, in `%APPDATA%\Punch Clock\supervisors.json`.

| Who | Whose files they're in |
|---|---|
| Employees in a department with a supervisor | That supervisor's |
| Employees in a department with no supervisor | The `Missing supervisor` files, which accounting reviews. They're also marked `MISSING SUPERVISOR` in the PDFs |
| Supervisors who are also employees | Whoever supervises the department in their position, so usually their own |
| Employees with no position | Nobody's: they're left out and listed in the validation file |

The department is the Jibble position, without any ending such as `- Supervisor`, so `Assembly` and `Assembly - Supervisor` are one department. That ending only fills in the first guess when the app first sees a department.

Each supervisor's files hold only their own departments.

A change applies to the next reports you make, not to files already sent out.

## How hours are calculated

| Item | Rule |
|---|---|
| Gross | Sum of completed In/Out sessions, rounded once per day to the nearest minute. Clocked-out time isn't counted. |
| Lunch | 30 minutes unpaid per worked day, even if the employee also clocked out that day. It's capped at gross, so net never goes below zero. |
| Net | Gross minus lunch. |
| Approved | Net plus the supervisor's adjustment. On an incomplete day, the hours the supervisor typed. |
| Overtime | Jibble's five recorded categories, added together. Never recalculated. |
| Incomplete punches | That day's and that week's gross and net show `MISSING` until reviewed. |
| No punches | Shown as `-`, not `0:00`. It doesn't confirm an absence. |

For an 8-hour span with a 20-minute gap, gross is 7:40 and net is 7:10, so 50 minutes are unpaid in total. If the employee's clocked-out time was their lunch, the supervisor can add the 30 minutes back as an adjustment.

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
| `supervisor_list.py` | Saves who supervises each department |
| `assignments.py` | Decides who reviews whom |
| `pdf_report.py` | Lays out the printable PDFs |
| `review_workbook.py` | Writes each supervisor's spreadsheet |
| `validation_report.py` | Writes the validation file |
| `reports.py` | Makes the week's reports and manages its folder |
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
