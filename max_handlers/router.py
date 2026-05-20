from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from maxapi import Router

from config import load_config
from database import crud
from max_handlers.state import clear_state, set_state, state_data, state_name, update_state
from max_handlers.utils import (
    answer_callback,
    answer_callback_message,
    callback_payload,
    get_bot,
    get_media_source,
    get_target_id,
    get_text,
    get_user_id,
    get_username,
    parse_command,
)
from max_keyboards.common_kb import help_kb, menu_only_kb
from max_keyboards.custom_kb import duration_kb
from max_keyboards.effects_kb import effects_kb
from max_keyboards.main_menu import main_menu_kb
from max_keyboards.payment_kb import (
    choose_subscription_kb,
    choose_subscription_prompt_kb,
    methods_kb,
    pay_url_kb,
    payment_success_kb,
    subscription_manage_kb,
)
from max_keyboards.tools_kb import tools_kb
from services import yookassa as yk
from services.balance_card import build_inactive_balance_text
from services.ffmpeg_service import check_ffmpeg, concat_videos, remove_fragment
from services.generation import (
    run_custom_generation,
    run_effect_generation,
    run_photo_custom_generation,
    run_photo_effect_generation,
    run_text_image_generation,
)
from services.max_adapter import MaxBotAdapter
from services.notify import notify_admin
from services.subscriptions import calc_period, get_plan, get_plans

router = Router("max_video_bot")
config = load_config()
logger = logging.getLogger(__name__)

POLL_INTERVAL = 30
POLL_TIMEOUT = 1800
EFFECT_DURATION_SEC = 6
DOWNLOAD_LIMIT_MB = 50
DOWNLOAD_LIMIT_BYTES = DOWNLOAD_LIMIT_MB * 1024 * 1024

_pending_yoo_tasks: dict[int, asyncio.Task] = {}
_payment_locks: dict[int, asyncio.Lock] = {}
GENERATION_RUNNING_STATE = "generation_running"


def _adapter(event) -> MaxBotAdapter:
    return MaxBotAdapter(get_bot(event))


def _target(event) -> int:
    target = get_target_id(event)
    if target is None:
        raise RuntimeError("MAX event has no target id")
    return int(target)


def _parse_start_payload(args: list[str]) -> str | None:
    return args[0].strip() if args else None


def _bot_link(username: str | None = None) -> str:
    base = config.max_bot_link_base.rstrip("/")
    if not base:
        base = "https://max.ru"
    if username and base in {"https://max.ru", "http://max.ru"}:
        return f"{base}/{username}"
    return base


def _start_link(payload: str, username: str | None = None) -> str:
    base = _bot_link(username)
    joiner = "&" if "?" in base else "?"
    return f"{base}{joiner}start={payload}"


async def _process_start(bot: MaxBotAdapter, target_id: int, user_id: int, payload: str | None, username: str | None = None) -> None:
    utm_source = referrer_id = promo_code = None
    if payload:
        payload = payload.strip()
        if payload.startswith("ref_") and payload[4:].isdigit():
            referrer_id = int(payload[4:])
            if referrer_id == user_id:
                referrer_id = None
        elif payload.startswith("promo_"):
            promo_code = payload[6:]
        else:
            utm_source = payload

    is_new = await crud.add_user(config.database_path, user_id, utm_source, referrer_id)
    if is_new and config.effect_cost > 0:
        await crud.update_balance(config.database_path, user_id, config.effect_cost)
        await bot.send_message(target_id, f"🎁 Бонус новичка: 1 бесплатная генерация ({config.effect_cost} токенов).")

    if promo_code:
        credits = await crud.use_promocode(config.database_path, promo_code, user_id)
        if credits:
            await crud.update_balance(config.database_path, user_id, credits)
            await bot.send_message(target_id, f"🎁 Промокод активирован. Начислено {credits} токенов.")
        else:
            await bot.send_message(target_id, "Промокод недействителен или уже использован.")

    if is_new:
        tag = utm_source or "без метки"
        await notify_admin(bot, config.admin_notify_ids, f"👤 Новый пользователь: {user_id} (@{username or '-'}), метка: {tag}")

    await _send_main(
        bot,
        target_id,
        "🎬 <b>Генератор Фото Видео ИИ</b>\n"
        "Создавай короткие видео из фото за пару минут.\n\n"
        "📸 <b>Идеи для фото</b> — готовые стили\n"
        "🎨 <b>ИИ-Фотошоп</b> — свой промпт для фото\n"
        "🖼 <b>Создать изображение</b> — по тексту\n"
        "✨ <b>Видео-эффекты</b> — готовые стили\n"
        "🎬 <b>Создать видео</b> — свой промпт\n"
        "📼 <b>Инструменты</b> — склейка и обрезка\n\n"
        "Выбирайте раздел ниже 👇",
    )


