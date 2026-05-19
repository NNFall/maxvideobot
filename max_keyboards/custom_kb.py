from __future__ import annotations

from math import ceil

from max_keyboards.builder import cb, inline_keyboard


def duration_kb(min_sec: int = 1, max_sec: int = 15, rows_count: int = 2):
    if max_sec < min_sec:
        max_sec = min_sec
    values = list(range(min_sec, max_sec + 1))
    per_row = max(1, ceil(len(values) / max(1, rows_count)))
    rows = []
    for i in range(0, len(values), per_row):
        rows.append([cb(f"{sec} сек", f"dur:{sec}") for sec in values[i : i + per_row]])
    rows.append([cb("🏠 Меню", "menu:main")])
    return inline_keyboard(rows)
