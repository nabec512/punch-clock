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

## Waiting on

- **The PowerPay import layout.** One example import file or template, the pay codes for regular and overtime hours, and how dates and the pay period are written. The import file can't be written until this is known.
- **The agency pay cycle.** Agencies share one two-week cycle, processed every second Wednesday. The plan is to count from one known period in the settings file, so it needs a real date, and confirmation that each period is two Monday-to-Sunday weeks.

## Next

1. **Read the approved hours back.** The step reads each returned supervisor workbook and works the totals out again with the same rules, rather than trusting what Excel last saved, and stops if they disagree. Corrections made on paper are typed into the workbook first, so there's one kind of input.
2. **Weekly payroll files.** A new button takes one week's approved files from every Jibble organization, checks they're all there and all the same week, and writes one import file per payroll. An employee with no link stops it, and agency employees are left out. A short summary gives the totals per payroll, so accounting can check them.
3. **Agency reports, every two weeks.** A separate button reads the approved files for both weeks of the agency pay period and writes one report per agency: each person's name, regular hours, overtime hours and the period's dates. Each total is the sum of the two weeks' own figures, as overtime is worked out a week at a time. Nothing is cached between weeks: the approved files are read again, so a correction made after the first week is included.
4. **Run alongside the manual process** for a few weeks, and compare the results with what accounting entered, before relying on it.

## Still to decide

- Where approved supervisor files are kept, so that every PC can find both weeks of an agency period.
- Whether agency reports are PDFs, Excel files or both.
- How holidays, vacation and sick days for hourly staff are handled: they aren't in Jibble's punches.
