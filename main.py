from __future__ import annotations

import asyncio
import logging

from maxapi import Bot, Dispatcher
from maxapi.enums.parse_mode import ParseMode
from maxapi.types import BotCommand

from config import load_config
from database.db import setup as setup_db
from max_handlers import all_routers
from max_handlers.router import pending_yookassa_watcher
from services.max_adapter import MaxBotAdapter
from services.smart_mailer import smart_mailing_loop
from services.subscription_tasks import subscription_watcher


async def _set_commands(bot: Bot) -> None:
    commands = [
        BotCommand(name="start", description="Запуск и главное меню"),
        BotCommand(name="menu", description="Главное меню"),
        BotCommand(name="balance", description="Баланс"),
        BotCommand(name="help", description="Помощь"),
        BotCommand(name="photo_ideas", description="Идеи для фото"),
        BotCommand(name="photo_edit", description="ИИ-Фотошоп"),
        BotCommand(name="image", description="Создать изображение"),
        BotCommand(name="effects", description="Видео-эффекты"),
        BotCommand(name="custom", description="Создать видео"),
        BotCommand(name="concat", description="Склеить видео"),
        BotCommand(name="cut", description="Вырезать фрагмент"),
        BotCommand(name="invite", description="Пригласить друга"),
    ]
    try:
        await bot.set_my_commands(*commands)
    except Exception as e:
        logging.getLogger(__name__).warning("Could not set MAX commands: %s", e)


async def main() -> None:
    cfg = load_config()
    if not cfg.max_bot_token:
        raise RuntimeError("MAX_BOT_TOKEN is empty. Fill .env")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    logger = logging.getLogger(__name__)

    await setup_db(cfg.database_path)

    bot = Bot(token=cfg.max_bot_token, format=ParseMode.HTML)
    adapter = MaxBotAdapter(bot)
    dp = Dispatcher()
    dp.include_routers(*all_routers)

    await _set_commands(bot)
    asyncio.create_task(subscription_watcher(adapter))
    asyncio.create_task(pending_yookassa_watcher(adapter))
    asyncio.create_task(smart_mailing_loop(adapter))

    try:
        if cfg.max_use_webhook:
            if not cfg.max_webhook_url:
                raise RuntimeError("MAX_WEBHOOK_URL is empty while MAX_USE_WEBHOOK=1")
            await bot.subscribe_webhook(cfg.max_webhook_url, secret=cfg.max_webhook_secret or None)
            logger.info("MAX webhook enabled: %s", cfg.max_webhook_url)
            await dp.handle_webhook(
                bot,
                host=cfg.max_webhook_host,
                port=cfg.max_webhook_port,
                path=cfg.max_webhook_path,
                secret=cfg.max_webhook_secret or None,
            )
        else:
            try:
                await bot.delete_webhook()
            except Exception:
                pass
            logger.info("MAX polling started")
            await dp.start_polling(bot, skip_updates=True)
    finally:
        await bot.close_session()


if __name__ == "__main__":
    asyncio.run(main())
