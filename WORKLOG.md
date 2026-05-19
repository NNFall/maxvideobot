# WORKLOG

## 2026-05-18

### Сделано

- Проведена инвентаризация Telegram-бота в `telegram_video_bot`.
- Создан корневой MAX-проект без удаления исходной Telegram-копии.
- Скопированы совместимые ядра:
  - `database/db.py`
  - `database/crud.py`
  - `database/seed_effects.py`
  - `services/kie_api.py`
  - `services/replicate_api.py`
  - `services/yookassa.py`
  - `services/subscriptions.py`
  - `services/ffmpeg_service.py`
- Добавлены MAX-слои:
  - `max_handlers/router.py`
  - `max_handlers/state.py`
  - `max_handlers/utils.py`
  - `max_keyboards/*`
  - `services/max_adapter.py`
- Перенесены основные пользовательские, платежные и админские сценарии.
- Выполнена проверка компиляции.

### Проверки

```bash
python -m compileall main.py config.py max_handlers max_keyboards services database
```

Результат: успешно.

Дополнительно:
- MAX-клавиатуры создаются как `Attachment`;
- SQLite-схема создается через `database.db.setup`;
- в корневом MAX-коде нет импортов `aiogram`.
- добавлен обработчик `bot_started` для MAX deeplink payload;
- `/start` и `bot_started` теперь используют общий стартовый helper;
- smart-рассылка не падает на Telegram demo `file_id`, а отправляет текстовый fallback;
- pending actions с входящим фото кешируют медиа локально до оплаты и чистят кеш после запуска;
- expired/canceled YooKassa pending payments чистят связанный pending media cache;
- `database/seed_effects.py` теперь использует `DATABASE_PATH` из `config.py`, а не жесткий Docker-путь;
- добавлен `.dockerignore`, чтобы не класть в Docker-образ `.env`, локальные БД/медиа/cache и `telegram_video_bot`;
- `maxapi` закреплен в `requirements.txt` как `maxapi==1.0.0`;
- pending-payment guard теперь блокирует любую активную pending-оплату пользователя, а не только тот же provider;
- admin-demo из MAX сохраняются в `MEDIA_DEMO_DIR`;
- сидер эффектов не переносит Telegram `file_id` в MAX demo-поля и не перетирает уже сохраненные demo;
- ссылки `/invite`, `/adtag` и YooKassa return URL корректно используют полный `MAX_BOT_LINK_BASE`;
- добавлены `tools/smoke_local.py` и `tools/max_payload_probe.py`.

### Проверки после стабилизации

```bash
python -m compileall main.py config.py max_handlers max_keyboards services database tools
python tools/smoke_local.py
```

Результат: успешно.

### Что проверить live

- Реальный формат входящих MAX attachment для фото и видео.
- Событие `bot_started` и payload `ref_`/`promo_`/UTM через MAX deeplink.
- Отправка локально скачанных/сгенерированных медиа в MAX.
- ЮKassa redirect + polling.
- Pending action после оплаты из середины генерации.
- Smart-рассылка на тестовой аудитории.
