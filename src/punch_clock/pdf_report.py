"""Printable PDF: a department headcount page, then up to two employees per page."""
from __future__ import annotations

import os
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFError, TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from punch_clock.approvals import ApprovalSet, EmployeeApproval
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


def _employee_block(export: WeeklyExport, employee: Employee, approval: Optional[EmployeeApproval] = None) -> list:
    block = [
        _table(
            [[_para(f"{employee.name} ({employee.code})", 12, bold=True), _para(employee.position, 11)]],
            [290, 250],
            header=False,
        ),
        Spacer(1, 5),
    ]
    rows = [["Day / date", "In", "Out", "Gross", "Lunch", "Net"]]
    if approval:
        rows[0] += ["Adj.", "Approved"]
    warnings: list[str] = []
    info: list[str] = []
    gross_days: list[Optional[int]] = []
    net_days: list[Optional[int]] = []
    for day in export.dates:
        record = employee.days[day]
        hours = record.hours
        gross_days.append(hours.gross)
        net_days.append(hours.net)
        label = day.strftime("%a %b %d")
        extra = _approval_cells(approval.days[day]) if approval else []
        if day.weekday() < 5 or record.punches or record.issues:
            if not hours.sessions:
                # No punches is not a recorded zero, so it never prints as 0:00.
                dash = "-" if hours.gross is not None else format_minutes(None)
                first = "No punches" if hours.gross is not None else "NR"
                rows.append([label, first, "", dash, dash, dash, *extra])
            for index, session in enumerate(hours.sessions):
                rows.append(
                    [
                        label if index == 0 else "",
                        _clock(session.start),
                        _clock(session.end),
                        format_minutes(hours.gross) if index == 0 else "",
                        format_minutes(hours.lunch) if index == 0 else "",
                        format_minutes(hours.net) if index == 0 else "",
                        *(extra if index == 0 else ["" for _ in extra]),
                    ]
                )
        if hours.gaps:
            info.append(_gap_note(day, hours))
        for punch in record.punches:
            if punch.note:
                info.append(f'{day:%a} {punch.kind} {_clock(punch.time)}, Jibble note: "{punch.note}"')
        if hours.gross is None and not (approval and approval.days[day].approved is not None):
            warnings.append(f"{day:%a}: incomplete or invalid punches; hours need supervisor review.")
        if hours.lunch_capped:
            warnings.append(f"{day:%a}: lunch capped at gross hours.")
        warnings.extend(f"{day:%a}: {issue}" for issue in record.issues)
        if approval:
            entry = approval.days[day]
            if entry.input.comment:
                info.append(f'{day:%a} supervisor comment: "{entry.input.comment}"')
            warnings.extend(f"{day:%a}: {problem}" for problem in entry.problems)
    widths = [84, 68, 68, 62, 58, 62, 58, 80] if approval else [110, 100, 100, 77, 76, 77]
    weekly = [
        "Weekly gross",
        format_minutes(weekly_total(gross_days)),
        "Weekly net",
        format_minutes(weekly_total(net_days)),
    ]
    if approval:
        weekly += ["Approved", format_minutes(approval.approved), "Jibble OT", format_minutes(employee.overtime)]
        weekly_widths = [76, 58, 66, 58, 66, 74, 62, 80]
    else:
        weekly += ["Jibble OT", format_minutes(employee.overtime)]
        weekly_widths = [110, 70, 100, 70, 110, 80]
    block += [
        _table(rows, widths, padding=4),
        Spacer(1, 6),
        _table([weekly], weekly_widths, header=False),
    ]
    if approval:
        if approval.week_comment:
            info.append(f'Week comment: "{approval.week_comment}"')
        warnings.extend(approval.problems)
    for note in dict.fromkeys(info):
        block += [Spacer(1, 4), _para(note, 9, MUTED)]
    for note in dict.fromkeys(warnings):
        block += [Spacer(1, 4), _para(note, 9, WARN)]
    block.append(Spacer(1, 9))
    if not approval:
        block.append(_para("Adjustment: __________  Approved hours: __________  Supervisor: __________________", 9))
    elif approval.reviewed:
        block.append(_para(f"Reviewed in: {approval.reviewed_in}", 9))
    else:
        block.append(_para(f"NOT REVIEWED YET. Review file: {approval.reviewed_in or 'not found'}", 9, WARN))
    block.append(Spacer(1, 6))
    return block


def _approval_cells(entry) -> list[str]:
    adjustment = entry.input.adjustment
    # A blank stays blank, so "reviewed with no change" (0) can be told from no entry.
    shown = "" if adjustment is None else f"{adjustment:+d} min" if adjustment else "0 min"
    if entry.unresolved:
        return [shown, format_minutes(None)]
    return [shown, "-" if entry.approved is None else format_minutes(entry.approved)]


def _gap_note(day, hours) -> str:
    ranges = ", ".join(
        f"{_clock(out)}-{_clock(back)} ({format_minutes(gap_minutes(out, back))})" for out, back in hours.gaps
    )
    note = f"{day:%a}: clocked out {ranges}; already excluded from gross."
    if hours.gross is None:
        return note
    if not hours.lunch:
        return f"{note} No lunch deducted."
    return f"{note} Counts toward lunch; {format_minutes(hours.lunch)} more deducted."


def _block_height(block: list) -> float:
    return sum(item.wrap(WIDTH, 10000)[1] for item in block)


def _draw_block(pdf, block: list, y: float) -> float:
    for item in block:
        height = item.wrap(WIDTH, 10000)[1]
        item.drawOn(pdf, LEFT, y - height)
        y -= height
    return y


