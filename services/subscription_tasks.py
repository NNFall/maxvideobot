from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta

from config import load_config
from database import crud
from services import yookassa as yk
from services.notify import notify_admin
from services.subscriptions import calc_period, get_plan

logger = logging.getLogger(__name__)


async def _apply_subscription(user_id: int, plan_id: str, provider: str, auto_renew: int, payment_method_id: str | None) -> None:
    plan = get_plan(plan_id)
    if not plan:
        return

    cfg = load_config()
    start, end = calc_period(plan.days)
    await crud.set_balance(cfg.database_path, user_id, plan.generations)
    await crud.upsert_subscription(
        cfg.database_path,
        user_id=user_id,
        plan_id=plan.id,
        provider=provider,
        auto_renew=auto_renew,
        payment_method_id=payment_method_id,
        current_period_start=start,
        current_period_end=end,
        status="active",
    )


def _calc_retry_time(current_period_end: str | None, days: int = 1) -> str:
    now = datetime.utcnow()
    base = now
    if current_period_end:
        try:
            parsed = datetime.fromisoformat(current_period_end)
            if parsed > now:
                base = parsed
        except Exception:
            pass
    return (base + timedelta(days=days)).isoformat(timespec="seconds")


def _build_receipt(cfg, amount_rub: int) -> dict | None:
    if not cfg.yookassa_tax_system_code:
        return None
    if not cfg.yookassa_receipt_email and not cfg.yookassa_receipt_phone:
        return None

    item = {
        "description": cfg.yookassa_item_name or "Подписка на токены",
        "quantity": "1.00",
        "amount": {"value": f"{amount_rub:.2f}", "currency": "RUB"},
        "vat_code": int(cfg.yookassa_vat_code) if str(cfg.yookassa_vat_code).isdigit() else 1,
    }
    if cfg.yookassa_payment_subject:
        item["payment_subject"] = cfg.yookassa_payment_subject
    if cfg.yookassa_payment_mode:
        item["payment_mode"] = cfg.yookassa_payment_mode

    return {
        "tax_system_code": int(cfg.yookassa_tax_system_code),
        "items": [item],
        "customer": {"email": cfg.yookassa_receipt_email}
        if cfg.yookassa_receipt_email
        else {"phone": cfg.yookassa_receipt_phone},
    }


async def process_due_subscriptions(bot) -> None:
    cfg = load_config()
    now_iso = datetime.utcnow().isoformat(timespec="seconds")

    expired = await crud.list_expired_subscriptions(cfg.database_path, now_iso)
    for sub in expired:
        await crud.mark_subscription_status(cfg.database_path, sub["user_id"], "expired")
        await crud.set_balance(cfg.database_path, sub["user_id"], 0)
        try:
            await bot.send_message(sub["user_id"], "Срок подписки истек. Токены обнулены.")
        except Exception:
            pass

    due = await crud.list_due_subscriptions(cfg.database_path, now_iso)
    if not due:
        return

    try:
        yk.configure(cfg.yookassa_shop_id, cfg.yookassa_secret_key)
    except Exception as e:
        await notify_admin(bot, cfg.admin_notify_ids, f"❌ YooKassa config error: {e}")
        return

    for sub in due:
        plan = get_plan(sub["plan_id"])
        if not plan or not sub.get("payment_method_id"):
            continue

        try:
            payment = await asyncio.to_thread(
                yk.create_recurrent_payment,
                plan.price_rub,
                f"Подписка {plan.title} - автосписание",
                sub["payment_method_id"],
                {"user_id": sub["user_id"], "plan_id": plan.id},
                _build_receipt(cfg, plan.price_rub),
            )
        except Exception as e:
            logger.error("Recurrent charge failed user_id=%s error=%s", sub["user_id"], e)
            if "payment_method_id" in str(e):
                await crud.cancel_subscription(cfg.database_path, sub["user_id"])
                retry_at = None
            else:
                retry_at = _calc_retry_time(sub.get("current_period_end"), days=1)
                await crud.set_subscription_period_end(cfg.database_path, sub["user_id"], retry_at)
            await notify_admin(
                bot,
                cfg.admin_notify_ids,
                f"❌ Автосписание: пользователь {sub['user_id']}, статус ошибка. Причина: {e}"
                + (f"\nСледующая попытка: {retry_at}" if retry_at else ""),
            )
            continue

        status = getattr(payment, "status", "unknown")
        payment_id = getattr(payment, "id", None)
        if status == "succeeded":
            await crud.create_transaction(
                cfg.database_path,
                user_id=sub["user_id"],
                amount=plan.price_rub,
                currency="RUB",
                credits=plan.generations,
                provider="yookassa",
                status="paid",
                provider_payment_id=payment_id,
                payload=json.dumps({"plan_id": plan.id, "auto_renew": True}),
            )
            await _apply_subscription(sub["user_id"], plan.id, "yookassa", 1, sub["payment_method_id"])
            await notify_admin(bot, cfg.admin_notify_ids, f"✅ Автосписание: пользователь {sub['user_id']}, статус успех, тариф {plan.id}")
        else:
            retry_at = _calc_retry_time(sub.get("current_period_end"), days=1)
            await crud.set_subscription_period_end(cfg.database_path, sub["user_id"], retry_at)
            await notify_admin(bot, cfg.admin_notify_ids, f"❌ Автосписание: пользователь {sub['user_id']}, статус {status}, тариф {plan.id}")


async def subscription_watcher(bot, interval_sec: int = 60) -> None:
    while True:
        try:
            await process_due_subscriptions(bot)
        except Exception as e:
            logger.exception("Subscription watcher error: %s", e)
        await asyncio.sleep(interval_sec)
