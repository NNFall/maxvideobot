import unittest
from types import SimpleNamespace

from tools.max_access_watch import EXPECTED_BOT_ID, RECOVERY_TEXT, check_access


class FakeBot:
    def __init__(self, error=None, bot_id=EXPECTED_BOT_ID, history=()):
        self.error = error
        self.bot_id = bot_id
        self.sent = 0
        self.history = history

    async def get_me(self):
        return SimpleNamespace(user_id=self.bot_id)

    async def send_message(self, **kwargs):
        self.sent += 1
        if self.error:
            raise self.error

    async def get_messages(self, **kwargs):
        return SimpleNamespace(messages=self.history)


class AccessWatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_me_success_does_not_hide_delivery_block(self):
        state = {}
        result = await check_access(FakeBot(RuntimeError("Profile is limited")), 1, state, None)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(state["status"], "blocked")
        self.assertNotIn("last_success_at", state)

    async def test_recovery_notifies_only_once(self):
        state = {"status": "blocked"}
        bot = FakeBot()
        first = await check_access(bot, 1, state, "2000-01-01T00:00:00+00:00")
        second = await check_access(bot, 1, state, "2000-01-01T00:00:00+00:00")
        self.assertTrue(first["recovered"])
        self.assertFalse(second["recovered"])
        self.assertEqual(second["status"], "no_new_refusal")
        self.assertEqual(bot.sent, 1)

    async def test_new_refusal_rearms_probe(self):
        state = {"status": "available", "last_success_at": "2026-10-01T00:00:00+00:00"}
        bot = FakeBot(RuntimeError("Profile is limited"))
        result = await check_access(bot, 1, state, "2026-10-14T11:00:04+00:00")
        self.assertEqual(bot.sent, 1)
        self.assertEqual(result["status"], "blocked")

    async def test_timeout_is_not_recovery(self):
        state = {"status": "blocked"}
        result = await check_access(FakeBot(TimeoutError()), 1, state, None)
        self.assertEqual(result["status"], "unreachable")
        self.assertEqual(state["status"], "blocked")

    async def test_wrong_bot_cannot_send(self):
        bot = FakeBot(bot_id=999)
        result = await check_access(bot, 1, {}, None)
        self.assertEqual(result["status"], "wrong_bot")
        self.assertEqual(bot.sent, 0)

    async def test_lost_response_does_not_duplicate_delivered_notification(self):
        state = {"status": "blocked"}
        await check_access(FakeBot(TimeoutError()), 1, state, None)
        from tools.max_access_watch import timestamp
        delivered = SimpleNamespace(
            sender=SimpleNamespace(user_id=EXPECTED_BOT_ID),
            timestamp=int(timestamp(state["pending_notification_at"]).timestamp() * 1000),
            body=SimpleNamespace(text=RECOVERY_TEXT),
        )
        bot = FakeBot(history=[delivered])
        result = await check_access(bot, 1, state, None)
        self.assertTrue(result["recovered"])
        self.assertEqual(bot.sent, 0)

    async def test_persistence_failure_prevents_send(self):
        def fail(_):
            raise OSError("Disk unavailable")
        bot = FakeBot()
        result = await check_access(bot, 1, {}, None, persist=fail)
        self.assertEqual(result["status"], "unreachable")
        self.assertEqual(bot.sent, 0)


if __name__ == "__main__":
    unittest.main()
