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
- На этом этапе баланс показывал подписку активной до конца оплаченного периода даже после отключения автопродления; позже это приведено к Telegram-логике.

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

## 2026-05-22, формат админ-команд и уведомлений

### Сделано

- MAX-админка сверена с Telegram-эталоном и приведена к тому же формату ответов:
  - `/session_del`, `/set_top`, `/get_prompt` принимают ID или название эффекта, либо показывают inline-список;
  - списки эффектов показывают префиксы `📸`/`🎬`;
  - `/get_prompt` выводит название, тип и prompt в `<pre>`;
  - `/adstats`, `/adstats_all`, `/botstats`, `/adtag`, `/genpromo` получили Telegram-формат с HTML-разметкой и расчетом конверсии/LTV/ARPU/ARPPU;
  - `/sub_check` больше не показывает сырой dict подписки, а выводит читаемые поля.
- Сценарий `/add_session` теперь повторяет Telegram-flow: тип эффекта, название, prompt на английском, demo-фото/demo-видео или `нет`; пустой или неверный demo-ввод не создает эффект.
- Owner-команда `/admin_list` показывает и config-админов, и админов из SQLite.
- Уведомления админам по FFmpeg-инструментам переведены на HTML с пользователем и деталями ошибки/интервала.
- Smart-рассылка в админских предпросмотрах и старте рассылки показывает название, тип и ID эффекта.
- `tools/smoke_local.py` расширен проверками `/get_prompt`, `/botstats`, `/adtag` и удаления эффекта.

### Проверки

```bash
python -m compileall main.py config.py max_handlers max_keyboards services database tools
python tools/smoke_local.py
```

Результат: успешно.

### Риски

- Live-доставку новых админских сообщений нужно подтвердить в MAX на реальных действиях: добавление/удаление эффекта, генерация, FFmpeg-инструменты, smart-рассылка.
- MAX может иметь лимиты на количество inline-кнопок в одном сообщении; текущая реализация выводит весь список эффектов, как Telegram-эталон.

## 2026-05-26, Telegram-логика активной подписки

### Сделано

- Карточка `/balance` в MAX приведена к Telegram-логике: подписка считается активной только если `status='active'` и `auto_renew=1`.
- После отключения автопродления баланс больше не показывает `✅ Подписка активна`, даже если оплаченный период еще не закончился; вместо этого отображается `❌ Подписка не активна` и остаток токенов.
- Активная карточка баланса теперь совпадает с Telegram-форматом: тариф и остаток токенов без отдельных строк `Доступно до` и `Автопродление`.
- После нажатия `❌ Отключить подписку` бот отправляет только подтверждение отмены, как в Telegram.
- `tools/smoke_local.py` расширен проверкой активной подписки с автопродлением и отмененной подписки с остатком токенов.

### Проверки

```bash
python -m compileall main.py config.py max_handlers max_keyboards services database tools
python tools/smoke_local.py
```

Результат: успешно.

### Риски

- Списания токенов за генерации остаются завязаны на балансе, поэтому у отменившего пользователя остаток токенов будет доступен, пока не израсходован или пока фоновые задачи не обнулят истекший период.

## 2026-05-28, фиксы генерации видео и фотошопа в MAX

### Сделано

- Исправлена клавиатура выбора длительности для `Создать видео`: MAX отклонял старую раскладку с ошибкой `errors.maxRowSize`, из-за чего после фото с подписью сценарий выглядел как «не реагирует».
- Ошибки пользователю и админам теперь выводятся с реальными переносами строк, без текстовых `\n`.
- Replicate больше не получает временный MAX URL как входное изображение; вместо этого используется base64 локально скачанного файла.
- `encode_image` определяет MIME по сигнатуре файла, а не только по расширению, чтобы MAX/провайдерские WebP/PNG не уходили как неверный JPEG.
- Видео-эффекты получили fallback на Replicate-видео, если Kie.ai не вернул задачу из-за ошибки провайдера, включая `Credits insufficient`.
- `tools/smoke_local.py` расширен проверками клавиатуры длительности, переносов в ошибках и MIME-detect для WebP.

### Проверки

```bash
python -m compileall main.py config.py max_handlers max_keyboards services database tools
python tools/smoke_local.py
```

Результат: успешно.

### Риски

- Если одновременно закончатся кредиты/лимиты и у Kie.ai, и у Replicate, видео-эффект все равно вернет ошибку и токены пользователю.
- Live-проверку полного результата генерации нужно сделать реальным фото после деплоя, потому что она зависит от внешних провайдеров.

