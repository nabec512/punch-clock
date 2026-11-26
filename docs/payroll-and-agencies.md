# Payroll and agency hours: plan and progress

Punch Clock makes each week's supervisor reports. The next step takes the hours the supervisors approved and prepares them for whoever pays each employee, so accounting no longer types them in by hand. This page records what has been decided, what's done, and what's next. Real names, companies and numbers stay in the private settings file, never here.

## How people are paid

- Most employees are paid weekly through payroll in PowerPay. Their approved hours will go in a file imported into PowerPay.
- Some are employed through staffing agencies and paid **every two weeks**. The company sends each agency its people's hours, and the agency bills for them.
- Where someone punches and who pays them are separate. The Jibble organization and position decide their supervisor and schedule, as they do now. The company on the books decides their payroll, and it can be a different company. So each employee is linked one by one, with no default for an organization.
- Employee numbers are only unique within one payroll, and an import replaces the hours of each employee it lists. So there's one complete import file per payroll, and it can include people from several Jibble organizations.
- Each employee punches in one Jibble organization. Someone who moves is taken out of the old one, so their hours are never in two exports.

## Done

**0.11.0: the settings file says who pays each employee.** Under `employees` in each organization's section, each member code has either a payroll and employee number, or an agency. The payrolls and agencies are listed at the top of the file. The README explains the layout under "Who pays each employee". Once anyone is linked, every report run names the employees who aren't yet, so they can be added before payday.

**0.11.0: approved hours can be read back from a returned review spreadsheet** (`approved_hours.py`).
- Each review spreadsheet carries a very hidden sheet with every row's member code and the fixed figures its formulas were built from. So a returned file says who each row is without relying on names, which aren't unique.
- The reader takes only what a supervisor can change: adjustments, hours typed for incomplete punches, Reviewed and comments. It works each day and week out again with the same rules as the rest of the app. Where the file holds Excel's own results, they must agree.
- Anything that stops an employee's hours being used is listed in plain words, for the whole file at once: incomplete punches with no hours typed, an adjustment that isn't in 15-minute steps or would go below zero, typed hours that aren't a length of time, and a locked cell that was typed over. Whether each employee is marked Reviewed is reported separately, and it's up to the step that uses the file what to do about it.
- A file that isn't a review file, whose rows were moved, or that was made before 0.11.0, is refused.
- Checked with real Excel: a file edited and saved in Excel, with an adjustment, typed hours and Reviewed set, reads back with the same totals Excel shows and no problems.

**0.11.0: agency hours every two weeks** (`agency_hours.py`, `agency_workbook.py`, the **Make the agency hours...** button).
- Modelled on the spreadsheet accounting already sends: the agency's company name and email (TO), the company sending the hours (FROM), and a row per person. A short table gives each person's two-week regular hours, overtime hours and lunch, and a detail by week below it gives each week's regular hours, overtime hours and lunch days, with weeks labelled by their Monday. Accounting found that clearer than one wide row per person. It's an Excel file, as accounting uses Excel.
- Accounting picks one folder, and every review file in it or below it from the last pay period that has ended is read again. This settles where approved files are kept for agencies: anywhere, as long as both weeks are in one folder. A file found twice is refused, as is a file with agency staff whose hours can't be used yet. Supervisors with a file for only one week, anyone not marked Reviewed, and anyone not linked are listed when it's done.
- One file per agency for each company sending hours. That's set per organization (`agencies_paid_by`), not by where people punch, because one company pays the agency staff of several organizations.
- Lunch is charged per scheduled day worked, at `agency_pay.lunch_per_day`, which can change from year to year. Weekend hours on a day off have no lunch. Lunch is optional for employees, so accounting changes the lunch days before sending. The amount and the totals are formulas, checked in real Excel.
- The cycle is counted in two-week steps from `agency_pay.period_starts`. Each period is processed on the Wednesday after it ends. The real starting Monday is only in the private settings file.

## Waiting on

- **The PowerPay import layout.** One example import file or template, the pay codes for regular and overtime hours, and how dates and the pay period are written. The import file can't be written until this is known.

## Next

1. **Gather a week's returned files.** Find every returned review spreadsheet for one week from each Jibble organization, check that none is missing or included twice, and read them all with `approved_hours`. Corrections made on paper are typed into the spreadsheet first, so there's one kind of input. This needs the decision on where approved files are kept.
2. **Weekly payroll files.** A new button takes one week's approved files from every Jibble organization, checks they're all there and all the same week, and writes one import file per payroll. An employee with no link stops it, and agency employees are left out. A short summary gives the totals per payroll, so accounting can check them.
3. **Run alongside the manual process** for a few weeks, and compare the results with what accounting entered, before relying on it.

## Still to decide

- Where approved supervisor files are kept for payroll. The agency step only needs both weeks in one folder.
- How holidays, vacation and sick days for hourly staff are handled: they aren't in Jibble's punches.
