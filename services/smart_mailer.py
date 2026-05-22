from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from html import escape

from config import load_config
from database import crud
from max_keyboards.builder import cb, inline_keyboard

logger = logging.getLogger(__name__)

SEND_RATE_PER_SEC = 25
PREVIEW_LEAD_SEC = 30 * 60
CYCLE_SLEEP_SEC = 12 * 60 * 60
PROGRESS_TICK_SEC = 60


def _html(value) -> str:
    return escape(str(value), quote=False)


def _effect_type_title(effect: dict) -> str:
    return "Фото" if effect.get("type") == "photo" else "Видео"


def _effect_admin_lines(effect: dict) -> str:
    return (
        f"Эффект: <b>{_html(effect['button_name'])}</b>\n"
        f"Тип: <b>{_effect_type_title(effect)}</b>\n"
        f"Effect ID: <code>{_html(effect.get('id') or '-')}</code>"
    )


def _promo_kb(effect_id: int, effect_type: str):
    prefix = "photo_effect" if effect_type == "photo" else "effect"
    text = "📸 Сделать фото" if effect_type == "photo" else "🎬 Сделать видео"
    return inline_keyboard([[cb(text, f"{prefix}:{effect_id}")]])


def _pick_next_effect(effects: list[dict], last_effect_id: int | None) -> dict | None:
    if not effects:
        return None
    if last_effect_id is None:
        return effects[0]
    for idx, effect in enumerate(effects):
        if int(effect["id"]) == int(last_effect_id):
            return effects[(idx + 1) % len(effects)]
    return effects[0]


async def _send_promo(bot, user_id: int, effect: dict) -> str:
    effect_type = effect.get("type") or "video"
    text = f"Попробуйте этот эффект! 👇\n<b>{_html(effect['button_name'])}</b>"
    demo = effect.get("demo_file_id")
    demo_type = effect.get("demo_type")
    kb = _promo_kb(int(effect["id"]), effect_type)
    try:
        if demo:
            try:
                if demo_type == "photo":
                    await bot.send_photo(user_id, demo, caption=text, reply_markup=kb)
                else:
                    await bot.send_video(user_id, demo, caption=text, reply_markup=kb)
            except Exception as e:
                logger.warning("Mailer: demo send failed, fallback to text user_id=%s effect_id=%s error=%s", user_id, effect.get("id"), e)
                await bot.send_message(user_id, text, reply_markup=kb)
        else:
            await bot.send_message(user_id, text, reply_markup=kb)
        return "sent"
    except Exception as e:
        msg = str(e).lower()
        if "blocked" in msg or "forbidden" in msg:
            logger.info("Mailer: user blocked bot user_id=%s", user_id)
            return "blocked"
        logger.warning("Mailer: send failed user_id=%s error=%s", user_id, e)
        return "failed"


def _admin_ids(cfg) -> list[int]:
    return [int(x) for x in (cfg.admin_notify_ids or cfg.admin_ids)]


async def _send_preview(bot, admin_ids: list[int], effect: dict) -> None:
    for admin_id in admin_ids:
        try:
            await bot.send_message(
                admin_id,
                "⚠️ <b>Внимание!</b> Через 30 минут начнется автоматическая рассылка.\n"
                f"{_effect_admin_lines(effect)}",
            )
            await _send_promo(bot, admin_id, effect)
        except Exception:
            continue


def _progress_text(sent: int, total: int, errors: int) -> str:
    percent = int((sent / total) * 100) if total else 0
    return (
        "⏳ <b>Идет рассылка...</b>\n"
        f"Отправлено: {sent} из {total} ({percent}%)\n"
        f"Ошибок/Блокировок: {errors}"
    )


async def _choose_effect(cfg, state: dict) -> tuple[dict | None, str | None]:
    video_effects = await crud.list_effects(cfg.database_path, active_only=True, effect_type="video")
    photo_effects = await crud.list_effects(cfg.database_path, active_only=True, effect_type="photo")
    if not video_effects and not photo_effects:
        return None, None
    last_type = state.get("last_type") or "photo"
    next_type = "photo" if last_type == "video" else "video"
    if next_type == "photo" and photo_effects:
        return _pick_next_effect(photo_effects, state.get("last_photo_id")), "photo"
    if next_type == "video" and video_effects:
        return _pick_next_effect(video_effects, state.get("last_video_id")), "video"
    if video_effects:
        return _pick_next_effect(video_effects, state.get("last_video_id")), "video"
    return _pick_next_effect(photo_effects, state.get("last_photo_id")), "photo"


