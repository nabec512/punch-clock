# Punch Clock

Punch Clock is a small Windows app that turns a weekly [Jibble](https://www.jibble.io/) timesheet export into a printable PDF and a review spreadsheet for each supervisor. The supervisors send their changes back to accounting, who process them from there.

It isn't affiliated with or endorsed by Jibble.

## What you get

Each export gets its own folder, named for its organization and week, and created beside it:

```text
Jibble timesheets Example Co 2026-03-02 to 2026-03-08\
    Validation 2026-03-02.txt               every comparison with Jibble's own totals
    Source export 2026-03-02.xlsx           an untouched copy of the export
    Supervisor files\
        Example Co. - Avery Lee - Assembly - 2026-03-02 - Printable.pdf     headcount page, then two employees per page
        Example Co. - Avery Lee - Assembly - 2026-03-02.xlsx
        Example Co. - Missing supervisor - 2026-03-02 - Printable.pdf
        Example Co. - Missing supervisor - 2026-03-02.xlsx
```

The organization is the company name Jibble puts at the top of the export. Each file name starts with it too, because files get sent on by themselves, and one person can supervise in more than one organization.

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

Jibble's filter picks people by their position now, but each punch keeps the position the person had when they made it. So in the week someone changes position, a filter on their old department leaves them out, and the app refuses the file rather than leave out their hours. Export again with their new position selected as well. Their hours go to their old department's supervisor, as their punches say, and the other department's files can be set aside.

### When Jibble keeps showing an old position

Jibble can go on showing someone's old position after it's changed, even on punches made since and on days not worked yet. The position filter then picks them by their new position, but every row of the file lists them in the old one. So they end up in their old department's reports. A filtered export can also be refused because of them, and the message names whoever in the old department punched first, not them.

Choosing a different position and then the right one again doesn't fix it. Jibble support's fix, which has worked:

1. In Jibble, open the person, clear their position so they have none, and save.
2. Open the person again, choose the right position, and save.
3. Export again, and check that their rows in `Raw Timesheets` and `Raw Time Entries` show the new position.

If that doesn't work, contact Jibble support. Until it's fixed, add their member code to `member_departments` in the settings file, as described in [The settings file](#the-settings-file). They then get that department's supervisor and schedule, and the PDF shows that department. The validation file lists them with the position Jibble shows. Remove them once Jibble's export is right.

## Who sees what

Each PC's window shows only the steps its user needs, chosen under **Show the steps for** at the bottom and remembered on that PC:

| Choice | Shows |
|---|---|
| Department supervisor | Making the weekly reports from the Jibble file |
| Accounting | Receiving returned files, the payroll files and the agency hours |
| Both | Everything, such as for someone in accounting who also makes the weekly reports. This is what shows until a choice is made |

This only tidies the window. What keeps pay private is where the files are: the accounting settings file and the accounting folder are on a share only accounting can open, so on anyone else's PC those steps can't read them, whatever is chosen.

## Weekly use

**Step 1: process the export.** Open Punch Clock, choose **Make this week's reports**, and select the file. A moving bar shows while the reports are being made, and the week's folder opens when it's ready. In `Supervisor files`, send each supervisor their PDF to print and their Excel file to fill in. Accounting keeps the two `Missing supervisor` files and reviews them.

**Step 2: supervisors review.** In their Excel file, each supervisor:

- Checks each day's **Regular hours**, **Overtime hours** and **Total approved hours**. The total is regular plus overtime.
- Enters any adjustment in minutes, in steps of 15, added to the total approved hours: `15` adds 15 minutes, `-15` removes 15 minutes, and `0` means no change. Regular and overtime hours update by themselves.
- Adds the time for anyone who forgot to punch as an adjustment, for example `300` for 5 hours. Every day of the week has a row, including Saturday and Sunday, so a forgotten weekend shift can be entered too.
- Types the total approved hours as `h:mm` in 15-minute steps on any orange row, where the punches are incomplete.
- Adds comments if needed.

**Step 3: accounting takes over.** Supervisors send their Excel files back to accounting. Accounting receives each one with **Receive returned files...** as it arrives (see [The accounting folder](#the-accounting-folder)), then makes the payroll files once they're all in. Agency staff are paid every two weeks instead: see [Agency payday](#agency-payday).

To correct a punch or a position, fix it in Jibble, export again, and start from step 1.

## The accounting folder

The returned spreadsheets hold everyone's hours, and the payroll and agency files hold who is paid what. So they're kept in one folder that Punch Clock looks after, on a share **only accounting staff can open**, such as the accounting server. The accounting settings file says where it is, with `accounting_folder`. Nobody chooses where a file goes, so files can't be misplaced or kept twice.

```text
<accounting folder>\
    Returned files\
        receipts.csv                           one line for every file received
        Example Co\
            2026-03-02\                         the week's Monday
                Example Co. - Avery Lee - 2026-03-02.xlsx
                Example Co. - Missing supervisor - 2026-03-02.xlsx
                history\                        earlier versions, replaced by a corrected file
                    Example Co. - Avery Lee - 2026-03-02 (replaced 2026-03-10 093012).xlsx
        Second Example Ltd\
            2026-03-02\
                ...
    Payroll files\
        Payroll files EXAMPLE 2026-03-02 to 2026-03-08\
    Agency hours\
        Agency hours 2026-03-02 to 2026-03-15\
```

Punch Clock creates the organization and week folders itself. Only the top folder needs to exist.

**Receiving a returned file.** When a supervisor sends back their Excel file, save the attachment anywhere, such as Downloads, choose **Receive returned files...**, and pick it. Several can be picked at once. Punch Clock:

1. Reads it, and refuses it if it isn't a review spreadsheet, can't be opened, or has had rows moved. Nothing in a batch is kept unless every file in it can be read.
2. Files it under its organization and week, named from what's inside it, so a renamed attachment still lands in the right place.
3. If a file for that supervisor and week was received before, moves the earlier one to `history` and keeps the new one. Receiving the same file twice changes nothing.
4. Writes a line in `receipts.csv`: when, which Windows user, the organization, supervisor and week, and the file's fingerprint (a SHA-256 checksum).
5. Lists anything to fix before payday, such as incomplete punches with no hours typed, or someone the accounting settings file doesn't link to a payroll or an agency. Fix it in the spreadsheet, or ask the supervisor to, and receive it again.

**Making payroll and agency files.** With an accounting folder, the payroll and agency buttons don't ask for a folder. They read the files received for the week or pay period, and make their files under `Payroll files` or `Agency hours`. Before using a file, they check its fingerprint against its receipt. A file that was changed in the accounting folder, or put there by hand, stops the run until it's received again through the app, so what's paid is always what was received.

If the accounting folder can't be reached, Punch Clock says so, and receives and makes nothing. It never keeps a copy on the PC instead, which the other PCs couldn't see.

**Setting it up.** Ask IT for a folder on the accounting server that only accounting staff can open, with read and write access for them and nobody else, and covered by the server's backups. Put the accounting settings file there too, as it holds everyone's payroll and employee numbers, and if possible let only the person who maintains it change it. Then add the folder to the accounting settings file, with each `\` written twice:

```json
"accounting_folder": "\\\\accounting-server\\Punch Clock"
```

Without `accounting_folder` in the accounting settings file, **Receive returned files...** explains what to add, and the payroll and agency buttons ask for a folder instead, and read every returned spreadsheet in it, as below.

## Payroll files

Once every supervisor has sent back their Excel file for the week, accounting makes one PowerPay import file per payroll.

Where each company's accounting makes its own payroll files, `payroll_runs` in the accounting settings file gives each one a button, such as **EXAMPLE Payroll Files...**, that reads only its own organizations' files. Without it there's one **Make the payroll files...** button for every organization.

1. Receive every returned Excel file for the week, as above. Corrections made on paper are typed into the Excel file first, and the file is received again.
2. Pick the week under **Week**, then choose the payroll button. The list has every week with files received, newest first, and starts on the last full week, Monday to Sunday, which is the usual one. Pick an earlier week to make its files again, for example after a correction. A week that isn't over yet says so in the list: its files can be made, for a test or to see the hours so far, with a reminder to make them again once it's over.
3. Punch Clock reads the files received for that week, and writes one `.csv` file per payroll into a new folder under `Payroll files`, with a summary of everyone's hours.

   Without an accounting folder, save every returned file for the week in one folder (folders inside it are fine), and pick it when asked. The files are then made in a new `Payroll files` folder there.
4. In PowerPay, import each file into its payroll's run, with the Employee Timesheet custom import template. **Import first, then key holidays, sick days and vacation:** an import replaces everything already keyed in that run for each person in the file.
5. Check the totals in PowerPay against the summary.

Each line starts with the person's name, so accounting can tell who it is. PowerPay ignores it, and it's written in plain letters, without accents or commas, as the import may not handle them: `ŻAK, ŁUCJA` becomes `ZAK LUCJA`. The summary keeps names as written. Each file has a line of regular hours (earning code `RT`) for each person with hours that week, and a line of overtime (`OT`) for anyone who worked any, as decimals, so 7.75 is 7 hours 45 minutes. Someone with no hours isn't listed, so nothing keyed for them is replaced. Agency staff are left out. A payroll's file can include people from several Jibble organizations.

It stops, and makes nothing, if:

- Anyone in the files isn't linked to a payroll or an agency in the accounting settings file. See [Who pays each employee](#who-pays-each-employee).
- A file in the accounting folder doesn't match its receipt. Receive it again.
- Without an accounting folder: a supervisor's file for the week, or one employee, is in the folder twice. Keep only the returned one.
- Someone paid through a payroll has hours that can't be used yet, such as incomplete punches with no hours typed. The message lists them all. A mistake on an agency person's row doesn't hold up payroll.
- Without an accounting folder: a spreadsheet in the folder with one of the weeks' dates in its name can't be read: it's open in Excel, has a password, was saved as another type such as `.xls`, or is a review file made before 0.11.0. The message says how to fix each.

When it's done, the window and the summary list any supervisor in the settings file with no file for the week, any organization with no files at all, any payroll with no one's hours that week, and any other spreadsheet in the folder that couldn't be opened.

### Setting up the import in PowerPay

This is done once, under **Company > Custom Import**: choose **Add Template**, pick **Employee Timesheet**, comma-delimited with a header row, and upload any file Punch Clock made as the sample. Match `employee_number` to Employee Number, `earning_code` to Earning Code, `hours` to Hours and `applicable_period` to Applicable Period (`1` is one week), and leave the rest unmatched, including `employee_name`. Each payroll run is then imported from **Payroll > Import > Custom Import**, once the run has been created.

## Agency payday

Staffing agencies are paid every two weeks, for two full weeks, Monday to Sunday. On the Wednesday after, accounting sends each agency its people's hours.

1. Make sure every supervisor's returned file for both weeks has been received.
2. Pick the pay period under **Pay period**, then choose **Make the agency hours...**. The list has every pay period with files received, and starts on the last one that has ended. Only real pay periods, counted in two weeks from `period_starts`, are listed.
3. Punch Clock reads the files received for that pay period, and writes one Excel file per agency into a new folder under `Agency hours`. An agency whose people are sent by two companies gets a file from each.

   Without an accounting folder, save every returned file for both weeks in one folder (folders inside it are fine), and pick it when asked. The files are then made in a new `Agency hours` folder there.
4. Check each file. Lunch is charged for each scheduled day worked, at the rate in the settings file. For anyone who didn't buy lunch, change their **Lunch days** under **Detail by week**, or type over their lunch, and the totals follow. Then send it to the agency's email at the top.

Each file starts with a short table of the agency's people, by the name the agency knows them by, with their regular and overtime hours for the two weeks and their lunch. Below it, **Detail by week** shows each week's regular hours, overtime hours and lunch days. Hours are decimals, so 7.75 is 7 hours 45 minutes. Each week's figures are the ones its supervisor approved: overtime is worked out a week at a time, so the two weeks are only added together.

The hours are worked out again from each file, as for payroll, so a correction saved in a file after the first week is included. It stops, and makes nothing, if:

- Without an accounting folder: a supervisor's file for a week, or one employee for a week, is in the folder twice, such as the file as sent and the file as returned. Keep only the returned one.
- Someone with an agency has hours that can't be used yet, such as incomplete punches with no hours typed. The message lists them all. A mistake on a payroll person's row doesn't hold up the agency files.
- Without an accounting folder: a spreadsheet in the folder with one of the weeks' dates in its name can't be read: it's open in Excel, has a password, was saved as another type such as `.xls`, or is a review file made before 0.11.0. The message says how to fix each.

When it's done, the window lists any supervisor in the settings file with no file for a week, anyone the accounting settings file doesn't link to a payroll or an agency, and any other spreadsheet in the folder that couldn't be opened, so they can be checked before the files are sent.

## Who reviews whom

[The settings file](#the-settings-file) says who reviews each department, separately for each organization, so two organizations can each have a `Production` department with different supervisors. A supervisor doesn't need to be in Jibble, and one person can cover several departments, with one PDF and one Excel file for all of them.

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
| Lunch | 30 minutes unpaid per worked day, even if the employee also clocked out that day. It's capped at gross, so net never goes below zero. There's no lunch on [weekend hours](#weekend-hours). |
| Net | Gross minus lunch. |
| Paid | Net by the schedule. Time before the start isn't paid. Arriving up to 5 minutes late counts as on time, so 8:05 AM counts as 8:00 AM on a schedule starting then, and 8:06 AM counts from 8:06 AM. Time under 15 minutes past the scheduled hours isn't paid. Then it's rounded down to a 15-minute block. |
| Total approved hours | Paid, plus the supervisor's adjustment. On an incomplete day, the hours the supervisor typed. Always in 15-minute blocks. |
| Overtime hours | Starts 15 minutes past the employee's scheduled hours, counted from the end of those hours, in 15-minute blocks. On an 8-hour schedule, 8h 22m paid gives 8:00 regular and 0:15 overtime, and 8h 14m gives 8:00 regular and no overtime. All hours on a scheduled day off are overtime. Jibble's overtime isn't used. |
| Regular hours | Total approved hours less overtime hours. |
| Week total | Overtime first makes up any regular hours the week is short of, up to the employee's scheduled week, which is never more than 40:00. With 37:00 regular and 10:00 overtime on a 40-hour schedule, the week shows 40:00 regular and 7:00 overtime. Total approved hours don't change, and each day still shows its own overtime. |
| Punch pairs | Each day's punches are paired in time order, ignoring Jibble's In and Out labels. |
| Incomplete punches | A day with an odd number of punches is missing one. That day's and that week's gross and net show `MISSING` until reviewed. |
| No punches | Shown as `-`, not `0:00`. It doesn't confirm an absence. |

For an 8-hour span with a 20-minute gap, gross is 7:40 and net is 7:10, so 50 minutes are unpaid in total, and 7:00 is approved after rounding down. If the employee's clocked-out time was their lunch, the supervisor can add the 30 minutes back as an adjustment.

On an 8:00 AM to 4:30 PM schedule:

| Punches | Regular hours | Overtime hours | Total approved hours |
|---|---|---|---|
| 8:06 AM to 4:30 PM | 7:45 | 0:00 | 7:45 |
| 8:05 AM to 4:30 PM | 8:00 | 0:00 | 8:00 |
| 8:00 AM to 4:44 PM | 8:00 | 0:00 | 8:00 |
| 8:00 AM to 4:52 PM | 8:00 | 0:15 | 8:15 |
| 8:00 AM to 5:00 PM | 8:00 | 0:30 | 8:30 |

### Weekend hours

In the busy season, some employees come in on days off for a short shift with no lunch. The settings file can give each day off its own hours, for example 7:30 AM to 12:30 PM on Saturday. On a day off with hours set:

- No lunch is deducted.
- Pay follows those hours like any schedule: arriving early isn't paid, up to 5 minutes late counts as on time, and under 15 minutes past the end isn't paid.
- All of it is overtime.

A day off with no hours set works as before: lunch is deducted, hours are paid as worked, and all of it is overtime.

To change the lunch length, grace period, overtime rule, block length or 40-hour week, edit the numbers at the top of [`hours.py`](src/punch_clock/hours.py) and the wording in [`pdf_report.py`](src/punch_clock/pdf_report.py), [`review_workbook.py`](src/punch_clock/review_workbook.py) and [`validation_report.py`](src/punch_clock/validation_report.py).

## The settings files

Nothing about the company's people is in the app or this repository, because both are public. It's in two files, kept apart because different people need them:

| File | Holds | Kept where |
|---|---|---|
| The **settings file** | Each organization's supervisors and work schedules | A shared drive every PC that makes the weekly reports can reach |
| The **accounting settings file** | Who pays each employee, the payrolls and agencies, the payroll buttons and the accounting folder | Somewhere only accounting can open, such as the accounting server |

A department supervisor's PC only ever reads the settings file. Nothing about pay is on it, or copied to it.

**Where each PC finds them.** The app looks for `punch-clock-settings.json` in the user's home folder. To use a file somewhere else, such as on a shared drive, choose **Settings file...** once on each PC, and pick it. A shared drive can have a different letter on each PC, so this is chosen on each one. On accounting PCs, also choose **Accounting settings file...** and pick that file. The app checks each file, then remembers it on that PC, including through updates. The window shows which files it's using.

To change a supervisor, a schedule or who pays someone, edit the file. There's no new version to release, and each PC uses the change the next time it reads the file. Files already sent out don't change.

### The settings file

It has a section for each organization, because organizations can have departments with the same name:

```json
{
  "organizations": {
    "Example Co.": {
      "weekend_schedule": {
        "Sat": { "start": "07:30", "end": "12:30" },
        "Sun": { "start": "07:30", "end": "12:30" }
      },
      "supervisors": { "Assembly": "Avery Lee", "Receiving": "" },
      "department_schedules": {
        "Assembly": { "start": "08:00", "end": "16:30" },
        "Receiving": { "start": "07:00", "end": "17:30", "days": ["Mon", "Tue", "Wed", "Thu"] },
        "Shipping": { "start": "08:00", "end": "16:30", "weekend": { "Sat": { "start": "04:30", "end": "09:30" } } }
      },
      "member_schedules": { "AB-1": { "start": "09:30", "end": "18:00" } },
      "member_departments": { "CD-1": "Receiving" }
    },
    "Second Example Ltd.": {
      "supervisors": { "Assembly": "Morgan Blake" },
      "department_schedules": { "Assembly": { "start": "07:00", "end": "15:30" } },
      "member_schedules": {}
    }
  }
}
```

| Key | Meaning |
|---|---|
| `minimum_version` | Optional, beside `organizations` at the top: `"minimum_version": "0.9.0"`. The oldest version of the app allowed to use this file. See [Keeping every PC on the same rules](#keeping-every-pc-on-the-same-rules) |
| `organizations` | One section per organization, named as Jibble writes it at the top of the export. Capitals and extra spaces don't matter. Each section needs all three keys below, even if they're empty: `{}` |
| `supervisors` | Who reviews each department. Leave a name blank, or the department out, and accounting reviews those employees |
| `department_schedules` | Hours for each department, matched to the Jibble position without any `- Supervisor` ending |
| `member_schedules` | Hours for anyone who differs from their department, by Jibble member code |
| `member_departments` | Optional. The department someone is in, by Jibble member code, whatever their Jibble position says. For someone Jibble still shows in an old position, when [the fix in Jibble](#when-jibble-keeps-showing-an-old-position) hasn't worked. The department must be listed in `supervisors` or `department_schedules`. Needs version 0.10.0, so also set `minimum_version` to `"0.10.0"` |
| `start`, `end` | 24-hour times on the quarter hour (`:00`, `:15`, `:30` or `:45`). The paid hours are the time between them, less the 30-minute lunch |
| `days` | Days worked. Leave it out for Monday to Friday |
| `weekend_schedule` | Optional. Hours for days off, by day name (`Mon` to `Sun`), with a `start` and `end` each. They're used only on a day the person's schedule has off, so `Fri` hours only affect a crew that works Monday to Thursday. See [Weekend hours](#weekend-hours) |
| `weekend` | Optional, on a department or member schedule. Changes the organization's weekend hours one day at a time. Above, Shipping starts at 4:30 AM on Saturday and keeps the organization's Sunday hours. A member schedule replaces the department's, so it starts again from the organization's weekend hours |

Anything to do with pay in this file is refused, with a message saying to move it to the accounting settings file.

### The accounting settings file

It names organizations exactly as the settings file does, but only to say who pays their people:

```json
{
  "organizations": {
    "Example Co.": {
      "employees": {
        "AB-1": { "name": "BROWN, ALEX", "payroll": "Example Payroll", "number": "1042" },
        "CD-1": { "name": "Casey Diaz", "agency": "Example Staffing" }
      },
      "agencies_paid_by": "Example Co. Inc."
    }
  },
  "payrolls": ["Example Payroll", "Second Payroll"],
  "agencies": {
    "Example Staffing": { "legal_name": "1234-5678 Example Inc.", "contact": "hours@example.com" }
  },
  "agency_pay": { "lunch_per_day": 3.00, "period_starts": "2026-03-02" },
  "payroll_runs": { "EXAMPLE": ["Example Co."], "SECOND": ["Second Example Ltd."] },
  "accounting_folder": "\\\\accounting-server\\Punch Clock"
}
```

| Key | Meaning |
|---|---|
| `organizations` | Optional. A section for any organization whose people are listed, spelled as in the settings file |
| `employees` | In an organization's section. Who pays each employee, by Jibble member code. See [Who pays each employee](#who-pays-each-employee) |
| `agencies_paid_by` | In an organization's section. The company that sends its agency staff hours to their agency, as it should appear after FROM. Needed once the organization has anyone with an agency under `employees` |
| `payrolls` | Every payroll named under `employees`, each written once |
| `agencies` | Every staffing agency named under `employees`, each written once, with the `legal_name` and the `contact` email its hours are sent to |
| `agency_pay` | Needed beside `agencies`. `lunch_per_day` is the dollars charged for each scheduled day an agency employee works, as a number. `period_starts` is the Monday any agency pay period started, as `"year-month-day"`. Every period is two weeks from there, so it only changes if the cycle does. See [Agency payday](#agency-payday) |
| `payroll_runs` | Optional. A payroll button for each name, reading only the organizations listed under it. Every organization in the settings file must be in exactly one. A payroll that pays people in two of them gets a file from each, and both are imported. See [Payroll files](#payroll-files) |
| `accounting_folder` | Optional. Where returned files are kept and payroll and agency files are made, with each `\` written twice. See [The accounting folder](#the-accounting-folder) |
| `minimum_version` | Optional, as in the settings file |

Unlike the settings file, it's never copied to the PC: if it can't be reached, receiving files and making payroll and agency files stop, and say so. The weekly reports don't need it.

**Settings files from before the split.** A file that holds both is refused, saying what to move. To split one, run `punch-clock --split-settings <file>`. It writes `<name> shared.json` and `<name> accounting.json` beside it, and never writes over a file that's already there. Check both, put each where it belongs, and choose them in the app.

Someone with no schedule is paid as worked, with overtime starting at 8:15.

### Who pays each employee

Some employees are on a different company's books from the organization they punch in, and some are employed through a staffing agency. So the accounting settings file says who pays each person, one by one, under `employees` in the section for the organization they punch in:

- **Through a payroll:** `name`, `payroll` and `number`. The number is their employee number in that payroll, in quotes. Numbers only need to be unique within a payroll, but one number can't be given to two people in the same payroll anywhere in the file.

  **Someone who moves organization or payroll** needs their links changed in a set order, so that older weeks still go where they were paid. See [When someone changes payroll or organization](#when-someone-changes-payroll-or-organization).
- **Through an agency:** `name` and `agency`. The agency is sent their hours and bills for them.

`name` is the person's name as the payroll or agency knows them, which can differ from Jibble's. Each payroll and agency must also be listed in `payrolls` or `agencies` at the top of the file, so a misspelled one is refused instead of being treated as a new one. Each agency is listed with where its hours go, and an organization with anyone from an agency says, in `agencies_paid_by`, which company sends them. That doesn't depend on where people punch: two organizations can name the same company.

Once anyone is listed, the window and the Validation file name everyone in the reports who isn't, so a new hire can be added before payday. These links decide who goes in each [payroll file](#payroll-files) and in each agency's file on [Agency payday](#agency-payday).

Set `minimum_version` to `"0.11.0"` when adding them, as older versions refuse a file with them.

An export from an organization with no section of its own is refused, with a message giving its name exactly as the export spells it, so it never gets another organization's supervisors or hours. To process it, add a section with that name. Settings files from before version 0.6.0 have no sections. The app refuses them and says how to fix them: put the existing `supervisors`, `department_schedules` and `member_schedules` inside a section named for their organization.

The app reads the settings file each time someone makes reports or payroll or agency files, and when the window opens, to show the right buttons. It doesn't touch the drive at any other time. It copies each good read of the settings file, never the accounting one, to `%APPDATA%\Punch Clock\saved-settings.json`, and remembers both files' locations beside it.

| What happens | What the app does |
|---|---|
| The file can't be reached within 5 seconds | Uses the saved copy, and says so on the screen and in the PDFs, Excel files and Validation file |
| It can't be reached, and this PC has no saved copy | Stops with a plain message |
| The file has a mistake in it | Stops with a plain message, and keeps the saved copy as it was |
| The file needs a newer version of the app | Stops, and says to update |

### When someone changes payroll or organization

Each Jibble member code has one link, and the app reads the links each time it makes files. So a change applies the next time files are made. Files already made or imported don't change.

The week is picked in the window, and the links are read as they are when the files are made, whichever week it is. So a week made again after a link has changed uses the new link. Making the same week again creates a new folder ending in `(2)`.

**Same organization, new payroll.** Say LEE, AVERY moves from Main Payroll to Second Payroll and keeps the same Jibble code, `AL-1`.

1. Make the files for the last week paid through the old payroll, and import them into that payroll in PowerPay.
2. Before the first week in the new payroll, change the link in the accounting settings file. Both payrolls must be listed under `payrolls`:

   ```json
   "employees": {
     "AL-1": { "name": "LEE, AVERY", "payroll": "Second Payroll", "number": "2210" }
   }
   ```

3. Choose **Settings file...** and pick the file, to check it.
4. Don't make files again for a week paid through the old payroll. If one is made again, its hours go to the new payroll. Enter that week's hours in the old payroll in PowerPay by hand.

**Different organization and different payroll.** Say LEE moves to Second Example Ltd. and gets a new code, `BX-7`, paid through Second Payroll as number `2210`.

1. Add the new code under the new organization, with its payroll and number.
2. Keep the old code under the old organization, still paid through Main Payroll as `1042`. Older weeks still go there. Only remove it once no week you might make again has hours under it.

   ```json
   "Example Co.": {
     "employees": {
       "AL-1": { "name": "LEE, AVERY", "payroll": "Main Payroll", "number": "1042" }
     }
   },
   "Second Example Ltd.": {
     "employees": {
       "BX-7": { "name": "LEE, AVERY", "payroll": "Second Payroll", "number": "2210" }
     }
   }
   ```

The two numbers are in different payrolls, so there's no clash.

**Different organization, same payroll.** Say LEE moves to Second Example Ltd. but stays in Main Payroll as `1042`. Add the new code under the new organization, with the same payroll, number and name, and keep the old code too. The same number is allowed under two codes only when the name is the same.

- If LEE has hours under both codes in the same week, the payroll file leaves LEE out, and the window and the summary say so. Enter that week's hours in PowerPay by hand, after the import.
- This check only sees the files of one payroll button. If the two organizations have different payroll buttons, it can't see the other one's files, so it doesn't warn. In that case, check both summaries for the same week before importing. If LEE is in both, stop and ask before importing, as the second import would replace the first.

**Agency and payroll.** Agency staff are paid every two weeks by the agency, and they're left out of the payroll files. To move someone from an agency to a payroll, replace their `agency` with `payroll` and `number`. The file refuses a person with both. Moving back works the same way in reverse.

- Make the change between pay periods: after an agency period's hours have been sent, and before the first payroll week. Each agency period is two weeks, starting on the Monday in `agency_pay`.
- Agency hours for a period are read with the links as they are when the agency files are made. So if the change happens in the middle of a period:
  - Agency to payroll: the person drops out of that period's agency file, for both weeks and with no warning. The first week's hours then aren't sent to the agency, so enter them by hand.
  - Payroll to agency: the agency file includes both weeks, including any already paid through payroll. Take those weeks out of the agency file by hand, to avoid paying them twice.

**Payroll buttons.** Each payroll button reads the files of its own organizations. So a file is made by the button of the organization the person punches in, under the new code, even if the payroll belongs to another company. If that payroll is also paid by another button, the summary says to import that file too. Check with the other company before importing it.

### Mistakes in the file

The file is edited by hand, so the app checks all of it each time and refuses it rather than guess. The message says where the mistake is and how to fix it:

- A missing or extra comma, quote mark or bracket, with the line it's on.
- A setting the app doesn't know, such as `day` for `days`. It's never ignored, because a misspelled setting would quietly change someone's pay.
- A missing section, a time or day that can't be read, an end that isn't after its start, or a schedule that leaves no paid hours after lunch.
- A department in `member_departments` that isn't listed in `supervisors` or `department_schedules`, as a misspelling would give that person the wrong hours.
- A payroll or agency under `employees` that isn't listed at the top, an employee number that isn't all digits, someone linked to both a payroll and an agency, or one employee number given to two people, with different names, in the same payroll.
- The same organization, department or member code twice.

Capitals don't matter in department names and member codes, and neither does a space before or after them.

To check the file after editing it, choose **Settings file...** and pick it again.

### Keeping every PC on the same rules

Every PC reads the same file, but each one updates when its user agrees to. An older copy of the app doesn't know about settings added since. So when you start using a newer setting, or want every PC on a newer version's rules, put that version at the top of the file:

```json
{
  "minimum_version": "0.9.0",
  "organizations": { }
}
```

A PC with an older version then stops and asks to be updated, instead of making reports that differ from everyone else's. This works from version 0.9.0. Earlier versions ignore it.

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
- Conflicting names or positions for one member code, unless `member_departments` in the settings file sets their department
- Punches from someone missing from the other sheets when their department is in the file
- Unknown entry types
- Mixed timezones
- Anything other than one Monday to Sunday week
- No organization name, or one with no section in the settings file
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
| `review_workbook.py` | Writes each supervisor's spreadsheet, with a very hidden sheet recording who each row is |
| `approved_hours.py` | Reads a returned spreadsheet and works its approved hours out again, listing anything that stops them being used |
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
