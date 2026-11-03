import hashlib
import json
import subprocess
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from urllib.error import URLError

import pytest

from punch_clock import app, updater

BASE = f"https://github.com/{updater.REPO}/releases/download/v9.9.9/"
INSTALLER = b"pretend installer"


def release(tag="v9.9.9", installer_url=BASE + "PunchClock-9.9.9-setup.exe", checksums_url=BASE + "SHA256SUMS.txt"):
    return {
        "tag_name": tag,
        "assets": [
            {"name": f"PunchClock-{tag.lstrip('v')}-setup.exe", "browser_download_url": installer_url},
            {"name": "SHA256SUMS.txt", "browser_download_url": checksums_url},
        ],
    }


def serve(monkeypatch, pages):
    def fetch(url, seconds):
        if url not in pages:
            raise URLError(f"unexpected address: {url}")
        return pages[url]

    monkeypatch.setattr(updater, "_fetch", fetch)


def serve_release(monkeypatch, body=None):
    serve(monkeypatch, {updater.LATEST_RELEASE: json.dumps(body or release()).encode()})


UPDATE = updater.Update("9.9.9", "PunchClock-9.9.9-setup.exe", BASE + "PunchClock-9.9.9-setup.exe", BASE + "SHA256SUMS.txt")


@pytest.mark.parametrize(
    "tag, running, expected",
    [
        ("v0.3.0", "0.2.0", "0.3.0"),
        ("v0.10.0", "0.9.0", "0.10.0"),  # numbers, not text: 10 is newer than 9
        ("v1.0.0", "0.99.99", "1.0.0"),
        ("v0.2.0", "0.2.0", None),
        ("v0.1.0", "0.2.0", None),  # never downgrades
        ("nightly", "0.2.0", None),
    ],
)
def test_only_a_newer_release_is_an_update(monkeypatch, tag, running, expected):
    serve_release(monkeypatch, release(tag))
    found = updater.find_update(running)
    assert (found.version if found else None) == expected


@pytest.mark.parametrize(
    "body",
    [
        {"tag_name": "v9.9.9", "assets": []},  # published, files not uploaded yet
        release(installer_url="https://example.com/PunchClock-9.9.9-setup.exe"),
        release(checksums_url="https://example.com/SHA256SUMS.txt"),
    ],
)
def test_a_release_with_missing_or_foreign_files_is_ignored(monkeypatch, body):
    serve_release(monkeypatch, body)
    assert updater.find_update("0.2.0") is None


def test_being_offline_raises_for_the_caller_to_handle(monkeypatch):
    serve(monkeypatch, {})
    with pytest.raises(OSError):
        updater.find_update("0.2.0")


@pytest.fixture
def temp_downloads(monkeypatch, tmp_path):
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))
    return tmp_path / "PunchClockUpdate"


def test_download_checks_the_installer_against_its_checksum(monkeypatch, temp_downloads):
    digest = hashlib.sha256(INSTALLER).hexdigest()
    sums = f"{'0' * 64}  PunchClock-9.9.9-windows.zip\n{digest}  PunchClock-9.9.9-setup.exe\n".encode()
    serve(monkeypatch, {UPDATE.checksums_url: sums, UPDATE.installer_url: INSTALLER})
    path = updater.download(UPDATE)
    assert path == temp_downloads / UPDATE.installer_name and path.read_bytes() == INSTALLER


@pytest.mark.parametrize("sums", [f"{'0' * 64}  PunchClock-9.9.9-setup.exe\n", f"{'0' * 64}  something-else.exe\n"])
def test_a_corrupt_or_unlisted_download_is_never_kept(monkeypatch, temp_downloads, sums):
    serve(monkeypatch, {UPDATE.checksums_url: sums.encode(), UPDATE.installer_url: INSTALLER})
    with pytest.raises(ValueError, match="checksum"):
        updater.download(UPDATE)
    assert list(temp_downloads.iterdir()) == []


@pytest.mark.parametrize("reopen, expected", [(True, True), (False, False)])
def test_install_runs_silently_and_only_reopens_when_asked(monkeypatch, tmp_path, reopen, expected):
    started = []
    monkeypatch.setattr(subprocess, "Popen", lambda arguments, **_: started.append(arguments))
    updater.install(tmp_path / "setup.exe", reopen=reopen)
    assert started[0][0] == str(tmp_path / "setup.exe") and "/SILENT" in started[0]
    assert ("/reopen=1" in started[0]) is expected


# --- The window -----------------------------------------------------------------


@pytest.fixture(scope="module")
def tk_root():
    root = tk.Tk()
    yield root
    root.destroy()


class Window:
    """Stands in for the app's window, so a test can watch it close."""

    def __init__(self, root, monkeypatch):
        monkeypatch.setattr(app, "UPDATE_POLL_MS", 5)
        self.root = root
        self.top = tk.Toplevel(root)
        self.status = tk.StringVar(self.top, value="start")
        self.button = ttk.Button(self.top, text="Make")
        self.busy = False
        self.asked = []
        self.errors = []
        monkeypatch.setattr(messagebox, "askyesno", lambda title, text, parent: self.asked.append(text) or self.answer)
        monkeypatch.setattr(messagebox, "showerror", lambda title, text, parent: self.errors.append(text))
        self.answer = True

    def offer(self):
        app._offer_update(self.top, self.status, [self.button], lambda: self.busy)

    def pump(self, seconds=0.3, until=lambda: False):
        end = time.time() + seconds
        while time.time() < end and not until():
            self.root.update()
            time.sleep(0.005)

    @property
    def closed(self):
        return not self.top.winfo_exists()

    def cleanup(self):
        if not self.closed:
            self.top.destroy()