def _format_date(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d")
    except Exception:
        return value


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _get_pending_action(data: dict) -> dict | None:
    payload = data.get("pending_action")
    if not payload:
        return None
    if isinstance(payload, dict):
        return payload
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


async def _ensure_user(user_id: int) -> None:
    await crud.add_user(config.database_path, user_id)


async def _run_generation(user_id: int, generation_coro) -> bool:
    generation_id = uuid.uuid4().hex
    set_state(user_id, GENERATION_RUNNING_STATE, generation_id=generation_id)
    try:
        return await generation_coro
    finally:
        data = state_data(user_id)
        if state_name(user_id) == GENERATION_RUNNING_STATE and data.get("generation_id") == generation_id:
            clear_state(user_id)


async def _is_admin(user_id: int) -> bool:
    return user_id in config.admin_ids or await crud.is_admin(config.database_path, user_id)


def _is_owner(user_id: int) -> bool:
    return user_id in config.admin_ids


async def _send_main(bot: MaxBotAdapter, target_id: int, text: str | None = None) -> None:
    await bot.send_message(
        target_id,
        text
        or (
            "🏠 <b>Главное меню</b>\n"
            "Выбирайте раздел ниже 👇"
        ),
        reply_markup=main_menu_kb(),
    )


async def _show_help(bot: MaxBotAdapter, target_id: int) -> None:
    support_line = "" if config.support_contact.startswith(("http://", "https://")) else f"\n\nПоддержка: {config.support_contact}"
    await bot.send_message(
        target_id,
        "❓ <b>Помощь</b>\n"
        "1) Выберите идею или свой промпт\n"
        "2) Отправьте фото и получите результат\n"
        "3) Для склейки пришлите два видео подряд\n"
        "4) Для вырезания фрагмента отправьте видео и таймкоды"
        f"{support_line}",
        reply_markup=help_kb(config.support_contact),
    )


async def _show_invite(bot: MaxBotAdapter, target_id: int, user_id: int) -> None:
    try:
        me = await bot.get_me()
        username = getattr(me, "username", None)
    except Exception:
        username = None
    link = _start_link(f"ref_{user_id}", username)
    await bot.send_message(
        target_id,
        "🤝 <b>Пригласить друга</b>\n"
        "Отправьте другу вашу персональную ссылку.\n"
        f"Бонус: <b>{config.ref_bonus}</b> токенов после первой покупки друга.\n\n"
        f"Ваша ссылка:\n<code>{link}</code>",
        reply_markup=menu_only_kb(),
    )


async def _show_balance(bot: MaxBotAdapter, target_id: int, user_id: int) -> None:
    await _expire_if_needed(user_id)
    balance = await crud.get_balance(config.database_path, user_id)
    sub = await crud.get_subscription(config.database_path, user_id)
    plans = get_plans()

    is_active = sub and sub.get("status") == "active" and int(sub.get("auto_renew", 0)) == 1
    if is_active:
        plan = get_plan(sub["plan_id"])
        plan_title = f"{plan.price_rub} ₽ / {plan.title} — {plan.generations} токенов" if plan else sub["plan_id"]
        await bot.send_message(
            target_id,
            "✅ <b>Подписка активна</b>\n"
            f"Тариф: <b>{plan_title}</b>\n"
            f"Остаток токенов: <b>{balance}</b>\n"
            f"Обновление токенов: <b>{_format_date(sub['current_period_end'])}</b>",
            reply_markup=subscription_manage_kb(sub["plan_id"], int(sub["auto_renew"]) == 1),
        )
        return

    text = await build_inactive_balance_text(bot, balance, include_header=True)
    await bot.send_message(target_id, text, reply_markup=choose_subscription_prompt_kb(), disable_web_page_preview=True)


async def _show_effects(bot: MaxBotAdapter, target_id: int, effect_type: str, page: int = 1, edit_event=None) -> None:
    effects = await crud.list_effects(config.database_path, active_only=True, effect_type=effect_type)
    if not effects:
        text = "⚠️ Эффекты еще не добавлены."
        kb = menu_only_kb()
        if edit_event is not None and await answer_callback_message(edit_event, text, kb):
            return
        await bot.send_message(target_id, text, reply_markup=kb)
        return

    if effect_type == "photo":
        text = "📸 <b>Идеи для фото</b>\nВыберите шаблон для обработки фото."
        kb = effects_kb(effects, page=page, effect_prefix="photo_effect", nav_prefix="photo_nav")
    else:
        text = (
            "✨ <b>Видео-эффекты</b>\n"
            "Выберите шаблон для видео из фото.\n"
            f"Длительность: <b>{EFFECT_DURATION_SEC}</b> сек."
        )
        kb = effects_kb(effects, page=page, effect_prefix="effect", nav_prefix="nav")
    if edit_event is not None and await answer_callback_message(edit_event, text, kb):
        return
    await bot.send_message(target_id, text, reply_markup=kb)


async def _select_effect(bot: MaxBotAdapter, target_id: int, user_id: int, effect_id: int, effect_type: str) -> None:
    effect = await crud.get_effect(config.database_path, effect_id)
    if not effect or not effect.get("is_active") or effect.get("type") != effect_type:
        await bot.send_message(target_id, "⚠️ Эффект недоступен.", reply_markup=menu_only_kb())
        return

    demo = effect.get("demo_file_id")
    if demo:
        try:
            if effect.get("demo_type") == "photo":
                await bot.send_photo(target_id, demo)
            else:
                await bot.send_video(target_id, demo)
        except Exception as e:
            logger.warning("Demo send failed effect_id=%s error=%s", effect_id, e)

    if effect_type == "photo":
        await bot.send_message(
            target_id,
            "🖼 <b>Хочешь такое же фото?</b>\n"
            f"Стоимость: <b>{config.photo_effect_cost}</b> токенов.\n"
            "Пришлите фотографию, и я обработаю ее в этом стиле 👇",
        )
        set_state(user_id, "photo_effect_waiting_photo", effect_id=effect_id)
    else:
        await bot.send_message(
            target_id,
            "🎞 <b>Хочешь такое же видео?</b>\n"
            f"Стоимость: <b>{config.effect_cost}</b> токенов.\n"
            f"Длительность: <b>{EFFECT_DURATION_SEC}</b> сек.\n"
            "Пришлите фотографию, и я анимирую ее в этом стиле 👇",
        )
        set_state(user_id, "effect_waiting_photo", effect_id=effect_id)


async def _start_custom(bot: MaxBotAdapter, target_id: int, user_id: int) -> None:
    clear_state(user_id)
    await bot.send_message(
        target_id,
        "📝 <b>Свой промпт</b>\n"
        "Пришлите фото и текстовый запрос. Можно по отдельности.\n"
        "Пример: <i>пусть девушка надевает черные очки</i>.\n"
        f"Цена: <b>{config.custom_cost_per_sec}</b> токенов за секунду.\n"
        "Длительность: <b>1-15</b> сек.",
    )
    set_state(user_id, "custom_waiting_photo_text")


async def _start_photo_custom(bot: MaxBotAdapter, target_id: int, user_id: int) -> None:
    clear_state(user_id)
    await bot.send_message(
        target_id,
        "🎨 <b>ИИ-Фотошоп</b>\n"
        "Пришлите фото и описание того, как его изменить. Можно по отдельности.\n"
        "Пример: <i>добавь в руки большой букет роз</i>.",
    )
    set_state(user_id, "photo_custom_waiting_photo_text")


async def _start_photo_text(bot: MaxBotAdapter, target_id: int, user_id: int) -> None:
    clear_state(user_id)
    await bot.send_message(
        target_id,
        "🖼 <b>Создать изображение</b>\n"
        "Пришлите текстовый запрос, и я сгенерирую изображение.\n"
        "Пример: <i>человек на Эвересте с кока-колой</i>.",
    )
    set_state(user_id, "photo_text_waiting_prompt")


async def _paywall(bot: MaxBotAdapter, target_id: int, user_id: int, pending_action: dict, balance: int) -> None:
    update_state(user_id, pending_action=json.dumps(pending_action))
    balance_text = await build_inactive_balance_text(bot, balance, include_header=False)
    await bot.send_message(
        target_id,
        f"⚠️ <b>Недостаточно токенов.</b>\n\n{balance_text}",
        reply_markup=choose_subscription_prompt_kb(),
        disable_web_page_preview=True,
    )


async def _persist_pending_media(bot: MaxBotAdapter, user_id: int, source: str, suffix: str = ".jpg") -> str:
    pending_path = Path(config.media_temp_dir) / f"pending_{user_id}_{uuid.uuid4().hex}{suffix}"
    try:
        await bot.download(source, pending_path)
        return str(pending_path)
    except Exception as e:
        logger.warning("Pending media cache failed user_id=%s source=%s error=%s", user_id, source, e)
        return source


async def _persist_demo_media(bot: MaxBotAdapter, user_id: int, source: str, demo_type: str) -> str:
    suffix = ".mp4" if demo_type == "video" else ".jpg"
    demo_dir = Path(config.media_demo_dir)
    demo_dir.mkdir(parents=True, exist_ok=True)
    demo_path = demo_dir / f"demo_{user_id}_{uuid.uuid4().hex}{suffix}"
    await bot.download(source, demo_path)
    return str(demo_path)


def _cleanup_pending_media(source: str | None) -> None:
    if not source:
        return
    try:
        path = Path(source)
        if not path.exists() or not path.name.startswith("pending_"):
            return
        root = Path(config.media_temp_dir).resolve()
        resolved = path.resolve()
        if root == resolved.parent or root in resolved.parents:
            resolved.unlink(missing_ok=True)
    except Exception:
        pass


async def _cleanup_pending_action_for_tx(tx_id: int) -> None:
    pending = await crud.consume_pending_action(config.database_path, tx_id)
    if not pending:
        return
    try:
        payload = json.loads(pending.get("action_payload") or "{}")
    except json.JSONDecodeError:
        return
    _cleanup_pending_media(payload.get("photo_file_id"))


async def _handle_photo_effect_state(event, bot: MaxBotAdapter, user_id: int, target_id: int, mode: str) -> None:
    source, width, height = get_media_source(event, "image")
    if not source:
        await bot.send_message(target_id, "📸 Нужна фотография. Пришлите фото.")
        return

    data = state_data(user_id)
    effect_id = int(data.get("effect_id") or 0)
    effect = await crud.get_effect(config.database_path, effect_id) if effect_id else None
    if not effect:
        await bot.send_message(target_id, "⚠️ Эффект не найден. Попробуйте снова.", reply_markup=menu_only_kb())
        clear_state(user_id)
        return

    username = get_username(event)
    if mode == "photo":
        cost = config.photo_effect_cost
        balance = await crud.get_balance(config.database_path, user_id)
        if balance < cost:
            pending_source = await _persist_pending_media(bot, user_id, source)
            await _paywall(bot, target_id, user_id, {"type": "photo_effect", "effect_id": effect_id, "photo_file_id": pending_source, "username": username}, balance)
            return
        await _run_generation(user_id, run_photo_effect_generation(bot, user_id, target_id, effect_id, source, username=username))
    else:
        cost = config.effect_cost
        balance = await crud.get_balance(config.database_path, user_id)
        if balance < cost:
            pending_source = await _persist_pending_media(bot, user_id, source)
            await _paywall(
                bot,
                target_id,
                user_id,
                {"type": "effect", "effect_id": effect_id, "photo_file_id": pending_source, "duration": EFFECT_DURATION_SEC, "username": username},
                balance,
            )
            return
        await _run_generation(user_id, run_effect_generation(bot, user_id, target_id, effect_id, source, username=username))


async def _handle_custom_photo_text(event, bot: MaxBotAdapter, user_id: int, target_id: int, photo_mode: bool) -> None:
    text = get_text(event)
    source, width, height = get_media_source(event, "image")
    data = state_data(user_id)
    prompt = data.get("prompt")
    photo_file_id = data.get("photo_file_id")
    photo_width = data.get("photo_width")
    photo_height = data.get("photo_height")

    if source:
        photo_file_id = source
        photo_width = width
        photo_height = height
        if text:
            prompt = text
    elif text:
        prompt = text

    update_state(user_id, photo_file_id=photo_file_id, photo_width=photo_width, photo_height=photo_height, prompt=prompt)

    if not photo_file_id:
        await bot.send_message(target_id, "📸 Пришлите фото.")
        return
    if not prompt:
        await bot.send_message(target_id, "✍️ Пришлите текстовый запрос.")
        return

    if photo_mode:
        balance = await crud.get_balance(config.database_path, user_id)
        if balance < config.photo_custom_cost:
            pending_source = await _persist_pending_media(bot, user_id, photo_file_id)
            await _paywall(bot, target_id, user_id, {"type": "photo_custom", "photo_file_id": pending_source, "prompt": prompt, "username": get_username(event)}, balance)
            return
        await _run_generation(user_id, run_photo_custom_generation(bot, user_id, target_id, photo_file_id, prompt, username=get_username(event)))
        return

    await bot.send_message(
        target_id,
        "⏱ <b>Выберите длительность</b>\n"
        f"Цена: <b>{config.custom_cost_per_sec}</b> токенов за секунду.\n"
        "Доступно: <b>1-15</b> сек.",
        reply_markup=duration_kb(1, 15),
    )
    set_state(user_id, "custom_waiting_duration", photo_file_id=photo_file_id, photo_width=photo_width, photo_height=photo_height, prompt=prompt)


async def _handle_photo_text(event, bot: MaxBotAdapter, user_id: int, target_id: int) -> None:
    prompt = get_text(event)
    if not prompt:
        await bot.send_message(target_id, "✍️ Пришлите текстовый запрос.")
        return
    balance = await crud.get_balance(config.database_path, user_id)
    if balance < config.photo_custom_cost:
        await _paywall(bot, target_id, user_id, {"type": "photo_text", "prompt": prompt, "username": get_username(event)}, balance)
        return
    await _run_generation(user_id, run_text_image_generation(bot, user_id, target_id, prompt, username=get_username(event)))


async def _handle_duration(event, bot: MaxBotAdapter, user_id: int, target_id: int, duration: int) -> None:
    if duration < 1 or duration > 15:
        await bot.send_message(target_id, "⚠️ Допустимая длительность: от 1 до 15 секунд.")
        return
    data = state_data(user_id)
    photo_file_id = data.get("photo_file_id")
    prompt = data.get("prompt")
    if not photo_file_id or not prompt:
        await bot.send_message(target_id, "⚠️ Данные потеряны. Начните заново.", reply_markup=menu_only_kb())
        clear_state(user_id)
        return
    cost = duration * config.custom_cost_per_sec
    balance = await crud.get_balance(config.database_path, user_id)
    if balance < cost:
        pending_source = await _persist_pending_media(bot, user_id, photo_file_id)
        await _paywall(
            bot,
            target_id,
            user_id,
            {
                "type": "custom",
                "photo_file_id": pending_source,
                "prompt": prompt,
                "duration": duration,
                "photo_width": data.get("photo_width"),
                "photo_height": data.get("photo_height"),
                "username": get_username(event),
            },
            balance,
        )
        return
    await _run_generation(
        user_id,
        run_custom_generation(
            bot,
            user_id,
            target_id,
            photo_file_id,
            prompt,
            duration,
            photo_width=data.get("photo_width"),
            photo_height=data.get("photo_height"),
            username=get_username(event),
        ),
    )


async def _start_concat(bot: MaxBotAdapter, target_id: int, user_id: int) -> None:
    clear_state(user_id)
    if not check_ffmpeg(config.ffmpeg_path):
        await bot.send_message(target_id, "⚠️ <b>FFmpeg не найден.</b>\nУстановите ffmpeg и укажите путь в <code>FFMPEG_PATH</code>.")
        return
    await bot.send_message(target_id, "📼 <b>Склейка видео</b>\nПришлите первое видео.")
    set_state(user_id, "concat_waiting_video1")


async def _start_cut(bot: MaxBotAdapter, target_id: int, user_id: int) -> None:
    clear_state(user_id)
    if not check_ffmpeg(config.ffmpeg_path):
        await bot.send_message(target_id, "⚠️ <b>FFmpeg не найден.</b>\nУстановите ffmpeg и укажите путь в <code>FFMPEG_PATH</code>.")
        return
    await bot.send_message(target_id, "✂️ <b>Вырезать фрагмент</b>\nПришлите видео, из которого нужно убрать часть.")
    set_state(user_id, "cut_waiting_video")


async def _download_video_from_event(event, bot: MaxBotAdapter, dest: Path) -> bool:
    source, _, _ = get_media_source(event, "video")
    if not source:
        return False
    await bot.download(source, dest)
    if dest.stat().st_size > DOWNLOAD_LIMIT_BYTES:
        dest.unlink(missing_ok=True)
        return False
    return True


async def _handle_concat1(event, bot: MaxBotAdapter, user_id: int, target_id: int) -> None:
    temp_dir = Path(config.media_temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    path1 = temp_dir / f"concat_{user_id}_{uuid.uuid4().hex}_1.mp4"
    try:
        ok = await _download_video_from_event(event, bot, path1)
    except Exception as e:
        logger.error("Concat download1 error user_id=%s error=%s", user_id, e)
        ok = False
    if not ok:
        await bot.send_message(target_id, f"📼 Нужен видеофайл до {DOWNLOAD_LIMIT_MB} МБ. Пришлите первое видео.")
        return
    set_state(user_id, "concat_waiting_video2", video1=str(path1))
    await bot.send_message(target_id, "📼 Теперь пришлите второе видео.")


async def _handle_concat2(event, bot: MaxBotAdapter, user_id: int, target_id: int) -> None:
    data = state_data(user_id)
    path1 = data.get("video1")
    if not path1:
        await bot.send_message(target_id, "Данные потеряны. Начните заново.", reply_markup=menu_only_kb())
        clear_state(user_id)
        return

    temp_dir = Path(config.media_temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    path2 = temp_dir / f"concat_{user_id}_{uuid.uuid4().hex}_2.mp4"
    output = temp_dir / f"concat_{user_id}_{uuid.uuid4().hex}_out.mp4"
    try:
        ok = await _download_video_from_event(event, bot, path2)
        if not ok:
            await bot.send_message(target_id, f"📼 Нужен видеофайл до {DOWNLOAD_LIMIT_MB} МБ. Пришлите второе видео.")
            return
        await asyncio.to_thread(concat_videos, [path1, str(path2)], str(output), config.ffmpeg_path)
        await bot.send_video(target_id, str(output))
        await notify_admin(bot, config.admin_notify_ids, f"✅ Склейка видео выполнена. Пользователь {user_id} (@{get_username(event) or '-'})")
    except Exception as e:
        logger.error("Concat error user_id=%s error=%s", user_id, e)
        await bot.send_message(target_id, "❌ Ошибка склейки видео. Проверьте формат и попробуйте снова.")
        await notify_admin(bot, config.admin_notify_ids, f"❌ Ошибка FFmpeg: {e} (user {user_id} @{get_username(event) or '-'})")
    finally:
        for item in (path1, str(path2), str(output)):
            try:
                Path(item).unlink(missing_ok=True)
            except Exception:
                pass
        clear_state(user_id)


def _parse_timecodes(text: str) -> tuple[int, int] | None:
    if "-" not in text:
        return None
    left, right = text.split("-", 1)

    def to_seconds(value: str) -> int | None:
        parts = value.strip().split(":")
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            return None
        mm = int(parts[0])
        ss = int(parts[1])
        if ss > 59:
            return None
        return mm * 60 + ss

    start = to_seconds(left)
    end = to_seconds(right)
    if start is None or end is None or end <= start:
        return None
    return start, end


async def _handle_cut_video(event, bot: MaxBotAdapter, user_id: int, target_id: int) -> None:
    temp_dir = Path(config.media_temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    input_path = temp_dir / f"cut_{user_id}_{uuid.uuid4().hex}.mp4"
    try:
        ok = await _download_video_from_event(event, bot, input_path)
    except Exception as e:
        logger.error("Cut download error user_id=%s error=%s", user_id, e)
        ok = False
    if not ok:
        await bot.send_message(target_id, f"✂️ Нужен видеофайл до {DOWNLOAD_LIMIT_MB} МБ. Пришлите видео.")
        return
    set_state(user_id, "cut_waiting_timecodes", input_path=str(input_path))
    await bot.send_message(
        target_id,
        "⏱ <b>Таймкоды удаления</b>\n"
        "Введите интервал, который нужно вырезать, в формате <code>мм:сс-мм:сс</code>\n"
        "Например: <code>00:05-00:09</code>.",
    )


async def _handle_cut_timecodes(event, bot: MaxBotAdapter, user_id: int, target_id: int) -> None:
    parsed = _parse_timecodes(get_text(event))
    if not parsed:
        await bot.send_message(target_id, "Неверный формат. Пример: <code>00:05-00:09</code>.")
        return

    data = state_data(user_id)
    input_path = data.get("input_path")
    if not input_path:
        await bot.send_message(target_id, "Данные потеряны. Начните заново.", reply_markup=menu_only_kb())
        clear_state(user_id)
        return

    temp_dir = Path(config.media_temp_dir)
    output = temp_dir / f"cut_{user_id}_{uuid.uuid4().hex}_out.mp4"
    start_sec, end_sec = parsed
    try:
        await asyncio.to_thread(remove_fragment, str(input_path), start_sec, end_sec, str(output), config.ffmpeg_path)
        await bot.send_video(target_id, str(output))
        await notify_admin(bot, config.admin_notify_ids, f"✅ Вырезан фрагмент. Пользователь {user_id} (@{get_username(event) or '-'})")
    except Exception as e:
        logger.error("Cut error user_id=%s error=%s", user_id, e)
        await bot.send_message(target_id, "❌ Ошибка обработки видео. Проверьте формат и попробуйте снова.")
        await notify_admin(bot, config.admin_notify_ids, f"❌ Ошибка FFmpeg (cut): {e} (user {user_id} @{get_username(event) or '-'})")
    finally:
        for item in (input_path, str(output)):
            try:
                Path(item).unlink(missing_ok=True)
            except Exception:
                pass
        clear_state(user_id)


async def _expire_if_needed(user_id: int) -> None:
    sub = await crud.get_subscription(config.database_path, user_id)
    if not sub or sub.get("status") not in ("active", "inactive") or int(sub.get("auto_renew", 0)) == 1:
        return
    try:
        end = datetime.fromisoformat(sub["current_period_end"])
    except Exception:
        return
    if datetime.utcnow() >= end:
        await crud.mark_subscription_status(config.database_path, user_id, "expired")
        await crud.set_balance(config.database_path, user_id, 0)


async def _guard_pending_payment(user_id: int, provider: str | None, bot: MaxBotAdapter) -> bool:
    tx = await crud.get_pending_transaction_by_user(config.database_path, user_id, provider)
    if not tx:
        return False
    created_at = _parse_datetime(tx.get("created_at"))
    if created_at and (datetime.utcnow() - created_at).total_seconds() > POLL_TIMEOUT:
        await crud.update_transaction_status(config.database_path, int(tx["id"]), "expired")
        await _cleanup_pending_action_for_tx(int(tx["id"]))
        return False
    await bot.send_message(user_id, "⏳ Оплата уже создана. Завершите предыдущую или дождитесь результата.")
    return True


def _build_receipt(amount_rub: int) -> dict | None:
    email = config.yookassa_receipt_email.strip() if config.yookassa_receipt_email else ""
    phone = config.yookassa_receipt_phone.strip() if config.yookassa_receipt_phone else ""
    tax_system = (config.yookassa_tax_system_code or "").strip()
    if not tax_system or (not email and not phone):
        return None
    item = {
        "description": (config.yookassa_item_name or "Подписка на токены").strip(),
        "quantity": "1.00",
        "amount": {"value": f"{amount_rub:.2f}", "currency": "RUB"},
        "vat_code": int(config.yookassa_vat_code) if str(config.yookassa_vat_code).isdigit() else 1,
    }
    if config.yookassa_payment_subject:
        item["payment_subject"] = config.yookassa_payment_subject
    if config.yookassa_payment_mode:
        item["payment_mode"] = config.yookassa_payment_mode
    return {
        "tax_system_code": int(tax_system),
        "items": [item],
        "customer": {"email": email} if email else {"phone": phone},
    }


async def _apply_subscription(user_id: int, plan_id: str, provider: str, auto_renew: int, payment_method_id: str | None) -> None:
    plan = get_plan(plan_id)
    if not plan:
        return
    start, end = calc_period(plan.days)
    await crud.set_balance(config.database_path, user_id, plan.generations)
    await crud.upsert_subscription(
        config.database_path,
        user_id=user_id,
        plan_id=plan.id,
        provider=provider,
        auto_renew=auto_renew,
        payment_method_id=payment_method_id,
        current_period_start=start,
        current_period_end=end,
        status="active",
    )

    user = await crud.get_user(config.database_path, user_id)
    if user and int(user.get("has_purchased", 0)) == 0:
        await crud.set_has_purchased(config.database_path, user_id, 1)
        referrer_id = await crud.get_referrer(config.database_path, user_id)
        rewarded = await crud.get_referrer_rewarded(config.database_path, user_id)
        if referrer_id and not rewarded:
            await crud.update_balance(config.database_path, referrer_id, config.ref_bonus)
            await crud.set_referrer_rewarded(config.database_path, user_id, 1)


def _parse_tx_payload(tx: dict) -> dict:
    try:
        return json.loads(tx.get("payload") or "{}")
    except Exception:
        return {}


async def _handle_pending_action(tx_id: int, user_id: int, bot: MaxBotAdapter) -> None:
    pending = await crud.consume_pending_action(config.database_path, tx_id)
    if not pending:
        return
    try:
        payload = json.loads(pending["action_payload"])
    except json.JSONDecodeError:
        return

    action_type = payload.get("type")
    username = payload.get("username")
    try:
        if action_type == "effect":
            await run_effect_generation(bot, user_id, user_id, int(payload["effect_id"]), payload["photo_file_id"], username=username)
        elif action_type == "photo_effect":
            await run_photo_effect_generation(bot, user_id, user_id, int(payload["effect_id"]), payload["photo_file_id"], username=username)
        elif action_type == "custom":
            await run_custom_generation(
                bot,
                user_id,
                user_id,
                payload["photo_file_id"],
                payload["prompt"],
                int(payload["duration"]),
                photo_width=payload.get("photo_width"),
                photo_height=payload.get("photo_height"),
                username=username,
            )
        elif action_type == "photo_custom":
            await run_photo_custom_generation(bot, user_id, user_id, payload["photo_file_id"], payload["prompt"], username=username)
        elif action_type == "photo_text":
            await run_text_image_generation(bot, user_id, user_id, payload["prompt"], username=username)
    finally:
        _cleanup_pending_media(payload.get("photo_file_id"))


async def _poll_yookassa_payment(bot: MaxBotAdapter, tx_id: int, user_id: int, username: str | None = None) -> None:
    try:
        start = asyncio.get_running_loop().time()
        while True:
            tx = await crud.get_transaction(config.database_path, tx_id)
            if not tx or tx["status"] == "paid":
                return
            try:
                payment = await asyncio.to_thread(yk.get_payment, tx["provider_payment_id"])
            except Exception as e:
                logger.error("YooKassa poll error tx_id=%s error=%s", tx_id, e)
                await asyncio.sleep(POLL_INTERVAL)
                continue

            status = getattr(payment, "status", "unknown")
            logger.info("YooKassa status tx_id=%s status=%s", tx_id, status)
            if status == "succeeded":
                await crud.update_transaction_status(config.database_path, tx_id, "paid")
                payload = _parse_tx_payload(tx)
                plan_id = payload.get("plan_id")
                if plan_id:
                    payment_method_id = None
                    try:
                        if payment.payment_method and getattr(payment.payment_method, "id", None):
                            payment_method_id = payment.payment_method.id
                    except Exception:
                        payment_method_id = None
                    auto_renew = 1 if payload.get("auto_renew") and payment_method_id else 0
                    provider = "yookassa" if auto_renew else "yookassa_once"
                    await _apply_subscription(user_id, plan_id, provider, auto_renew, payment_method_id)
                    await bot.send_message(user_id, "✅ Подписка активирована. Токены начислены.", reply_markup=payment_success_kb())
                    kind = "Продлил подписку" if payload.get("renew_now") else "Успешная оплата"
                    await notify_admin(bot, config.admin_notify_ids, f"💰 {kind} (ЮKassa). Пользователь {user_id} (@{username or '-'}) , план {plan_id}")
                else:
                    await bot.send_message(user_id, "✅ Оплата прошла успешно.", reply_markup=payment_success_kb())
                await _handle_pending_action(tx_id, user_id, bot)
                return

            if status == "canceled":
                await crud.update_transaction_status(config.database_path, tx_id, "expired")
                await _cleanup_pending_action_for_tx(tx_id)
                return

            if asyncio.get_running_loop().time() - start > POLL_TIMEOUT:
                await crud.update_transaction_status(config.database_path, tx_id, "expired")
                await _cleanup_pending_action_for_tx(tx_id)
                return
            await asyncio.sleep(POLL_INTERVAL)
    finally:
        _pending_yoo_tasks.pop(tx_id, None)


async def pending_yookassa_watcher(bot: MaxBotAdapter) -> None:
    while True:
        try:
            pending = await crud.list_pending_transactions(config.database_path, provider="yookassa")
            pending += await crud.list_pending_transactions(config.database_path, provider="yookassa_once")
            for tx in pending:
                tx_id = int(tx["id"])
                task = _pending_yoo_tasks.get(tx_id)
                if task and not task.done():
                    continue
                created_at = _parse_datetime(tx.get("created_at"))
                if created_at and (datetime.utcnow() - created_at).total_seconds() > POLL_TIMEOUT:
                    await crud.update_transaction_status(config.database_path, tx_id, "expired")
                    await _cleanup_pending_action_for_tx(tx_id)
                    continue
                _pending_yoo_tasks[tx_id] = asyncio.create_task(_poll_yookassa_payment(bot, tx_id, int(tx["user_id"])))
        except Exception:
            logger.exception("Pending YooKassa watcher failed")
        await asyncio.sleep(POLL_INTERVAL)


async def _start_yoo_payment(bot: MaxBotAdapter, user_id: int, plan_id: str, *, auto_renew: bool, renew_now: bool = False, username: str | None = None) -> None:
    provider = "yookassa" if auto_renew else "yookassa_once"
    lock = _payment_locks.setdefault(user_id, asyncio.Lock())
    if lock.locked():
        await bot.send_message(user_id, "⏳ Оплата уже создается. Подождите пару секунд.")
        return
    async with lock:
        if await _guard_pending_payment(user_id, None, bot):
            return
        plan = get_plan(plan_id)
        if not plan:
            await bot.send_message(user_id, "Тариф не найден.")
            return
        try:
            yk.configure(config.yookassa_shop_id, config.yookassa_secret_key)
        except Exception as e:
            await bot.send_message(user_id, "ЮKassa не настроена. Проверьте ключи.")
            await notify_admin(bot, config.admin_notify_ids, f"❌ YooKassa config error: {e}")
            return

        try:
            me = await bot.get_me()
            username_bot = getattr(me, "username", None)
        except Exception:
            username_bot = None
        return_url = _bot_link(username_bot)
        payment = await asyncio.to_thread(
            yk.create_payment,
            amount_rub=plan.price_rub,
            description=f"Подписка {plan.title}",
            return_url=return_url,
            metadata={"user_id": user_id, "plan_id": plan.id},
            save_payment_method=auto_renew,
            receipt=_build_receipt(plan.price_rub),
        )
        tx_id = await crud.create_transaction(
            config.database_path,
            user_id=user_id,
            amount=plan.price_rub,
            currency="RUB",
            credits=plan.generations,
            provider=provider,
            status="pending",
            provider_payment_id=payment.id,
            payload=json.dumps({"plan_id": plan.id, "days": plan.days, "auto_renew": auto_renew, "renew_now": renew_now}),
        )

        pending = _get_pending_action(state_data(user_id))
        if pending:
            await crud.create_pending_action(config.database_path, tx_id, user_id, pending.get("type", "unknown"), json.dumps(pending))
            clear_state(user_id)

        await bot.send_message(
            user_id,
            "Оплата через ЮKassa. Нажмите кнопку ниже и завершите оплату.",
            reply_markup=pay_url_kb(payment.confirmation.confirmation_url),
        )
        _pending_yoo_tasks[tx_id] = asyncio.create_task(_poll_yookassa_payment(bot, tx_id, user_id, username=username))


async def _renew_yoo(bot: MaxBotAdapter, user_id: int, plan_id: str, username: str | None = None) -> None:
    plan = get_plan(plan_id)
    if not plan:
        await bot.send_message(user_id, "Тариф не найден.")
        return
    sub = await crud.get_subscription(config.database_path, user_id)
    if sub and int(sub.get("auto_renew", 0)) == 1 and sub.get("payment_method_id"):
        try:
            yk.configure(config.yookassa_shop_id, config.yookassa_secret_key)
            payment = await asyncio.to_thread(
                yk.create_recurrent_payment,
                plan.price_rub,
                f"Подписка {plan.title} - продление",
                sub["payment_method_id"],
                {"user_id": user_id, "plan_id": plan.id},
                _build_receipt(plan.price_rub),
            )
        except Exception as e:
            await bot.send_message(user_id, "Не удалось выполнить списание. Попробуйте позже.")
            if "payment_method_id" in str(e):
                await crud.cancel_subscription(config.database_path, user_id)
            await notify_admin(bot, config.admin_notify_ids, f"❌ Продление не удалось (ошибка списания): {e}")
            return
        tx_id = await crud.create_transaction(
            config.database_path,
            user_id=user_id,
            amount=plan.price_rub,
            currency="RUB",
            credits=plan.generations,
            provider="yookassa",
            status="pending",
            provider_payment_id=payment.id,
            payload=json.dumps({"plan_id": plan.id, "days": plan.days, "auto_renew": True, "renew_now": True}),
        )
        _pending_yoo_tasks[tx_id] = asyncio.create_task(_poll_yookassa_payment(bot, tx_id, user_id, username=username))
        await bot.send_message(user_id, "🔄 Запрос на продление отправлен. Ожидаем подтверждение оплаты.")
        return
    await _start_yoo_payment(bot, user_id, plan_id, auto_renew=True, renew_now=True, username=username)


async def _handle_payment_callback(payload: str, bot: MaxBotAdapter, user_id: int) -> bool:
    if payload == "sub:choose":
        await bot.send_message(user_id, "Выберите подписку 👇", reply_markup=choose_subscription_kb(get_plans()))
        return True
    if payload.startswith("sub:choose:yoo:") or payload.startswith("sub:method:yoo:"):
        await _start_yoo_payment(bot, user_id, payload.rsplit(":", 1)[1], auto_renew=True)
        return True
    if payload.startswith("sub:choose:once:") or payload.startswith("sub:method:once:"):
        await _start_yoo_payment(bot, user_id, payload.rsplit(":", 1)[1], auto_renew=False)
        return True
    if payload.startswith("sub:plan:"):
        plan_id = payload.rsplit(":", 1)[1]
        plan = get_plan(plan_id)
        if not plan:
            await bot.send_message(user_id, "Тариф не найден.")
        else:
            await bot.send_message(user_id, f"Тариф: <b>{plan.generations} токенов</b>.\nВыберите способ оплаты:", reply_markup=methods_kb(plan_id))
        return True
    if payload == "sub:renew_choose":
        await bot.send_message(user_id, "🔄 <b>Обновить подписку</b>\nВыберите тариф для продления:", reply_markup=choose_subscription_kb(get_plans(), cb_yoo_prefix="sub:renew:yoo", cb_once_prefix="sub:renew:once"))
        return True
    if payload.startswith("sub:renew:yoo:"):
        await _renew_yoo(bot, user_id, payload.rsplit(":", 1)[1])
        return True
    if payload.startswith("sub:renew:once:"):
        await _start_yoo_payment(bot, user_id, payload.rsplit(":", 1)[1], auto_renew=False, renew_now=True)
        return True
    if payload == "sub:cancel":
        sub = await crud.get_subscription(config.database_path, user_id)
        if not sub:
            await bot.send_message(user_id, "Подписка не найдена.")
            return True
        end_date = _format_date(sub.get("current_period_end") or "неизвестно")
        await crud.cancel_subscription(config.database_path, user_id)
        await bot.send_message(user_id, "✅ Подписка отменена. Автопродление отключено.")
        await bot.send_message(user_id, f"Текущие токены доступны до <b>{end_date}</b>.")
        await notify_admin(bot, config.admin_notify_ids, f"❌ Отключил подписку. Пользователь {user_id}")
        return True
    return False


async def _handle_admin_command(event, bot: MaxBotAdapter, user_id: int, target_id: int, command: str, args: list[str]) -> bool:
    if command not in {
        "admin_help",
        "add_session",
        "session_del",
        "sub_on",
        "sub_off",
        "sub_check",
        "sub_cancel",
        "adstats",
        "adstats_all",
        "botstats",
        "adtag",
        "genpromo",
        "set_top",
        "get_prompt",
        "admin_add",
        "admin_del",
        "admin_list",
    }:
        return False
    if not await _is_admin(user_id):
        await bot.send_message(target_id, "Команда доступна только администратору.")
        return True

    if command == "admin_help":
        await bot.send_message(
            target_id,
            "<b>Админ-команды</b>\n"
            "/add_session\n/session_del\n/sub_on &lt;ID&gt; &lt;amount&gt;\n/sub_off &lt;ID&gt;\n/sub_check &lt;ID&gt;\n/sub_cancel &lt;ID&gt;\n"
            "/adstats &lt;метка&gt;\n/adstats_all\n/botstats\n/adtag &lt;метка&gt;\n/genpromo &lt;кол-во&gt;\n/set_top\n/get_prompt\n"
            "/admin_add &lt;ID&gt;\n/admin_del &lt;ID&gt;\n/admin_list",
        )
    elif command == "add_session":
        set_state(user_id, "admin_add_type")
        from max_keyboards.builder import cb, inline_keyboard

        await bot.send_message(target_id, "Это эффект для ФОТО или для ВИДЕО?", reply_markup=inline_keyboard([[cb("Фото", "admin_add_type:photo"), cb("Видео", "admin_add_type:video")]]))
    elif command == "session_del":
        effects = await crud.list_effects(config.database_path, active_only=True)
        if not effects:
            await bot.send_message(target_id, "Эффектов нет.")
        else:
            from max_keyboards.builder import cb, inline_keyboard

            await bot.send_message(target_id, "Выберите эффект для удаления:", reply_markup=inline_keyboard([[cb(e["button_name"], f"admin_del:{e['id']}")] for e in effects[:50]]))
    elif command == "sub_on":
        if len(args) < 2 or not args[0].isdigit() or not args[1].isdigit():
            await bot.send_message(target_id, "Использование: /sub_on <code>ID amount</code>")
        else:
            await crud.update_balance(config.database_path, int(args[0]), int(args[1]))
            await bot.send_message(target_id, f"Начислено {args[1]} токенов пользователю {args[0]}.")
    elif command == "sub_off":
        if not args or not args[0].isdigit():
            await bot.send_message(target_id, "Использование: /sub_off <code>ID</code>")
        else:
            await crud.set_balance(config.database_path, int(args[0]), 0)
            await bot.send_message(target_id, f"Баланс пользователя {args[0]} обнулен.")
    elif command == "sub_check":
        if not args or not args[0].isdigit():
            await bot.send_message(target_id, "Использование: /sub_check <code>ID</code>")
        else:
            balance = await crud.get_balance(config.database_path, int(args[0]))
            sub = await crud.get_subscription(config.database_path, int(args[0]))
            await bot.send_message(target_id, f"Баланс пользователя {args[0]}: <b>{balance}</b> токенов\nПодписка: <code>{sub or '-'}</code>")
    elif command == "sub_cancel":
        if not args or not args[0].isdigit():
            await bot.send_message(target_id, "Использование: /sub_cancel <code>ID</code>")
        else:
            await crud.cancel_subscription(config.database_path, int(args[0]))
            await bot.send_message(target_id, f"Подписка пользователя {args[0]} отключена.")
    elif command == "adstats":
        if not args:
            await bot.send_message(target_id, "Использование: /adstats <code>метка</code>")
        else:
            tag = args[0]
            users = await crud.count_users_by_utm(config.database_path, tag)
            buyers = await crud.count_buyers_by_utm(config.database_path, tag)
            payments = await crud.sum_payments_by_utm(config.database_path, tag)
            await bot.send_message(target_id, f"<b>Статистика метки</b> <code>{tag}</code>\nПользователи: {users}\nПокупатели: {buyers}\nПлатежи: {payments}")
    elif command == "adstats_all":
        stats = await crud.list_utm_stats(config.database_path)
        lines = ["<b>UTM-статистика</b>"]
        for row in stats[:30]:
            lines.append(f"<code>{row.get('utm_source') or 'без метки'}</code>: {row.get('users', 0)} / buyers {row.get('buyers', 0)}")
        await bot.send_message(target_id, "\n".join(lines))
    elif command == "botstats":
        users = await crud.count_users(config.database_path)
        paid_users = await crud.count_paid_users(config.database_path)
        active = await crud.count_active_subscriptions(config.database_path, datetime.utcnow().isoformat(timespec="seconds"))
        sums = await crud.sum_paid_by_currency(config.database_path)
        await bot.send_message(target_id, f"<b>Статистика бота</b>\nПользователи: {users}\nПлатившие: {paid_users}\nАктивные подписки: {active}\nОплаты: {sums}")
    elif command == "adtag":
        if not args:
            await bot.send_message(target_id, "Использование: /adtag <code>метка</code>")
        else:
            try:
                me = await bot.get_me()
                username = getattr(me, "username", None)
            except Exception:
                username = None
            link = _start_link(args[0], username)
            await bot.send_message(target_id, f"Ссылка для метки <code>{args[0]}</code>:\n<code>{link}</code>")
    elif command == "genpromo":
        if not args or not args[0].isdigit():
            await bot.send_message(target_id, "Использование: /genpromo <code>кол-во</code>")
        else:
            code = uuid.uuid4().hex[:10].upper()
            await crud.create_promocode(config.database_path, code, int(args[0]))
            await bot.send_message(target_id, f"Промокод создан: <code>{code}</code>")
    elif command in {"set_top", "get_prompt"}:
        effects = await crud.list_effects(config.database_path, active_only=True)
        from max_keyboards.builder import cb, inline_keyboard

        prefix = "admin_top" if command == "set_top" else "admin_prompt"
        await bot.send_message(target_id, "Выберите эффект:", reply_markup=inline_keyboard([[cb(e["button_name"], f"{prefix}:{e['id']}")] for e in effects[:50]]))
    elif command == "admin_list":
        admins = await crud.list_admins(config.database_path)
        await bot.send_message(target_id, "Админы:\n" + "\n".join(f"- {a}" for a in admins) if admins else "Админов нет.")
    elif command == "admin_add":
        if not _is_owner(user_id):
            await bot.send_message(target_id, "Только owner.")
        elif not args or not args[0].isdigit():
            await bot.send_message(target_id, "Использование: /admin_add <code>ID</code>")
        else:
            await crud.add_admin(config.database_path, int(args[0]), user_id)
            await bot.send_message(target_id, f"Админ добавлен: {args[0]}")
    elif command == "admin_del":
        if not _is_owner(user_id):
            await bot.send_message(target_id, "Только owner.")
        elif not args or not args[0].isdigit():
            await bot.send_message(target_id, "Использование: /admin_del <code>ID</code>")
        else:
            await crud.remove_admin(config.database_path, int(args[0]))
            await bot.send_message(target_id, f"Админ удален: {args[0]}")
    return True


async def _handle_admin_state(event, bot: MaxBotAdapter, user_id: int, target_id: int, name: str) -> bool:
    if not name.startswith("admin_"):
        return False
    if not await _is_admin(user_id):
        clear_state(user_id)
        return True

    text = get_text(event)
    if name == "admin_add_name":
        if not text:
            await bot.send_message(target_id, "Название не может быть пустым.")
            return True
        set_state(user_id, "admin_add_prompt", **state_data(user_id), button_name=text)
        await bot.send_message(target_id, "Теперь отправьте промпт.")
    elif name == "admin_add_prompt":
        if not text:
            await bot.send_message(target_id, "Промпт не может быть пустым.")
            return True
        set_state(user_id, "admin_add_demo", **state_data(user_id), prompt=text)
        await bot.send_message(target_id, 'Пришлите демо-видео или фото. Если примера нет, напишите "нет".')
    elif name == "admin_add_demo":
        data = state_data(user_id)
        demo_file_id = None
        demo_type = None
        if text.lower() not in {"нет", "no", "-"}:
            source, _, _ = get_media_source(event, "image")
            if source:
                demo_type = "photo"
                try:
                    demo_file_id = await _persist_demo_media(bot, user_id, source, demo_type)
                except Exception as e:
                    logger.warning("Admin demo photo persist failed user_id=%s error=%s", user_id, e)
                    demo_file_id = source
            else:
                source, _, _ = get_media_source(event, "video")
                if source:
                    demo_type = "video"
                    try:
                        demo_file_id = await _persist_demo_media(bot, user_id, source, demo_type)
                    except Exception as e:
                        logger.warning("Admin demo video persist failed user_id=%s error=%s", user_id, e)
                        demo_file_id = source
        effect_id = await crud.add_effect(
            config.database_path,
            data["button_name"],
            data["prompt"],
            demo_file_id=demo_file_id,
            demo_type=demo_type,
            effect_type=data.get("effect_type", "video"),
        )
        clear_state(user_id)
        await bot.send_message(target_id, f"Эффект добавлен (ID: {effect_id}).")
    return True


@router.bot_started()
async def handle_bot_started(event) -> None:
    user_id = get_user_id(event)
    if user_id is None:
        return
    target_id = _target(event)
    bot = _adapter(event)
    clear_state(user_id)
    await _process_start(bot, target_id, user_id, getattr(event, "payload", None), get_username(event))


@router.message_callback()
async def handle_callback(event) -> None:
    user_id = get_user_id(event)
    if user_id is None:
        return
    await _ensure_user(user_id)
    target_id = _target(event)
    bot = _adapter(event)
    payload = callback_payload(event)
    callback_edits_message = payload.startswith("nav:") or payload.startswith("photo_nav:")
    if not callback_edits_message:
        await answer_callback(event)

    if payload == "menu:main":
        clear_state(user_id)
        await _send_main(bot, target_id)
    elif payload == "menu:help":
        await _show_help(bot, target_id)
    elif payload == "menu:invite":
        await _show_invite(bot, target_id, user_id)
    elif payload == "menu:balance":
        await _show_balance(bot, target_id, user_id)
    elif payload == "menu:effects":
        await _show_effects(bot, target_id, "video")
    elif payload == "menu:photo_ideas":
        await _show_effects(bot, target_id, "photo")
    elif payload == "menu:custom":
        await _start_custom(bot, target_id, user_id)
    elif payload == "menu:photo_custom":
        await _start_photo_custom(bot, target_id, user_id)
    elif payload == "menu:photo_text":
        await _start_photo_text(bot, target_id, user_id)
    elif payload == "menu:tools":
        clear_state(user_id)
        await bot.send_message(target_id, "📼 <b>Инструменты</b>\nВыберите действие:", reply_markup=tools_kb())
    elif payload == "menu:concat":
        await _start_concat(bot, target_id, user_id)
    elif payload == "menu:cut":
        await _start_cut(bot, target_id, user_id)
    elif payload.startswith("nav:"):
        page = int(payload.rsplit(":", 1)[1]) if payload.rsplit(":", 1)[1].isdigit() else 1
        await _show_effects(bot, target_id, "video", page, edit_event=event)
    elif payload.startswith("photo_nav:"):
        page = int(payload.rsplit(":", 1)[1]) if payload.rsplit(":", 1)[1].isdigit() else 1
        await _show_effects(bot, target_id, "photo", page, edit_event=event)
    elif payload.startswith("effect:"):
        value = payload.split(":", 1)[1]
        if value.isdigit():
            await _select_effect(bot, target_id, user_id, int(value), "video")
    elif payload.startswith("photo_effect:"):
        value = payload.split(":", 1)[1]
        if value.isdigit():
            await _select_effect(bot, target_id, user_id, int(value), "photo")
    elif payload.startswith("again:effect:"):
        value = payload.rsplit(":", 1)[1]
        if value.isdigit():
            set_state(user_id, "effect_waiting_photo", effect_id=int(value))
            await bot.send_message(target_id, "🎞 Пришлите новую фотографию для этого эффекта 👇")
    elif payload.startswith("again:photo_effect:"):
        value = payload.rsplit(":", 1)[1]
        if value.isdigit():
            set_state(user_id, "photo_effect_waiting_photo", effect_id=int(value))
            await bot.send_message(target_id, "🖼 Пришлите новую фотографию для этого эффекта 👇")
    elif payload == "again:custom":
        await _start_custom(bot, target_id, user_id)
    elif payload == "again:photo_custom":
        await _start_photo_custom(bot, target_id, user_id)
    elif payload == "again:photo_text":
        await _start_photo_text(bot, target_id, user_id)
    elif payload.startswith("dur:") and state_name(user_id) == "custom_waiting_duration":
        value = payload.split(":", 1)[1]
        if value.isdigit():
            await _handle_duration(event, bot, user_id, target_id, int(value))
    elif payload.startswith("admin_add_type:") and await _is_admin(user_id):
        effect_type = payload.rsplit(":", 1)[1]
        set_state(user_id, "admin_add_name", effect_type=effect_type)
        await bot.send_message(target_id, "Введите название кнопки.")
    elif payload.startswith("admin_del:") and await _is_admin(user_id):
        effect_id = int(payload.rsplit(":", 1)[1])
        await crud.deactivate_effect(config.database_path, effect_id)
        await bot.send_message(target_id, "Эффект удален.")
    elif payload.startswith("admin_top:") and await _is_admin(user_id):
        effect_id = int(payload.rsplit(":", 1)[1])
        await crud.set_effect_top(config.database_path, effect_id)
        await bot.send_message(target_id, "Эффект поднят в ТОП.")
    elif payload.startswith("admin_prompt:") and await _is_admin(user_id):
        effect_id = int(payload.rsplit(":", 1)[1])
        effect = await crud.get_effect(config.database_path, effect_id)
        await bot.send_message(target_id, f"<b>{effect['button_name']}</b>\n<code>{effect['prompt']}</code>" if effect else "Эффект не найден.")
    elif await _handle_payment_callback(payload, bot, user_id):
        return


@router.message_created()
async def handle_message(event) -> None:
    user_id = get_user_id(event)
    if user_id is None:
        return
    target_id = _target(event)
    bot = _adapter(event)
    text = get_text(event)
    parsed = parse_command(text)

    if parsed:
        command, args = parsed
        if command == "start":
            clear_state(user_id)
            payload = _parse_start_payload(args)
            await _process_start(bot, target_id, user_id, payload, get_username(event))
            return

        await _ensure_user(user_id)
        if await _handle_admin_command(event, bot, user_id, target_id, command, args):
            return
        if command == "menu":
            clear_state(user_id)
            await _send_main(bot, target_id)
        elif command == "balance":
            await _show_balance(bot, target_id, user_id)
        elif command == "help":
            await _show_help(bot, target_id)
        elif command == "invite":
            await _show_invite(bot, target_id, user_id)
        elif command == "effects":
            await _show_effects(bot, target_id, "video")
        elif command == "photo_ideas":
            await _show_effects(bot, target_id, "photo")
        elif command == "custom":
            await _start_custom(bot, target_id, user_id)
        elif command == "photo_edit":
            await _start_photo_custom(bot, target_id, user_id)
        elif command == "image":
            await _start_photo_text(bot, target_id, user_id)
        elif command == "concat":
            await _start_concat(bot, target_id, user_id)
        elif command == "cut":
            await _start_cut(bot, target_id, user_id)
        else:
            await bot.send_message(target_id, "Выберите режим ниже 👇", reply_markup=main_menu_kb())
        return

    await _ensure_user(user_id)
    name = state_name(user_id)
    if name and await _handle_admin_state(event, bot, user_id, target_id, name):
        return
    if name == "effect_waiting_photo":
        await _handle_photo_effect_state(event, bot, user_id, target_id, "video")
    elif name == "photo_effect_waiting_photo":
        await _handle_photo_effect_state(event, bot, user_id, target_id, "photo")
    elif name == "custom_waiting_photo_text":
        await _handle_custom_photo_text(event, bot, user_id, target_id, photo_mode=False)
    elif name == "photo_custom_waiting_photo_text":
        await _handle_custom_photo_text(event, bot, user_id, target_id, photo_mode=True)
    elif name == "photo_text_waiting_prompt":
        await _handle_photo_text(event, bot, user_id, target_id)
    elif name == "concat_waiting_video1":
        await _handle_concat1(event, bot, user_id, target_id)
    elif name == "concat_waiting_video2":
        await _handle_concat2(event, bot, user_id, target_id)
    elif name == "cut_waiting_video":
        await _handle_cut_video(event, bot, user_id, target_id)
    elif name == "cut_waiting_timecodes":
        await _handle_cut_timecodes(event, bot, user_id, target_id)
    elif name == GENERATION_RUNNING_STATE:
        await bot.send_message(target_id, "⏳ Генерация уже запущена. Результат пришлю сюда, меню и команды доступны.")
    else:
        await bot.send_message(target_id, "Выберите режим ниже 👇", reply_markup=main_menu_kb())
