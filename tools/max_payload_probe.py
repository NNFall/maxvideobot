from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from dotenv import load_dotenv
from maxapi import Bot, Dispatcher, Router
from maxapi.enums.parse_mode import ParseMode


load_dotenv()

router = Router("payload_probe")


def _dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude={"bot"})
    if isinstance(value, dict):
        return value
    return {"repr": repr(value)}


def _short_payload(event: Any) -> str:
    data = _dump(event)
    return json.dumps(data, ensure_ascii=False, indent=2)[:3500]


async def _reply(event: Any, text: str) -> None:
    try:
        message = getattr(event, "message", None)
        if message is not None:
            await message.answer(text=text, format=ParseMode.HTML)
            return
        bot = event._ensure_bot()  # noqa: SLF001
        chat_id, user_id = event.get_ids()
        if user_id is not None:
            await bot.send_message(user_id=user_id, text=text, format=ParseMode.HTML)
        else:
            await bot.send_message(chat_id=chat_id, text=text, format=ParseMode.HTML)
    except Exception:
        logging.getLogger(__name__).exception("Probe reply failed")


@router.message_created()
async def on_message(event) -> None:
    logging.info("MESSAGE_CREATED\n%s", _short_payload(event))
    await _reply(event, "<b>probe</b>: MESSAGE_CREATED received. Payload printed to console.")


@router.message_callback()
async def on_callback(event) -> None:
    logging.info("MESSAGE_CALLBACK\n%s", _short_payload(event))
    await event.answer(notification="probe: callback received", raise_if_not_exists=False)


@router.bot_started()
async def on_started(event) -> None:
    logging.info("BOT_STARTED\n%s", _short_payload(event))
    await _reply(event, "<b>probe</b>: BOT_STARTED received. Payload printed to console.")


async def main() -> None:
    token = os.getenv("MAX_BOT_TOKEN")
    if not token:
        raise RuntimeError("MAX_BOT_TOKEN is empty")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    bot = Bot(token=token, format=ParseMode.HTML)
    dp = Dispatcher()
    dp.include_routers(router)
    try:
        await bot.delete_webhook()
    except Exception:
        pass
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
