"""Write the spreadsheet of a staffing agency's hours for one pay period.

Accounting sends it to the agency on payday. The main table is short: each person's regular and
overtime hours for the two weeks, and their lunch. Below it, the detail by week shows where those
came from, with each week's lunch days. Hours are written as decimals, as the agency expects.

The totals and lunch are live Excel formulas, stored with their results so they show in previews
too. Lunch is the lunch days in the detail times the lunch per day from the settings file, which
isn't shown, so accounting can change someone's lunch days, or type over their lunch, for anyone
who didn't buy lunch, and the totals follow. The main table's Total row is highlighted, as it's
what the agency is paid for.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import xlsxwriter
from xlsxwriter.utility import xl_rowcol_to_cell

if TYPE_CHECKING:
    from punch_clock.agency_hours import AgencyReport

SHEET = "Hours"
REGULAR, OVERTIME, LUNCH, LUNCH_DAYS = "Regular", "Overtime", "Lunch", "Lunch days"
DETAIL_TITLE = "Detail by week"
TOTAL = "Total"
HEADER_ROW = 9  # zero-based: the main table's column labels
DETAIL_GAP = 2  # empty rows between the main table's total and the detail's title
WEEK_COLUMNS = 3  # regular, overtime and lunch days for each week in the detail
HOURS_FORMAT = "0.00"
TOTAL_FILL = "#C6E0B4"  # the main table's Total row: what the agency is paid for
MONEY_FORMAT = '_($* #,##0.00_);_($* (#,##0.00);_($* "-"??_);_(@_)'


def detail_header_row(employees: int) -> int:
    """Zero-based: the detail's week headings, with its column labels below them."""
    return HEADER_ROW + employees + 2 + DETAIL_GAP + 1


def _hours(minutes: int) -> float:
    return minutes / 60


def write_agency_workbook(report: "AgencyReport", path: Path) -> None:
    from punch_clock.agency_hours import day_label, period_label

    workbook = xlsxwriter.Workbook(str(path))
    make = workbook.add_format
    bold = make({"bold": True})
    title = make({"bold": True, "font_size": 12})
    week_heading = make({"bold": True, "align": "center", "border": 1, "bg_color": "#FFF2CC"})
    label = make({"bold": True, "align": "center", "border": 1, "bg_color": "#FFF2CC", "text_wrap": True})
    name_label = make({"bold": True, "border": 1, "bg_color": "#FFF2CC"})
    name = make({"border": 1})
    hours = make({"num_format": HOURS_FORMAT, "border": 1})
    days = make({"num_format": "0", "border": 1})
    money = make({"num_format": MONEY_FORMAT, "border": 1})
    total = {"bold": True, "top": 2, "bottom": 2, "border": 1, "bg_color": TOTAL_FILL}
    total_label = make(total)
    total_hours = make({**total, "num_format": HOURS_FORMAT})
    total_money = make({**total, "num_format": MONEY_FORMAT})

    weeks = report.week_starts
    employees = report.employees
    sheet = workbook.add_worksheet(SHEET)
    sheet.set_column(0, 0, 32)
    sheet.set_column(1, len(weeks) * WEEK_COLUMNS, 12)
    sheet.write(0, 0, "TO:", bold)
    sheet.write(1, 0, report.agency.legal_name, bold)
    sheet.write(2, 0, report.agency.contact)
    sheet.write(4, 0, "FROM:", bold)
    sheet.write(5, 0, report.paid_by, bold)
    sheet.write(7, 0, "Pay period:", bold)
    sheet.write(7, 1, period_label(report.start))
    rate = f"{report.lunch_per_day:.2f}"

    # The detail by week, first, as the main table's formulas use its cells.
    detail = detail_header_row(len(employees))
    sheet.write(detail - 1, 0, DETAIL_TITLE, title)
    sheet.write(detail, 0, "", week_heading)
    sheet.write(detail + 1, 0, "Employee", name_label)
    for index, week in enumerate(weeks):
        first_column = 1 + WEEK_COLUMNS * index
        sheet.merge_range(detail, first_column, detail, first_column + WEEK_COLUMNS - 1, f"Week of {day_label(week)}", week_heading)
        for offset, text in enumerate((REGULAR, OVERTIME, LUNCH_DAYS)):
            sheet.write(detail + 1, first_column + offset, text, label)
    detail_rows = []
    for row, employee in enumerate(employees, start=detail + 2):
        detail_rows.append(row)
        sheet.write(row, 0, employee.name, name)
        for index, week in enumerate(employee.weeks):
            first_column = 1 + WEEK_COLUMNS * index
            sheet.write_number(row, first_column, _hours(week.regular), hours)
            sheet.write_number(row, first_column + 1, _hours(week.overtime), hours)
            sheet.write_number(row, first_column + 2, week.lunch_days, days)

    # The main table: the two weeks' totals and lunch.
    for column, text in enumerate(("Employee", REGULAR, OVERTIME, LUNCH)):
        sheet.write(HEADER_ROW, column, text, name_label if column == 0 else label)
    first = HEADER_ROW + 1
    cached_totals = [0.0, 0.0, 0.0]
    for row, employee, source in zip(range(first, first + len(employees)), employees, detail_rows):
        sheet.write(row, 0, employee.name, name)

        def across_weeks(offset: int) -> str:
            return "+".join(xl_rowcol_to_cell(source, 1 + WEEK_COLUMNS * index + offset) for index in range(len(weeks)))

        regular = sum(_hours(week.regular) for week in employee.weeks)
        overtime = sum(_hours(week.overtime) for week in employee.weeks)
        lunch = -round(sum(week.lunch_days for week in employee.weeks) * report.lunch_per_day, 2)
        sheet.write_formula(row, 1, f"={across_weeks(0)}", hours, regular)
        sheet.write_formula(row, 2, f"={across_weeks(1)}", hours, overtime)
        sheet.write_formula(row, 3, f"=-ROUND(({across_weeks(2)})*{rate},2)", money, lunch)
        for index, value in enumerate((regular, overtime, lunch)):
            cached_totals[index] += value
    total_row = first + len(employees)
    sheet.write(total_row, 0, TOTAL, total_label)
    for column, (style, value) in enumerate(zip((total_hours, total_hours, total_money), cached_totals), start=1):
        cells = f"{xl_rowcol_to_cell(first, column)}:{xl_rowcol_to_cell(total_row - 1, column)}"
        sheet.write_formula(total_row, column, f"=SUM({cells})", style, round(value, 2))

    notes = detail + 2 + len(employees) + 1
    sheet.write(notes, 0, "Hours are in decimals: 7.75 is 7 hours 45 minutes.")
    sheet.write(notes + 1, 0, "Lunch is charged for each scheduled day worked.")

    sheet.set_landscape()
    sheet.fit_to_pages(1, 0)
    sheet.print_area(0, 0, notes + 1, len(weeks) * WEEK_COLUMNS)
    workbook.close()
