# Changelog

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
