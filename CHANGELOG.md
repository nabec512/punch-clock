# Changelog

## 0.11.0

The first part of preparing hours for payroll and for staffing agencies.
- The settings file can say who pays each employee, under `employees` in their organization's section: a payroll with their employee number there, or a staffing agency. This follows the company on the books, not the organization they punch in. Every payroll and agency is also listed once in `payrolls` and `agencies` at the top of the file, so a misspelled one is refused. The README explains this under "Who pays each employee".
- Mistakes are refused with a plain message, including an employee number that isn't all digits, someone linked to both a payroll and an agency, and one employee number given to two people in the same payroll anywhere in the file. The same number can be given to two member codes with the same name, for someone who moved organization: the payroll file leaves them out, to be entered by hand, only if both codes have hours in one week.
- Once anyone is linked, the window and the Validation file name everyone in the reports who isn't, so they can be added before payday. The payroll and agency files below use these links.
- Each review spreadsheet now has a hidden sheet that records each employee's member code and the figures their rows were built from. Supervisors don't see it, and the spreadsheet works as before. It lets Punch Clock read the approved hours back from a returned spreadsheet, working them out again from the adjustments and typed hours rather than trusting the totals, and listing anything that stops them being used, such as an adjustment that isn't in 15-minute steps or a locked cell typed over. Only spreadsheets made by this version or later can be read back.
- **Payroll files, every week.** The new **Make the payroll files...** button reads every supervisor's returned review file in a folder from the last full week, and writes one PowerPay Employee Timesheet import file per payroll: regular hours as `RT` and overtime as `OT`, for everyone with hours that week, plus a summary to check the totals against PowerPay. Agency staff are left out. Anyone not linked to a payroll or an agency, a file found twice, or a file with payroll staff whose hours can't be used yet, stops it with a plain message. The README explains it under "Payroll files", with the one-time setup in PowerPay.
- **Agency hours, every two weeks.** The new **Make the agency hours...** button reads every supervisor's returned review file in a folder from the last two-week agency pay period that has ended, and writes one Excel file per agency for accounting to send: each person's regular and overtime hours for each week, the two-week totals, and lunch at a rate per scheduled day worked. Lunch and the totals are formulas, so accounting can change someone's lunch days before sending. A file found twice, or a file with agency staff whose hours can't be used yet, stops it with a plain message. The README explains it under "Agency payday".
- In the settings file, each agency in `agencies` is listed with the `legal_name` and `contact` email its hours are sent to, `agency_pay` holds `lunch_per_day` and `period_starts`, and each organization with agency staff has `agencies_paid_by`, the company that sends their hours.
- **Set `"minimum_version": "0.11.0"` in the settings file when adding `employees`, `payrolls`, `agencies` or `agency_pay`.** Older versions refuse a file with them.

## 0.10.1

Makes the review spreadsheet easier to read.
- Each employee's section now starts with a shaded row showing their name and department, and there's an empty row between employees. Before, the bold name on the Week total row looked like a heading for the next employee's days.
- The Regular hours, Overtime hours and Total approved hours cells on each Week total row are now purple, so accounting can find them quickly. A day's overtime is still green.

## 0.10.0

- The settings file can put someone in a department whatever their Jibble position says, with `"member_departments": { "AB-1": "Shipping" }` in an organization's section. This is for someone Jibble still shows in their old position after it's changed, when the fix in Jibble hasn't worked: clear their position and save, then open them again and choose the new one. The README explains this under "When Jibble keeps showing an old position". They get that department's supervisor and schedule, and a position filter on that department no longer refuses the file because of them. The PDF shows the department, and the validation file lists them with the position Jibble shows. The department must be one listed in `supervisors` or `department_schedules`.
- For someone in `member_departments`, a position that changes during the week no longer stops the run.
- **Set `"minimum_version": "0.10.0"` in the settings file when adding `member_departments`.** Older versions refuse a file with it.

## 0.9.0

Catches mistakes in the settings file instead of ignoring them, and shows that the reports are being made.
- **A setting the app doesn't know is now refused.** Before, a misspelled one was ignored without a word: `day` instead of `days` paid a Monday to Thursday crew as Monday to Friday. The message names the setting and lists the ones that can go there. Check the settings file after installing this version, as a file with such a mistake was accepted until now.
- Mistakes in the settings file are explained in plain words: which line a missing comma or bracket is on, which section is missing, or which time or day can't be read.
- A schedule that leaves no paid hours after lunch, or that lists no days, is refused.
- A space typed before or after a department or member code no longer stops it matching.
- The settings file can name the oldest version of the app allowed to use it, with `"minimum_version": "0.9.0"`. An older copy then asks to be updated instead of making reports without settings it doesn't know. Versions before this one ignore it.
- The window shows a moving bar and a message while the reports are being made, instead of freezing.
- An unexpected error while downloading an update no longer leaves the window stuck on "Downloading the update".

## 0.8.1

