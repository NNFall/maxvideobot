from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXPECTED_BOT_ID = 281911477
RECOVERY_CHAT_ID = 277384767
RECOVERY_TEXT = (
    "<b>Доступ к генератору в MAX восстановлен.</b>\n"
    "MAX принял это сообщение: ограничение отправки больше не действует "
    "в этом чате. Можно проверить /start и /menu, затем возобновить рассылку."
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


async def check_access(bot, recipient: int, state: dict, blocked_at: str | None,
                       persist=None) -> dict:
    checked_at = utc_now()
    if blocked_at:
        timestamp(blocked_at)
        if state.get("last_success_at") and timestamp(blocked_at) > timestamp(
            state["last_success_at"]
        ):
            state.update(status="blocked", last_blocked_at=blocked_at)
    try:
        me = await asyncio.wait_for(bot.get_me(), timeout=30)
        if me.user_id != EXPECTED_BOT_ID:
            return {"status": "wrong_bot", "checked_at": checked_at}

        last_success = state.get("last_success_at")
        # A new platform refusal arms one recovery notification again.
        if state.get("status") == "available" and not state.get(
            "pending_notification_at"
        ) and last_success and (
            not blocked_at or timestamp(blocked_at) <= timestamp(last_success)
        ):
            result = {"status": "no_new_refusal", "recovered": False,
                      "checked_at": checked_at, "last_success_at": last_success}
            state.update(last_check=result)
            return result

        pending_at = state.get("pending_notification_at")
        reconciled = False
        if pending_at:
            # Check delivery after a lost response before retrying the notification.
            started = timestamp(pending_at)
            history = await asyncio.wait_for(bot.get_messages(
                chat_id=RECOVERY_CHAT_ID, from_time=started,
                to_time=started + timedelta(seconds=120), count=100,
            ), timeout=30)
            last_blocked = state.get("last_blocked_at")
            cutoff = max(started, timestamp(last_blocked)) if last_blocked else started
            reconciled = any(
                message.sender and message.sender.user_id == EXPECTED_BOT_ID
                and message.timestamp / 1000 >= cutoff.timestamp()
                and "Доступ к генератору в MAX восстановлен." in (message.body.text or "")
                for message in history.messages
            )

        if not reconciled:
            state.update(pending_notification_at=utc_now())
            if persist:
                persist(state)
            await asyncio.wait_for(
                bot.send_message(user_id=recipient, text=RECOVERY_TEXT), timeout=30
            )
    except Exception as exc:
        limited = "profile is limited" in str(exc).lower()
        result = {"status": "blocked" if limited else "unreachable",
                  "checked_at": checked_at, "error_type": type(exc).__name__}
        if limited:
            state.update(status="blocked", last_blocked_at=checked_at)
            state.pop("pending_notification_at", None)
        state.update(last_check=result)
        return result

    confirmed_at = utc_now()
    state.update(status="available", last_success_at=confirmed_at)
    state.pop("pending_notification_at", None)
    result = {"status": "available", "recovered": True,
              "checked_at": checked_at, "last_success_at": confirmed_at,
              "notification_recipient": recipient}
    state.update(last_check=result)
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

    parser = argparse.ArgumentParser(description="One-shot MAX delivery recovery check")
    parser.add_argument("--recipient", type=int, required=True)
    parser.add_argument("--blocked-at", help="Newest Profile is limited log timestamp, UTC")
    parser.add_argument("--log-scan-at", help="Log scan start time for the next check")
    args = parser.parse_args()
    cfg = load_config()
    if args.recipient not in set(cfg.admin_ids + cfg.admin_notify_ids):
        raise SystemExit("Recovery recipient must be a configured administrator")
    if args.recipient != 4533898:
        raise SystemExit("Recovery chat is configured for administrator 4533898")
    path = Path(cfg.database_path).parent / "max_access_watch.json"
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if args.log_scan_at:
        timestamp(args.log_scan_at)
        state["last_log_scan_at"] = args.log_scan_at
    bot = Bot(token=cfg.max_bot_token, format=ParseMode.HTML)
    bot.set_api_url(cfg.max_api_url.rstrip("/"))
    try:
        result = await check_access(bot, args.recipient, state, args.blocked_at,
                                    persist=lambda value: save_state(path, value))
        save_state(path, state)
        print(json.dumps(result, ensure_ascii=False))
    finally:
        await bot.close_session()


if __name__ == "__main__":
    asyncio.run(main())
