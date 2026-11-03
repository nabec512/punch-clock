"""Plain-text validation record saved beside each PDF."""
from __future__ import annotations

from punch_clock.assignments import departments_without_supervisor, review_groups
from punch_clock.hours import format_minutes, weekly_total
from punch_clock.jibble_export import ENTRIES, TIMESHEETS, WeeklyExport


def build_validation_text(export: WeeklyExport) -> str:
    included = export.included
    excluded = ", ".join(f"{e.name} / {e.code}" for e in export.excluded) or "None"
    included_payroll = weekly_total(e.total("Payroll Hours") for e in included)
    lines = [
        "Weekly timesheet report - validation record",
        export.period,
        f"Source: {export.source_name}",
        f"SHA-256: {export.sha256}",
        "",
        "REPORT SELECTION",
        f"Included: {len(included)} employees with nonblank positions.",
        "Sort: department A-Z, then employee name A-Z (case-insensitive).",
        f"Excluded (blank position): {excluded}",
        f"Included payroll total: {format_minutes(included_payroll)}",
        "Source reconciliation below covers the entire export, before filtering.",
        "",
        f"Employees: {len(export.employees)}",
        f"{TIMESHEETS}: {export.timesheet_rows} data rows; {export.column_counts[TIMESHEETS]} columns",
        f"{ENTRIES}: {export.entry_rows} event rows; {export.column_counts[ENTRIES]} columns",
        "",
        "MAPPING",
        "Employee identity = Member Code, cross-checked to name and Team Summary roster.",
        f"Position = {TIMESHEETS} Position, checked for consistency across days. "
        'Department = position without a trailing "- Supervisor" tag.',
        f"Start / end = {TIMESHEETS} First In / Last Out; checked against raw events and individual summaries.",
        "Break events are not supported: the fixed lunch replaces Jibble break tracking, "
        "so exports containing them are rejected.",
        "Gross = sum of In/Out sessions rounded once per day to the nearest minute.",
        "Net = gross minus min(remaining lunch, gross) on worked days. Remaining lunch = 30 minutes less "
        "that day's clocked-out gaps, added and rounded once to the nearest minute.",
        "Incomplete sequences remain unavailable. Source payroll checks below retain Jibble values.",
        "Overtime = Daily OT + Daily Double OT + Weekly OT + Rest Day OT + Public Holiday OT.",
        "Zero is preserved. Blank duration propagates as MISSING, never zero. NR means no timestamp.",
        "Times are displayed in the source timezone with seconds; no schedule times are substituted.",
        "Team Summary dash is interpreted as zero only for reconciliation.",
        "",
        "RECONCILIATION (hours:minutes)",
    ]
    for check in export.checks:
        status = "PASS" if check.match else "REVIEW"
        lines.append(
            f"{status}: {check.label}: {format_minutes(check.calculated)} vs {format_minutes(check.source)}"
        )
    lines += ["", "DAILY HOURS (included employees, days with punches)"]
    for employee in included:
        for day in export.dates:
            record = employee.days[day]
            if record.punches:
                hours = record.hours
                lines.append(
                    f"{employee.code} {day}: gross {format_minutes(hours.gross)}, "
                    f"lunch {format_minutes(hours.lunch)}, net {format_minutes(hours.net)}"
                )
    lines += ["", "REVIEW FILES"]
    for group in review_groups(export):
        lines.append(f"{group.title}: {len(group.employees)} employees")
    lines.append(f"Departments with no tagged supervisor: {', '.join(departments_without_supervisor(export)) or 'None'}")
    lines.append("Supervisors review their own hours along with their department's.")
    lines += ["", "EMPLOYEE NOTES"]
    for employee in export.employees:
        lines.append(f"{employee.name} / {employee.code} / {employee.position or 'MISSING POSITION'}")
        lines.extend(f"  {note}" for note in employee.notes)
        for day in export.dates:
            record = employee.days[day]
            lines.extend(f"  {day}, {TIMESHEETS} row {record.row}: {issue}" for issue in record.issues)
    lines += [
        "",
        "LIMITS",
        "Supports the detailed weekly XLSX layout and the hours/minutes duration format.",
        "Unknown entry types, ambiguous identity, duplicate daily rows, mixed timezones, unexpected "
        "durations and page overflow stop generation.",
        "Employees with a blank position are excluded from employee pages and included totals. "
        "Source validation still covers all employees.",
        "Jibble overtime remains unchanged.",
        "The workbook was read only; the original export is unchanged.",
    ]
    return "\n".join(lines) + "\n"
