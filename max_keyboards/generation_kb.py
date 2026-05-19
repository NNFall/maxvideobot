from __future__ import annotations

from max_keyboards.builder import cb, inline_keyboard


def effect_done_kb(effect_id: int):
    return inline_keyboard([[cb("🔁 Сгенерировать еще", f"again:effect:{effect_id}")], [cb("🏠 Главное меню", "menu:main")]])


def custom_done_kb():
    return inline_keyboard([[cb("🔁 Сгенерировать еще", "again:custom")], [cb("🏠 Главное меню", "menu:main")]])


def photo_effect_done_kb(effect_id: int):
    return inline_keyboard([[cb("🔁 Сгенерировать еще", f"again:photo_effect:{effect_id}")], [cb("🏠 Главное меню", "menu:main")]])


def photo_custom_done_kb():
    return inline_keyboard([[cb("🔁 Сгенерировать еще", "again:photo_custom")], [cb("🏠 Главное меню", "menu:main")]])


def photo_text_done_kb():
    return inline_keyboard([[cb("🔁 Сгенерировать еще", "again:photo_text")], [cb("🏠 Главное меню", "menu:main")]])
