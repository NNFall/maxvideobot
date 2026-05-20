from __future__ import annotations

from max_keyboards.builder import cb, inline_keyboard, link


def plans_kb(plans: dict[str, object], callback_prefix: str = "sub:plan"):
    rows = []
    for plan_id, plan in plans.items():
        period = getattr(plan, "title", "период").lower()
        prefix = "🔥" if plan_id == "week" else "⭐"
        rows.append([cb(f"{prefix} {plan.price_rub} ₽ / {period} — {plan.generations} токенов", f"{callback_prefix}:{plan_id}")])
    rows.append([cb("🏠 Меню", "menu:main")])
    return inline_keyboard(rows)


def methods_kb(plan_id: str):
    return inline_keyboard(
        [
            [cb("💳 ЮKassa с автопродлением", f"sub:method:yoo:{plan_id}")],
            [cb("⬅️ Назад", "menu:balance")],
        ]
    )


def choose_subscription_kb(
    plans: dict[str, object],
    cb_yoo_prefix: str = "sub:choose:yoo",
):
    rows = []
    week = plans.get("week")
    month = plans.get("month")
    if week:
        rows.append([cb(f"🔥 {week.price_rub} ₽ / {week.title.lower()} — {week.generations} токенов", f"{cb_yoo_prefix}:{week.id}")])
    if month:
        rows.append([cb(f"⭐ {month.price_rub} ₽ / {month.title.lower()} — {month.generations} токенов", f"{cb_yoo_prefix}:{month.id}")])
    rows.append([cb("⬅️ Назад", "menu:balance")])
    return inline_keyboard(rows)


def subscription_manage_kb(plan_id: str, auto_renew: bool):
    rows = [[cb("🔄 Обновить подписку сейчас", "sub:renew_choose")]]
    if auto_renew:
        rows.append([cb("❌ Отключить подписку", "sub:cancel")])
    rows.append([cb("🏠 Главное меню", "menu:main")])
    return inline_keyboard(rows)


def choose_subscription_prompt_kb():
    return inline_keyboard([[cb("✅ Выбрать подписку", "sub:choose")]])


def pay_url_kb(url: str):
    return inline_keyboard([[link("💳 Оплатить", url)], [cb("🏠 Меню", "menu:main")]])


def payment_success_kb():
    return inline_keyboard([[cb("✨ Видео-эффекты", "menu:effects")], [cb("🏠 Главное меню", "menu:main")]])
