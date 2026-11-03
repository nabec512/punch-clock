"""Accounting's summary of approved hours, written after the review files come back."""
from __future__ import annotations

from datetime import datetime, time
from pathlib import Path
from typing import Optional

import xlsxwriter

from punch_clock.approvals import ApprovalSet
from punch_clock.hours import weekly_total
from punch_clock.jibble_export import WeeklyExport


def write_summary_workbook(export: WeeklyExport, approvals: ApprovalSet, path: str | Path) -> None:
    workbook = xlsxwriter.Workbook(str(path), {"remove_timezone": True})
    workbook.set_properties({"title": f"Approved hours {export.start}", "author": "", "comments": ""})
    formats = {
        "title": workbook.add_format({"bold": True, "font_size": 14}),
        "note": workbook.add_format({"font_color": "#52616A"}),
        "warn": workbook.add_format({"bold": True, "font_color": "#8B4B09"}),
        "header": workbook.add_format({"bold": True, "bg_color": "#183340", "font_color": "#FFFFFF", "text_wrap": True, "valign": "vcenter"}),
        "text": workbook.add_format({"valign": "top"}),
        "wrap": workbook.add_format({"valign": "top", "text_wrap": True}),
        "hours": workbook.add_format({"num_format": "[h]:mm", "align": "right", "valign": "top"}),
        "decimal": workbook.add_format({"num_format": "0.00", "align": "right", "valign": "top"}),
        "number": workbook.add_format({"num_format": "+0;-0;0", "align": "right", "valign": "top"}),
        "count": workbook.add_format({"num_format": "0", "align": "right", "valign": "top"}),
        "date": workbook.add_format({"num_format": "ddd mmm d", "align": "left", "valign": "top"}),
        "total": workbook.add_format({"bold": True, "top": 1}),
        "total_hours": workbook.add_format({"bold": True, "top": 1, "num_format": "[h]:mm", "align": "right"}),
        "total_count": workbook.add_format({"bold": True, "top": 1, "num_format": "0", "align": "right"}),
    }
    _summary_sheet(workbook, formats, export, approvals)
    _employee_sheet(workbook, formats, export, approvals)
    _adjustment_sheet(workbook, formats, export, approvals)
    workbook.close()


def _write_hours(sheet, row, column, minutes: Optional[int], formats, key="hours") -> None:
    if minutes is None:
        sheet.write(row, column, "MISSING", formats[key])
    else:
        sheet.write_number(row, column, minutes / 1440, formats[key])


def _weekly(employee, attribute: str) -> Optional[int]:
    return weekly_total(getattr(record.hours, attribute) for record in employee.days.values())


def _summary_sheet(workbook, formats, export, approvals: ApprovalSet) -> None:
    sheet = workbook.add_worksheet("Summary")
    sheet.write(0, 0, f"{export.company or 'Weekly'} hours summary", formats["title"])
    sheet.write(1, 0, export.period, formats["note"])
    outstanding = len(approvals.not_reviewed)
    if approvals.is_final:
        sheet.write(2, 0, "All employees are reviewed.", formats["note"])
    else:
        sheet.write(2, 0, f"PROVISIONAL: {outstanding} of {len(approvals.employees)} employees aren't reviewed yet.", formats["warn"])
    labels = ["Department", "Employees", "With punches", "Gross", "Net", "Adjustments (min)", "Approved", "Not reviewed"]
    for column, label in enumerate(labels):
        sheet.write(4, column, label, formats["header"])
        sheet.set_column(column, column, 26 if column == 0 else 12)
    departments: dict[str, list] = {}
    for approval in approvals.employees.values():
        employee = approval.employee
        departments.setdefault(employee.department.casefold(), []).append(approval)
    row = 5
    all_members = []
    for key in sorted(departments):
        members = departments[key]
        all_members += members
        _summary_row(sheet, row, members[0].employee.department, members, formats, "text", "count", "hours")
        row += 1
    _summary_row(sheet, row, "Total", all_members, formats, "total", "total_count", "total_hours")
    if approvals.missing_files:
        sheet.write(row + 2, 0, "Review files not found: " + ", ".join(approvals.missing_files), formats["warn"])


def _summary_row(sheet, row, label, members, formats, text, count, hours) -> None:
    sheet.write(row, 0, label, formats[text])
    sheet.write_number(row, 1, len(members), formats[count])
    sheet.write_number(row, 2, sum(m.employee.has_punches for m in members), formats[count])
    _write_hours(sheet, row, 3, weekly_total(_weekly(m.employee, "gross") for m in members), formats, hours)
    _write_hours(sheet, row, 4, weekly_total(_weekly(m.employee, "net") for m in members), formats, hours)
    sheet.write_number(row, 5, sum(m.adjustment_total for m in members), formats[count])
    _write_hours(sheet, row, 6, weekly_total(m.approved for m in members), formats, hours)
    sheet.write_number(row, 7, sum(not m.reviewed for m in members), formats[count])


