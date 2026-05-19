from __future__ import annotations

from max_keyboards.builder import cb, inline_keyboard


def menu_only_kb():
    return inline_keyboard([[cb("🏠 Главное меню", "menu:main")]])