def _paginate(export: WeeklyExport, approvals: Optional[ApprovalSet] = None) -> list[list[list]]:
    """Measure whole employee blocks before packing, so an employee is never split."""
    pages: list[list[list]] = []
    current: list[list] = []
    used = 0.0
    for employee in export.included:
        block = _employee_block(export, employee, approvals.employees[employee.code] if approvals else None)
        height = _block_height(block)
        if height > PAGE_CAPACITY:
            raise UnsupportedExport(
                f"{employee.name}: too much detail for one printed page. Review the export; no report was made."
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


def _department_chunks(export: WeeklyExport) -> list[list[tuple[str, list[Employee]]]]:
    departments: dict[str, tuple[str, list[Employee]]] = {}
    for employee in export.included:
        key = employee.department.casefold()
        departments.setdefault(key, (employee.department, []))[1].append(employee)
    ordered = [departments[key] for key in sorted(departments)]
    return [ordered[i : i + DEPARTMENTS_PER_PAGE] for i in range(0, len(ordered), DEPARTMENTS_PER_PAGE)] or [[]]


def page_count(export: WeeklyExport, approvals: Optional[ApprovalSet] = None) -> int:
    return len(_department_chunks(export)) + len(_paginate(export, approvals))


def _page_frame(pdf, export: WeeklyExport, title: str, page: int, pages: int) -> None:
    regular, heavy = _fonts()
    pdf.setFillColor(INK)
    pdf.setFont(heavy, 12)
    pdf.drawString(LEFT, 754, export.company or "Weekly timesheets")
    pdf.setFont(regular, 10)
    pdf.drawRightString(RIGHT, 754, title)
    pdf.drawString(LEFT, 733, export.period)
    pdf.setStrokeColor(RULE)
    pdf.line(LEFT, 722, RIGHT, 722)
    pdf.setFont(regular, 8)
    pdf.setFillColor(MUTED)
    pdf.drawString(LEFT, 34, f"{export.exported}  |  {export.timezone}  |  {page} / {pages}")


def _write_note(pdf, text, y, size=9, color=MUTED) -> float:
    paragraph = _para(text, size, color)
    height = paragraph.wrap(WIDTH, 700)[1]
    paragraph.drawOn(pdf, LEFT, y - height)
    return y - height - 8


def _headcount_page(pdf, export: WeeklyExport, chunk, is_last: bool, approvals: Optional[ApprovalSet] = None) -> None:
    y = CONTENT_TOP
    if approvals and not approvals.is_final:
        y = _write_note(pdf, _provisional_text(approvals), y, 10, WARN)
    y = _write_note(pdf, "Distinct employees in this export with a recorded position.", y)
    rows = [["Department", "Employees", "With punches"]]
    widths = [340, 100, 100]
    if approvals:
        rows[0] += ["Reviewed", "Approved"]
        widths = [240, 75, 85, 70, 70]

    def row(label: str, members: list[Employee]) -> list[str]:
        cells = [label, str(len(members)), str(sum(m.has_punches for m in members))]
        if approvals:
            entries = [approvals.employees[m.code] for m in members]
            cells.append(str(sum(a.reviewed for a in entries)))
            cells.append(format_minutes(weekly_total(a.approved for a in entries)))
        return cells

    for department, members in chunk:
        rows.append(row(department, members))
    if is_last:
        rows.append(row("Total", export.included))
    y = _draw_block(pdf, [_table(rows, widths, padding=7)], y) - 15
    if not export.included:
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
        "Clocked-out gaps that day count toward the 30 minutes, so only the remainder is deducted. "
        "Days without punches have no deduction. Incomplete punches leave gross/net unavailable.",
        y,
    )
    _write_note(
        pdf,
        "Jibble overtime is retained as exported. It is not recalculated from net hours. "
        "NR = no recorded timestamp; it does not establish absence. "
        "Full source comparisons are in the validation file.",
        y,
    )


def _provisional_text(approvals: ApprovalSet) -> str:
    parts = ["PROVISIONAL: not everything is approved."]
    waiting = len(approvals.not_reviewed)
    if waiting:
        parts.append(f"{waiting} of {len(approvals.employees)} employees are not reviewed yet.")
    needing = sum(a.approved is None for a in approvals.employees.values())
    if needing:
        parts.append(f"{needing} still need hours entered.")
    if approvals.missing_files:
        parts.append("Review files not found: " + ", ".join(approvals.missing_files) + ".")
    return " ".join(parts)


def render(export: WeeklyExport, path: str | Path, approvals: Optional[ApprovalSet] = None) -> None:
    pdf = canvas.Canvas(str(path), pagesize=PAGE_SIZE)
    pdf.setTitle(f"{export.company or 'Weekly'} timesheets - {export.start:%Y-%m-%d}")
    chunks = _department_chunks(export)
    employee_pages = _paginate(export, approvals)
    pages = len(chunks) + len(employee_pages)
    title = "Employee timesheets"
    if approvals:
        title = "Approved timesheets" if approvals.is_final else "PROVISIONAL timesheets"
    for number, chunk in enumerate(chunks, 1):
        _page_frame(pdf, export, "Department headcount", number, pages)
        _headcount_page(pdf, export, chunk, number == len(chunks), approvals)
        pdf.showPage()
    regular, _ = _fonts()
    for number, blocks in enumerate(employee_pages, len(chunks) + 1):
        _page_frame(pdf, export, title, number, pages)
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
