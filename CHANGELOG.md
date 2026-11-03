# Changelog

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