## 2026-05-29, кнопка создания песни

### Сделано

- В главное MAX-меню добавлена inline link-кнопка `🎤 Создать песню`.
- Кнопка размещена после `📼 Инструменты` и ведет на `https://max.ru/id644927208311_bot?start=gen`.
- `tools/smoke_local.py` обновлен: проверяет наличие ссылки и позицию кнопки между `Инструменты` и `Баланс / Купить`.

### Проверки

```bash
python -m compileall main.py config.py max_handlers max_keyboards services database tools
python tools/smoke_local.py
```

Результат: успешно.

### Риски

- Кнопка ведет во внешний MAX-бот, поэтому его доступность и поведение зависят от того бота, не от текущего сервиса.

## 2026-05-29, склейка видео из MAX

### Сделано

- `get_media_source` для MAX-видео теперь сначала выбирает прямые `mp4_*` ссылки и не берет preview/thumbnail `webp` как исходное видео.
- `concat_videos` сначала пробует быструю склейку `-c copy`, а при несовместимом кодеке/контейнере автоматически перекодирует результат в H.264 mp4.
- Админское уведомление по ошибкам инструментов ограничивает технические детали, чтобы длинный stderr ffmpeg не занимал несколько экранов.
- `tools/smoke_local.py` расширен проверками MAX-видео attachment с preview `webp`, укороченного админского сообщения и fallback-склейки ffmpeg.

### Проверки

```bash
python -m compileall main.py config.py max_handlers max_keyboards services database tools
python tools/smoke_local.py
```

Результат: локально успешно.

### Риски

- Если MAX начнет отдавать видео не через `mp4_*`, а через новый тип поля, нужно будет дополнить централизованный парсер `get_media_source`.

## 2026-06-17, fallback видео на Kie Grok Imagine Video 1.5

### Сделано

- Добавлен Kie createTask-клиент для модели `grok-imagine-video-1-5-preview`.
- Для нового fallback используются параметры: `aspect_ratio=auto`, `resolution=480p`, `duration=1..15`, `nsfw_checker=false`.
- `Создать видео` теперь сначала пробует Replicate, а при отказе/ошибке Replicate переключается на Kie Grok video fallback.
- Видео-эффекты теперь имеют цепочку: старый Kie video -> Replicate video fallback -> Kie Grok video fallback.
- `.env.example` дополнен переменными `KIE_GROK_VIDEO_*`.
- `tools/smoke_local.py` проверяет payload новой Kie-задачи без реального API-вызова.

### Проверки

```bash
python -m compileall main.py config.py max_handlers max_keyboards services database tools
python tools/smoke_local.py
```

Результат: локально и в контейнере выполнены успешно.

```bash
python -m compileall main.py config.py max_handlers max_keyboards services database tools
python tools/smoke_local.py
docker compose exec -T bot python -m compileall main.py config.py max_handlers max_keyboards services database tools
docker compose exec -T bot python tools/smoke_local.py
```

После деплоя на сервере обновлены переменные:
- `KIE_API_KEY` и `REPLICATE_API_TOKEN` под актуальные ключи.
- `KIE_GROK_VIDEO_MODEL=grok-imagine-video-1-5-preview`.
- `KIE_GROK_VIDEO_ASPECT_RATIO=auto`.
- `KIE_GROK_VIDEO_RESOLUTION=480p`.
- `KIE_GROK_VIDEO_NSFW_CHECKER=0`.
Перезапуск контейнера выполнен через `docker compose up -d --build --force-recreate bot`.

### Риски

- Новый fallback все равно зависит от баланса Kie.ai; если на Kie нет кредитов, после отказа Replicate генерация также вернет ошибку и токены пользователю.
- Slug модели взят из Kie-документации Create Task для Grok Imagine Video 1.5; если Kie изменит API slug, нужно поменять `KIE_GROK_VIDEO_MODEL` в `.env`.

## 2026-06-18, исправление slug Kie Grok video

### Сделано

- Исправлен unsupported model error от Kie: вместо `grok-imagine-video-1.5` используется `grok-imagine-video-1-5-preview`.
- Обновлены дефолты в `config.py`, `services/kie_api.py`, `.env.example` и smoke-проверка payload.
- На production нужно обновить `/root/maxvideobot/.env`: `KIE_GROK_VIDEO_MODEL=grok-imagine-video-1-5-preview`.

### Проверки

```bash
python tools/smoke_local.py
python -m compileall main.py config.py max_handlers max_keyboards services database tools
```

Результат: локально выполнено успешно.
