"""Timesheet PDF: a department headcount page, then up to two employees per page."""
from __future__ import annotations

import os
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Optional, Sequence

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFError, TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from punch_clock import __version__
from punch_clock.assignments import MISSING_SUPERVISOR_TITLE, ReviewGroup, missing_supervisor_codes
from punch_clock.hours import format_minutes, gap_minutes, weekly_total
from punch_clock.jibble_export import Employee, UnsupportedExport, WeeklyExport

INK = colors.HexColor("#183340")
MUTED = colors.HexColor("#52616A")
LIGHT = colors.HexColor("#EDF2F4")
WARN = colors.HexColor("#8B4B09")
RULE = colors.HexColor("#AAB7BD")
CELL_RULE = colors.HexColor("#C8D1D5")

PAGE_SIZE = (612, 792)  # Letter, portrait
LEFT, RIGHT = 36, 576
WIDTH = RIGHT - LEFT
CONTENT_TOP = 706
PAGE_CAPACITY = 630  # height available for employee blocks on one page
BLOCK_GAP = 24
EMPLOYEES_PER_PAGE = 2
DEPARTMENTS_PER_PAGE = 15


@lru_cache(maxsize=1)
def _fonts() -> tuple[str, str]:
    """Prefer Arial: the built-in PDF fonts cannot print names such as "Łukasz"."""
    folder = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    try:
        pdfmetrics.registerFont(TTFont("ReportFont", str(folder / "arial.ttf")))
        pdfmetrics.registerFont(TTFont("ReportFont-Bold", str(folder / "arialbd.ttf")))
    except (TTFError, OSError):
        return "Helvetica", "Helvetica-Bold"
    pdfmetrics.registerFontFamily(
        "ReportFont",
        normal="ReportFont",
        bold="ReportFont-Bold",
        italic="ReportFont",
        boldItalic="ReportFont-Bold",
    )
    return "ReportFont", "ReportFont-Bold"


def _para(text, size=10, color=INK, bold=False) -> Paragraph:
    body = escape(str(text)).replace("\n", "<br/>")
    regular, heavy = _fonts()
    style = ParagraphStyle(
        "cell",
        fontName=heavy if bold else regular,
        fontSize=size,
        leading=size * 1.35,
        textColor=color,
    )
    return Paragraph(body, style)


def _table(rows, widths, header=True, size=10, padding=5) -> Table:
    cells = [[v if isinstance(v, Paragraph) else _para(v, size) for v in row] for row in rows]
    table = Table(cells, colWidths=widths)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), padding),
        ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, CELL_RULE),
    ]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), LIGHT))
    table.setStyle(TableStyle(style))
    return table


def _clock(value) -> str:
    return "NR" if value is None else value.strftime("%H:%M:%S")


def _employee_block(export: WeeklyExport, employee: Employee, missing_supervisor: bool = False) -> list:
    block = [
        _table(
            [[_para(f"{employee.name} ({employee.code})", 12, bold=True), _para(employee.position, 11)]],
            [290, 250],
            header=False,
        ),
        Spacer(1, 5),
    ]
    if missing_supervisor:
        block += [_para(MISSING_SUPERVISOR_TITLE.upper(), 9, WARN, bold=True), Spacer(1, 5)]
    rows = [["Day / date", "In", "Out", "Gross", "Lunch", "Net", "Paid"]]
    warnings: list[str] = []
    info: list[str] = []
    pay_notes: dict[str, list[str]] = {}
    gross_days: list[Optional[int]] = []
    net_days: list[Optional[int]] = []
    for day in export.dates:
        record = employee.days[day]
        hours = record.hours
        gross_days.append(hours.gross)
        net_days.append(hours.net)
        label = day.strftime("%a %b %d")
        if day.weekday() < 5 or record.punches or record.issues:
            if not hours.sessions:
                # No punches is not a recorded zero, so it never prints as 0:00.
                dash = "-" if hours.gross is not None else format_minutes(None)
                first = "No punches" if hours.gross is not None else "NR"
                rows.append([label, first, "", dash, dash, dash, dash])
            for index, session in enumerate(hours.sessions):
                rows.append(
                    [
                        label if index == 0 else "",
                        _clock(session.start),
                        _clock(session.end),
                        format_minutes(hours.gross) if index == 0 else "",
                        format_minutes(hours.lunch) if index == 0 else "",
                        format_minutes(hours.net) if index == 0 else "",
                        format_minutes(hours.paid) if index == 0 else "",
                    ]
                )
        if hours.gaps:
            info.append(_gap_note(day, hours))
        if hours.note:
            info.append(f"{day:%a}: {hours.note}")
        if hours.pay_note:
            pay_notes.setdefault(hours.pay_note, []).append(f"{day:%a}")
        for punch in record.punches:
            if punch.note:
                info.append(f'{day:%a} {punch.kind} {_clock(punch.time)}, Jibble note: "{punch.note}"')
        if hours.gross is None:
            warnings.append(f"{day:%a}: incomplete or invalid punches; hours need supervisor review.")
        if hours.lunch_capped:
            warnings.append(f"{day:%a}: lunch capped at gross hours.")
        warnings.extend(f"{day:%a}: {issue}" for issue in record.issues)
    # These can apply most days, so each gets one line for the week rather than one line a day.
    info += [f"{', '.join(days)}: {note}" for note, days in pay_notes.items()]
    weekly = [
        "Weekly gross",
        format_minutes(weekly_total(gross_days)),
        "Net",
        format_minutes(weekly_total(net_days)),
        "Paid",
        format_minutes(weekly_total(employee.days[day].hours.paid for day in export.dates)),
        "Overtime",
        format_minutes(weekly_total(employee.days[day].hours.overtime for day in export.dates)),
    ]
    block += [
        _table(rows, [100, 85, 85, 70, 60, 70, 70], padding=4),
        Spacer(1, 6),
        _table([weekly], [100, 65, 55, 65, 55, 65, 70, 65], header=False),
    ]
    for note in dict.fromkeys(info):
        block += [Spacer(1, 4), _para(note, 9, MUTED)]
    for note in dict.fromkeys(warnings):
        block += [Spacer(1, 4), _para(note, 9, WARN)]
    block.append(Spacer(1, 9))
    block.append(_para("Adjustment: __________  Approved hours: __________  Supervisor: __________________", 9))
    block.append(Spacer(1, 6))
    return block


