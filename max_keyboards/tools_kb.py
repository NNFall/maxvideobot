from __future__ import annotations

from max_keyboards.builder import cb, inline_keyboard


def tools_kb():
    return inline_keyboard(
        [
            [cb("📼 Склеить видео", "menu:concat")],
            [cb("✂️ Вырезать фрагмент", "menu:cut")],
            [cb("🏠 Меню", "menu:main")],
        ]
    )
