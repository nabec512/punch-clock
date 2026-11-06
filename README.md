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

It runs on 64-bit Windows 10 and 11. Nothing else needs installing, but the PC needs to reach its settings file the first time it makes reports. See [The settings file](#the-settings-file).

Once installed, the app keeps itself up to date. Each time it opens, it checks GitHub for a newer release and offers to install it, then reopens by itself. If the PC is offline, it carries on without saying anything. Updates don't affect the settings file. To update without being asked, for example from a scheduled task, run `PunchClock.exe --update`. Automatic updates only work from the installer's copy, starting with the first version that includes them.

Or download `PunchClock-<version>-windows.zip`, extract the whole folder, and run `PunchClock.exe`.

The app isn't code-signed yet, so Windows may show a SmartScreen warning the first time. To continue, choose **More info**, then **Run anyway**. You can check your download against `SHA256SUMS.txt` in the release.

## Tablet setup

To set up an Android tablet as a shared time clock, follow the [tablet setup guide](docs/tablet-setup.md). It covers the Jibble kiosk, locking the tablet down with FreeKiosk, USB troubleshooting, tests to run and how to recover it.

## What to export from Jibble

Export one full Monday to Sunday week from Timesheets as XLSX, with durations in hours and minutes (for example `1h 06m`). Turn on all three options:

| Jibble option | Sheet it creates | Used for |
|---|---|---|
| Timesheets list in single tabs | `Raw Timesheets` | Positions, payroll hours |
| Time entries list in single tabs | `Raw Time Entries` | Every In/Out punch and note |
| Timesheets per member in individual tabs | One sheet per member | Cross-checking the totals |

The `Team Summary` sheet is also used, for the week, company name and team totals.

To make reports for just some departments, filter the export by position in Jibble. Jibble still lists everyone's punches in `Raw Time Entries`, so the app skips punches from departments the rest of the file leaves out, and the validation file says how many it skipped.

## Weekly use

**Step 1: process the export.** Open Punch Clock, choose **Make this week's reports**, and select the file. The week's folder opens when it's ready. In `Supervisor files`, send each supervisor their PDF to print and their Excel file to fill in. Accounting keeps the two `Missing supervisor` files and reviews them.

**Step 2: supervisors review.** In their Excel file, each supervisor:

- Enters any adjustment in minutes, added to Net: `15` adds 15 minutes, `-15` removes 15 minutes, and `0` means no change. Overtime updates by itself.
- Types the approved hours as `h:mm` on any orange row, where the punches are incomplete.
- Adds comments if needed.
- Chooses **Yes** under **Reviewed** in each employee's **Week total** row.

**Step 3: accounting takes over.** Supervisors send their Excel files back to accounting, who process them from there.

To correct a punch or a position, fix it in Jibble, export again, and start from step 1.

## Who reviews whom

[The settings file](#the-settings-file) says who reviews each department. A supervisor doesn't need to be in Jibble, and one person can cover several departments, with one PDF and one Excel file for all of them.

| Who | Whose files they're in |
|---|---|
| Employees in a department with a supervisor | That supervisor's |
| Employees in a department with no supervisor | The `Missing supervisor` files, which accounting reviews. They're also marked `MISSING SUPERVISOR` in the PDFs |
| Supervisors who are also employees | Whoever supervises the department in their position, so usually their own |
| Employees with no position | Nobody's: they're left out and listed in the validation file |
| Employees whose position is `Test` | Nobody's: practice accounts are left out and listed in the validation file, because Jibble can still export them after they're archived |

The department is the Jibble position, without any ending such as `- Supervisor`, so `Assembly` and `Assembly - Supervisor` are one department. That ending doesn't make anyone a supervisor.

Each supervisor's files hold only their own departments.

## How hours are calculated

| Item | Rule |
|---|---|
| Gross | Sum of completed In/Out sessions, rounded once per day to the nearest minute. Clocked-out time isn't counted. |
| Lunch | 30 minutes unpaid per worked day, even if the employee also clocked out that day. It's capped at gross, so net never goes below zero. |
| Net | Gross minus lunch. |
| Paid | Net by the schedule. Time before the start isn't paid. Arriving up to 5 minutes late counts as on time, so 8:05 AM counts as 8:00 AM on a schedule starting then, and 8:06 AM counts from 8:06 AM. Time under 15 minutes past the scheduled hours isn't paid. |
| Approved | Paid, plus the supervisor's adjustment. On an incomplete day, the hours the supervisor typed. |
| Overtime | Starts 15 minutes past the scheduled hours, counted from the end of those hours. On an 8-hour schedule, approved hours of 8:15 give 0:15 of overtime and 8:14 give none. All hours on a scheduled day off are overtime. Jibble's overtime isn't used. |
| Punch pairs | Each day's punches are paired in time order, ignoring Jibble's In and Out labels. |
| Incomplete punches | A day with an odd number of punches is missing one. That day's and that week's gross and net show `MISSING` until reviewed. |
| No punches | Shown as `-`, not `0:00`. It doesn't confirm an absence. |

For an 8-hour span with a 20-minute gap, gross is 7:40 and net is 7:10, so 50 minutes are unpaid in total. If the employee's clocked-out time was their lunch, the supervisor can add the 30 minutes back as an adjustment.

To change the lunch length, grace period or overtime rule, edit the numbers at the top of [`hours.py`](src/punch_clock/hours.py) and the wording in [`pdf_report.py`](src/punch_clock/pdf_report.py), [`review_workbook.py`](src/punch_clock/review_workbook.py) and [`validation_report.py`](src/punch_clock/validation_report.py).

## The settings file

Supervisors and work schedules aren't in the app or this repository, because both are public. They're in one file that you keep somewhere every PC can reach, such as a shared drive.

The app looks for `punch-clock-settings.json` in the user's home folder. To use a file somewhere else, choose **Settings file...** in the app once on each PC, and pick the file. The app checks it, then remembers it on that PC, including through updates. The window shows which file it's using.

To change a supervisor or a schedule, edit that file. There's no new version to release, and each PC uses the change the next time it makes reports. Files already sent out don't change.

```json
{
  "supervisors": { "Assembly": "Avery Lee", "Receiving": "" },
  "department_schedules": {
    "Assembly": { "start": "08:00", "end": "16:30" },
    "Receiving": { "start": "07:00", "end": "17:30", "days": ["Mon", "Tue", "Wed", "Thu"] }
  },
  "member_schedules": { "AB-1": { "start": "09:30", "end": "18:00" } }
}
```

| Key | Meaning |
|---|---|
| `supervisors` | Who reviews each department. Leave a name blank, or the department out, and accounting reviews those employees |
| `department_schedules` | Hours for each department, matched to the Jibble position without any `- Supervisor` ending |
| `member_schedules` | Hours for anyone who differs from their department, by Jibble member code |
| `start`, `end` | 24-hour times. The paid hours are the time between them, less the 30-minute lunch |
| `days` | Days worked. Leave it out for Monday to Friday |

Someone with no schedule is paid as worked, with overtime starting at 8:15.

The app reads the file once each time someone makes reports, and doesn't touch the drive at any other time. It copies each good read to `%APPDATA%\Punch Clock\saved-settings.json`, and remembers the file's location beside it.

| What happens | What the app does |
|---|---|
| The file can't be reached within 5 seconds | Uses the saved copy, and says so on the screen and in the PDFs, Excel files and Validation file |
| It can't be reached, and this PC has no saved copy | Stops with a plain message |
| The file has a mistake in it | Stops with a plain message, and keeps the saved copy as it was |

For keeping your own copy in a clone of this repository, the `private/` folder is ignored by Git.

## Forgotten punches

Each Jibble punch simply flips between In and Out. If someone forgets to clock out, their next morning's punch is recorded as `Out`, and their labels stay swapped until another punch is missed. So the app doesn't rely on the labels:

| Punches on a day | What the app does |
|---|---|
| Two, or any even number | Pairs them in time order. If the labels were swapped, it says so in the notes |
| One, or any odd number | Asks for the hours, because a punch is missing |
| Odd, with two moments apart | Counts the two as one, as that's someone fixing a forgotten punch by punching twice |
| None | Shows `No punches`. This is what forgetting both punches looks like, so it doesn't confirm an absence |

If someone forgets two punches on a day when they also clocked out and back during the day, the day can look complete with the wrong hours.

Staying swapped doesn't affect the app's hours, but Jibble's own totals stay wrong until it's fixed, and the end-of-run message names anyone who may be swapped. To get back in sync, the person clocks out and straight back in when they next arrive at work. No special code or comment is needed. Avoid doing this on a day off, because a lone punch on that day would then ask for hours.

Jibble's own totals count the time until the next punch as worked, so its payroll hours can be too high after a forgotten clock-out. The app's hours don't use them. To correct Jibble itself, fix the punch there and export again.

## When a file is refused

The app stops with a plain message rather than risk a wrong report. It refuses an export with:

- Missing sheets or renamed columns
- Duplicate daily rows
- Conflicting names or positions for one member code
- Punches from someone missing from the other sheets when their department is in the file
- Unknown entry types
- Mixed timezones
- Anything other than one Monday to Sunday week
- Jibble break punches, because the fixed lunch can't be mixed with Jibble's break tracking
- An employee with too many punches to fit on one printed page
- A folder path too long for Excel to open

The app assumes no shift crosses midnight. A day that seems to do so is treated as a forgotten punch.

## Privacy

Exports contain names, hours and locations, and the settings file contains names and work schedules. Don't commit them, and don't attach real ones to GitHub issues. `.gitignore` blocks spreadsheets, CSVs, PDFs and the `private/` folder, and a test fails if any are tracked. Tests use a fictional export built by [`tests/sample_export.py`](tests/sample_export.py).

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
| `hours.py` | Pairs punches and applies the gross, lunch, net, paid and overtime rules |
| `settings.py` | Finds and reads the settings file, and keeps a copy on the PC |
| `jibble_export.py` | Reads the export by its labels and cross-checks the sheets |
| `assignments.py` | Decides who reviews whom |
| `pdf_report.py` | Lays out the printable PDFs |
| `review_workbook.py` | Writes each supervisor's spreadsheet |
| `validation_report.py` | Writes the validation file |
| `reports.py` | Makes the week's reports and manages its folder |
| `updater.py` | Finds, downloads and installs newer releases |
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

GitHub Actions then runs the same build and publishes the files as a GitHub Release. Installing a new version over an old one upgrades it in place, and every installed copy offers the update the next time it opens.

The tag must match `__version__`, and each new version number must be higher than the last, or installed copies won't see it as an update.

## License

[MIT](LICENSE). The packaged app also includes Python, openpyxl, XlsxWriter, ReportLab, pypdf and Pillow, under their own licenses.
