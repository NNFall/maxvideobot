from __future__ import annotations

import asyncio
import json
import os
import subprocess
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
        os.environ["ADMIN_IDS"] = "1001"
        os.environ["ADMIN_NOTIFY_IDS"] = "1001"

        from database import crud
        from database.db import setup
        from max_handlers.router import _cleanup_pending_action_for_tx, _cleanup_pending_media, _format_tool_admin_message, _handle_admin_command, _persist_demo_media, _persist_pending_media, _process_start, _show_balance, router
        from max_handlers.utils import answer_callback_message, get_media_source
        from max_keyboards.custom_kb import duration_kb
        from max_keyboards.effects_kb import effects_kb
        from max_keyboards.common_kb import help_kb
        from max_keyboards.main_menu import SONG_BOT_URL, main_menu_kb
        from max_keyboards.payment_kb import choose_subscription_kb
        from services import kie_api
        from services.generation import _build_admin_error_message, _build_user_error_message
        from services.ffmpeg_service import check_ffmpeg, concat_videos
        from services.kie_api import create_grok_video_task
        from services.replicate_api import encode_image
        from services.subscriptions import get_plans

        await setup(db_path)

        kb = main_menu_kb()
        assert kb is not None
        menu_json = kb.model_dump_json()
        assert "Создать песню" in menu_json
        assert SONG_BOT_URL in menu_json
        assert menu_json.index("Инструменты") < menu_json.index("Создать песню") < menu_json.index("Баланс / Купить")
        assert "Создать презентацию" not in menu_json
        subscription_json = choose_subscription_kb(get_plans()).model_dump_json()
        assert "разово" not in subscription_json.lower()
        support_url = "https://max.ru/u/f9LHodD0cOL1NLfuFBoMvvVMSgRmsLKspQSSM1d9_6ZR68W1oT3zfN20xA8"
        support_kb = help_kb(support_url)
        assert support_url in support_kb.model_dump_json()
        assert hasattr(router, "message_created")
        assert hasattr(router, "message_callback")
        assert hasattr(router, "bot_started")
        duration_rows = duration_kb(1, 15).model_dump()["payload"]["buttons"]
        assert max(len(row) for row in duration_rows) <= 3
        user_error = _build_user_error_message(RuntimeError("smoke"))
        admin_error = _build_admin_error_message("Smoke", RuntimeError("smoke"), 1001, "smoke_user")
        assert "\\n" not in user_error and "\n" in user_error
        assert "\\n" not in admin_error and "\n" in admin_error
        tool_error = _format_tool_admin_message("Smoke", 1001, "smoke_user", ok=False, details={"error": "x" * 1200})
        assert "x" * 600 not in tool_error
        image_path = Path(tmp) / "image-with-wrong-extension.jpg"
        image_path.write_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8 ")
        assert encode_image(str(image_path)).startswith("data:image/webp;base64,")

        class FakeKieResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"data": {"taskId": "kie-smoke-task"}}

        kie_posts: list[dict] = []
        original_kie_post = kie_api.requests.post

        def fake_kie_post(*args, **kwargs):
            kie_posts.append({"args": args, "kwargs": kwargs})
            return FakeKieResponse()

        kie_api.requests.post = fake_kie_post
        try:
            task_id = create_grok_video_task(
                "https://example.com/input.jpg",
                "Smoke prompt",
                8,
                "kie-smoke-key",
            )
        finally:
            kie_api.requests.post = original_kie_post
        assert task_id == "kie-smoke-task"
        kie_payload = kie_posts[0]["kwargs"]["json"]
        assert kie_payload["model"] == "grok-imagine-video-1.5"
        assert kie_payload["input"]["image_urls"] == ["https://example.com/input.jpg"]
        assert kie_payload["input"]["aspect_ratio"] == "auto"
        assert kie_payload["input"]["resolution"] == "480p"
        assert kie_payload["input"]["duration"] == 8
        assert kie_payload["input"]["nsfw_checker"] is False

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
                            "url": "https://example.com/preview.webp",
                            "urls": {"mp4_240": "https://example.com/video.mp4"},
                            "thumbnail": {"url": "https://example.com/thumb.webp"},
                        }
                    ]
                )
            )
        )
        video_source, video_width, video_height = get_media_source(video_event, "video")
        assert video_source == "https://example.com/video.mp4"
        assert video_width == 1280
        assert video_height == 720

        if check_ffmpeg():
            first_video = Path(tmp) / "concat-first.webm"
            second_video = Path(tmp) / "concat-second.mp4"
            concat_output = Path(tmp) / "concat-output.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=red:s=160x240:d=0.5",
                    "-c:v",
                    "libvpx-vp9",
                    str(first_video),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=blue:s=160x240:d=0.5",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(second_video),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            concat_videos([str(first_video), str(second_video)], str(concat_output))
            assert concat_output.exists()
            assert concat_output.stat().st_size > 0

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

        effect_id = await crud.add_effect(
            db_path,
            "Smoke effect",
            "Generate a smoke test image",
            demo_file_id=demo,
            demo_type="photo",
            effect_type="photo",
        )
        await _handle_admin_command(SimpleNamespace(), bot, 1001, 1001, "get_prompt", [str(effect_id)])
        assert "<pre>Generate a smoke test image</pre>" in (bot.messages[-1][1] or "")
        await _handle_admin_command(SimpleNamespace(), bot, 1001, 1001, "botstats", [])
        assert "📊 <b>Общая статистика бота</b>" in (bot.messages[-1][1] or "")
        await _handle_admin_command(SimpleNamespace(), bot, 1001, 1001, "adtag", ["smoke"])
        assert "Метка: <code>smoke</code>" in (bot.messages[-1][1] or "")
        await _handle_admin_command(SimpleNamespace(), bot, 1001, 1001, "session_del", [str(effect_id)])
        assert bot.messages[-1][1] == "Эффект удален (деактивирован)."

        await crud.upsert_subscription(
            db_path,
            user_id=1002,
            plan_id="week",
            provider="yookassa",
            auto_renew=1,
            payment_method_id="pm-active",
            current_period_start="2026-05-01T00:00:00",
            current_period_end="2099-01-01T00:00:00",
            status="active",
        )
        await crud.set_balance(db_path, 1002, 60)
        await _show_balance(bot, 1002, 1002)
        assert "✅ <b>Подписка активна</b>" in (bot.messages[-1][1] or "")
        assert "Автопродление" not in (bot.messages[-1][1] or "")
        assert "Доступно до" not in (bot.messages[-1][1] or "")

        await crud.upsert_subscription(
            db_path,
            user_id=1003,
            plan_id="week",
            provider="yookassa",
            auto_renew=0,
            payment_method_id="pm-canceled",
            current_period_start="2026-05-01T00:00:00",
            current_period_end="2099-01-01T00:00:00",
            status="inactive",
        )
        await crud.set_balance(db_path, 1003, 60)
        await _show_balance(bot, 1003, 1003)
        assert "❌ <b>Подписка не активна</b>" in (bot.messages[-1][1] or "")

        print("SMOKE OK")
        print(f"db={db_path}")
        print(f"messages={len(bot.messages)}")


if __name__ == "__main__":
    asyncio.run(main())
