import pytest

from punch_clock import reports


@pytest.fixture(autouse=True)
def allow_long_temp_paths(monkeypatch):
    """pytest's own temp folders are long enough to trip the path check."""
    monkeypatch.setattr(reports, "EXCEL_PATH_LIMIT", 10_000)
