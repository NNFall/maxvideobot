from __future__ import annotations

from max_keyboards.builder import cb, inline_keyboard, link


SONG_BOT_URL = "https://max.ru/id644927208311_bot?start=gen"


def main_menu_kb():
    return inline_keyboard(
        [
            [cb("📸 Идеи для фото", "menu:photo_ideas")],
            [cb("🎨 ИИ-Фотошоп", "menu:photo_custom")],
            [cb("🖼 Создать изображение", "menu:photo_text")],
            [cb("✨ Видео-эффекты", "menu:effects")],
            [cb("🎬 Создать видео", "menu:custom")],
            [cb("📼 Инструменты", "menu:tools")],
            [link("🎤 Создать песню", SONG_BOT_URL)],
            [cb("💳 Баланс / Купить", "menu:balance")],
            [cb("❓ Помощь", "menu:help")],
        ]
    )
