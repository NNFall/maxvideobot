from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXPECTED_BOT_ID = 281911477
RECOVERY_TEXT = (
    "<b>Отправка сообщений генератора в MAX восстановлена.</b>\n"
    "MAX разрешил отправку в ваш чат.\n"
    "Основной бот, рассылка и платежные задачи остаются остановленными. "
    "Для возобновления работы потребуется запуск бота."
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def admin_recipients(cfg) -> list[int]:
    recipients = set(cfg.admin_ids + cfg.admin_notify_ids)
    database = Path(cfg.database_path).resolve()
    # Read dynamic administrators without initializing or changing the database.
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        recipients.update(row[0] for row in connection.execute("SELECT user_id FROM admins"))
    return sorted(recipients)


async def check_access(bot, recipients: list[int], state: dict) -> dict:
    result = {"checked_at": utc_now(), "recipients": list(dict.fromkeys(recipients)),
              "notified": [], "failed": [], "status": "unreachable"}
    try:
        me = await asyncio.wait_for(bot.get_me(), timeout=30)
        if me.user_id != EXPECTED_BOT_ID:
            result["status"] = "wrong_bot"
        elif not result["recipients"]:
            result["status"] = "no_admins"
        else:
            for recipient in result["recipients"]:
                try:
                    await asyncio.wait_for(
                        bot.send_message(user_id=recipient, text=RECOVERY_TEXT), timeout=30
                    )
                except Exception as exc:
                    limited = "profile is limited" in str(exc).lower()
                    result["failed"].append({"recipient": recipient,
                                             "error_type": type(exc).__name__})
                    if limited:
                        result["profile_limited"] = True
                else:
                    result["notified"].append(recipient)
            if len(result["notified"]) == len(result["recipients"]):
                result["status"] = "available"
            elif result["notified"]:
                result["status"] = "partial_delivery"
            elif result.get("profile_limited"):
                result["status"] = "blocked"
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        if "profile is limited" in str(exc).lower():
            result["status"] = "blocked"

    state.update(status=result["status"], last_check=result)
    if result["notified"]:
        state["last_success_at"] = utc_now()
    return result


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, path)


async def main() -> None:
    from config import load_config
    from maxapi import Bot
    from maxapi.enums.parse_mode import ParseMode

    cfg = load_config()
    recipients = admin_recipients(cfg)
    path = Path(cfg.database_path).parent / "max_access_watch.json"
    bot = Bot(token=cfg.max_bot_token, format=ParseMode.HTML)
    bot.set_api_url(cfg.max_api_url.rstrip("/"))
    try:
        # Every scheduled run performs delivery checks, even after a previous success.
        state = {}
        result = await check_access(bot, recipients, state)
        save_state(path, state)
        print(json.dumps(result, ensure_ascii=False))
    finally:
        await bot.close_session()


if __name__ == "__main__":
    asyncio.run(main())
