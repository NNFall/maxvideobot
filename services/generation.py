from __future__ import annotations

import asyncio
import re
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from config import load_config
from database import crud
from services.kie_api import (
    upload_file,
    create_task,
    poll_task,
    extract_result_url,
    create_image_task,
    extract_result_urls,
)
from services.replicate_api import (
    create_prediction,
    create_image_prediction,
    poll_prediction,
    extract_output_url,
    extract_output_urls as extract_replicate_output_urls,
    encode_image,
    closest_aspect_ratio,
)
from services.logging_utils import shorten, format_user
from services.notify import notify_admin
from max_keyboards.generation_kb import (
    effect_done_kb,
    custom_done_kb,
    photo_effect_done_kb,
    photo_custom_done_kb,
    photo_text_done_kb,
)
from max_keyboards.common_kb import menu_only_kb

logger = logging.getLogger(__name__)
REPLICATE_MAX_ATTEMPTS = 3
REPLICATE_ATTEMPT_TIMEOUT_SEC = 90
REPLICATE_POLL_INTERVAL_SEC = 10
REPLICATE_VIDEO_MAX_ATTEMPTS = 3
REPLICATE_VIDEO_TOTAL_TIMEOUT_SEC = 600
REPLICATE_VIDEO_ATTEMPT_TIMEOUT_SEC = REPLICATE_VIDEO_TOTAL_TIMEOUT_SEC // REPLICATE_VIDEO_MAX_ATTEMPTS
KIE_FALLBACK_DURATION_SEC = 6
GENERATION_MAX_ATTEMPTS = 3
GENERATION_RETRY_DELAY_SEC = 2


def _is_replicate_sensitive_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        'flagged as sensitive' in msg
        or '(e005)' in msg
        or 'code: e005' in msg
    )


def _is_replicate_no_retry_error(exc: Exception) -> bool:
    msg = str(exc)
    return (
        'status=402' in msg
        or 'Insufficient credit' in msg
        or 'status=422' in msg
        or 'Unprocessable Entity' in msg
        or _is_replicate_sensitive_error(exc)
    )


def _is_kie_policy_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        'inappropriate content' in msg
        or 'flagged by website as violating content policies' in msg
        or 'violating content policies' in msg
        or 'content policies' in msg
    )


def _build_user_error_message(exc: Exception) -> str:
    if _is_replicate_sensitive_error(exc) or _is_kie_policy_error(exc):
        return (
            '\u26a0\ufe0f \u0417\u0430\u043f\u0440\u043e\u0441 \u043e\u0442\u043a\u043b\u043e\u043d\u0435\u043d \u0444\u0438\u043b\u044c\u0442\u0440\u043e\u043c \u0431\u0435\u0437\u043e\u043f\u0430\u0441\u043d\u043e\u0441\u0442\u0438.\\n'
            '\u0418\u0437\u043c\u0435\u043d\u0438\u0442\u0435 \u0444\u043e\u0440\u043c\u0443\u043b\u0438\u0440\u043e\u0432\u043a\u0443 \u0437\u0430\u043f\u0440\u043e\u0441\u0430 \u0438\u043b\u0438 \u0444\u043e\u0442\u043e \u0438 \u043f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u0441\u043d\u043e\u0432\u0430.\\n'
            '\u0422\u043e\u043a\u0435\u043d\u044b \u0432\u043e\u0437\u0432\u0440\u0430\u0449\u0435\u043d\u044b.'
        )
    return '\u274c \u0418\u0437\u0432\u0438\u043d\u0438\u0442\u0435, \u043f\u0440\u043e\u0438\u0437\u043e\u0448\u043b\u0430 \u043e\u0448\u0438\u0431\u043a\u0430 \u0433\u0435\u043d\u0435\u0440\u0430\u0446\u0438\u0438. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u043f\u043e\u0437\u0436\u0435.\\n\u0422\u043e\u043a\u0435\u043d\u044b \u0432\u043e\u0437\u0432\u0440\u0430\u0449\u0435\u043d\u044b.'


