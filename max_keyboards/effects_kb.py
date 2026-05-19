from __future__ import annotations

from math import ceil

from max_keyboards.builder import cb, inline_keyboard


def effects_kb(
    effects: list[dict],
    page: int,
    per_page: int = 8,
    effect_prefix: str = "effect",
    nav_prefix: str = "nav",
):
    total = len(effects)
    total_pages = max(1, ceil(total / per_page))
    page = max(1, min(page, total_pages))

    start = (page - 1) * per_page
    current = effects[start : start + per_page]

    rows = [[cb(effect["button_name"], f"{effect_prefix}:{effect['id']}")] for effect in current]
    nav = []
    if page > 1:
        nav.append(cb("⬅️", f"{nav_prefix}:prev:{page - 1}"))
    if page < total_pages:
        nav.append(cb("➡️", f"{nav_prefix}:next:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([cb("🏠 Меню", "menu:main")])
    return inline_keyboard(rows)
