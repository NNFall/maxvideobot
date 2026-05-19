# AGENTS.md

## Проект

Корневой проект — MAX-версия Telegram-бота из `telegram_video_bot`.

Цель миграции: сохранить продуктовую и монетизационную логику Telegram-бота для генерации/редактирования фото и видео, заменив транспортный слой на Messenger MAX.

## Неизменяемое ядро

По возможности не ломать:
- `database/db.py`
- `database/crud.py`
- `services/kie_api.py`
- `services/replicate_api.py`
- `services/yookassa.py`
- `services/subscriptions.py`
- `services/ffmpeg_service.py`
- схему таблиц `users`, `effects`, `transactions`, `promocodes`, `pending_actions`, `admins`, `subscriptions`, `mailer_state`.

## MAX-слой

Транспорт MAX находится здесь:
- `main.py`
- `max_handlers/`
- `max_keyboards/`
- `services/max_adapter.py`
- MAX-версии фоновых задач: `services/subscription_tasks.py`, `services/smart_mailer.py`.

Правила:
- использовать `maxapi`, не `aiogram`;
- тексты отправлять в HTML parse mode;
- все пользовательские действия делать через inline-кнопки;
- callback payload держать короткими и системными;
- медиа из MAX извлекать через `max_handlers/utils.py`;
- demo-файлы, добавленные через MAX-админку, хранить в `MEDIA_DEMO_DIR`, не как временный attachment URL;
- если формат входящего MAX attachment меняется, править централизованно `get_media_source`.

## Исходник

`telegram_video_bot` — рабочая Telegram-копия. Ее не удалять и не переписывать без отдельной причины. Она нужна как эталон поведения.

## Платежи

Сохраняется ЮKassa:
- redirect-платеж;
- polling статуса;
- `save_payment_method=True` для автопродления;
- recurrent charge через `payment_method_id`;
- pending actions после оплаты.

Telegram Stars в MAX недоступны. Разовая покупка реализуется через ЮKassa без `save_payment_method`.

## Документация

Поддерживать актуальными:
- `README.md`
- `MAX_MIGRATION_PLAN.md`
- `WORKLOG.md`

После каждого крупного блока фиксировать:
- что изменено;
- какие команды проверки запускались;
- какие риски остались.

## Проверки

Минимальная локальная проверка:

```bash
python -m compileall main.py config.py max_handlers max_keyboards services database tools
python tools/smoke_local.py
```

Перед production:
- live `/start`;
- live `bot_started` с deeplink payload;
- live callbacks меню;
- входящие фото и видео в MAX;
- отправка результата генерации;
- тестовая ЮKassa-оплата;
- pending action после оплаты;
- админ-команды;
- smart-рассылка на тестовой аудитории;
- webhook с публичным HTTPS URL.