def _error_kind(exc: Exception) -> str:
    if _is_replicate_sensitive_error(exc):
        return '\u041a\u043e\u043d\u0442\u0435\u043d\u0442 \u043e\u0442\u043a\u043b\u043e\u043d\u0435\u043d \u043c\u043e\u0434\u0435\u0440\u0430\u0446\u0438\u0435\u0439 Replicate (E005)'
    if _is_kie_policy_error(exc):
        return '\u041a\u043e\u043d\u0442\u0435\u043d\u0442 \u043e\u0442\u043a\u043b\u043e\u043d\u0435\u043d \u043c\u043e\u0434\u0435\u0440\u0430\u0446\u0438\u0435\u0439 Kie.ai'
    msg = str(exc).lower()
    if 'too many requests' in msg or 'status=429' in msg:
        return '\u041b\u0438\u043c\u0438\u0442 \u0437\u0430\u043f\u0440\u043e\u0441\u043e\u0432 (429)'
    if 'unprocessable entity' in msg or 'status=422' in msg:
        return '\u041d\u0435\u043a\u043e\u0440\u0440\u0435\u043a\u0442\u043d\u044b\u0435 \u0432\u0445\u043e\u0434\u043d\u044b\u0435 \u0434\u0430\u043d\u043d\u044b\u0435 (422)'
    if 'insufficient credit' in msg or 'status=402' in msg:
        return '\u041d\u0435\u0434\u043e\u0441\u0442\u0430\u0442\u043e\u0447\u043d\u043e \u0441\u0440\u0435\u0434\u0441\u0442\u0432 \u0443 \u043f\u0440\u043e\u0432\u0430\u0439\u0434\u0435\u0440\u0430 (402)'
    if 'timed out' in msg or 'timeout' in msg:
        return '\u0422\u0430\u0439\u043c\u0430\u0443\u0442 \u0437\u0430\u043f\u0440\u043e\u0441\u0430 \u043a \u043f\u0440\u043e\u0432\u0430\u0439\u0434\u0435\u0440\u0443'
    return '\u0422\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a\u0430\u044f \u043e\u0448\u0438\u0431\u043a\u0430 \u043f\u0440\u043e\u0432\u0430\u0439\u0434\u0435\u0440\u0430'


def _build_admin_error_message(
    error_source: str,
    exc: Exception,
    user_id: int,
    username: str | None,
) -> str:
    return (
        '\u274c <b>\u041e\u0448\u0438\u0431\u043a\u0430 \u0433\u0435\u043d\u0435\u0440\u0430\u0446\u0438\u0438</b>\\n'
        f'\u041f\u0440\u043e\u0432\u0430\u0439\u0434\u0435\u0440: <code>{error_source}</code>\\n'
        f'\u0422\u0438\u043f: {_error_kind(exc)}\\n'
        f'\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c: <code>{user_id}</code> (@{username or '-'})\\n'
        f'\u0414\u0435\u0442\u0430\u043b\u0438: <code>{shorten(str(exc), 350)}</code>'
    )


async def _with_retries(
    label: str,
    user_id: int,
    username: str | None,
    fn,
    *,
    max_attempts: int = GENERATION_MAX_ATTEMPTS,
    retry_delay_sec: float = GENERATION_RETRY_DELAY_SEC,
    stop_on=None,
    delay_fn=None,
):
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await fn()
        except Exception as e:
            if stop_on and stop_on(e):
                raise
            last_error = e
            logger.warning(
                "%s attempt failed %s attempt=%s/%s error=%s",
                label,
                format_user(user_id, username),
                attempt,
                max_attempts,
                e,
            )
            if attempt < max_attempts:
                delay = retry_delay_sec
                if delay_fn:
                    try:
                        delay = float(delay_fn(attempt, e))
                    except Exception:
                        delay = retry_delay_sec
                await asyncio.sleep(max(0.0, delay))
    if last_error:
        raise last_error
    raise RuntimeError(f"{label} failed without exception")


