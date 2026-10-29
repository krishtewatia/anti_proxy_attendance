"""CSV files that teachers open in Excel.

Excel guesses each cell's type: a 13-digit roll number becomes ``2.4E+12`` and
``1/1`` becomes a date. Roll numbers are therefore written as text formulas
(``="2401331540096"``), and the file starts with a byte-order mark so Excel
reads it as UTF-8 (names with accents or Indic letters stay readable).
"""

from __future__ import annotations

import csv
import io
from typing import Any, Iterable

BOM = "\ufeff"


def excel_text(value: Any) -> str:
    """A cell Excel keeps as written: long digit strings are wrapped as text."""
    text = "" if value is None else str(value)
    return f'="{text}"' if text.isdigit() and len(text) > 5 else text


def to_csv(rows: Iterable[list[Any]]) -> str:
    out = io.StringIO()
    out.write(BOM)
    csv.writer(out).writerows(rows)
    return out.getvalue()