- Overtime now makes up a short week. When an employee's regular hours for the week come to less than their scheduled week, which is never more than 40:00, overtime fills the gap first. For example, someone who leaves early on Thursday after staying late on other days, with 37:00 regular and 10:00 overtime, now has 40:00 regular and 7:00 overtime for the week. Total approved hours don't change.
- This applies to the week total in the review spreadsheet, where it updates with adjustments and typed hours, and in the PDF. Each day still shows its own overtime, and a note on the week total says how much overtime was counted as regular hours.

## 0.8.0

Weekend hours, 15-minute blocks and clearer hour columns, after the first week of supervisor reviews.
- Hours are paid in 15-minute blocks, always rounded down, so supervisors no longer adjust a few minutes at a time. Overtime is still measured against each employee's own schedule: on an 8-hour day, 8h 22m gives 8:00 regular and 0:15 overtime, and an 8:06 AM arrival gives 7:45. Adjustments and typed hours go in steps of 15 minutes.
- The review spreadsheet and PDF now show **Regular hours**, **Overtime hours** and **Total approved hours** on each day and on the week's total, instead of approved hours that included overtime.
- Weekend hours: each organization in the settings file can set hours for days off, such as Saturday and Sunday from 7:30 AM to 12:30 PM, and a department or member can change them a day at a time. On those days no lunch is deducted, pay follows those hours, and all of it is overtime. Without them, a day off works as before.
- Every day of the week now has a row, including Saturday and Sunday without punches, so a forgotten weekend shift can be entered as an adjustment.
- The instructions at the top of the review spreadsheet no longer stay on screen when scrolling. Only the employee column stays fixed.
- **Schedule times in the settings file must now be on the quarter hour** (`:00`, `:15`, `:30` or `:45`). A file with other times is refused with a message naming the time.

## 0.7.0

Explains what to do when someone's position changed during the week.
- Jibble's position filter picks people by their position now, but each punch keeps the position the person had when they made it. So in the week someone changes position, an export filtered on their old department leaves them out of everything except their punches. The app still refuses that file, so their hours aren't lost, but the message now names the person and says to export again with their new position selected as well.

## 0.6.0

Works for more than one organization, without mixing up their supervisors and schedules.
- The settings file now has a section for each organization, named as Jibble writes it at the top of the export. Two organizations can each have a department with the same name, such as `Production`, with different supervisors and hours. Before, an export from one organization could be given another one's supervisor and schedule.
- **The settings file must be changed to the new layout when this version is installed.** Move the existing `supervisors`, `department_schedules` and `member_schedules` into a section under `organizations` named for that organization. The app refuses a file in the old layout and says how to fix it.
- An export from an organization with no section in the settings file is refused, with a message giving the name to add.
- The week's folder and each supervisor's files now start with the organization's name, so each organization's reports for a week can sit side by side.

## 0.5.0

Lets each supervisor export just their own departments, and shows departments in the review spreadsheet.
- An export filtered by position in Jibble can now be used, so each supervisor can export just their own departments. Jibble still lists everyone's punches in it, so the app skips punches from departments the rest of the file leaves out, and the validation file says how many.
- Each row of the review spreadsheet now shows the employee's department after their name, for example `Sam Ortiz - Assembly`.

## 0.4.0

Handles forgotten punches, pays by work schedules, and moves supervisors and schedules out of the app.
- A forgotten punch no longer skews the week: each day's punches are paired in time order, and a day with an odd number of punches asks for the hours.
- Pay follows each department's or person's schedule: time before the start isn't paid, arriving up to 5 minutes late counts as on time, and under 15 minutes past the end of the day isn't paid.
- Overtime is worked out by the app instead of coming from Jibble. It starts 15 minutes past the scheduled hours, and all hours on a scheduled day off are overtime.
- Supervisors and schedules now come from one settings file outside the app, read once each time reports are made. The app looks in the home folder, and **Settings file...** points each PC to another location. This replaces the Supervisors window, so **the settings file must be set up before the first reports on each PC**.
- If the settings file can't be reached, the app uses its last saved copy and says so on the reports.
- Test accounts are left out of the reports.

## 0.3.0 

Adds the auto-updater to the app
- Uses the public github artefacts to auto-update the app if there is a newer version available.

## 0.2.0 

Second release.
- Simplification of the application and excel 
- Split view of pdf and excel per supervisor
- Ability to set the supervisor of each dept in the app instead of relying on the `- Supervisor` tag.

## 0.1.0

First packaged release.

- Printable PDF with a department headcount page and every In/Out pair per employee.
- Gross, lunch and net hours. Clocked-out gaps count toward the 30-minute lunch.
- A dated output folder for each export, which is never overwritten.
- A protected review spreadsheet for each supervisor, assigned from the `- Supervisor` position tag.
- An approved report and hours summary built from the returned spreadsheets.
- Validation file comparing calculated hours with Jibble's own totals.
- Windows app and per-user installer that don't need Python.
