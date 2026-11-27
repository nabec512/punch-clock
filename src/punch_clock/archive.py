"""Keep the supervisors' returned review files in one place that Punch Clock looks after.

The settings file names an accounting folder, meant for a share only accounting can open. Each
returned file is received through the app, which checks it straight away and files it as

    <accounting folder>\\Returned files\\<organization>\\<week's Monday>\\<organization> - <supervisor> - <week>.xlsx

so nobody has to decide where it goes, and a file can't be kept twice. A corrected file replaces
the one before, which is moved to a history folder beside it rather than deleted. Every file
received is written to a receipt log, with when, by whom, and a fingerprint of the file (its
SHA-256). The payroll and agency steps read only from here, and refuse a file whose fingerprint
doesn't match its receipt, or that has none, as it was changed or put there by hand.

If the folder can't be reached, nothing is received or made: a copy kept on one PC instead would
leave the others with a different set of files.
"""
from __future__ import annotations

import csv
import getpass
import hashlib
import os
import shutil
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional

from punch_clock import settings
from punch_clock.approved_hours import ApprovedFile, read_approved_hours
from punch_clock.assignments import safe_file_name
from punch_clock.jibble_export import UnsupportedExport
from punch_clock.returned_files import check_twice, day_label

RETURNED, PAYROLL, AGENCY = "Returned files", "Payroll files", "Agency hours"
HISTORY = "history"
RECEIPTS = "receipts.csv"
RECEIPT_COLUMNS = ("received_at", "received_by", "organization", "week", "supervisor", "file", "sha256", "replaced")


@dataclass(frozen=True)
class Received:
    approved: ApprovedFile  # as read from the file received
    path: Path  # where it's kept now
    replaced: Optional[Path]  # the earlier version, now in history
    unchanged: bool  # the same file was already received, so nothing changed


@dataclass(frozen=True)
class ReceiveResult:
    received: tuple[Received, ...]
    warnings: tuple[str, ...]  # what needs fixing in the files before payday


def accounting_folder(current: settings.Settings) -> Path:
    """The accounting folder, which must be reachable now: nothing is kept anywhere else instead."""
    if current.accounting_folder is None:
        raise UnsupportedExport(
            f'The settings file doesn\'t say where accounting keeps the returned files yet. Add "{settings.ACCOUNTING_FOLDER}" '
            f"to it, with the folder on the accounting server:\n\n{current.path}"
        )
    folder = current.accounting_folder
    if not folder.is_dir():
        raise UnsupportedExport(
            f"The accounting folder can't be reached:\n\n{folder}\n\nCheck that this PC is connected to the accounting "
            "server, then try again. Nothing was received or made."
        )
    return folder


def fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def kept_path(root: Path, approved: ApprovedFile) -> Path:
    """Where a returned file is kept, from what's inside it rather than its name, which people change."""
    organization = safe_file_name(approved.company)
    name = safe_file_name(f"{approved.company} - {approved.group} - {approved.start}") + ".xlsx"
    return root / RETURNED / organization / approved.start.isoformat() / name


def _receipts_path(root: Path) -> Path:
    return root / RETURNED / RECEIPTS


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root / RETURNED).as_posix()


