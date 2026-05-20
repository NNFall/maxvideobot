from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str | None]] = []
        self.callbacks: list[dict] = []

    async def send_message(self, chat_id: int, text: str | None = None, **kwargs):
        self.messages.append((chat_id, text))
        return SimpleNamespace(message=SimpleNamespace(body=SimpleNamespace(mid="smoke-mid")))

    async def send_callback(self, **kwargs):
        self.callbacks.append(kwargs)
        return SimpleNamespace(ok=True)

    async def get_me(self):
        return SimpleNamespace(username="smoke_bot")

    async def download(self, source: str, destination: str | Path):
        dest = Path(destination)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"smoke-media")
        return dest


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="maxvideobot_smoke_") as tmp:
        db_path = str(Path(tmp) / "database.db")
        media_dir = str(Path(tmp) / "media")
        demo_dir = str(Path(tmp) / "demos")
        os.environ["DATABASE_PATH"] = db_path
        os.environ["MEDIA_TEMP_DIR"] = media_dir
        os.environ["MEDIA_DEMO_DIR"] = demo_dir
        os.environ.setdefault("MAX_BOT_TOKEN", "smoke-token")
        os.environ.setdefault("ADMIN_IDS", "")
        os.environ.setdefault("ADMIN_NOTIFY_IDS", "")

        from database import crud
        from database.db import setup
        from max_handlers.router import _cleanup_pending_action_for_tx, _cleanup_pending_media, _persist_demo_media, _persist_pending_media, _process_start, router
        from max_handlers.utils import answer_callback_message, get_media_source
        from max_keyboards.effects_kb import effects_kb
        from max_keyboards.common_kb import help_kb
        from max_keyboards.main_menu import main_menu_kb
        from max_keyboards.payment_kb import choose_subscription_kb
        from services.subscriptions import get_plans

        await setup(db_path)

        kb = main_menu_kb()
        assert kb is not None
        menu_json = kb.model_dump_json()
        assert "Создать песню" not in menu_json
        assert "Создать презентацию" not in menu_json
        subscription_json = choose_subscription_kb(get_plans()).model_dump_json()
        assert "разово" not in subscription_json.lower()
        support_kb = help_kb("https://web.max.ru/69942834")
        assert "https://web.max.ru/69942834" in support_kb.model_dump_json()
        assert hasattr(router, "message_created")
        assert hasattr(router, "message_callback")
        assert hasattr(router, "bot_started")

        await crud.create_promocode(db_path, "SMOKE", 7)
        bot = FakeBot()
        await _process_start(bot, 1001, 1001, "promo_SMOKE", "smoke_user")
        balance = await crud.get_balance(db_path, 1001)
        assert balance == 7, f"expected promo 7 without starter bonus, got {balance}"
        assert len(bot.messages) >= 2

        event = SimpleNamespace(
            message=SimpleNamespace(
                body=SimpleNamespace(
                    attachments=[
                        {
                            "type": "image",
                            "width": 800,
                            "height": 600,
                            "payload": {"url": "https://example.com/image.jpg"},
                        }
                    ]
                )
            )
        )
        source, width, height = get_media_source(event, "image")
        assert source == "https://example.com/image.jpg"
        assert width == 800
        assert height == 600

        callback_event = SimpleNamespace(callback=SimpleNamespace(callback_id="smoke-callback"), bot=bot)
        callback_ok = await answer_callback_message(
            callback_event,
            "<b>Smoke callback</b>",
            effects_kb([{"id": 1, "button_name": "Smoke"}], page=1),
        )
        assert callback_ok
        assert bot.callbacks and bot.callbacks[-1]["message"].text == "<b>Smoke callback</b>"

        video_event = SimpleNamespace(
            message=SimpleNamespace(
                body=SimpleNamespace(
                    attachments=[
                        {
                            "type": "video",
                            "width": 1280,
                            "height": 720,
                            "urls": {"mp4_240": "https://example.com/video.mp4"},
                            "thumbnail": {"url": "https://example.com/thumb.jpg"},
                        }
                    ]
                )
            )
        )
        video_source, video_width, video_height = get_media_source(video_event, "video")
        assert video_source == "https://example.com/video.mp4"
        assert video_width == 1280
        assert video_height == 720

        cached = await _persist_pending_media(bot, 1001, "https://example.com/image.jpg")
        assert Path(cached).exists()
        _cleanup_pending_media(cached)
        assert not Path(cached).exists()

        cached_for_tx = await _persist_pending_media(bot, 1001, "https://example.com/image.jpg")
        tx_id = await crud.create_transaction(
            db_path,
            user_id=1001,
            amount=199,
            currency="RUB",
            credits=60,
            provider="yookassa",
            status="pending",
            provider_payment_id="smoke-payment",
            payload="{}",
        )
        await crud.create_pending_action(
            db_path,
            tx_id,
            1001,
            "effect",
            json.dumps({"type": "effect", "photo_file_id": cached_for_tx}),
        )
        assert Path(cached_for_tx).exists()
        await _cleanup_pending_action_for_tx(tx_id)
        assert not Path(cached_for_tx).exists()
        assert await crud.consume_pending_action(db_path, tx_id) is None

        demo = await _persist_demo_media(bot, 1001, "https://example.com/demo.jpg", "photo")
        assert Path(demo).exists()
        assert Path(demo).parent == Path(demo_dir)

        print("SMOKE OK")
        print(f"db={db_path}")
        print(f"messages={len(bot.messages)}")


if __name__ == "__main__":
    asyncio.run(main())
