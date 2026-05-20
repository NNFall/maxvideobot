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

## 2026-05-19

### Деплой

- Создан локальный Git-репозиторий и опубликован `main` в `https://github.com/NNFall/maxvideobot`.
- На сервере `185.171.83.116` развернут checkout в `/root/maxvideobot`.
- Серверный `.env` создан отдельно от Git и не коммитится.
- Docker запущен через `docker compose up -d`.
- Внешние данные примонтированы:
  - `/root/maxvideobot/data` -> `/app/data`
  - `/root/maxvideobot/media` -> `/app/media`
- База создана и засеяна через `python database/seed_effects.py`.

### Проверки деплоя

```bash
docker compose ps
docker compose logs --tail=120 bot
docker compose exec -T bot python - <<'PY'
import asyncio
from config import load_config
from database import crud

async def main():
    cfg = load_config()
    print(cfg.database_path, cfg.media_temp_dir, cfg.media_demo_dir)
    print(len(await crud.list_effects(cfg.database_path, active_only=True, effect_type='video')))
    print(len(await crud.list_effects(cfg.database_path, active_only=True, effect_type='photo')))

asyncio.run(main())
PY
```

Результат:
- контейнер `maxvideobot-bot-1` в статусе `running`;
- restart count `0`;
- polling стартовал;
- бот авторизован как `@id644009650098_3_bot`;
- в БД активны 21 video-effect и 27 photo-effect.

## 2026-05-20

### Исправления после live-проверки

- Включена конкурентная обработка MAX updates через `Dispatcher(use_create_task=True)`, чтобы генерация не задерживала последующие нажатия кнопок.
- Долгие AI-сценарии переводят пользователя в state `generation_running`; команды и меню остаются доступны, а лишние текстовые/медиа-сообщения не запускают старый сценарий повторно.
- Синхронные FFmpeg-операции склейки и вырезания перенесены в `asyncio.to_thread`, чтобы не блокировать event loop.
- Синхронные запросы создания платежей ЮKassa перенесены в `asyncio.to_thread`.
- Стрелки пагинации эффектов теперь пытаются обновить исходное MAX-сообщение через callback-ответ с новой клавиатурой; если MAX-клиент/API не редактирует сообщение, остается fallback на новое сообщение.
- Контакт поддержки по умолчанию заменен с `@kiperovka` на `@NNFall`.

### Проверки

```bash
python -m compileall main.py config.py max_handlers max_keyboards services database tools
python tools/smoke_local.py
```

Результат: успешно.

Дополнительно локально проверены:
- сборка callback-ответа MAX с inline-клавиатурой;
- `concat_videos` и `remove_fragment` на коротких синтетических mp4.

### Риски

- Поведение редактирования сообщения через callback нужно подтвердить live в MAX: библиотека поддерживает такой ответ, но клиент может все равно показывать новое сообщение.
- Live AI API и ЮKassa после исправления не вызывались локально, чтобы не тратить платные лимиты без необходимости.

## 2026-05-20, правка ссылок

### Сделано

- `OFFER_URL` по умолчанию заменен на `https://dimonk95.github.io/tarobotrustore/`.
- `PRODUCT_SUPPORT` по умолчанию заменен на `https://web.max.ru/69942834`.
- В меню помощи добавлена link-кнопка `🛟 Техподдержка`; кнопка `🏠 Главное меню` оставлена отдельной строкой.

### Проверки

```bash
python -m compileall main.py config.py max_handlers max_keyboards services database tools
python tools/smoke_local.py
```

Результат: успешно.