def _employee_sheet(workbook, formats, export, approvals: ApprovalSet) -> None:
    sheet = workbook.add_worksheet("Employees")
    columns = [
        ("Department", 20), ("Employee", 26), ("Member code", 10), ("Position", 24), ("Review file", 30),
        ("Gross", 9), ("Lunch", 9), ("Net", 9), ("Adjustments (min)", 12), ("Approved", 10), ("Approved (decimal)", 10),
        ("Jibble payroll", 9), ("Jibble overtime", 9), ("Reviewed", 9), ("Notes", 50),
    ]
    for column, (label, width) in enumerate(columns):
        sheet.write(0, column, label, formats["header"])
        sheet.set_column(column, column, width)
    row = 0
    for employee in export.included:
        row += 1
        approval = approvals.employees[employee.code]
        sheet.write(row, 0, employee.department, formats["text"])
        sheet.write(row, 1, employee.name, formats["text"])
        sheet.write(row, 2, employee.code, formats["text"])
        sheet.write(row, 3, employee.position, formats["text"])
        sheet.write(row, 4, approval.reviewed_in or "Not found", formats["text"])
        _write_hours(sheet, row, 5, _weekly(employee, "gross"), formats)
        _write_hours(sheet, row, 6, _weekly(employee, "lunch"), formats)
        _write_hours(sheet, row, 7, _weekly(employee, "net"), formats)
        sheet.write_number(row, 8, approval.adjustment_total, formats["number"])
        _write_hours(sheet, row, 9, approval.approved, formats)
        if approval.approved is None:
            sheet.write(row, 10, "MISSING", formats["decimal"])
        else:
            sheet.write_number(row, 10, round(approval.approved / 60, 2), formats["decimal"])
        _write_hours(sheet, row, 11, employee.total("Payroll Hours"), formats)
        _write_hours(sheet, row, 12, employee.overtime, formats)
        sheet.write(row, 13, "Yes" if approval.reviewed else "No", formats["text"])
        sheet.write(row, 14, _notes(export, approval), formats["wrap"])
    sheet.autofilter(0, 0, max(row, 0), len(columns) - 1)
    sheet.freeze_panes(1, 2)


def _notes(export, approval) -> str:
    notes = [*approval.problems]
    for day in export.dates:
        entry = approval.days[day]
        notes += [f"{day:%a}: {problem}" for problem in entry.problems]
        if entry.unresolved:
            notes.append(f"{day:%a}: approved hours are needed.")
    return " ".join(dict.fromkeys(notes))


def _adjustment_sheet(workbook, formats, export, approvals: ApprovalSet) -> None:
    """Every change and comment a supervisor made, for the audit trail."""
    sheet = workbook.add_worksheet("Adjustments")
    columns = [
        ("Employee", 26), ("Member code", 10), ("Date", 12), ("Net", 9), ("Adjustment (min)", 11),
        ("Typed hours", 9), ("Approved", 10), ("Comment", 60), ("Review file", 30),
    ]
    for column, (label, width) in enumerate(columns):
        sheet.write(0, column, label, formats["header"])
        sheet.set_column(column, column, width)
    row = 0
    for employee in export.included:
        approval = approvals.employees[employee.code]
        for day in export.dates:
            entry = approval.days[day]
            if not entry.input.has_input:
                continue
            row += 1
            hours = employee.days[day].hours
            sheet.write(row, 0, employee.name, formats["text"])
            sheet.write(row, 1, employee.code, formats["text"])
            sheet.write_datetime(row, 2, datetime.combine(day, time()), formats["date"])
            if hours.sessions and hours.net is not None:
                sheet.write_number(row, 3, hours.net / 1440, formats["hours"])
            if entry.input.adjustment is not None:
                sheet.write_number(row, 4, entry.input.adjustment, formats["number"])
            if entry.input.typed_hours is not None:
                sheet.write_number(row, 5, entry.input.typed_hours / 1440, formats["hours"])
            if entry.approved is not None:
                sheet.write_number(row, 6, entry.approved / 1440, formats["hours"])
            sheet.write(row, 7, entry.input.comment, formats["wrap"])
            sheet.write(row, 8, approval.reviewed_in or "", formats["text"])
        if approval.week_comment:
            row += 1
            sheet.write(row, 0, employee.name, formats["text"])
            sheet.write(row, 1, employee.code, formats["text"])
            sheet.write(row, 2, "Week", formats["text"])
            sheet.write(row, 7, approval.week_comment, formats["wrap"])
            sheet.write(row, 8, approval.reviewed_in or "", formats["text"])
    sheet.autofilter(0, 0, max(row, 0), len(columns) - 1)
    sheet.freeze_panes(1, 0)
