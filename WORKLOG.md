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

- `OFFER_URL` по умолчанию заменен на актуальную оферту фото/видео-бота.
- `PRODUCT_SUPPORT` по умолчанию заменен на ссылку MAX-техподдержки.
- В меню помощи добавлена link-кнопка `🛟 Техподдержка`; кнопка `🏠 Главное меню` оставлена отдельной строкой.

### Проверки

```bash
python -m compileall main.py config.py max_handlers max_keyboards services database tools
python tools/smoke_local.py
```

Результат: успешно.

## 2026-05-20, перенос demo из Telegram file_id

### Сделано

- Добавлен `tools/migrate_telegram_demos.py`.
- Скрипт берет исходные Telegram `demo_file_id` из `database.seed_effects.EFFECTS`, скачивает файлы через Telegram Bot API в `MEDIA_DEMO_DIR` и обновляет MAX-БД на локальные пути.
- Скрипт безопасен для повторного запуска: существующие локальные/URL demo пропускаются без `--overwrite`.
- В логах скрипта токен Telegram маскируется.

### Проверки

```bash
python -m compileall main.py config.py max_handlers max_keyboards services database tools
python tools/smoke_local.py
python tools/migrate_telegram_demos.py --dry-run --limit 3
```

Результат: успешно.

### Production-запуск

- Перед импортом создан backup `/root/maxvideobot/data/database.db` в `/root/maxvideobot/data/backups/`.
- Первый запуск с серверным `BOT_TOKEN` вернул Telegram `getFile` 400 для всех файлов: серверный токен не был владельцем старых `file_id`.
- Повторный запуск выполнен с токеном исходного Telegram-бота из эталонного проекта, без записи токена в Git.
- Импортировано активных demo: 48 из 48.
- По типам: 27 photo, 21 video.
- Общий размер demo-файлов в `/app/media/demos`: 67 864 872 байт.
- Контейнер после импорта: `running`, restart count `0`.

## 2026-05-20, синхронизация effects из актуальной Telegram-БД

### Сделано

- Найдена актуальная копия Telegram-БД: `telegram_video_bot/database/database.db`, размер 7 536 640 байт.
- Добавлен `tools/sync_effects_from_telegram_db.py`.
- Скрипт синхронизирует `effects` из SQLite-БД Telegram-бота в MAX-БД:
  - обновляет `button_name`, `prompt`, `demo_file_id`, `demo_type`, `type`, `is_active`, `sort_order`, `created_at`;
  - добавляет недостающие дубли по `button_name/type`;
  - скачивает Telegram `file_id` в `MEDIA_DEMO_DIR`;
  - создает backup target DB перед изменением.

### Предварительное сравнение

- Telegram-БД: 89 effects, активных 51 (`photo`: 28, `video`: 23), с demo 66.
- MAX-БД до синхронизации: 85 effects, активных 48 (`photo`: 27, `video`: 21), с demo 48.
- В Telegram-БД 3 группы дублей, которых MAX-БД не отражала полностью:
  - `Пакет с тюльпанами 🌷` / `photo`;
  - `Поцелуй в камеру 😘` / `video`;
  - `Сердечко ❤️` / `video`.

### Production-запуск

- Копия актуальной Telegram-БД временно загружена на сервер как `/root/maxvideobot/data/import_source_telegram_database.db`.
- Синхронизация выполнена командой `tools/sync_effects_from_telegram_db.py` внутри Docker-контейнера.
- Перед изменением создан backup `/app/data/backups/database.db.before-effect-sync-20260520-103452`.
- Результат синхронизации: `updated=85`, `inserted=4`, `errors=0`.
- MAX-БД после синхронизации:
  - всего effects: 89;
  - активных effects: 51;
  - типы: `photo` 35, `video` 54;
  - активные типы: `photo` 28, `video` 23;
  - demo rows: 66;
  - существующие локальные demo-файлы: 66;
  - demo по типам: `photo` 32, `video` 34.
- Дубли теперь совпадают с Telegram-БД:
  - `Пакет с тюльпанами 🌷` / `photo`: 2 строки, 1 активная;
  - `Поцелуй в камеру 😘` / `video`: 3 строки, 1 активная;
  - `Сердечко ❤️` / `video`: 2 строки, 1 активная.
- Временная копия Telegram-БД удалена с сервера после синхронизации.

### Проверки

