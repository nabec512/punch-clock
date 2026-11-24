"""Turn a weekly Jibble timesheet export into a printable supervisor report."""
from __future__ import annotations

import re
from typing import Optional

__version__ = "0.11.0"


def version_numbers(text: str) -> Optional[tuple[int, int, int]]:
    """A version such as 0.9.0 or v0.9.0 as numbers to compare, or None if it isn't written that way."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", text.strip())
    return (int(match[1]), int(match[2]), int(match[3])) if match else None
