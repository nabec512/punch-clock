"""Build a fictional workbook laid out like a detailed weekly Jibble export.

Tests and the packaging smoke test use this so no real export ever enters the
repository. Run it directly to write a sample file:

    python tests/sample_export.py sample.xlsx
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import openpyxl

WEEK_START = date(2026, 3, 2)
COMPANY = "Example Manufacturing Inc."
TIMEZONE = "America/Vancouver"
ZERO = "0h 00m"


@dataclass
class Person:
    name: str
    code: str
    position: str = ""
    # (day offset from Monday, kind, "HH:MM:SS", note)
    punches: list[tuple] = field(default_factory=list)


def default_people() -> list[Person]:
    return [
        Person(
            "Avery Lee",
            "AL-1",
            "Assembly - Supervisor",
            [
                (0, "In", "08:00:10", ""),
                (0, "Out", "11:30:20", ""),
                (0, "In", "12:45:05", "dentist appointment"),
                (0, "Out", "16:30:00", ""),
            ],
        ),
        Person(
            "Sam Ortiz",
            "SO-1",
            "Assembly",
            [(0, "In", "08:05:42", ""), (0, "Out", "16:20:19", ""), (1, "In", "08:00:00", ""), (1, "Out", "16:30:00", "")],
        ),
        Person(
            "Łucja Żak",
            "LZ-1",
            "Receiving",
            [
                (2, "In", "09:00:00", ""),
                (2, "Out", "12:00:00", ""),
                (2, "In", "12:20:00", ""),
                (2, "Out", "17:00:00", ""),
            ],
        ),
        Person("Riley Chen", "RC-1", "", []),
    ]


def duration(minutes: int) -> str:
    return f"{minutes // 60}h {minutes % 60:02d}m"


def _clock(day: date, text: str) -> datetime:
    return datetime.combine(day, datetime.strptime(text, "%H:%M:%S").time())


def _daily_minutes(person: Person, offset: int, week_start: date) -> tuple[int, datetime | None, datetime | None]:
    """Jibble-style payroll for one day: sessions summed exactly, then rounded once."""
    day = week_start + timedelta(days=offset)
    punches = [p for p in person.punches if p[0] == offset]
    seconds = 0
    opened = None
    for _, kind, text, _ in punches:
        moment = _clock(day, text)
        if kind == "In":
            opened = moment
        elif opened is not None:
            seconds += int((moment - opened).total_seconds())
            opened = None
    first = _clock(day, punches[0][2]) if punches else None
    last = _clock(day, punches[-1][2]) if punches else None
    return (seconds + 30) // 60, first, last


def build_workbook(people: list[Person] | None = None, week_start: date = WEEK_START) -> openpyxl.Workbook:
    people = default_people() if people is None else people
    workbook = openpyxl.Workbook()
    team = workbook.active
    team.title = "Team Summary"
    dates = [week_start + timedelta(days=i) for i in range(7)]
    period = f"{dates[0]:%d %B %Y} - {dates[6]:%d %B %Y}"
    payroll = {p.code: [_daily_minutes(p, i, week_start) for i in range(7)] for p in people}

    _team_sheet(team, people, dates, period, payroll)
    for person in people:
        _individual_sheet(workbook, person, dates, period, payroll[person.code])
    _timesheet_sheet(workbook, people, dates, payroll)
    _entries_sheet(workbook, people, dates)
    return workbook


def _team_sheet(sheet, people, dates, period, payroll) -> None:
    sheet["A1"], sheet["M1"] = "Weekly Timesheets", COMPANY
    sheet["A3"], sheet["B3"] = "Week", period
    sheet["A5"], sheet["B5"], sheet["D5"], sheet["F5"] = "Legend", "Public holiday", "Rest day", "Time off"
    for i, day in enumerate(dates):
        sheet.cell(8, 4 + i, day.strftime("%a"))
    header = ["NAME", "MEMBER CODE", "TYPE", *[d.strftime("%B %d") for d in dates], "TOTALS", "RATES", "TOTALS"]
    for column, label in enumerate(header, 1):
        sheet.cell(9, column, label)
    row = 10
    grand = 0
    for person in people:
        minutes = [m for m, _, _ in payroll[person.code]]
        grand += sum(minutes)
        for offset, kind in enumerate(("Payroll Hours", "Regular Hours")):
            if offset == 0:
                sheet.cell(row, 1, person.name)
                sheet.cell(row, 2, person.code)
            sheet.cell(row, 3, kind)
            for i, value in enumerate(minutes):
                sheet.cell(row, 4 + i, duration(value) if value else "-")
            sheet.cell(row, 11, duration(sum(minutes)) if sum(minutes) else "-")
            row += 1
    row += 2
    sheet.cell(row, 3, "Total Hours")
    for label, value in (
        ("Payroll", grand),
        ("Regular", grand),
        ("Daily OT", 0),
        ("Double OT", 0),
        ("Weekly OT", 0),
        ("Rest Day OT", 0),
        ("Public Holiday OT", 0),
        ("Paid Time Off", 0),
    ):
        row += 1
        sheet.cell(row, 3, label)
        sheet.cell(row, 11, duration(value) if value else "-")
    sheet.cell(row + 3, 13, f"Exported on {dates[0]:%d %B %Y}")


def _individual_sheet(workbook, person, dates, period, daily) -> None:
    sheet = workbook.create_sheet(f"{person.name} ({person.code}) Summary"[:31])
    sheet["A1"], sheet["M1"] = "Weekly Timesheets", COMPANY
    sheet["A3"], sheet["B3"] = "Week", period
    sheet["A5"], sheet["B5"] = "Member", person.name
    sheet["A6"], sheet["B6"] = "Code", person.code
    sheet["A7"] = "Manager(s)"
    header = [
        "DATE", "DAY", "FIRST IN", "LAST OUT", "PAYROLL HRS", "REG. HRS", "DAILY OT", "DOUBLE OT",
        "REST DAY OT", "WEEKLY OT", "PUBLIC HOLIDAY OT", "PTO", "TIME OFF POLICY",
    ]
    for column, label in enumerate(header, 1):
        sheet.cell(10, column, label)
    for i, day in enumerate(dates):
        minutes, first, last = daily[i]
        row = 11 + i
        sheet.cell(row, 1, datetime.combine(day, datetime.min.time()))
        sheet.cell(row, 2, day.strftime("%A"))
        sheet.cell(row, 3, first)
        sheet.cell(row, 4, last)
        sheet.cell(row, 5, duration(minutes))
        sheet.cell(row, 6, duration(minutes))
        for column in range(7, 13):
            sheet.cell(row, column, ZERO)
    total = sum(m for m, _, _ in daily)
    sheet.cell(18, 4, "Total Hours")
    sheet.cell(18, 5, duration(total))
    sheet.cell(18, 6, duration(total))
    for column in range(7, 13):
        sheet.cell(18, column, ZERO)


TIMESHEET_HEADER = [
    "Date", "Day", "Full Name", "Member Code", "Position", "Employment Type", "Group", "Manager(s)", "Work Schedule",
    "Tracked Hours", "Worked Hours", "Break Hours (paid)", "Break Hours (unpaid)", "Deductions", "Payroll Hours",
    "Regular Hours", "Daily OT", "Daily Double OT", "Weekly OT", "Rest Day OT", "Public Holiday OT",
    "Paid Time Off", "Time Off Name", "First In", "Last Out",
]


def _timesheet_sheet(workbook, people, dates, payroll) -> None:
    sheet = workbook.create_sheet("Raw Timesheets")
    sheet["A1"] = "Custom period - Team RAW TIMESHEET"
    sheet.append(TIMESHEET_HEADER)
    for i, day in enumerate(dates):
        for person in people:
            minutes, first, last = payroll[person.code][i]
            cells = dict.fromkeys(TIMESHEET_HEADER, ZERO)
            hours = duration(minutes)
            cells.update(
                {
                    "Date": datetime.combine(day, datetime.min.time()),
                    "Day": day.strftime("%A"),
                    "Full Name": person.name,
                    "Member Code": person.code,
                    "Position": person.position or None,
                    "Employment Type": None,
                    "Group": None,
                    "Manager(s)": "",
                    "Work Schedule": "Standard",
                    "Tracked Hours": hours,
                    "Worked Hours": hours,
                    "Payroll Hours": hours,
                    "Regular Hours": hours,
                    "Time Off Name": None,
                    "First In": first,
                    "Last Out": last,
                }
            )
            sheet.append([cells[name] for name in TIMESHEET_HEADER])


ENTRY_HEADER = [
    "Date", "Full Name", "Member Code", "Position", "Entry Type", "Time", "Time (unrounded)", "Duration",
    "Notes", "Timezone",
]


def _entries_sheet(workbook, people, dates) -> None:
    sheet = workbook.create_sheet("Raw Time Entries")
    sheet["A1"] = "Custom period - Team RAW TIME ENTRIES"
    sheet.append(ENTRY_HEADER)
    rows = []
    for person in people:
        for offset, kind, text, note in person.punches:
            day = dates[offset]
            moment = _clock(day, text)
            rows.append(
                [
                    datetime.combine(day, datetime.min.time()),
                    person.name,
                    person.code,
                    person.position or None,
                    kind,
                    moment,
                    None,
                    None,
                    note or None,
                    TIMEZONE,
                ]
            )
    # Jibble lists entries by time across the team, not grouped per person.
    for row in sorted(rows, key=lambda r: r[5]):
        sheet.append(row)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "sample-export.xlsx"
    build_workbook().save(target)
    print(target)