async def run_effect_generation(
    bot: Any,
    user_id: int,
    chat_id: int,
    effect_id: int,
    photo_file_id: str,
    username: str | None = None,
) -> bool:
    config = load_config()
    await _expire_subscription_if_needed(user_id)
    effect = await crud.get_effect(config.database_path, effect_id)
    if not effect:
        await bot.send_message(chat_id, 'Эффект не найден. Попробуйте снова.')
        return False

    balance = await crud.get_balance(config.database_path, user_id)
    if balance < config.effect_cost:
        await bot.send_message(chat_id, f'Недостаточно токенов. Нужно {config.effect_cost} токенов.')
        return False

    await crud.update_balance(config.database_path, user_id, -config.effect_cost)
    charged = True

    temp_dir = Path(config.media_temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"effect_{user_id}_{uuid.uuid4().hex}.jpg"
    final_prompt = f"{config.system_prompt} {effect['prompt']}".strip()

    try:
        await bot.download(photo_file_id, destination=temp_path)
        await bot.send_message(
            chat_id,
            f'💳 Списано <b>{config.effect_cost}</b> токенов.\n'
            f'⏱ Длительность: <b>6</b> сек.\n'
            '✨ Генерирую видео, подождите...'
        )
        async def _kie_video_once() -> str:
            logger.info('Kie request %s prompt="%s"', format_user(user_id, username), shorten(final_prompt))
            image_url = await asyncio.to_thread(upload_file, str(temp_path), config.kie_api_key)
            task_id = await asyncio.to_thread(
                create_task,
                image_url,
                final_prompt,
                6,
                config.kie_api_key,
                config.kie_api_url,
            )
            logger.info('Kie task created task_id=%s %s', task_id, format_user(user_id, username))
            record = await poll_task(task_id, config.kie_api_key, timeout_sec=420)
            url = extract_result_url(record)
            if not url:
                raise RuntimeError('Kie result url not found')
            return url

        url = await _with_retries('Kie video generation', user_id, username, _kie_video_once)

        await bot.send_video(chat_id, url)
        await bot.send_message(
            chat_id,
            f'✅ Видео создано\nЭффект: <b>{effect["button_name"]}</b>',
            reply_markup=effect_done_kb(effect_id),
        )
        await notify_admin(
            bot,
            config.admin_notify_ids,
            f'✅ Успешная генерация (Эффект). Пользователь {user_id} (@{username or "-"}) , эффект {effect_id}'
        )
        return True
    except Exception as e:
        logger.exception('Kie generation failed %s effect_id=%s', format_user(user_id, username), effect_id)
        if charged:
            await crud.update_balance(config.database_path, user_id, config.effect_cost)
        await bot.send_message(chat_id, _build_user_error_message(e), reply_markup=menu_only_kb())
        await notify_admin(
            bot,
            config.admin_notify_ids,
            _build_admin_error_message('Kie.ai', e, user_id, username)
        )
        return False
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass


async def _send_image_group(bot: Any, chat_id: int, urls: list[str]) -> None:
    await bot.send_media_group(chat_id, urls)


async def _resolve_replicate_image_input(
    bot: Any,
    photo_file_id: str,
    temp_path: Path,
    bot_token: str,
) -> str:
    try:
        public_url = await bot.resolve_public_file_url(photo_file_id)
        if public_url:
            return public_url
    except Exception:
        pass

    return encode_image(str(temp_path))


async def _replicate_image_urls(
    bot: Any,
    user_id: int,
    username: str | None,
    prompt: str,
    image_input: str | None,
    aspect_ratio: str | None,
) -> list[str]:
    _ = bot
    config = load_config()
    configured_field = (config.replicate_image_field or 'image').strip()

    async def _replicate_once() -> list[str]:
        field_candidates = [configured_field]
        if image_input:
            for alt in ('image', 'image_url', 'image_input'):
                if alt not in field_candidates:
                    field_candidates.append(alt)

        last_error: Exception | None = None
        prediction: dict | None = None
        used_field = configured_field

        for field_name in field_candidates:
            try:
                prediction = await asyncio.to_thread(
                    create_image_prediction,
                    prompt,
                    config.replicate_api_token,
                    config.replicate_api_url,
                    config.replicate_image_model,
                    image_input,
                    field_name,
                    aspect_ratio,
                )
                used_field = field_name
                break
            except Exception as e:
                last_error = e
                msg = str(e)
                is_422 = ('status=422' in msg or 'Unprocessable Entity' in msg)
                if is_422 and field_name != field_candidates[-1]:
                    logger.warning(
                        'Replicate rejected image field=%s, try next field %s',
                        field_name,
                        format_user(user_id, username),
                    )
                    continue
                raise

        if prediction is None:
            raise last_error or RuntimeError('Replicate image prediction create failed')

        prediction_id = prediction.get('id')
        if not prediction_id:
            raise RuntimeError('Replicate image missing prediction id')

        logger.info(
            'Replicate image task created prediction_id=%s field=%s %s',
            prediction_id,
            used_field,
            format_user(user_id, username),
        )

        prediction = await poll_prediction(
            prediction_id,
            config.replicate_api_token,
            config.replicate_api_url,
            interval_sec=REPLICATE_POLL_INTERVAL_SEC,
            timeout_sec=REPLICATE_ATTEMPT_TIMEOUT_SEC,
        )
        urls = extract_replicate_output_urls(prediction)
        if not urls:
            raise RuntimeError('Replicate image output url not found')
        return urls[:2]

    def _stop_on(exc: Exception) -> bool:
        return _is_replicate_no_retry_error(exc)

    def _delay(attempt: int, exc: Exception) -> float:
        msg = str(exc)
        if 'status=429' in msg or 'Too Many Requests' in msg:
            m = re.search(r'retry_after=(\d+)', msg)
            if m:
                return max(10.0, float(m.group(1)))
            return 15.0 * attempt
        return GENERATION_RETRY_DELAY_SEC

    return await _with_retries(
        'Replicate image generation',
        user_id,
        username,
        _replicate_once,
        max_attempts=REPLICATE_MAX_ATTEMPTS,
        stop_on=_stop_on,
        delay_fn=_delay,
    )


async def run_photo_effect_generation(
    bot: Any,
    user_id: int,
    chat_id: int,
    effect_id: int,
    photo_file_id: str,
    username: str | None = None,
) -> bool:
    config = load_config()
    await _expire_subscription_if_needed(user_id)
    effect = await crud.get_effect(config.database_path, effect_id)
    if not effect:
        await bot.send_message(chat_id, 'Эффект не найден. Попробуйте снова.')
        return False

    balance = await crud.get_balance(config.database_path, user_id)
    if balance < config.photo_effect_cost:
        await bot.send_message(
            chat_id,
            f'Недостаточно токенов. Нужно {config.photo_effect_cost} токенов.'
        )
        return False

    await crud.update_balance(config.database_path, user_id, -config.photo_effect_cost)
    charged = True

    temp_dir = Path(config.media_temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"photo_effect_{user_id}_{uuid.uuid4().hex}.jpg"
    final_prompt = f"{effect['prompt']}".strip()

    error_source = 'Kie.ai (image)'
    try:
        await bot.download(photo_file_id, destination=temp_path)
        await bot.send_message(
            chat_id,
            f'💳 Списано <b>{config.photo_effect_cost}</b> токенов.\n'
            '✨ Генерирую фото, подождите...'
        )

        async def _kie_photo_once() -> list[str]:
            logger.info('Kie image request %s prompt="%s"', format_user(user_id, username), shorten(final_prompt))
            image_url = await asyncio.to_thread(upload_file, str(temp_path), config.kie_api_key)
            task_id = await asyncio.to_thread(
                create_image_task,
                final_prompt,
                config.kie_image_model,
                config.kie_api_key,
                config.kie_api_url,
                image_url,
            )
            logger.info('Kie image task created task_id=%s %s', task_id, format_user(user_id, username))
            record = await poll_task(task_id, config.kie_api_key)
            urls = extract_result_urls(record)
            if not urls:
                raise RuntimeError('Kie image result urls not found')
            return urls

        try:
            urls = await _with_retries('Kie photo effect generation', user_id, username, _kie_photo_once)
        except Exception as kie_error:
            logger.warning(
                'Kie photo effect failed after retries, fallback to Replicate %s effect_id=%s error=%s',
                format_user(user_id, username),
                effect_id,
                kie_error,
            )
            error_source = 'Replicate (image fallback)'
            image_input = await _resolve_replicate_image_input(bot, photo_file_id, temp_path, config.bot_token)
            urls = await _replicate_image_urls(
                bot,
                user_id,
                username,
                final_prompt,
                image_input,
                None,
            )

        await _send_image_group(bot, chat_id, urls)
        await bot.send_message(
            chat_id,
            f'✅ Фото создано\nЭффект: <b>{effect["button_name"]}</b>',
            reply_markup=photo_effect_done_kb(effect_id),
        )
        await notify_admin(
            bot,
            config.admin_notify_ids,
            f'✅ Успешная генерация (Фото-эффект). Пользователь {user_id} (@{username or "-"}) , эффект {effect_id}'
        )
        return True
    except Exception as e:
        logger.exception('Photo effect generation failed %s effect_id=%s', format_user(user_id, username), effect_id)
        if charged:
            await crud.update_balance(config.database_path, user_id, config.photo_effect_cost)
        await bot.send_message(
            chat_id,
            _build_user_error_message(e),
            reply_markup=menu_only_kb(),
        )
        await notify_admin(
            bot,
            config.admin_notify_ids,
            _build_admin_error_message(error_source, e, user_id, username)
        )
        return False
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass


async def run_custom_generation(
    bot: Any,
    user_id: int,
    chat_id: int,
    photo_file_id: str,
    prompt: str,
    duration: int,
    photo_width: int | None = None,
    photo_height: int | None = None,
    username: str | None = None,
) -> bool:
    config = load_config()
    await _expire_subscription_if_needed(user_id)
    cost = duration * config.custom_cost_per_sec

    balance = await crud.get_balance(config.database_path, user_id)
    if balance < cost:
        await bot.send_message(chat_id, f'Недостаточно токенов. Нужно {cost} токенов.')
        return False

    await crud.update_balance(config.database_path, user_id, -cost)
    charged = True

    temp_dir = Path(config.media_temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"custom_{user_id}_{uuid.uuid4().hex}.jpg"
    final_prompt = f"{config.system_prompt} {prompt}".strip()

    error_source = 'Replicate'
    try:
        await bot.download(photo_file_id, destination=temp_path)
        await bot.send_message(
            chat_id,
            f'💳 Списано <b>{cost}</b> токенов.\n'
            f'⏱ Длительность: <b>{duration}</b> сек.\n'
            f'Цена: <b>{config.custom_cost_per_sec}</b> токенов/сек.\n'
            '✨ Генерирую видео, подождите...'
        )
        logger.info('Replicate request %s prompt="%s"', format_user(user_id, username), shorten(final_prompt))

        image_input = await _resolve_replicate_image_input(bot, photo_file_id, temp_path, config.bot_token)

        aspect_ratio = None
        if config.replicate_aspect_ratio_mode == 'match' and photo_width and photo_height:
            aspect_ratio = closest_aspect_ratio(photo_width, photo_height)

        replicate_error: Exception | None = None
        url: str | None = None
        for attempt in range(1, REPLICATE_VIDEO_MAX_ATTEMPTS + 1):
            try:
                try:
                    prediction = await asyncio.to_thread(
                        create_prediction,
                        image_input,
                        final_prompt,
                        duration,
                        config.replicate_api_token,
                        config.replicate_api_url,
                        config.replicate_model_version,
                        config.replicate_image_field,
                        aspect_ratio,
                    )
                except Exception:
                    if aspect_ratio:
                        logger.warning('Replicate aspect_ratio rejected, retry without. ratio=%s', aspect_ratio)
                        prediction = await asyncio.to_thread(
                            create_prediction,
                            image_input,
                            final_prompt,
                            duration,
                            config.replicate_api_token,
                            config.replicate_api_url,
                            config.replicate_model_version,
                            config.replicate_image_field,
                            None,
                        )
                    else:
                        raise

                prediction_id = prediction.get('id')
                if not prediction_id:
                    raise RuntimeError('Replicate missing prediction id')
                logger.info(
                    'Replicate task created prediction_id=%s %s attempt=%s/%s',
                    prediction_id,
                    format_user(user_id, username),
                    attempt,
                    REPLICATE_VIDEO_MAX_ATTEMPTS,
                )

                prediction = await poll_prediction(
                    prediction_id,
                    config.replicate_api_token,
                    config.replicate_api_url,
                    interval_sec=REPLICATE_POLL_INTERVAL_SEC,
                    timeout_sec=REPLICATE_VIDEO_ATTEMPT_TIMEOUT_SEC,
                )
                url = extract_output_url(prediction)
                if not url:
                    raise RuntimeError('Replicate output url not found')
                break
            except Exception as e:
                replicate_error = e
                logger.warning(
                    'Replicate attempt failed %s attempt=%s/%s error=%s',
                    format_user(user_id, username),
                    attempt,
                    REPLICATE_VIDEO_MAX_ATTEMPTS,
                    e,
                )
                err_text = str(e)
                if _is_replicate_no_retry_error(e):
                    break
                if attempt < REPLICATE_VIDEO_MAX_ATTEMPTS:
                    if 'status=429' in err_text or 'Too Many Requests' in err_text:
                        await asyncio.sleep(10 * attempt)
                    else:
                        await asyncio.sleep(2)

        if not url:
            logger.warning(
                'Replicate failed after retries (no Kie fallback) %s error=%s',
                format_user(user_id, username),
                replicate_error,
            )
            raise replicate_error or RuntimeError('Replicate generation failed')

        await bot.send_video(chat_id, url)
        await bot.send_message(
            chat_id,
            f'✅ Видео создано\nЗапрос: <i>{shorten(prompt, 200)}</i>',
            reply_markup=custom_done_kb(),
        )
        await notify_admin(
            bot,
            config.admin_notify_ids,
            f'✅ Успешная генерация (Свой промпт). Пользователь {user_id} (@{username or "-"})'
        )
        return True
    except Exception as e:
        logger.exception('Replicate generation failed %s', format_user(user_id, username))
        if charged:
            await crud.update_balance(config.database_path, user_id, cost)
        await bot.send_message(chat_id, _build_user_error_message(e), reply_markup=menu_only_kb())
        await notify_admin(
            bot,
            config.admin_notify_ids,
            _build_admin_error_message(error_source, e, user_id, username)
        )
        return False
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass


async def run_photo_custom_generation(
    bot: Any,
    user_id: int,
    chat_id: int,
    photo_file_id: str,
    prompt: str,
    username: str | None = None,
) -> bool:
    config = load_config()
    await _expire_subscription_if_needed(user_id)
    balance = await crud.get_balance(config.database_path, user_id)
    if balance < config.photo_custom_cost:
        await bot.send_message(
            chat_id,
            f'Недостаточно токенов. Нужно {config.photo_custom_cost} токенов.'
        )
        return False

    await crud.update_balance(config.database_path, user_id, -config.photo_custom_cost)
    charged = True

    temp_dir = Path(config.media_temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"photo_custom_{user_id}_{uuid.uuid4().hex}.jpg"
    final_prompt = f"{prompt}".strip()

    error_source = 'Kie.ai (image)'
    try:
        await bot.download(photo_file_id, destination=temp_path)
        await bot.send_message(
            chat_id,
            f'💳 Списано <b>{config.photo_custom_cost}</b> токенов.\n'
            '✨ Генерирую фото, подождите...'
        )

        async def _kie_photo_custom_once() -> list[str]:
            logger.info('Kie image request %s prompt="%s"', format_user(user_id, username), shorten(final_prompt))
            image_url = await asyncio.to_thread(upload_file, str(temp_path), config.kie_api_key)
            task_id = await asyncio.to_thread(
                create_image_task,
                final_prompt,
                config.kie_image_model,
                config.kie_api_key,
                config.kie_api_url,
                image_url,
            )
            logger.info('Kie image task created task_id=%s %s', task_id, format_user(user_id, username))
            record = await poll_task(task_id, config.kie_api_key)
            urls = extract_result_urls(record)
            if not urls:
                raise RuntimeError('Kie image result urls not found')
            return urls

        try:
            urls = await _with_retries('Kie photo custom generation', user_id, username, _kie_photo_custom_once)
        except Exception as kie_error:
            logger.warning(
                'Kie photo custom failed after retries, fallback to Replicate %s error=%s',
                format_user(user_id, username),
                kie_error,
            )
            error_source = 'Replicate (image fallback)'
            image_input = await _resolve_replicate_image_input(bot, photo_file_id, temp_path, config.bot_token)
            urls = await _replicate_image_urls(
                bot,
                user_id,
                username,
                final_prompt,
                image_input,
                None,
            )

        await _send_image_group(bot, chat_id, urls)
        await bot.send_message(
            chat_id,
            f'✅ Фото создано\nЗапрос: <i>{shorten(prompt, 200)}</i>',
            reply_markup=photo_custom_done_kb(),
        )
        await notify_admin(
            bot,
            config.admin_notify_ids,
            f'✅ Успешная генерация (ИИ-Фотошоп). Пользователь {user_id} (@{username or "-"})'
        )
        return True
    except Exception as e:
        logger.exception('Photo custom generation failed %s', format_user(user_id, username))
        if charged:
            await crud.update_balance(config.database_path, user_id, config.photo_custom_cost)
        await bot.send_message(
            chat_id,
            _build_user_error_message(e),
            reply_markup=menu_only_kb(),
        )
        await notify_admin(
            bot,
            config.admin_notify_ids,
            _build_admin_error_message(error_source, e, user_id, username)
        )
        return False
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass


async def run_text_image_generation(
    bot: Any,
    user_id: int,
    chat_id: int,
    prompt: str,
    username: str | None = None,
) -> bool:
    config = load_config()
    await _expire_subscription_if_needed(user_id)
    balance = await crud.get_balance(config.database_path, user_id)
    if balance < config.photo_custom_cost:
        await bot.send_message(
            chat_id,
            f'Недостаточно токенов. Нужно {config.photo_custom_cost} токенов.'
        )
        return False

    await crud.update_balance(config.database_path, user_id, -config.photo_custom_cost)
    charged = True
    final_prompt = prompt.strip()

    error_source = 'Kie.ai (text image)'
    try:
        await bot.send_message(
            chat_id,
            f'💳 Списано <b>{config.photo_custom_cost}</b> токенов.\n'
            '✨ Генерирую изображение, подождите...'
        )

        async def _kie_text_image_once() -> list[str]:
            logger.info('Kie image request %s prompt="%s"', format_user(user_id, username), shorten(final_prompt))
            task_id = await asyncio.to_thread(
                create_image_task,
                final_prompt,
                config.kie_text_image_model,
                config.kie_api_key,
                config.kie_api_url,
                None,
            )
            logger.info('Kie image task created task_id=%s %s', task_id, format_user(user_id, username))
            record = await poll_task(task_id, config.kie_api_key)
            urls = extract_result_urls(record)
            if not urls:
                raise RuntimeError('Kie image result urls not found')
            return urls

        try:
            urls = await _with_retries('Kie text image generation', user_id, username, _kie_text_image_once)
        except Exception as kie_error:
            logger.warning(
                'Kie text image failed after retries, fallback to Replicate %s error=%s',
                format_user(user_id, username),
                kie_error,
            )
            error_source = 'Replicate (image fallback)'
            urls = await _replicate_image_urls(
                bot,
                user_id,
                username,
                final_prompt,
                None,
                config.replicate_image_aspect_ratio,
            )

        await _send_image_group(bot, chat_id, urls)
        await bot.send_message(
            chat_id,
            f'✅ Изображение создано\nЗапрос: <i>{shorten(prompt, 200)}</i>',
            reply_markup=photo_text_done_kb(),
        )
        await notify_admin(
            bot,
            config.admin_notify_ids,
            f'✅ Успешная генерация (Текст→Фото). Пользователь {user_id} (@{username or "-"})'
        )
        return True
    except Exception as e:
        logger.exception('Text image generation failed %s', format_user(user_id, username))
        if charged:
            await crud.update_balance(config.database_path, user_id, config.photo_custom_cost)
        await bot.send_message(
            chat_id,
            _build_user_error_message(e),
            reply_markup=menu_only_kb(),
        )
        await notify_admin(
            bot,
            config.admin_notify_ids,
            _build_admin_error_message(error_source, e, user_id, username)
        )
        return False


async def _expire_subscription_if_needed(user_id: int) -> None:
    sub = await crud.get_subscription(load_config().database_path, user_id)
    if not sub:
        return
    if sub.get('status') not in ('active', 'inactive'):
        return
    if int(sub.get('auto_renew', 0)) == 1:
        return
    try:
        end = datetime.fromisoformat(sub['current_period_end'])
    except Exception:
        return
    if datetime.utcnow() >= end:
        await crud.mark_subscription_status(load_config().database_path, user_id, 'expired')
        await crud.set_balance(load_config().database_path, user_id, 0)
