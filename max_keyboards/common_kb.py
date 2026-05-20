from __future__ import annotations

from max_keyboards.builder import cb, inline_keyboard, link


def menu_only_kb():
    return inline_keyboard([[cb("🏠 Главное меню", "menu:main")]])


def help_kb(support_url: str):
    rows = []
    if support_url.startswith(("http://", "https://")):
        rows.append([link("🛟 Техподдержка", support_url)])
    rows.append([cb("🏠 Главное меню", "menu:main")])
    return inline_keyboard(rows)
