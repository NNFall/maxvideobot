import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from tools.max_access_watch import EXPECTED_BOT_ID, admin_recipients, check_access


class FakeBot:
    def __init__(self, errors=None, bot_id=EXPECTED_BOT_ID):
        self.errors = errors or {}
        self.bot_id = bot_id
        self.attempts = []

    async def get_me(self):
        return SimpleNamespace(user_id=self.bot_id)

    async def send_message(self, user_id, **kwargs):
        self.attempts.append(user_id)
        if user_id in self.errors:
            raise self.errors[user_id]


class AccessWatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_available_profile_notifies_all_admins_each_check(self):
        state = {}
        bot = FakeBot()
        for _ in range(2):
            result = await check_access(bot, [1, 2, 3, 2], state)
            self.assertEqual(result["status"], "available")
            self.assertEqual(result["notified"], [1, 2, 3])
        self.assertEqual(bot.attempts, [1, 2, 3, 1, 2, 3])

    async def test_get_me_success_does_not_hide_delivery_block(self):
        bot = FakeBot({user_id: RuntimeError("Profile is limited") for user_id in [1, 2, 3]})
        result = await check_access(bot, [1, 2, 3], {})
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["notified"], [])
        self.assertEqual(bot.attempts, [1, 2, 3])

    async def test_limited_chat_does_not_skip_other_admins(self):
        bot = FakeBot({1: RuntimeError("Profile is limited")})
        result = await check_access(bot, [1, 2, 3], {})
        self.assertEqual(result["status"], "partial_delivery")
        self.assertEqual(result["notified"], [2, 3])
        self.assertEqual(bot.attempts, [1, 2, 3])

    async def test_one_unavailable_admin_does_not_skip_others(self):
        bot = FakeBot({1: RuntimeError("Chat not found")})
        result = await check_access(bot, [1, 2, 3], {})
        self.assertEqual(result["status"], "partial_delivery")
        self.assertEqual(result["notified"], [2, 3])
        self.assertEqual(bot.attempts, [1, 2, 3])

    async def test_timeout_is_not_recovery(self):
        result = await check_access(FakeBot({1: TimeoutError()}), [1], {})
        self.assertEqual(result["status"], "unreachable")
        self.assertEqual(result["notified"], [])

    async def test_wrong_bot_cannot_send(self):
        bot = FakeBot(bot_id=999)
        result = await check_access(bot, [1, 2], {})
        self.assertEqual(result["status"], "wrong_bot")
        self.assertEqual(bot.attempts, [])

    async def test_empty_audience_is_not_available(self):
        result = await check_access(FakeBot(), [], {})
        self.assertEqual(result["status"], "no_admins")

    async def test_administrators_include_configuration_and_database(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "database.db"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("CREATE TABLE admins (user_id INTEGER)")
                connection.execute("INSERT INTO admins VALUES (3)")
                connection.commit()
            cfg = SimpleNamespace(admin_ids=[1, 2], admin_notify_ids=[2],
                                  database_path=str(database))
            self.assertEqual(admin_recipients(cfg), [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