@pytest.fixture
def window(tk_root, monkeypatch):
    shown = Window(tk_root, monkeypatch)
    yield shown
    shown.cleanup()


def test_nothing_is_shown_when_up_to_date_or_offline(window, monkeypatch):
    monkeypatch.setattr(updater, "find_update", lambda: None)
    window.offer()
    window.pump()
    assert window.asked == [] and not window.closed

    def offline():
        raise URLError("no network")

    monkeypatch.setattr(updater, "find_update", offline)
    window.offer()
    window.pump()
    assert window.asked == [] and window.errors == [] and not window.closed


def test_choosing_later_downloads_nothing(window, monkeypatch):
    monkeypatch.setattr(updater, "find_update", lambda: UPDATE)
    monkeypatch.setattr(updater, "download", lambda update: pytest.fail("downloaded"))
    window.answer = False
    window.offer()
    window.pump(until=lambda: window.asked)
    window.pump(0.1)
    assert "9.9.9" in window.asked[0] and not window.closed


def test_accepting_downloads_installs_and_closes_the_app(window, monkeypatch, tmp_path):
    installed = []
    monkeypatch.setattr(updater, "find_update", lambda: UPDATE)
    monkeypatch.setattr(updater, "download", lambda update: tmp_path / "setup.exe")
    monkeypatch.setattr(updater, "install", lambda path: installed.append(path))
    window.offer()
    window.pump(2, until=lambda: window.closed)
    assert installed == [tmp_path / "setup.exe"] and window.closed


def test_buttons_are_off_during_the_download(window, monkeypatch, tmp_path):
    release_download = threading.Event()

    def slow(update):
        release_download.wait(2)
        return tmp_path / "setup.exe"

    monkeypatch.setattr(updater, "find_update", lambda: UPDATE)
    monkeypatch.setattr(updater, "download", slow)
    monkeypatch.setattr(updater, "install", lambda path: None)
    window.offer()
    window.pump(1, until=lambda: window.button.instate(["disabled"]))
    assert window.button.instate(["disabled"]) and "Downloading" in window.status.get()
    release_download.set()
    window.pump(2, until=lambda: window.closed)
    assert window.closed


@pytest.mark.parametrize("step", ["download", "install"])
def test_a_failed_update_leaves_the_app_usable(window, monkeypatch, tmp_path, step):
    def fails(*_):
        raise OSError("nope")

    monkeypatch.setattr(updater, "find_update", lambda: UPDATE)
    monkeypatch.setattr(updater, "download", fails if step == "download" else lambda update: tmp_path / "setup.exe")
    monkeypatch.setattr(updater, "install", fails)
    window.offer()
    window.pump(2, until=lambda: window.errors)
    assert "try again" in window.errors[0] and not window.closed
    assert window.status.get() == "start" and not window.button.instate(["disabled"])


def test_the_offer_waits_until_the_user_has_finished_what_they_are_doing(window, monkeypatch):
    monkeypatch.setattr(updater, "find_update", lambda: UPDATE)
    window.answer = False
    window.busy = True
    window.offer()
    window.pump(0.2)
    assert window.asked == []
    window.busy = False
    window.pump(1, until=lambda: window.asked)
    assert len(window.asked) == 1


# --- The command line ------------------------------------------------------------


def test_update_command_only_works_from_an_installed_copy(capsys, monkeypatch):
    monkeypatch.setattr(updater, "is_packaged", lambda: False)
    assert app.main(["--update"]) == 1
    assert "installed copy" in capsys.readouterr().err


def test_update_command_when_already_current(capsys, monkeypatch):
    monkeypatch.setattr(updater, "is_packaged", lambda: True)
    monkeypatch.setattr(updater, "find_update", lambda: None)
    monkeypatch.setattr(updater, "install", lambda *_, **__: pytest.fail("installed"))
    assert app.main(["--update"]) == 0
    assert "up to date" in capsys.readouterr().out


def test_update_command_installs_without_reopening(capsys, monkeypatch, tmp_path):
    installed = []
    monkeypatch.setattr(updater, "is_packaged", lambda: True)
    monkeypatch.setattr(updater, "find_update", lambda: UPDATE)
    monkeypatch.setattr(updater, "download", lambda update: tmp_path / "setup.exe")
    monkeypatch.setattr(updater, "install", lambda path, reopen: installed.append((path, reopen)))
    assert app.main(["--update"]) == 0
    assert installed == [(tmp_path / "setup.exe", False)]
    assert "9.9.9" in capsys.readouterr().out


def test_update_command_reports_being_offline(capsys, monkeypatch):
    def offline():
        raise URLError("no network")

    monkeypatch.setattr(updater, "is_packaged", lambda: True)
    monkeypatch.setattr(updater, "find_update", offline)
    assert app.main(["--update"]) == 1
    assert "Error" in capsys.readouterr().err