def latest_receipts(root: Path) -> dict[str, str]:
    """The fingerprint of the last file received at each place, by its path inside Returned files."""
    receipts: dict[str, str] = {}
    try:
        with open(_receipts_path(root), encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                receipts[row["file"]] = row["sha256"]
    except FileNotFoundError:
        pass
    return receipts


def received_weeks(root: Path) -> set[date]:
    """The Mondays of the weeks with files received, from the receipt log, for the week list in the window."""
    weeks = set()
    try:
        with open(_receipts_path(root), encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                try:
                    weeks.add(date.fromisoformat(row["week"] or ""))
                except (KeyError, TypeError, ValueError):
                    continue  # a line it can't read just isn't offered; the files are still checked when read
    except FileNotFoundError:
        pass
    return weeks


def _write_receipt(root: Path, row: dict) -> None:
    path = _receipts_path(root)
    new = not path.exists()
    with open(path, "a", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, RECEIPT_COLUMNS)
        if new:
            writer.writeheader()
        writer.writerow(row)


def _who() -> str:
    try:
        return getpass.getuser()
    except Exception:  # no user name to be had; the receipt is still worth keeping
        return ""


def receive_files(paths: Iterable[str | Path], now: Optional[datetime] = None) -> ReceiveResult:
    """Check each returned file and keep it in the accounting folder. Nothing is kept unless every file can be read."""
    current = settings.load_full()
    root = accounting_folder(current)
    now = now or datetime.now()
    paths = [Path(path) for path in paths]
    files = [read_approved_hours(path) for path in paths]  # refuses one that isn't a review file, or was changed
    for file in files:
        current.organization(file.company)  # an organization the settings file doesn't know is refused
    check_twice(files, Path.cwd())
    targets = [kept_path(root, file) for file in files]

    received, warnings = [], []
    receipts = latest_receipts(root)
    for source, file, target in zip(paths, files, targets):
        sha = fingerprint(source)
        if target.exists() and receipts.get(_relative(target, root)) == sha and fingerprint(target) == sha:
            received.append(Received(file, target, None, True))
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        replaced = None
        if target.exists():
            history = target.parent / HISTORY
            history.mkdir(exist_ok=True)
            replaced = history / f"{target.stem} (replaced {now:%Y-%m-%d %H%M%S}){target.suffix}"
            os.replace(target, replaced)
        pending = target.with_name(target.name + ".pending")
        shutil.copy2(source, pending)
        if fingerprint(pending) != sha:
            pending.unlink(missing_ok=True)
            raise UnsupportedExport(f"{source.name} didn't copy to the accounting folder correctly. Try again.")
        os.replace(pending, target)
        _write_receipt(root, {
            "received_at": now.isoformat(timespec="seconds"),
            "received_by": _who(),
            "organization": file.company,
            "week": file.start.isoformat(),
            "supervisor": file.group,
            "file": _relative(target, root),
            "sha256": sha,
            "replaced": _relative(replaced, root) if replaced else "",
        })
        received.append(Received(file, target, replaced, False))
        if file.problems:
            warnings.append(
                f"{target.name} needs fixing before payday:\n" + "\n".join(f"  {problem}" for problem in file.problems)
            )
    for file in files:
        organization = current.organization(file.company)
        unlinked = [e.name for e in file.employees if current.links_pay and organization.pay_link(e.code) is None]
        if unlinked:
            warnings.append(
                f"The settings file doesn't say who pays these people in {file.group}'s file for the week of "
                f"{day_label(file.start)}: {', '.join(unlinked)}."
            )
    return ReceiveResult(tuple(received), tuple(warnings))


def read_archive(
    current: settings.Settings, weeks: tuple[date, ...], period: str, only: Optional[set[str]] = None
) -> tuple[list[ApprovedFile], list[str]]:
    """Every file kept for these weeks, checked against its receipt, read, and checked for duplicates."""
    root = accounting_folder(current)
    receipts = latest_receipts(root)
    paths, changed = [], []
    for key, organization in current.organizations.items():
        if only is not None and key not in only:
            continue
        for week in weeks:
            folder = root / RETURNED / safe_file_name(organization.name) / week.isoformat()
            for path in sorted(folder.glob("*.xlsx")) if folder.is_dir() else ():
                if receipts.get(_relative(path, root)) != fingerprint(path):
                    changed.append(path)
                else:
                    paths.append(path)
    if changed:
        raise UnsupportedExport(
            "These files in the accounting folder have been changed, or put there, without going through Receive "
            "returned files, so Punch Clock can't be sure they're what the supervisor sent:\n\n"
            + "\n".join(_relative(path, root) for path in changed)
            + "\n\nReceive the supervisor's file again with Receive returned files..., then try again."
        )
    if not paths:
        raise UnsupportedExport(
            f"No supervisor files have been received for {period} yet. Receive them with Receive returned files..., "
            "then try again."
        )
    files = [read_approved_hours(path) for path in paths]
    check_twice(files, root / RETURNED)
    return files, []


def output_parent(current: settings.Settings, kind: str) -> Path:
    """Where payroll or agency files are made: beside the returned files, on the accounting server."""
    parent = accounting_folder(current) / kind
    parent.mkdir(exist_ok=True)
    return parent
