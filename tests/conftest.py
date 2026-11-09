import tempfile
from pathlib import Path

import pytest

from sample_export import write_settings

from punch_clock import reports, settings


def pytest_configure(config):
    """Windows stops at 260 characters, and pytest's usual temp folders use up much of that."""
    if not config.option.basetemp:
        config.option.basetemp = str(Path(tempfile.gettempdir()) / "punch-clock-tests")


@pytest.fixture(autouse=True)
def allow_long_temp_paths(monkeypatch):
    """pytest's own temp folders are long enough to trip the path check."""
    monkeypatch.setattr(reports, "EXCEL_PATH_LIMIT", 10_000)


@pytest.fixture(autouse=True)
def private_settings(monkeypatch, tmp_path_factory):
    """Tests must never read this PC's real settings file, its saved copy or where it remembers the file is."""
    monkeypatch.setenv("APPDATA", str(tmp_path_factory.mktemp("appdata")))
    monkeypatch.setenv("USERPROFILE", str(tmp_path_factory.mktemp("home")))
    write_settings(settings.file_path())
