from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from maxapi.enums.parse_mode import ParseMode
from maxapi.types.updates.message_callback import MessageForCallback


def get_bot(event):
    bot = getattr(event, "bot", None)
    if bot is not None:
        return bot
    return event._ensure_bot()  # noqa: SLF001


def get_user(event):
    if hasattr(event, "callback"):
        return event.callback.user
    message_user = getattr(getattr(event, "message", None), "sender", None)
    if message_user is not None:
        return message_user
    user = getattr(event, "user", None)
    if user is not None:
        return user
    return getattr(event, "from_user", None)


def get_user_id(event) -> int | None:
    user = get_user(event)
    return getattr(user, "user_id", None)


def get_username(event) -> str | None:
    user = get_user(event)
    return getattr(user, "username", None)


def get_chat_id(event) -> int | None:
    try:
        chat_id, _ = event.get_ids()
        return chat_id
    except Exception:
        return None


def get_target_id(event) -> int | None:
    return get_user_id(event) or get_chat_id(event)


def get_text(event) -> str:
    body = getattr(getattr(event, "message", None), "body", None)
    return (getattr(body, "text", None) or "").strip()


def parse_command(text: str) -> tuple[str, list[str]] | None:
    if not text.startswith("/"):
        return None
    parts = text.split()
    if not parts:
        return None
    command = parts[0][1:].split("@", 1)[0].lower()
    return command, parts[1:]


def callback_payload(event) -> str:
    return (getattr(getattr(event, "callback", None), "payload", None) or "").strip()


async def answer_callback(event, notification: str | None = None) -> None:
    try:
        await event.answer(notification=notification, raise_if_not_exists=False)
    except Exception:
        pass


async def answer_callback_message(event, text: str, reply_markup=None, notification: str | None = None) -> bool:
    callback = getattr(event, "callback", None)
    if callback is None:
        return False
    try:
        attachments = []
        if reply_markup is not None:
            attachments.append(reply_markup.model_dump() if hasattr(reply_markup, "model_dump") else reply_markup)
        message = MessageForCallback(
            text=text,
            attachments=attachments,
            format=ParseMode.HTML,
            notify=False,
        )
        await get_bot(event).send_callback(
            callback_id=callback.callback_id,
            message=message,
            notification=notification,
        )
        return True
    except Exception:
        await answer_callback(event, notification=notification)
        return False


async def send_text(bot, target_id: int, text: str, reply_markup=None, disable_web_page_preview: bool | None = None):
    attachments = [reply_markup] if reply_markup is not None else None
    return await bot.send_message(
        user_id=target_id,
        text=text,
        attachments=attachments,
        format=ParseMode.HTML,
        disable_link_preview=disable_web_page_preview,
    )


async def reply(event, text: str, reply_markup=None, disable_web_page_preview: bool | None = None):
    message = getattr(event, "message", None)
    attachments = [reply_markup] if reply_markup is not None else None
    if message is not None:
        try:
            return await message.answer(
                text=text,
                attachments=attachments,
                format=ParseMode.HTML,
                disable_link_preview=disable_web_page_preview,
            )
        except Exception:
            pass
    target_id = get_target_id(event)
    if target_id is None:
        return None
    return await send_text(get_bot(event), target_id, text, reply_markup, disable_web_page_preview)


def _model_dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="python")
    if isinstance(value, dict):
        return value
    if isinstance(value, (list, tuple)):
        return [_model_dump(v) for v in value]
    return value


def _walk(value: Any) -> Iterable[Any]:
    value = _model_dump(value)
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk(child)


def _looks_like_image_url(url: str) -> bool:
    clean = url.split("?", 1)[0].lower()
    return clean.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic", ".heif"))


def _find_urls(value: Any, keys: tuple[str, ...] | None = None) -> list[str]:
    urls = []
    search_keys = keys or ("url", "download_url", "mp4_1080", "mp4_720", "mp4_480", "mp4_360", "mp4_240", "mp4_144", "hls")
    for node in _walk(value):
        if isinstance(node, dict):
            for key in search_keys:
                candidate = node.get(key)
                if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                    urls.append(candidate)
    return urls


def _find_video_urls(value: Any) -> list[str]:
    mp4_urls = _find_urls(value, ("mp4_1080", "mp4_720", "mp4_480", "mp4_360", "mp4_240", "mp4_144"))
    if mp4_urls:
        return mp4_urls
    direct_urls = _find_urls(value, ("download_url", "url"))
    return [url for url in direct_urls if not _looks_like_image_url(url)]


def _attachment_type(att: Any) -> str:
    t = getattr(att, "type", None)
    value = getattr(t, "value", t)
    if value:
        return str(value).lower()
    dumped = _model_dump(att)
    if isinstance(dumped, dict):
        return str(dumped.get("type") or "").lower()
    return ""


def get_media_source(event, expected: str) -> tuple[str | None, int | None, int | None]:
    body = getattr(getattr(event, "message", None), "body", None)
    attachments = getattr(body, "attachments", None) or []
    fallback = None
    for att in attachments:
        att_type = _attachment_type(att)
        urls = _find_video_urls(att) if expected == "video" else _find_urls(att, ("url", "download_url"))
        if not urls:
            continue
        dumped = _model_dump(att)
        width = height = None
        if isinstance(dumped, dict):
            width = dumped.get("width")
            height = dumped.get("height")
        if expected == "image" and att_type in {"image", "photo"}:
            return urls[0], width, height
        if expected == "video" and att_type == "video":
            return urls[0], width, height
        fallback = (urls[0], width, height)
    return fallback or (None, None, None)


def message_mid(result) -> str | None:
    for obj in (
        getattr(result, "message", None),
        result,
    ):
        body = getattr(obj, "body", None)
        mid = getattr(body, "mid", None)
        if mid:
            return mid
        mid = getattr(obj, "message_id", None)
        if mid:
            return str(mid)
    return None