def _gap_note(day, hours) -> str:
    ranges = ", ".join(
        f"{_clock(out)}-{_clock(back)} ({format_minutes(gap_minutes(out, back))})" for out, back in hours.gaps
    )
    note = f"{day:%a}: clocked out {ranges}; already excluded from gross."
    if hours.gross is None:
        return note
    return f"{note} {format_minutes(hours.lunch)} lunch also deducted."


def _block_height(block: list) -> float:
    return sum(item.wrap(WIDTH, 10000)[1] for item in block)


def _draw_block(pdf, block: list, y: float) -> float:
    for item in block:
        height = item.wrap(WIDTH, 10000)[1]
        item.drawOn(pdf, LEFT, y - height)
        y -= height
    return y


def _paginate(export: WeeklyExport, employees: Sequence[Employee]) -> list[list[list]]:
    """Measure whole employee blocks before packing, so an employee is never split."""
    pages: list[list[list]] = []
    current: list[list] = []
    used = 0.0
    unsupervised = missing_supervisor_codes(export)
    for employee in employees:
        block = _employee_block(export, employee, employee.code in unsupervised)
        height = _block_height(block)
        if height > PAGE_CAPACITY:
            raise UnsupportedExport(
                f"{employee.name} has too much information to fit on one printed page, so no report was made. "
                "Check this employee's punches and notes."
            )
        gap = BLOCK_GAP if current else 0
        if current and (len(current) == EMPLOYEES_PER_PAGE or used + gap + height > PAGE_CAPACITY):
            pages.append(current)
            current, used, gap = [], 0.0, 0
        current.append(block)
        used += gap + height
    if current:
        pages.append(current)
    return pages


def _department_chunks(employees: Sequence[Employee]) -> list[list[tuple[str, list[Employee]]]]:
    departments: dict[str, tuple[str, list[Employee]]] = {}
    for employee in employees:
        key = employee.department.casefold()
        departments.setdefault(key, (employee.department, []))[1].append(employee)
    ordered = [departments[key] for key in sorted(departments)]
    return [ordered[i : i + DEPARTMENTS_PER_PAGE] for i in range(0, len(ordered), DEPARTMENTS_PER_PAGE)] or [[]]


def _employees(export: WeeklyExport, group: Optional[ReviewGroup]) -> Sequence[Employee]:
    return group.employees if group else export.included


def page_count(export: WeeklyExport, group: Optional[ReviewGroup] = None) -> int:
    employees = _employees(export, group)
    return len(_department_chunks(employees)) + len(_paginate(export, employees))