```bash
python -m compileall main.py config.py max_handlers max_keyboards services database tools
python tools/smoke_local.py
```

Результат: успешно в Docker-контейнере. Контейнер `running`, restart count `0`.

## 2026-05-20, админ-уведомления и smart-рассылка

### Сделано

- Проверена текущая MAX-реализация админ-уведомлений.
- Уточнены успешные уведомления о генерациях:
  - тип генерации;
  - пользователь;
  - название шаблона и `effect_id` для готовых эффектов;
  - промпт/запрос;
  - списанные токены;
  - длительность для видео.
- Уточнены уведомления о платежах ЮKassa: тариф, сумма, токены и признак автопродления.
- Username теперь прокидывается из платежных callback в polling оплаты и сохраняется в payload транзакции.
- Уточнены уведомления об отключении подписки: тариф, статус до отмены и дата окончания доступа.
- Уточнены уведомления фонового автосписания.
- В smart-рассылке и пользовательских генерационных ответах экранируется HTML в названиях/промптах.
- Подтверждено, что smart-рассылка отправляет demo-фото/demo-видео при наличии локального `demo_file_id`, а при ошибке медиа использует текстовый fallback.

### Проверки

```bash
python -m compileall main.py config.py max_handlers max_keyboards services database tools
python tools/smoke_local.py
```

Результат: успешно.

### Риски

- Live-доставку админ-уведомлений нужно подтвердить реальными действиями в MAX: генерация, тестовая ЮKassa-оплата, отключение подписки.
- Если старые pending-транзакции были созданы до этой правки, в их уведомлениях после рестарта может быть только `user_id` без username.

## 2026-05-20, упрощение монетизации и главного меню

### Сделано

- Убран бонус новичка при `/start` и `bot_started`.
- Убраны кнопки `Создать песню` и `Создать презентацию` из главного меню.
- Разовая покупка отключена в пользовательском UI:
  - в карточке баланса больше нет блока разовой покупки;
  - в выборе подписки остались только два тарифа: неделя и месяц;
  - в выборе способа оплаты осталась только ЮKassa с автопродлением.
- Старые callback-кнопки разовой покупки из уже отправленных сообщений не создают платеж, а предлагают выбрать подписку.
- Удалены неиспользуемые Stars/one-time настройки из `.env.example`, `config.py`, `services/subscriptions.py`.
- Удален неиспользуемый `services/pricing.py`.
- Баланс теперь показывает подписку активной до конца оплаченного периода даже после отключения автопродления.

### Проверки

```bash
python -m compileall main.py config.py max_handlers max_keyboards services database tools
python tools/smoke_local.py
```

Результат: успешно. `tools/smoke_local.py` обновлен под новую логику без starter-бонуса.

### Риски

- У пользователей, которые уже получили бонус до этой правки, баланс не списывался автоматически. Новым пользователям бонус больше не начисляется.
- Старые pending-транзакции `yookassa_once`, созданные до правки, остаются в базе до завершения/истечения, но новые разовые платежи из UI больше не создаются.

## 2026-05-21, ссылка оферты

### Сделано

- `OFFER_URL` в `config.py` и `.env.example` заменен на `https://dimonk95.github.io/photo-video-ai-max/`.
- Оферта в карточке баланса продолжает браться из `cfg.offer_url`, поэтому ссылка в пользовательском тексте меняется через переменную окружения.

### Проверки

```bash
python -m compileall main.py config.py max_handlers max_keyboards services database tools
python tools/smoke_local.py
```

Результат: успешно.

### Риски

- На production сервере нужно отдельно обновить `/root/maxvideobot/.env`, потому что он переопределяет дефолт из `config.py`.

## 2026-05-22, ссылка техподдержки

### Сделано

- Текущая production-ссылка техподдержки до правки: `https://web.max.ru/69942834`.
- `PRODUCT_SUPPORT` в `config.py` и `.env.example` заменен на `https://max.ru/u/f9LHodD0cOL1NLfuFBoMvvVMSgRmsLKspQSSM1d9_6ZR68W1oT3zfN20xA8`.

### Проверки

```bash
python -m compileall main.py config.py max_handlers max_keyboards services database tools
python tools/smoke_local.py
```

Результат: успешно. `tools/smoke_local.py` проверяет новую ссылку техподдержки в keyboard.

### Риски

- На production сервере нужно отдельно обновить `/root/maxvideobot/.env`, потому что он переопределяет дефолт из `config.py`.