async def smart_mailing_loop(bot) -> None:
    cfg = load_config()
    delay = 1 / SEND_RATE_PER_SEC
    admin_ids = _admin_ids(cfg)

    while True:
        try:
            state = await crud.get_mailer_state(cfg.database_path) or {}
            next_run_at = None
            if state.get("updated_at"):
                try:
                    next_run_at = datetime.fromisoformat(state["updated_at"]) + timedelta(seconds=CYCLE_SLEEP_SEC)
                except Exception:
                    next_run_at = None

            effect = None
            next_type = None
            if next_run_at:
                preview_at = next_run_at - timedelta(seconds=PREVIEW_LEAD_SEC)
                now = datetime.utcnow()
                if now < preview_at:
                    await asyncio.sleep((preview_at - now).total_seconds())
                effect, next_type = await _choose_effect(cfg, state)
                if effect and admin_ids:
                    await _send_preview(bot, admin_ids, effect)
                if datetime.utcnow() < next_run_at:
                    await asyncio.sleep((next_run_at - datetime.utcnow()).total_seconds())

            if effect is None:
                effect, next_type = await _choose_effect(cfg, state)
            if not effect or not next_type:
                await asyncio.sleep(60 * 60)
                continue

            now_iso = datetime.utcnow().isoformat(timespec="seconds")
            active = set(await crud.list_active_subscription_user_ids(cfg.database_path, now_iso))
            target_ids = [uid for uid in await crud.list_user_ids(cfg.database_path) if uid not in active]
            total = len(target_ids)

            progress_msgs: dict[int, str] = {}
            for admin_id in admin_ids:
                try:
                    msg = await bot.send_message(
                        admin_id,
                        "🚀 <b>Рассылка началась!</b>\n"
                        f"{_effect_admin_lines(effect)}\n"
                        f"Целевая аудитория: <b>{total}</b> чел.",
                    )
                    mid = getattr(getattr(msg, "message", None), "body", None)
                    progress_msgs[admin_id] = getattr(mid, "mid", None) or getattr(msg, "message_id", "")
                except Exception:
                    continue

            sent = blocked = failed = 0
            last_tick = datetime.utcnow()
            for user_id in target_ids:
                now_iso = datetime.utcnow().isoformat(timespec="seconds")
                if await crud.is_subscription_active(cfg.database_path, user_id, now_iso):
                    continue
                status = await _send_promo(bot, user_id, effect)
                if status == "sent":
                    sent += 1
                elif status == "blocked":
                    blocked += 1
                else:
                    failed += 1
                await asyncio.sleep(delay)

                if progress_msgs and (datetime.utcnow() - last_tick).total_seconds() >= PROGRESS_TICK_SEC:
                    last_tick = datetime.utcnow()
                    for admin_id, msg_id in list(progress_msgs.items()):
                        if msg_id:
                            try:
                                await bot.edit_message_text(_progress_text(sent, total, blocked + failed), chat_id=admin_id, message_id=msg_id)
                            except Exception:
                                pass

            finish_text = (
                "✅ <b>Рассылка завершена.</b>\n"
                f"Успешно доставлено: <b>{sent}</b>\n"
                f"Не доставлено (бот заблокирован): <b>{blocked}</b>\n"
                "Следующая рассылка через 12 часов."
            )
            if failed:
                finish_text += f"\nОшибок: <b>{failed}</b>"
            for admin_id, msg_id in list(progress_msgs.items()):
                try:
                    if msg_id:
                        await bot.edit_message_text(finish_text, chat_id=admin_id, message_id=msg_id)
                    else:
                        await bot.send_message(admin_id, finish_text)
                except Exception:
                    pass

            if next_type == "photo":
                await crud.set_mailer_state(cfg.database_path, int(effect["id"]), last_type="photo", last_photo_id=int(effect["id"]))
            else:
                await crud.set_mailer_state(cfg.database_path, int(effect["id"]), last_type="video", last_video_id=int(effect["id"]))

            logger.info("Mailer done effect_id=%s type=%s sent=%s blocked=%s failed=%s", effect["id"], next_type, sent, blocked, failed)
        except Exception as e:
            logger.exception("Mailer loop error: %s", e)
            await asyncio.sleep(60)