def _page_frame(pdf, export: WeeklyExport, group: Optional[ReviewGroup], title: str, page: int, pages: int) -> None:
    regular, heavy = _fonts()
    pdf.setFillColor(INK)
    pdf.setFont(heavy, 12)
    pdf.drawString(LEFT, 754, export.company or "Weekly timesheets")
    pdf.setFont(regular, 10)
    pdf.drawRightString(RIGHT, 754, title)
    pdf.drawString(LEFT, 733, export.period)
    if group:
        pdf.setFont(heavy, 10)
        pdf.setFillColor(WARN if group.supervisor is None else INK)
        pdf.drawRightString(RIGHT, 733, group.title)
    pdf.setStrokeColor(RULE)
    pdf.line(LEFT, 722, RIGHT, 722)
    pdf.setFont(regular, 8)
    pdf.setFillColor(MUTED)
    pdf.drawString(LEFT, 34, f"{export.exported}  |  {export.timezone}  |  Punch Clock {__version__}  |  {page} / {pages}")
    if export.settings_note:
        pdf.setFillColor(WARN)
        pdf.drawString(LEFT, 24, export.settings_note)


def _write_note(pdf, text, y, size=9, color=MUTED) -> float:
    paragraph = _para(text, size, color)
    height = paragraph.wrap(WIDTH, 700)[1]
    paragraph.drawOn(pdf, LEFT, y - height)
    return y - height - 8


def _headcount_page(pdf, export: WeeklyExport, group: Optional[ReviewGroup], chunk, is_last: bool) -> None:
    employees = _employees(export, group)
    y = CONTENT_TOP
    if group and group.supervisor is None:
        y = _write_note(
            pdf,
            "These departments have no supervisor on the list in Punch Clock, so accounting reviews them.",
            y,
            10,
            WARN,
        )
    y = _write_note(pdf, f"Distinct employees in this {'report' if group else 'export'} with a recorded position.", y)
    rows = [["Department", "Employees", "With punches"]]

    def row(label: str, members: Sequence[Employee]) -> list[str]:
        return [label, str(len(members)), str(sum(m.has_punches for m in members))]

    for department, members in chunk:
        rows.append(row(department, members))
    if is_last:
        rows.append(row("Total", employees))
    y = _draw_block(pdf, [_table(rows, [340, 100, 100], padding=7)], y) - 15
    if not employees:
        y = _write_note(
            pdf,
            "No employees have a recorded position in this export, so there are no employee pages. "
            "Add positions in Jibble, then export again.",
            y,
            10,
            WARN,
        )
    y = _write_note(
        pdf,
        "Gross = sum of completed in/out sessions, rounded once per day to the nearest minute. "
        "Time between an out punch and the next in punch is already excluded.",
        y,
    )
    y = _write_note(
        pdf,
        "Net = gross less a 30-minute unpaid lunch per day with work, capped at gross hours. "
        "The 30 minutes are deducted even if the employee also clocked out that day; supervisors can adjust this. "
        "Days without punches have no deduction. Incomplete punches leave gross/net unavailable.",
        y,
    )
    _write_note(
        pdf,
        "Paid follows each schedule: arriving early isn't paid, and arriving up to 5 minutes late counts as on time. "
        "Overtime starts 15 minutes past the scheduled hours, counted from the end of those hours. "
        "NR = no recorded timestamp; it does not establish absence. "
        "Full source comparisons are in the validation file.",
        y,
    )


def render(export: WeeklyExport, path: str | Path, group: Optional[ReviewGroup] = None) -> None:
    """Report on one review group, or on all included employees when no group is given."""
    pdf = canvas.Canvas(str(path), pagesize=PAGE_SIZE)
    named = f" - {group.title}" if group else ""
    pdf.setTitle(f"{export.company or 'Weekly'} timesheets{named} - {export.start:%Y-%m-%d}")
    employees = _employees(export, group)
    chunks = _department_chunks(employees)
    employee_pages = _paginate(export, employees)
    pages = len(chunks) + len(employee_pages)
    for number, chunk in enumerate(chunks, 1):
        _page_frame(pdf, export, group, "Department headcount", number, pages)
        _headcount_page(pdf, export, group, chunk, number == len(chunks))
        pdf.showPage()
    regular, _ = _fonts()
    for number, blocks in enumerate(employee_pages, len(chunks) + 1):
        _page_frame(pdf, export, group, "Employee timesheets", number, pages)
        y = CONTENT_TOP
        for index, block in enumerate(blocks):
            if index:
                pdf.setStrokeColor(RULE)
                pdf.setDash(2, 3)
                pdf.line(LEFT, y - 12, RIGHT, y - 12)
                pdf.setDash()
                y -= BLOCK_GAP
            y = _draw_block(pdf, block, y)
        pdf.setFillColor(MUTED)
        pdf.setFont(regular, 8)
        pdf.drawString(
            LEFT,
            49,
            'NR = no timestamp. "-" = no punches (absence not confirmed). '
            "Hours H:MM. Gross excludes clocked-out gaps; net deducts lunch.",
        )
        pdf.showPage()
    pdf.save()
