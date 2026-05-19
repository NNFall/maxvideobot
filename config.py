from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _get_env(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)


def _csv_ints(name: str) -> list[int]:
    return [int(x) for x in os.getenv(name, "").split(",") if x.strip().isdigit()]


def _bool_env(name: str, default: bool = False) -> bool:
    value = (os.getenv(name) or "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    max_bot_token: str
    max_use_webhook: bool
    max_webhook_url: str
    max_webhook_secret: str
    max_webhook_host: str
    max_webhook_port: int
    max_webhook_path: str
    max_bot_link_base: str
    bot_token: str
    kie_api_key: str
    kie_api_url: str
    kie_image_model: str
    kie_text_image_model: str
    replicate_api_token: str
    replicate_api_url: str
    replicate_model_version: str
    replicate_image_field: str
    replicate_image_model: str
    replicate_image_aspect_ratio: str
    yookassa_shop_id: str
    yookassa_secret_key: str
    yookassa_receipt_email: str
    yookassa_receipt_phone: str
    yookassa_tax_system_code: str
    yookassa_vat_code: str
    yookassa_item_name: str
    yookassa_payment_subject: str
    yookassa_payment_mode: str
    offer_url: str
    support_contact: str
    admin_ids: list[int]
    admin_notify_ids: list[int]
    database_path: str
    media_temp_dir: str
    media_demo_dir: str
    ref_bonus: int
    effect_cost: int
    custom_cost_per_sec: int
    photo_effect_cost: int
    photo_custom_cost: int
    stars_rub_rate: float
    stars_provider_token: str
    system_prompt: str
    ffmpeg_path: str
    replicate_aspect_ratio_mode: str
    sub_week_price_rub: int
    sub_week_price_stars: int
    sub_week_generations: int
    sub_week_days: int
    sub_month_price_rub: int
    sub_month_price_stars: int
    sub_month_generations: int
    sub_month_days: int


def load_config() -> Config:
    admin_ids = _csv_ints("ADMIN_IDS")
    admin_notify_ids = _csv_ints("ADMIN_NOTIFY_IDS") or admin_ids

    return Config(
        max_bot_token=_get_env("MAX_BOT_TOKEN", "") or "",
        max_use_webhook=_bool_env("MAX_USE_WEBHOOK", False),
        max_webhook_url=_get_env("MAX_WEBHOOK_URL", "") or "",
        max_webhook_secret=_get_env("MAX_WEBHOOK_SECRET", "") or "",
        max_webhook_host=_get_env("MAX_WEBHOOK_HOST", "0.0.0.0") or "0.0.0.0",
        max_webhook_port=int(_get_env("MAX_WEBHOOK_PORT", "8080") or "8080"),
        max_webhook_path=_get_env("MAX_WEBHOOK_PATH", "/max-webhook") or "/max-webhook",
        max_bot_link_base=_get_env("MAX_BOT_LINK_BASE", "https://max.ru") or "https://max.ru",
        bot_token=_get_env("BOT_TOKEN", "") or "",
        kie_api_key=_get_env("KIE_API_KEY", "") or "",
        kie_api_url=_get_env("KIE_API_URL", "https://api.kie.ai/api/v1/jobs/createTask") or "",
        kie_image_model=_get_env("KIE_IMAGE_MODEL", "grok-imagine/image-to-image") or "grok-imagine/image-to-image",
        kie_text_image_model=_get_env("KIE_TEXT_IMAGE_MODEL", "grok-imagine/text-to-image") or "grok-imagine/text-to-image",
        replicate_api_token=_get_env("REPLICATE_API_TOKEN", "") or "",
        replicate_api_url=_get_env("REPLICATE_API_URL", "https://api.replicate.com/v1/predictions") or "",
        replicate_model_version=_get_env("REPLICATE_MODEL_VERSION", "") or "",
        replicate_image_field=_get_env("REPLICATE_IMAGE_FIELD", "image") or "image",
        replicate_image_model=_get_env("REPLICATE_IMAGE_MODEL", "xai/grok-imagine-image") or "xai/grok-imagine-image",
        replicate_image_aspect_ratio=_get_env("REPLICATE_IMAGE_ASPECT_RATIO", "1:1") or "1:1",
        yookassa_shop_id=_get_env("YOOKASSA_SHOP_ID", "") or "",
        yookassa_secret_key=_get_env("YOOKASSA_SECRET_KEY", "") or "",
        yookassa_receipt_email=_get_env("YOOKASSA_RECEIPT_EMAIL", "") or "",
        yookassa_receipt_phone=_get_env("YOOKASSA_RECEIPT_PHONE", "") or "",
        yookassa_tax_system_code=_get_env("YOOKASSA_TAX_SYSTEM_CODE", "") or "",
        yookassa_vat_code=_get_env("YOOKASSA_VAT_CODE", "1") or "1",
        yookassa_item_name=_get_env("YOOKASSA_ITEM_NAME", "Подписка на токены") or "Подписка на токены",
        yookassa_payment_subject=_get_env("YOOKASSA_PAYMENT_SUBJECT", "") or "",
        yookassa_payment_mode=_get_env("YOOKASSA_PAYMENT_MODE", "") or "",
        offer_url=_get_env("OFFER_URL", "https://nnfall.github.io/NeiroFotoVideo/") or "",
        support_contact=_get_env("PRODUCT_SUPPORT", "@NNFall") or "@NNFall",
        admin_ids=admin_ids,
        admin_notify_ids=admin_notify_ids,
        database_path=_get_env("DATABASE_PATH", "database/database.db") or "database/database.db",
        media_temp_dir=_get_env("MEDIA_TEMP_DIR", "media/temp") or "media/temp",
        media_demo_dir=_get_env("MEDIA_DEMO_DIR", "media/demos") or "media/demos",
        ref_bonus=int(_get_env("REF_BONUS", "20") or "20"),
        effect_cost=int(_get_env("EFFECT_COST", "10") or "10"),
        custom_cost_per_sec=int(_get_env("CUSTOM_COST_PER_SEC", "5") or "5"),
        photo_effect_cost=int(_get_env("PHOTO_EFFECT_COST", "4") or "4"),
        photo_custom_cost=int(_get_env("PHOTO_CUSTOM_COST", "4") or "4"),
        stars_rub_rate=float(_get_env("STARS_RUB_RATE", "2.0") or "2.0"),
        stars_provider_token=_get_env("STARS_PROVIDER_TOKEN", "") or "",
        system_prompt=_get_env(
            "SYSTEM_PROMPT",
            "Оживи это фото в видео высокого качества. Сохрани черты лица и внешность персонажа с исходного изображения. "
            "Стиль: фотореализм, кинемататографичное освещение, высокое разрешение 4K, плавное движение.",
        )
        or "",
        ffmpeg_path=_get_env("FFMPEG_PATH", "ffmpeg") or "ffmpeg",
        replicate_aspect_ratio_mode=_get_env("REPLICATE_ASPECT_RATIO_MODE", "match") or "match",
        sub_week_price_rub=int(_get_env("SUB_WEEK_PRICE_RUB", "199") or "199"),
        sub_week_price_stars=int(_get_env("SUB_WEEK_PRICE_STARS", "199") or "199"),
        sub_week_generations=int(_get_env("SUB_WEEK_GENERATIONS", "60") or "60"),
        sub_week_days=int(_get_env("SUB_WEEK_DAYS", "7") or "7"),
        sub_month_price_rub=int(_get_env("SUB_MONTH_PRICE_RUB", "499") or "499"),
        sub_month_price_stars=int(_get_env("SUB_MONTH_PRICE_STARS", "499") or "499"),
        sub_month_generations=int(_get_env("SUB_MONTH_GENERATIONS", "100") or "100"),
        sub_month_days=int(_get_env("SUB_MONTH_DAYS", "30") or "30"),
    )
