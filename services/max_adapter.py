from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path
from typing import Iterable

import requests
from maxapi.enums.parse_mode import ParseMode
from maxapi.types.input_media import InputMedia

from config import load_config


class MaxBotAdapter:
    def __init__(self, bot):
        self.bot = bot

    def __getattr__(self, name: str):
        return getattr(self.bot, name)

    async def get_me(self):
        return await self.bot.get_me()

    async def close_session(self):
        return await self.bot.close_session()

    async def send_message(
        self,
        chat_id: int | None = None,
        text: str | None = None,
        reply_markup=None,
        attachments: list | None = None,
        disable_web_page_preview: bool | None = None,
        **kwargs,
    ):
        items = list(attachments or [])
        if reply_markup is not None:
            items.append(reply_markup)
        return await self.bot.send_message(
            user_id=chat_id,
            text=text,
            attachments=items or None,
            format=ParseMode.HTML,
            disable_link_preview=disable_web_page_preview,
        )

    async def edit_message_text(self, text: str, chat_id: int | None = None, message_id: str | None = None, reply_markup=None, **kwargs):
        attachments = [reply_markup] if reply_markup is not None else None
        if message_id:
            return await self.bot.edit_message(message_id=message_id, text=text, attachments=attachments, format=ParseMode.HTML)
        return await self.send_message(chat_id, text, reply_markup=reply_markup)

    async def delete_message(self, chat_id: int | None = None, message_id: str | None = None, **kwargs):
        if message_id:
            return await self.bot.delete_message(message_id)
        return None

    async def download(self, source: str, destination: str | Path) -> Path:
        dest = Path(destination)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if source.startswith(("http://", "https://")):
            return await asyncio.to_thread(_download_url, source, dest)
        src = Path(source)
        if src.exists():
            shutil.copyfile(src, dest)
            return dest
        raise FileNotFoundError(f"Cannot download MAX media source: {source}")

    async def resolve_public_file_url(self, source: str) -> str | None:
        if source.startswith(("http://", "https://")):
            return source
        return None

    async def send_photo(self, chat_id: int, photo, caption: str | None = None, reply_markup=None, **kwargs):
        path = await self._materialize_media(photo, suffix=".jpg")
        try:
            attachments = [InputMedia(str(path))]
            if reply_markup is not None:
                attachments.append(reply_markup)
            return await self.bot.send_message(user_id=chat_id, text=caption, attachments=attachments, format=ParseMode.HTML)
        finally:
            _safe_unlink(path)

    async def send_video(self, chat_id: int, video, caption: str | None = None, reply_markup=None, **kwargs):
        path = await self._materialize_media(video, suffix=".mp4")
        try:
            attachments = [InputMedia(str(path))]
            if reply_markup is not None:
                attachments.append(reply_markup)
            return await self.bot.send_message(user_id=chat_id, text=caption, attachments=attachments, format=ParseMode.HTML)
        finally:
            _safe_unlink(path)

    async def send_media_group(self, chat_id: int, urls: Iterable[str]):
        for url in urls:
            await self.send_photo(chat_id, url)

    async def _materialize_media(self, media, suffix: str) -> Path:
        cfg = load_config()
        temp_dir = Path(cfg.media_temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)
        path = temp_dir / f"max_send_{uuid.uuid4().hex}{suffix}"
        if isinstance(media, (str, Path)):
            value = str(media)
            if value.startswith(("http://", "https://")):
                return await asyncio.to_thread(_download_url, value, path)
            src = Path(value)
            if src.exists():
                shutil.copyfile(src, path)
                return path
        raise FileNotFoundError(f"Cannot send media source: {media}")


def _download_url(url: str, dest: Path) -> Path:
    with requests.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        with dest.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if chunk:
                    fh.write(chunk)
    return dest


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass
