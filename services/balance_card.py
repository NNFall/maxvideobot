from __future__ import annotations

from config import load_config
from services.subscriptions import get_plans


async def _balance_link(bot) -> str:
    try:
        me = await bot.get_me()
        username = getattr(me, "username", None)
        if username:
            return f"{load_config().max_bot_link_base.rstrip('/')}/{username}"
    except Exception:
        pass
    return "/balance"


async def build_inactive_balance_text(bot, balance: int, include_header: bool = True) -> str:
    cfg = load_config()
    plans = get_plans()
    week = plans.get("week")
    month = plans.get("month")
    balance_link = await _balance_link(bot)
    balance_hint = f'<a href="{balance_link}">/balance</a>' if balance_link != "/balance" else "<code>/balance</code>"

    header = ""
    if include_header:
        header = f"❌ <b>Подписка не активна</b>\n🎬 <b>Токены:</b> {balance}\n\n"

    return (
        f"{header}"
        "<b>Подписка с автосписанием</b>\n"
        f"🔥 {week.price_rub} ₽ / {week.title.lower()} — {week.generations} токенов\n"
        f"⭐ {month.price_rub} ₽ / {month.title.lower()} — {month.generations} токенов\n\n"
        "<b>Разовая покупка через ЮKassa</b>\n"
        f"⭐ {week.price_rub} ₽ — {week.generations} токенов\n"
        f"⭐ {month.price_rub} ₽ — {month.generations} токенов\n\n"
        f"Отключить автопродление можно в любой момент в {balance_hint}.\n\n"
        f'Переходя к оплате, вы соглашаетесь с <a href="{cfg.offer_url}">офертой</a>.'
    )
