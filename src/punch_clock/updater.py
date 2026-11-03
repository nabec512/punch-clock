"""Find a newer release on GitHub, download its installer, and run it.

The repository's releases are public, so no login or token is needed.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from punch_clock import __version__

REPO = "nabec512/punch-clock"
LATEST_RELEASE = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOADS = f"https://github.com/{REPO}/releases/download/"
CHECKSUMS = "SHA256SUMS.txt"
CHECK_SECONDS = 10
DOWNLOAD_SECONDS = 120


@dataclass(frozen=True)
class Update:
    version: str
    installer_name: str
    installer_url: str
    checksums_url: str


def is_packaged() -> bool:
    """Only an installed copy can update itself, not one run from the source code."""
    return bool(getattr(sys, "frozen", False))


def _fetch(url: str, seconds: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": f"PunchClock/{__version__}"})
    try:
        with urllib.request.urlopen(request, timeout=seconds) as response:
            return response.read()
    except http.client.HTTPException as error:
        raise OSError(str(error)) from error


def _version_numbers(text: str) -> Optional[tuple[int, int, int]]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", text)
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def find_update(current: str = __version__) -> Optional[Update]:
    """The latest release if it's newer than ``current``. Raises OSError or ValueError if GitHub can't be read."""
    release = json.loads(_fetch(LATEST_RELEASE, CHECK_SECONDS))
    latest = _version_numbers(str(release.get("tag_name", "")))
    running = _version_numbers(current)
    if not latest or not running or latest <= running:
        return None
    version = ".".join(str(number) for number in latest)
    installer_name = f"PunchClock-{version}-setup.exe"
    urls = {asset.get("name"): str(asset.get("browser_download_url", "")) for asset in release.get("assets", [])}
    installer_url, checksums_url = urls.get(installer_name, ""), urls.get(CHECKSUMS, "")
    if not installer_url.startswith(DOWNLOADS) or not checksums_url.startswith(DOWNLOADS):
        return None  # a release still being published, or not one of ours
    return Update(version, installer_name, installer_url, checksums_url)


def download(update: Update) -> Path:
    """Download the installer and confirm it matches the release's checksum. Raises OSError or ValueError."""
    folder = Path(tempfile.gettempdir()) / "PunchClockUpdate"
    shutil.rmtree(folder, ignore_errors=True)  # any earlier update's installer
    folder.mkdir(parents=True, exist_ok=True)
    expected = None
    for line in _fetch(update.checksums_url, CHECK_SECONDS).decode("ascii").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == update.installer_name:
            expected = parts[0].lower()
    installer = _fetch(update.installer_url, DOWNLOAD_SECONDS)
    if expected is None or hashlib.sha256(installer).hexdigest() != expected:
        raise ValueError("The downloaded update doesn't match its checksum.")
    path = folder / update.installer_name
    path.write_bytes(installer)
    return path


def install(installer: Path, reopen: bool = True) -> None:
    """Start the installer, showing only its progress bar. The app must exit straight after, so its files can be replaced."""
    arguments = [str(installer), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"]
    if reopen:
        arguments.append("/reopen=1")  # read by installer.iss
    subprocess.Popen(arguments, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP, close_fds=True)
