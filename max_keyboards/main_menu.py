from __future__ import annotations

from max_keyboards.builder import cb, link, inline_keyboard


def main_menu_kb():
    return inline_keyboard(
        [
            [cb("📸 Идеи для фото", "menu:photo_ideas")],
            [cb("🎨 ИИ-Фотошоп", "menu:photo_custom")],
            [cb("🖼 Создать изображение", "menu:photo_text")],
            [cb("✨ Видео-эффекты", "menu:effects")],
            [cb("🎬 Создать видео", "menu:custom")],
            [cb("📼 Инструменты", "menu:tools")],
            [link("🎤 Создать песню", "https://t.me/your_trackbot?start=pl14")],
            [link("🖥 Создать презентацию", "https://t.me/slidesgenai_bot?start=pl6")],
            [cb("💳 Баланс / Купить", "menu:balance")],
            [cb("❓ Помощь", "menu:help")],
        ]
    )
